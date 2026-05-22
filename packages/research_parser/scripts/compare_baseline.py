#!/usr/bin/env python3
"""Record and compare extraction baselines for a set of documents."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.config import get_settings
from src.drive import DriveWatcher
from src.extraction import (
    extract_metadata,
    extract_themes,
    extract_trades,
    strip_boilerplate,
)
from src.llm import LLMClient, load_model_config
from src.parser import DoclingBackend, LlamaIndexBackend, LlamaIndexParser


DEFAULT_METADATA = {
    "source": "Unknown",
    "area": "Other",
    "region": "Global",
    "asset_focus": "multi-asset",
}


@dataclass
class DocumentSpec:
    key: str
    name: str
    file_id: str | None = None
    path: Path | None = None


def _normalize_label(label: str) -> str:
    return " ".join(label.lower().split())


def _trade_signature(text: str, word_limit: int = 10) -> str:
    words = [w.strip(".,;:()[]{}") for w in text.lower().split()]
    words = [w for w in words if w]
    return " ".join(words[:word_limit])


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _load_manifest(path: Path) -> list[DocumentSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("documents", data)
    specs: list[DocumentSpec] = []
    for item in items:
        name = item.get("name") or item.get("file_name") or item.get("path") or item.get("id")
        file_id = item.get("id") or item.get("file_id")
        file_path = item.get("path")
        if not name:
            raise ValueError("Each manifest entry must include at least one of: name, path, id")
        if file_id:
            key = f"drive:{file_id}"
            specs.append(DocumentSpec(key=key, name=name, file_id=file_id))
        elif file_path:
            path_obj = Path(file_path)
            key = f"path:{path_obj}"
            specs.append(DocumentSpec(key=key, name=name, path=path_obj))
        else:
            raise ValueError(f"Manifest entry for {name} missing id or path")
    return specs


def _parse_document(path: Path, settings, model_config) -> str:
    docling_backend = DoclingBackend()
    llama_backend = LlamaIndexBackend(
        parser=LlamaIndexParser(api_key=settings.llamaindex_api_key)
    )
    try:
        text_result = docling_backend.parse_text(path)
        markdown = text_result.raw_output
    except Exception:
        markdown = None
    if not markdown:
        text_result = llama_backend.parse_text(path)
        markdown = text_result.raw_output
    if not markdown:
        raise RuntimeError("Parser returned empty markdown")
    return markdown


def _load_document(spec: DocumentSpec, settings) -> Path:
    if spec.path is not None:
        if not spec.path.exists():
            raise FileNotFoundError(f"Missing local file: {spec.path}")
        return spec.path
    if spec.file_id:
        watcher = DriveWatcher(
            credentials_path=settings.google_credentials_path,
            folder_id=settings.google_drive_folder_id,
        )
        return watcher.download_file(spec.file_id, spec.name)
    raise ValueError(f"Document spec {spec.name} missing path and id")


def _summarize_document(
    spec: DocumentSpec,
    settings,
    model_config,
    deterministic_only: bool,
) -> dict[str, Any]:
    path = _load_document(spec, settings)
    try:
        markdown = _parse_document(path, settings, model_config)
        client = LLMClient(
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=settings.openai_api_key,
            groq_api_key=getattr(settings, "groq_api_key", None),
            deepinfra_api_key=getattr(settings, "deepinfra_api_key", None),
            openrouter_api_key=getattr(settings, "openrouter_api_key", None),
            fireworks_api_key=getattr(settings, "fireworks_api_key", None),
            together_api_key=getattr(settings, "together_api_key", None),
        )
        clean_text = strip_boilerplate(
            client,
            markdown,
            config=model_config.boilerplate,
            deterministic_only=deterministic_only,
            document_name=spec.name,
            artifact_dir=settings.artifact_base_dir / f"compare_baseline_{spec.key}",
        )
        metadata = extract_metadata(client, clean_text, config=model_config.metadata)
        themes = extract_themes(client, clean_text, config=model_config.themes)
        trades = extract_trades(client, clean_text, config=model_config.trades)
    finally:
        if spec.file_id and path.exists():
            try:
                os.unlink(path)
            except Exception:
                pass

    theme_labels = [_normalize_label(t.label) for t in themes]
    trade_sigs = [_trade_signature(t.text) for t in trades]
    return {
        "key": spec.key,
        "name": spec.name,
        "metadata": {
            "source": metadata.source,
            "area": metadata.area,
            "region": metadata.region,
            "asset_focus": metadata.asset_focus,
        },
        "theme_count": len(themes),
        "trade_count": len(trades),
        "theme_labels": theme_labels,
        "trade_signatures": trade_sigs,
    }


def _compare_document(
    baseline: dict[str, Any],
    current: dict[str, Any],
    theme_delta: int,
    trade_delta: int,
    min_theme_jaccard: float,
    min_trade_jaccard: float,
    strict_metadata: bool,
) -> tuple[bool, list[str]]:
    failures: list[str] = []

    baseline_metadata = baseline.get("metadata", {})
    current_metadata = current.get("metadata", {})
    for field, default_value in DEFAULT_METADATA.items():
        baseline_value = baseline_metadata.get(field)
        current_value = current_metadata.get(field)
        if baseline_value is None:
            continue
        if not strict_metadata and baseline_value == default_value:
            continue
        if str(baseline_value).strip().lower() != str(current_value).strip().lower():
            failures.append(
                f"metadata.{field} mismatch (baseline={baseline_value}, current={current_value})"
            )

    baseline_themes = set(baseline.get("theme_labels") or [])
    current_themes = set(current.get("theme_labels") or [])
    baseline_trades = set(baseline.get("trade_signatures") or [])
    current_trades = set(current.get("trade_signatures") or [])

    theme_count = current.get("theme_count", 0)
    trade_count = current.get("trade_count", 0)

    if abs(theme_count - baseline.get("theme_count", 0)) > theme_delta:
        failures.append(
            f"theme_count delta too large (baseline={baseline.get('theme_count')}, current={theme_count})"
        )
    if abs(trade_count - baseline.get("trade_count", 0)) > trade_delta:
        failures.append(
            f"trade_count delta too large (baseline={baseline.get('trade_count')}, current={trade_count})"
        )

    theme_jaccard = _jaccard(baseline_themes, current_themes)
    trade_jaccard = _jaccard(baseline_trades, current_trades)
    if baseline_themes and theme_jaccard < min_theme_jaccard:
        failures.append(
            f"theme label overlap low (jaccard={theme_jaccard:.2f})"
        )
    if baseline_trades and trade_jaccard < min_trade_jaccard:
        failures.append(
            f"trade signature overlap low (jaccard={trade_jaccard:.2f})"
        )

    return (len(failures) == 0), failures


def main() -> None:
    parser = argparse.ArgumentParser(description="Record or compare extraction baselines.")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to JSON manifest")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/baselines/baseline.json"),
        help="Path to baseline output (record mode)",
    )
    parser.add_argument(
        "--mode",
        choices=("record", "compare"),
        default="compare",
        help="Record a baseline or compare to an existing baseline",
    )
    parser.add_argument("--theme-delta", type=int, default=1)
    parser.add_argument("--trade-delta", type=int, default=1)
    parser.add_argument("--min-theme-jaccard", type=float, default=0.4)
    parser.add_argument("--min-trade-jaccard", type=float, default=0.2)
    parser.add_argument("--strict-metadata", action="store_true")
    parser.add_argument("--deterministic-only", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    model_config = load_model_config(config_path=settings.model_config_path)
    specs = _load_manifest(args.manifest)

    if args.mode == "record":
        summaries = [
            _summarize_document(
                spec, settings, model_config, deterministic_only=args.deterministic_only
            )
            for spec in specs
        ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "documents": summaries,
        }
        args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Wrote baseline to {args.output}")
        return

    baseline_payload = json.loads(args.output.read_text(encoding="utf-8"))
    baseline_docs = {doc["key"]: doc for doc in baseline_payload.get("documents", [])}

    all_ok = True
    for spec in specs:
        baseline = baseline_docs.get(spec.key)
        if not baseline:
            print(f"[WARN] No baseline found for {spec.name} ({spec.key})")
            all_ok = False
            continue
        current = _summarize_document(
            spec, settings, model_config, deterministic_only=args.deterministic_only
        )
        ok, failures = _compare_document(
            baseline,
            current,
            theme_delta=args.theme_delta,
            trade_delta=args.trade_delta,
            min_theme_jaccard=args.min_theme_jaccard,
            min_trade_jaccard=args.min_trade_jaccard,
            strict_metadata=args.strict_metadata,
        )
        if ok:
            print(f"[PASS] {spec.name}")
        else:
            all_ok = False
            print(f"[FAIL] {spec.name}")
            for failure in failures:
                print(f"  - {failure}")

    if not all_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
