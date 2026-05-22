"""Strip boilerplate text from financial research documents."""

from datetime import datetime, timezone
from functools import lru_cache
import json
from pathlib import Path
import re

import structlog
import yaml
from tenacity import retry, stop_after_attempt, wait_random_exponential

from src.llm import LLMClient, ModelConfig

from .prompts import get_boilerplate_prompt

logger = structlog.get_logger()
RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "boilerplate_rules.yaml"
LEARNED_ARTIFACTS_DIR = Path(__file__).resolve().parents[2] / "data" / "boilerplate_artifacts"
LEARNED_ARTIFACTS_PATH = LEARNED_ARTIFACTS_DIR / "llm_boilerplate_artifacts.jsonl"


@retry(
    stop=stop_after_attempt(5),
    wait=wait_random_exponential(multiplier=1, min=2, max=45),
    reraise=True,
)
def strip_boilerplate(
    client: LLMClient,
    text: str,
    config: ModelConfig,
    log=None,
    deterministic_only: bool = False,
    document_name: str | None = None,
    source_hint: str | None = None,
    artifact_dir: Path | None = None,
) -> str:
    """
    Strip boilerplate sections from a financial research document.

    Uses the configured model to remove legal disclaimers, disclosures,
    and other non-research content.
    """
    log = log or logger
    log.info(
        "Stripping boilerplate",
        text_length=len(text),
        provider=config.provider,
        model=config.model,
    )

    deterministic, match_info = _strip_boilerplate_deterministic(
        text,
        document_name=document_name,
        source_hint=source_hint,
    )
    if deterministic is not None:
        log.info(
            "Boilerplate stripped (deterministic)",
            original_length=len(text),
            result_length=len(deterministic),
            reduction=f"{(1 - len(deterministic) / len(text)) * 100:.1f}%",
            match_info=match_info,
        )
        return deterministic
    if match_info is not None:
        log.info(
            "Deterministic strip did not meet confidence thresholds",
            match_info=match_info,
        )
    if deterministic_only:
        log.info("Boilerplate header not found, deterministic-only enabled")
        return text
    log.info("Boilerplate header not found, falling back to LLM")

    result = client.generate(
        config=config,
        system=get_boilerplate_prompt(),
        user=text,
    )

    # Safeguard: if result is suspiciously short, fall back to original
    # This prevents downstream extraction from failing on empty/minimal content
    min_reasonable_length = min(2000, len(text) * 0.05)  # At least 5% or 2000 chars
    reduction = 1 - (len(result) / len(text)) if text else 0
    max_reasonable_reduction = 0.90
    placeholder_markers = (
        "[remaining content",
        "[content omitted",
        "[exhibits",
        "the rest of the document continues",
        "with boilerplate sections removed",
        "here is the filtered document",
        "i will filter the document",
        "document remains unchanged",
    )
    placeholder_detected = any(marker in result.lower() for marker in placeholder_markers)
    if len(result) < min_reasonable_length or reduction > max_reasonable_reduction or placeholder_detected:
        sample_len = 500
        log.warning(
            "Boilerplate result suspiciously short, using original",
            original_length=len(text),
            result_length=len(result),
            min_threshold=min_reasonable_length,
            reduction=f"{reduction * 100:.1f}%",
            max_reduction=f"{max_reasonable_reduction * 100:.0f}%",
            placeholder_detected=placeholder_detected,
            result_preview_start=result[:sample_len],
            result_preview_end=result[-sample_len:] if len(result) > sample_len else "",
        )
        return text

    log.info(
        "Boilerplate stripped",
        original_length=len(text),
        result_length=len(result),
        reduction=f"{(1 - len(result) / len(text)) * 100:.1f}%",
    )
    _persist_llm_boilerplate_artifacts(
        original_text=text,
        cleaned_text=result,
        config=config,
        document_name=document_name,
        source_hint=source_hint,
        artifact_dir=artifact_dir,
        log=log,
    )

    return result


_BOILERPLATE_HEADERS = [
    "appendix",
    "analyst certification",
    "analyst certifications",
    "analyst certification",
    "analyst disclosure",
    "analyst disclosures",
    "analyst compensation",
    "analyst coverage",
    "important disclosure",
    "important disclosures",
    "important disclosure",
    "important disclosures",
    "important information",
    "important legal information",
    "important legal disclosures",
    "additional information",
    "disclosure",
    "disclosures",
    "other disclosures",
    "company-specific disclosures",
    "disclosures and disclaimers",
    "research disclosures",
    "legal disclaimer",
    "legal disclosure",
    "legal disclosures",
    "legal and regulatory disclosures",
    "regulatory and legal disclosures",
    "notices and disclaimers",
    "disclaimer",
    "disclaimers",
    "regulatory disclosure",
    "regulatory disclosures",
    "conflict of interest",
    "conflicts of interest",
    "company specific disclosures",
    "investor disclosures",
    "risk disclosures",
    "distribution",
    "copyright",
]


_LEGAL_MARKERS = [
    "analyst certification",
    "analyst certifications",
    "analyst disclosure",
    "analyst disclosures",
    "important disclosure",
    "important disclosures",
    "important legal",
    "conflict of interest",
    "conflicts of interest",
    "disclaimer",
    "disclosures and disclaimers",
    "regulatory",
    "distribution",
    "research analyst",
    "investment banking",
    "compensation",
    "rating history",
    "price target",
    "non us analyst disclosure",
    "us analyst disclosure",
    "copyright",
]


@lru_cache(maxsize=1)
def _load_rules() -> dict:
    """Load deterministic boilerplate rules from config."""
    if not RULES_PATH.exists():
        return {}
    with open(RULES_PATH) as f:
        data = yaml.safe_load(f) or {}
    return data


@lru_cache(maxsize=1)
def _load_learned_headers() -> dict[str, list[str]]:
    """Load normalized learned headers mined from prior LLM fallback artifacts."""
    if not LEARNED_ARTIFACTS_PATH.exists():
        return {}

    counts: dict[str, dict[str, int]] = {}
    try:
        with open(LEARNED_ARTIFACTS_PATH) as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                source_key = rec.get("source_key") or "_global"
                for header in rec.get("candidate_headers", []):
                    normalized = _normalize_candidate(header)
                    if not normalized:
                        continue
                    counts.setdefault(source_key, {})
                    counts[source_key][normalized] = counts[source_key].get(normalized, 0) + 1
    except Exception:
        return {}

    learned: dict[str, list[str]] = {}
    for source_key, header_counts in counts.items():
        # Keep a bounded ranked set; allow count>=1 so new artifacts can help quickly.
        ranked = sorted(header_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        learned[source_key] = [header for header, _ in ranked[:80]]
    return learned


def _infer_source_key(
    rules: dict,
    text: str,
    document_name: str | None = None,
    source_hint: str | None = None,
) -> str | None:
    """Infer source key using explicit hint, file name, and text head."""
    sources = rules.get("sources", {})
    if source_hint:
        hint = source_hint.strip().lower()
        if hint in sources:
            return hint

    file_haystack = (document_name or "").lower()
    text_haystack = text[:6000].lower()
    for key, cfg in sources.items():
        aliases = [a.lower() for a in cfg.get("aliases", [])]
        if any(alias and alias in file_haystack for alias in aliases):
            return key
        if any(alias and alias in text_haystack for alias in aliases):
            return key
    return None


def _profile_for_source(rules: dict, source_key: str | None) -> dict:
    """Merge default rules with optional source-specific overrides."""
    defaults = rules.get("defaults", {})
    source_cfg = rules.get("sources", {}).get(source_key or "", {})
    learned = _load_learned_headers()
    learned_headers = learned.get("_global", []) + learned.get(source_key or "", [])
    headers = list(dict.fromkeys(
        defaults.get("headers", _BOILERPLATE_HEADERS)
        + source_cfg.get("headers", [])
        + learned_headers
    ))
    markers = list(dict.fromkeys(
        defaults.get("markers", _LEGAL_MARKERS)
        + source_cfg.get("markers", [])
    ))
    return {
        "source_key": source_key,
        "headers": [h.lower().strip() for h in headers if h],
        "markers": [m.lower().strip() for m in markers if m],
        "min_fraction": source_cfg.get("min_fraction", defaults.get("min_fraction", 0.7)),
        "density_window_lines": source_cfg.get(
            "density_window_lines",
            defaults.get("density_window_lines", 40),
        ),
        "min_density": source_cfg.get("min_density", defaults.get("min_density", 0.12)),
        "min_hits": source_cfg.get("min_hits", defaults.get("min_hits", 3)),
    }


def _is_parser_noise(line: str) -> bool:
    """Identify parser artifact lines that should not drive deterministic matching."""
    lower = line.lower()
    if "data:image/" in lower:
        return True
    if "<bound method" in lower:
        return True
    if lower.startswith("![figure") and "pictureitem" in lower:
        return True
    return False


def _normalize_candidate(line: str) -> str:
    """Normalize a line for stable header detection."""
    stripped = line.strip()
    if not stripped:
        return ""
    candidate = stripped
    if ":" in stripped:
        head = stripped.split(":", 1)[0]
        if head and len(head) <= 120:
            candidate = head
    candidate = re.sub(r"^#+\s*", "", candidate)
    return re.sub(r"^[\W_]*(\d+(\.\d+)*)\s+|[\s\-:]+$", "", candidate).lower()


def _normalize_line_for_match(line: str) -> str:
    """Normalize line for structural matching between original and cleaned outputs."""
    return re.sub(r"\s+", " ", line.strip())


def _common_prefix_lines(original_lines: list[str], cleaned_lines: list[str]) -> int:
    """Count shared leading lines between original and cleaned text."""
    limit = min(len(original_lines), len(cleaned_lines))
    idx = 0
    while idx < limit:
        if _normalize_line_for_match(original_lines[idx]) != _normalize_line_for_match(cleaned_lines[idx]):
            break
        idx += 1
    return idx


def _extract_candidate_headers(removed_lines: list[str], markers: list[str]) -> list[str]:
    """Extract short legal-looking header candidates from removed section."""
    candidates: list[str] = []
    legal_header_tokens = (
        "disclosure",
        "disclosures",
        "disclaimer",
        "certification",
        "conflict",
        "regulatory",
        "distribution",
        "copyright",
        "analyst",
        "legal",
    )
    for line in removed_lines:
        if _is_parser_noise(line):
            continue
        normalized = _normalize_candidate(line)
        if not normalized or len(normalized) > 120:
            continue
        has_legal_token = any(token in normalized for token in legal_header_tokens)
        has_marker = any(marker in normalized for marker in markers)
        if has_legal_token or has_marker:
            candidates.append(normalized)
        if len(candidates) >= 12:
            break
    # Preserve order while deduplicating.
    return list(dict.fromkeys(candidates))


def _persist_llm_boilerplate_artifacts(
    *,
    original_text: str,
    cleaned_text: str,
    config: ModelConfig,
    document_name: str | None,
    source_hint: str | None,
    artifact_dir: Path | None,
    log,
) -> None:
    """Persist boilerplate learning artifacts from successful LLM fallback runs."""
    original_lines = original_text.splitlines()
    cleaned_lines = cleaned_text.splitlines()
    prefix_lines = _common_prefix_lines(original_lines, cleaned_lines)
    cleaned_line_count = max(len(cleaned_lines), 1)

    # If cleaned output does not align with original structure, skip learning capture.
    if prefix_lines < max(8, int(cleaned_line_count * 0.25)):
        log.info(
            "Skipping boilerplate artifact persistence due low structural overlap",
            prefix_lines=prefix_lines,
            cleaned_lines=cleaned_line_count,
        )
        return
    if prefix_lines >= len(original_lines):
        return

    rules = _load_rules()
    source_key = _infer_source_key(
        rules=rules,
        text=original_text,
        document_name=document_name,
        source_hint=source_hint,
    )
    profile = _profile_for_source(rules, source_key)
    markers = profile["markers"] or _LEGAL_MARKERS
    removed_lines = original_lines[prefix_lines:]
    candidate_headers = _extract_candidate_headers(removed_lines, markers)

    marker_lines = []
    for line in removed_lines:
        if any(marker in line.lower() for marker in markers):
            marker_lines.append(line.strip())
        if len(marker_lines) >= 8:
            break

    record = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "document_name": document_name,
        "source_key": source_key,
        "provider": config.provider,
        "model": config.model,
        "original_length": len(original_text),
        "result_length": len(cleaned_text),
        "reduction_ratio": round(1 - (len(cleaned_text) / max(len(original_text), 1)), 4),
        "cut_line_index": prefix_lines + 1,
        "total_lines": len(original_lines),
        "candidate_headers": candidate_headers,
        "marker_lines": marker_lines,
    }

    LEARNED_ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LEARNED_ARTIFACTS_PATH, "a") as f:
        f.write(json.dumps(record, ensure_ascii=True) + "\n")

    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / "boilerplate_llm_artifact.json"
        with open(artifact_path, "w") as f:
            json.dump(record, f, indent=2, ensure_ascii=True)

    # Ensure newly written artifacts can be used by deterministic checks on future calls.
    _load_learned_headers.cache_clear()
    log.info(
        "Boilerplate artifact persisted",
        source_key=source_key,
        candidate_headers=len(candidate_headers),
        learned_artifacts_path=str(LEARNED_ARTIFACTS_PATH),
    )


def _legal_density(
    lines: list[str],
    start_idx: int,
    markers: list[str],
    window_lines: int,
) -> tuple[float, int]:
    """Return legal phrase density and hit count in a post-header window."""
    end_idx = min(len(lines), start_idx + max(window_lines, 1))
    window = lines[start_idx:end_idx]
    hits = 0
    for raw in window:
        lower = raw.lower()
        if any(marker in lower for marker in markers):
            hits += 1
    size = max(len(window), 1)
    return hits / size, hits


def _classify_confidence(
    density: float,
    hits: int,
    line_fraction: float,
    min_density: float,
    min_hits: int,
) -> str:
    """Classify deterministic confidence for logging and gating."""
    strong_density = density >= (min_density * 1.8)
    strong_hits = hits >= (min_hits * 2)
    late_in_doc = line_fraction >= 0.8
    if strong_density and strong_hits and late_in_doc:
        return "high"
    if density >= min_density and hits >= min_hits:
        return "medium"
    return "low"


def _strip_boilerplate_deterministic(
    text: str,
    document_name: str | None = None,
    source_hint: str | None = None,
) -> tuple[str | None, dict | None]:
    """Strip boilerplate by truncating from a high-confidence header."""
    lines = text.splitlines()
    total_lines = max(len(lines), 1)
    rules = _load_rules()
    source_key = _infer_source_key(
        rules=rules,
        text=text,
        document_name=document_name,
        source_hint=source_hint,
    )
    profile = _profile_for_source(rules, source_key)
    headers = profile["headers"] or _BOILERPLATE_HEADERS
    markers = profile["markers"] or _LEGAL_MARKERS
    min_fraction = profile["min_fraction"]  # Boilerplate is expected near the end.
    min_density = profile["min_density"]
    min_hits = profile["min_hits"]
    density_window_lines = profile["density_window_lines"]

    first_early_match: dict | None = None
    best_rejected_match: dict | None = None
    for idx, line in enumerate(lines):
        if _is_parser_noise(line):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        candidate = _normalize_candidate(stripped)
        # Skip very long lines to avoid matching within paragraphs.
        if len(candidate) > 120:
            continue
        for header in headers:
            if candidate == header or re.match(rf"^{re.escape(header)}(\s|$)", candidate):
                line_fraction = idx / total_lines
                match_info = {
                    "line_index": idx + 1,
                    "total_lines": total_lines,
                    "line": stripped,
                    "source_key": source_key,
                    "header": header,
                }
                if (idx / total_lines) >= min_fraction:
                    density, hits = _legal_density(
                        lines=lines,
                        start_idx=idx,
                        markers=markers,
                        window_lines=density_window_lines,
                    )
                    confidence = _classify_confidence(
                        density=density,
                        hits=hits,
                        line_fraction=line_fraction,
                        min_density=min_density,
                        min_hits=min_hits,
                    )
                    candidate_info = {
                        **match_info,
                        "legal_density": round(density, 4),
                        "legal_hits": hits,
                        "line_fraction": round(line_fraction, 4),
                        "confidence": confidence,
                    }
                    if density >= min_density and hits >= min_hits:
                        return "\n".join(lines[:idx]).rstrip(), candidate_info
                    candidate_info["reason"] = "low_legal_density"
                    if (
                        best_rejected_match is None
                        or candidate_info["legal_density"] > best_rejected_match["legal_density"]
                    ):
                        best_rejected_match = candidate_info
                if first_early_match is None:
                    first_early_match = {
                        **match_info,
                        "reason": "header_too_early",
                        "line_fraction": round(line_fraction, 4),
                    }
                break
    if best_rejected_match is not None:
        return None, best_rejected_match
    return None, first_early_match
