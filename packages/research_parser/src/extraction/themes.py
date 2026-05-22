"""Extract themes from financial research documents."""

import json
import re
from collections.abc import Iterable

import structlog
from tenacity import retry, stop_after_attempt, wait_random_exponential

from src.llm import LLMClient, ModelConfig

from .input_slicing import chunk_for_structured_extraction
from .json_utils import clean_json_response
from .models import ArgumentStructure, Theme
from .prompts import get_themes_prompt
from .structured import generate_with_validation_fallback

logger = structlog.get_logger()

_THEME_STRENGTH_RANK = {"Primary": 3, "Secondary": 2, "Peripheral": 1}
_THEME_CONFIDENCE_RANK = {"High": 3, "Medium": 2, "Low": 1}
_THEME_CLASSIFICATION_RANK = {"Opinion": 3, "Forecast": 2, "Description": 1}
_MAX_FINAL_THEMES = 12
_THEME_MAX_CHUNK_CHARS = 12_000
_THEME_TARGET_CHUNK_CHARS = 9_000
_THEME_MIN_PROGRESS_CHARS = 4_000
_THEME_CHUNK_OVERLAP_CHARS = 1_000
_THEME_RETRY_MIN_CHUNK_CHARS = 4_000
_THEME_MAX_SPLIT_DEPTH = 4

_THEMES_RESPONSE_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "themes_response",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "coverage": {
                    "type": "object",
                    "additionalProperties": True,
                },
                "themes": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": True,
                        "properties": {
                            "label": {"type": "string"},
                            "excerpts": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": True,
                                    "properties": {"text": {"type": "string"}},
                                    "required": ["text"],
                                },
                            },
                            "relevance": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "classification": {"type": "string"},
                            "mention_count": {"type": "number"},
                            "evidence_count": {"type": "number"},
                            "strength": {"type": "string"},
                            "directionality": {
                                "type": ["object", "null"],
                                "additionalProperties": {"type": "integer"},
                            },
                            "confidence": {"type": "string"},
                            "context": {"type": ["string", "null"]},
                            "argument_structure": {"type": ["object", "null"]},
                        },
                        "required": [
                            "label",
                            "excerpts",
                            "relevance",
                            "classification",
                            "strength",
                            "confidence",
                            "context",
                        ],
                    },
                },
                "excluded_topics": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["themes"],
        },
    },
}


def _normalize_relevance(value, primary_category) -> list[str]:
    """Normalize model output to the Theme.relevance shape.

    Open-weight models sometimes omit `relevance` or emit a scalar instead of a
    list even when the prompt marks it as required.
    """
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, dict)):
        cleaned = [item for item in value if isinstance(item, str) and item]
        if cleaned:
            return cleaned
    if isinstance(primary_category, str) and primary_category:
        return [primary_category]
    return []


def _normalize_excerpts(value) -> list[dict[str, str]]:
    """Coerce excerpt variants into Theme.excerpts-compatible objects."""
    if value is None:
        return []
    if isinstance(value, str) and value:
        return [{"text": value}]
    if not isinstance(value, Iterable) or isinstance(value, (bytes, dict)):
        return []

    cleaned: list[dict[str, str]] = []
    for item in value:
        if isinstance(item, str) and item:
            cleaned.append({"text": item})
            continue
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if isinstance(text, str) and text:
            cleaned.append({"text": text})
    return cleaned


def _normalize_theme_key(label: str) -> str:
    return re.sub(r"\s+", " ", label.strip().lower())


def _ordered_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        cleaned = value.strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _normalize_argument_structure(value) -> ArgumentStructure | None:
    """Normalize argument_structure from model output."""
    if value is None:
        return None
    if isinstance(value, ArgumentStructure):
        return value
    if isinstance(value, dict):
        try:
            return ArgumentStructure(**value)
        except Exception:
            return None
    return None


def _merge_argument_structure(
    existing: ArgumentStructure | None, incoming: ArgumentStructure | None
) -> ArgumentStructure | None:
    """Merge argument_structure from two themes."""
    if existing is None:
        return incoming
    if incoming is None:
        return existing

    conditionals = _ordered_unique([*existing.conditionals, *incoming.conditionals])
    dependencies = _ordered_unique([*existing.dependencies, *incoming.dependencies])
    contradictions = _ordered_unique([*existing.contradictions, *incoming.contradictions])

    confidence_basis = existing.confidence_basis
    if incoming.confidence_basis and len(incoming.confidence_basis) > len(confidence_basis):
        confidence_basis = incoming.confidence_basis

    return ArgumentStructure(
        conditionals=conditionals,
        confidence_basis=confidence_basis,
        dependencies=dependencies,
        contradictions=contradictions,
    )


def _merge_theme(existing: Theme, incoming: Theme) -> Theme:
    excerpt_map = {
        excerpt.text.strip().lower(): excerpt
        for excerpt in existing.excerpts
        if excerpt.text.strip()
    }
    for excerpt in incoming.excerpts:
        key = excerpt.text.strip().lower()
        if key and key not in excerpt_map:
            excerpt_map[key] = excerpt

    classification = existing.classification
    if _THEME_CLASSIFICATION_RANK.get(incoming.classification, 0) > _THEME_CLASSIFICATION_RANK.get(
        classification, 0
    ):
        classification = incoming.classification

    strength = existing.strength
    if _THEME_STRENGTH_RANK.get(incoming.strength, 0) > _THEME_STRENGTH_RANK.get(strength, 0):
        strength = incoming.strength

    confidence = existing.confidence
    if _THEME_CONFIDENCE_RANK.get(incoming.confidence, 0) > _THEME_CONFIDENCE_RANK.get(
        confidence, 0
    ):
        confidence = incoming.confidence

    directionality: dict[str, int] | None = existing.directionality or incoming.directionality
    if existing.directionality and incoming.directionality:
        merged_directionality: dict[str, int] = dict(existing.directionality)
        for key, value in incoming.directionality.items():
            current = merged_directionality.get(key)
            if current is None or abs(value) > abs(current):
                merged_directionality[key] = value
        directionality = merged_directionality

    context = existing.context
    if len(incoming.context.strip()) > len(context.strip()):
        context = incoming.context

    argument_structure = _merge_argument_structure(
        existing.argument_structure, incoming.argument_structure
    )

    return Theme(
        label=existing.label if len(existing.label) >= len(incoming.label) else incoming.label,
        excerpts=list(excerpt_map.values()),
        relevance=_ordered_unique([*existing.relevance, *incoming.relevance]),
        classification=classification,
        mention_count=max(existing.mention_count, incoming.mention_count),
        strength=strength,
        directionality=directionality,
        confidence=confidence,
        context=context,
        argument_structure=argument_structure,
    )


def _merge_chunk_themes(chunks: list[list[Theme]]) -> list[Theme]:
    merged: dict[str, Theme] = {}
    order: list[str] = []

    for themes in chunks:
        for theme in themes:
            key = _normalize_theme_key(theme.label)
            if not key:
                continue
            if key not in merged:
                merged[key] = theme
                order.append(key)
                continue
            merged[key] = _merge_theme(merged[key], theme)

    ranked = [merged[key] for key in order]
    ranked.sort(
        key=lambda theme: (
            _THEME_STRENGTH_RANK.get(theme.strength, 0),
            _THEME_CONFIDENCE_RANK.get(theme.confidence, 0),
            theme.mention_count,
            len(theme.excerpts),
            len(theme.context.strip()),
        ),
        reverse=True,
    )
    return ranked[:_MAX_FINAL_THEMES]


# _clean_json_response moved to json_utils.py


def _parse_themes_response(raw: str) -> list[Theme]:
    cleaned = clean_json_response(raw)
    data = json.loads(cleaned)
    if isinstance(data, dict) and "themes" in data:
        data = data["themes"]
    if not isinstance(data, list):
        data = [data]
    normalized: list[dict] = []
    for theme in data:
        if not isinstance(theme, dict):
            continue
        if "mention_count" not in theme and "evidence_count" in theme:
            theme["mention_count"] = theme["evidence_count"]
        theme["relevance"] = _normalize_relevance(
            theme.get("relevance"),
            theme.get("primary_category"),
        )
        theme["excerpts"] = _normalize_excerpts(theme.get("excerpts"))
        if theme.get("context") is None:
            theme["context"] = ""
        directionality = theme.get("directionality")
        if isinstance(directionality, dict):
            cleaned_dir = {}
            for key, value in directionality.items():
                try:
                    cleaned_dir[key] = int(value)
                except (TypeError, ValueError):
                    continue
            theme["directionality"] = cleaned_dir or None
        elif directionality is not None:
            theme["directionality"] = None
        theme["argument_structure"] = _normalize_argument_structure(theme.get("argument_structure"))
        normalized.append(theme)
    return [Theme(**t) for t in normalized]


def _is_request_too_large_error(exc: Exception) -> bool:
    message = str(exc).lower()
    oversized_markers = (
        "request too large",
        "context length",
        "maximum context length",
        "maximum context size",
        "413",
        "tokens per minute",
    )
    return any(marker in message for marker in oversized_markers)


def _smaller_theme_chunks(chunk: str) -> list[str]:
    reduced_max = max(_THEME_RETRY_MIN_CHUNK_CHARS, min(_THEME_MAX_CHUNK_CHARS, len(chunk) // 2))
    if reduced_max >= len(chunk):
        return [chunk]
    reduced_target = max(_THEME_RETRY_MIN_CHUNK_CHARS - 1, int(reduced_max * 0.75))
    reduced_min_progress = max(1_500, min(reduced_target, reduced_max // 3))
    reduced_overlap = max(250, min(_THEME_CHUNK_OVERLAP_CHARS, reduced_max // 8))
    return chunk_for_structured_extraction(
        chunk,
        max_chunk_chars=reduced_max,
        target_chunk_chars=reduced_target,
        min_progress_chars=reduced_min_progress,
        overlap_chars=reduced_overlap,
    )


def _extract_themes_chunk(
    client: LLMClient,
    chunk: str,
    config: ModelConfig,
    log,
    *,
    split_depth: int = 0,
) -> list[Theme]:
    try:
        return generate_with_validation_fallback(
            client=client,
            config=config,
            system=get_themes_prompt(),
            user=chunk,
            parser=_parse_themes_response,
            log=log,
            step="themes",
            response_format=_THEMES_RESPONSE_SCHEMA,
        )
    except Exception as exc:
        if not _is_request_too_large_error(exc):
            raise
        if len(chunk) <= _THEME_RETRY_MIN_CHUNK_CHARS or split_depth >= _THEME_MAX_SPLIT_DEPTH:
            raise

        smaller_chunks = _smaller_theme_chunks(chunk)
        if len(smaller_chunks) <= 1:
            raise

        log.warning(
            "Theme extraction chunk exceeded model budget; splitting and retrying",
            chunk_length=len(chunk),
            split_depth=split_depth,
            replacement_chunk_count=len(smaller_chunks),
            replacement_max_chunk_length=max(len(item) for item in smaller_chunks),
            error=str(exc),
        )
        nested_results: list[list[Theme]] = []
        for idx, smaller_chunk in enumerate(smaller_chunks, start=1):
            nested_results.append(
                _extract_themes_chunk(
                    client,
                    smaller_chunk,
                    config,
                    log.bind(
                        split_depth=split_depth + 1,
                        split_chunk_index=idx,
                        split_chunk_count=len(smaller_chunks),
                    ),
                    split_depth=split_depth + 1,
                )
            )
        return _merge_chunk_themes(nested_results)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_random_exponential(multiplier=1, min=2, max=45),
    reraise=True,
)
def extract_themes(
    client: LLMClient,
    text: str,
    config: ModelConfig,
    log=None,
) -> list[Theme]:
    """
    Extract key themes from a financial research document.

    Uses extended thinking (if configured) for deeper reasoning about theme relationships.
    """
    thinking_enabled = config.extended_thinking and config.extended_thinking.enabled
    log = log or logger
    log.info(
        "Extracting themes",
        text_length=len(text),
        provider=config.provider,
        model=config.model,
        thinking_enabled=thinking_enabled,
        thinking_budget=config.extended_thinking.budget_tokens if thinking_enabled else None,
    )
    chunks = chunk_for_structured_extraction(
        text,
        max_chunk_chars=_THEME_MAX_CHUNK_CHARS,
        target_chunk_chars=_THEME_TARGET_CHUNK_CHARS,
        min_progress_chars=_THEME_MIN_PROGRESS_CHARS,
        overlap_chars=_THEME_CHUNK_OVERLAP_CHARS,
    )
    if len(chunks) > 1:
        log.info(
            "Chunking theme extraction input",
            original_text_length=len(text),
            chunk_count=len(chunks),
            max_chunk_length=max(len(chunk) for chunk in chunks),
        )

    chunk_results: list[list[Theme]] = []
    for idx, chunk in enumerate(chunks, start=1):
        chunk_log = log.bind(chunk_index=idx, chunk_count=len(chunks))
        chunk_results.append(
            _extract_themes_chunk(
                client,
                chunk,
                config,
                chunk_log,
                split_depth=0,
            )
        )

    themes = _merge_chunk_themes(chunk_results)
    log.info("Themes extracted", count=len(themes))
    return themes
