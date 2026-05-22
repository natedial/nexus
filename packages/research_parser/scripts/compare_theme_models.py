#!/usr/bin/env python3
"""Compare theme extraction quality/latency across model choices."""

from __future__ import annotations

import argparse
import json
import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from src.config import get_settings
from src.extraction import extract_themes, strip_boilerplate
from src.llm import LLMClient, ModelConfig, load_model_config


def _parse_model_spec(spec: str, default_max_tokens: int) -> ModelConfig:
    try:
        provider, model = spec.split(":", 1)
    except ValueError as exc:
        raise ValueError(f"Invalid model spec {spec!r}; expected provider:model") from exc
    return ModelConfig(
        provider=provider,
        model=model,
        max_tokens=default_max_tokens,
        temperature=0,
    )


@dataclass
class DocumentSpec:
    artifact: Path
    document_name: str


class ModelTimeoutError(TimeoutError):
    """Raised when a model comparison exceeds the wall-clock budget."""


def _write_snapshot(output_path: Path | None, payload: dict) -> None:
    if not output_path:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _emit_progress(message: str) -> None:
    print(message, flush=True)


def _serialize_themes(themes) -> list[dict]:
    serialized = []
    for theme in themes:
        serialized.append(
            {
                "label": theme.label,
                "relevance": theme.relevance,
                "classification": theme.classification,
                "mention_count": theme.mention_count,
                "strength": theme.strength,
                "confidence": theme.confidence,
                "context": theme.context,
                "directionality": theme.directionality,
                "excerpts": [excerpt.text for excerpt in theme.excerpts],
            }
        )
    return serialized


@contextmanager
def _wall_clock_timeout(seconds: int | None):
    if not seconds or seconds <= 0:
        yield
        return

    def _handle_timeout(signum, frame):
        raise ModelTimeoutError(f"Timed out after {seconds}s")

    previous = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _handle_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def _load_documents(args) -> list[DocumentSpec]:
    if args.manifest:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
        items = payload.get("documents", payload)
        return [
            DocumentSpec(
                artifact=Path(item["artifact"]),
                document_name=item["document_name"],
            )
            for item in items
        ]
    if args.artifact and args.document_name:
        return [DocumentSpec(artifact=args.artifact, document_name=args.document_name)]
    raise ValueError("Provide either --manifest or both --artifact and --document-name")


def _compare_document(
    spec: DocumentSpec,
    client: LLMClient,
    config,
    settings,
    model_specs: list[str],
    max_tokens: int,
    per_model_timeout: int | None,
    disable_extraction_retry: bool,
) -> dict:
    _emit_progress(f"[start] {spec.document_name}")
    markdown = spec.artifact.read_text(encoding="utf-8")
    clean_text = strip_boilerplate(
        client,
        markdown,
        config=config.boilerplate,
        deterministic_only=settings.boilerplate_deterministic_only,
        document_name=spec.document_name,
        artifact_dir=settings.artifact_base_dir / f"compare_theme_{spec.artifact.stem}",
    )

    results = []
    for model_spec in model_specs:
        model_cfg = _parse_model_spec(model_spec, max_tokens)
        start = time.time()
        _emit_progress(f"[model] {spec.document_name} :: {model_spec}")
        try:
            extractor = extract_themes.__wrapped__ if disable_extraction_retry else extract_themes
            with _wall_clock_timeout(per_model_timeout):
                themes = extractor(client, clean_text, config=model_cfg)
            result = {
                "model": model_spec,
                "elapsed_s": round(time.time() - start, 2),
                "count": len(themes),
                "labels": [theme.label for theme in themes],
                "themes": _serialize_themes(themes),
            }
            results.append(result)
            _emit_progress(
                f"[done] {spec.document_name} :: {model_spec} :: {result['elapsed_s']}s :: {result['count']} themes"
            )
        except Exception as exc:
            result = {
                "model": model_spec,
                "elapsed_s": round(time.time() - start, 2),
                "error": f"{type(exc).__name__}: {exc}",
            }
            results.append(result)
            _emit_progress(
                f"[error] {spec.document_name} :: {model_spec} :: {result['elapsed_s']}s :: {result['error']}"
            )
    return {
        "artifact": str(spec.artifact),
        "document_name": spec.document_name,
        "clean_chars": len(clean_text),
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare theme models on a cleaned artifact.")
    parser.add_argument("--artifact", type=Path, help="Path to a single document markdown artifact")
    parser.add_argument("--document-name", help="Document name for single-artifact mode")
    parser.add_argument("--manifest", type=Path, help="JSON manifest for multi-document mode")
    parser.add_argument(
        "--model",
        action="append",
        required=True,
        help="Repeated provider:model entries to compare, e.g. deepinfra:moonshotai/Kimi-K2-Instruct-0905",
    )
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--per-model-timeout", type=int, default=150)
    parser.add_argument(
        "--disable-extraction-retry",
        action="store_true",
        help="Bypass the retry wrapper around theme extraction for cleaner evaluation runs",
    )
    parser.add_argument("--output", type=Path, help="Optional path to write JSON results")
    args = parser.parse_args()

    settings = get_settings()
    config = load_model_config(config_path=settings.model_config_path)
    docs = _load_documents(args)
    client = LLMClient(
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
        groq_api_key=settings.groq_api_key,
        deepinfra_api_key=settings.deepinfra_api_key,
        openrouter_api_key=settings.openrouter_api_key,
        fireworks_api_key=settings.fireworks_api_key,
        together_api_key=settings.together_api_key,
    )
    payload = {"documents": []}
    for doc in docs:
        payload["documents"].append(
            _compare_document(
                spec=doc,
                client=client,
                config=config,
                settings=settings,
                model_specs=args.model,
                max_tokens=args.max_tokens,
                per_model_timeout=args.per_model_timeout,
                disable_extraction_retry=args.disable_extraction_retry,
            )
        )
        _write_snapshot(args.output, payload)
    rendered = json.dumps(payload, indent=2)
    _write_snapshot(args.output, payload)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
