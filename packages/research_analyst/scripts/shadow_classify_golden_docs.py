#!/usr/bin/env python3
"""Run shadow decision classification over a small set of public golden docs.

Eval-only: extracts AssertionDrafts deterministically, classifies via the
configured DecisionModel (use --provider jev for live), and writes sidecar
artifacts. Does not touch analyze_document or production outputs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running as `python scripts/...` from the package root.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from research_analysis_layer.config import Settings
from research_analysis_layer.evals.decision_artifacts import write_shadow_artifact
from research_analysis_layer.evals.decision_classifier import (
    ShadowDecisionClassifier,
    assertion_unit_id,
)
from research_analysis_layer.evals.runner import load_golden_annotations
from research_analysis_layer.models import AnalysisChunkDraft, EvidenceUnitDraft
from research_analysis_layer.models.assertion_models import normalize_text
from research_analysis_layer.services.assertion_extractor import AssertionExtractor
from research_analysis_layer.services.decision_model_factory import (
    DecisionModelConfigError,
    build_decision_model,
)


def _full_text(content: str) -> str:
    match = re.search(
        r"## Full Text Excerpt\n(.*?)(?=\n---|\n## Themes)",
        content,
        re.DOTALL,
    )
    return match.group(1).strip() if match else content.strip()


def _paragraph_chunks(text: str) -> list[AnalysisChunkDraft]:
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[AnalysisChunkDraft] = []
    for idx, part in enumerate(parts, start=1):
        # Drop pure markdown heading-only crumbs.
        body = re.sub(r"^#+\s*", "", part).strip()
        if len(body) < 40:
            continue
        title = body.split("\n", 1)[0][:80]
        chunks.append(
            AnalysisChunkDraft(
                chunk_order=len(chunks) + 1,
                chunk_type="retrieval_chunk",
                title=title,
                text=body,
                section_name=None,
            )
        )
    return chunks


def _extract_assertions(text: str) -> tuple[list, dict[str, dict], dict[str, str]]:
    extractor = AssertionExtractor()
    chunks = _paragraph_chunks(text)
    assertions = []
    provenance: dict[str, dict] = {}
    section_by_unit: dict[str, str] = {}
    for chunk in chunks:
        evidence = [
            EvidenceUnitDraft(
                chunk_order=chunk.chunk_order,
                evidence_order=1,
                evidence_type="theme_context",
                text=chunk.text,
                normalized_text=normalize_text(chunk.text),
                source_ref={"chunk_key": f"chunk-{chunk.chunk_order}"},
            )
        ]
        for assertion in extractor.extract(chunk, evidence):
            unit_id = assertion_unit_id(assertion)
            assertions.append(assertion)
            provenance[unit_id] = {
                "assertion_key": unit_id,
                "chunk_key": f"chunk-{assertion.chunk_order}",
                "doc_section_title": chunk.title,
            }
            section_by_unit[unit_id] = chunk.title
    return assertions, provenance, section_by_unit


def _readable_rows(artifact) -> list[dict]:
    rows = []
    for unit in artifact.units:
        choice = next(
            (r for r in unit.results if r.question_id == "statement_type"), None
        )
        dist = choice.distribution if choice and choice.distribution else None
        noul_yes = []
        for r in unit.results:
            if r.question_id == "statement_type" or not r.distribution:
                continue
            if r.distribution.selected == "yes" and (r.distribution.raw_probability or 0) >= 0.55:
                noul_yes.append(
                    {
                        "id": r.question_id,
                        "p_yes": r.distribution.raw_probability,
                    }
                )
        noul_yes.sort(key=lambda item: item["p_yes"] or 0, reverse=True)
        rows.append(
            {
                "unit_id": unit.unit_id,
                "text": unit.source_text,
                "deterministic_assertion_type": unit.assertion_type,
                "statement_type": dist.selected if dist else None,
                "statement_type_p": dist.raw_probability if dist else None,
                "statement_type_top": (
                    sorted(
                        (dist.probabilities or {}).items(),
                        key=lambda kv: kv[1],
                        reverse=True,
                    )[:3]
                    if dist
                    else []
                ),
                "noul_yes": noul_yes,
                "coverage_status": unit.coverage_status,
                "provenance": unit.provenance,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--golden",
        type=Path,
        default=Path("evals/golden"),
        help="Golden dataset directory",
    )
    parser.add_argument(
        "--docs",
        type=str,
        default="doc_001,doc_002,doc_003,doc_004,doc_007",
        help="Comma-separated golden document_ids",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="fake",
        choices=["fake", "jev"],
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Durable output directory for artifacts + review index",
    )
    parser.add_argument("--batch-size", type=int, default=2)
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    try:
        model = build_decision_model(settings, provider=args.provider)
    except DecisionModelConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    annotations = load_golden_annotations(args.golden)
    doc_ids = [d.strip() for d in args.docs.split(",") if d.strip()]
    classifier = ShadowDecisionClassifier(model, batch_size=args.batch_size)
    args.output.mkdir(parents=True, exist_ok=True)

    index: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": args.provider,
        "question_set_note": "decision-question-set from package constants",
        "documents": [],
        "total_units": 0,
    }

    for doc_id in doc_ids:
        if doc_id not in annotations:
            print(f"Error: unknown document_id {doc_id}", file=sys.stderr)
            return 1
        info = annotations[doc_id]
        path = args.golden / info["document_path"]
        content = path.read_text(encoding="utf-8")
        text = _full_text(content)
        assertions, provenance, sections = _extract_assertions(text)
        artifact = classifier.classify_assertions(
            assertions,
            document_key=doc_id,
            document_hash=None,
            shared_context=f"Golden eval document {doc_id} ({info.get('source_type')})",
            provenance_by_unit=provenance,
            section_context_by_unit=sections,
            source_metadata={
                "document_path": info["document_path"],
                "source_type": info.get("source_type"),
            },
        )
        art_path = write_shadow_artifact(artifact, args.output, prefix=f"shadow_{doc_id}")
        readable = _readable_rows(artifact)
        readable_path = args.output / f"review_{doc_id}.json"
        readable_path.write_text(
            json.dumps(
                {
                    "document_id": doc_id,
                    "document_path": info["document_path"],
                    "source_type": info.get("source_type"),
                    "unit_count": len(readable),
                    "units": readable,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        index["documents"].append(
            {
                "document_id": doc_id,
                "document_path": info["document_path"],
                "source_type": info.get("source_type"),
                "unit_count": len(readable),
                "artifact": art_path.name,
                "review_json": readable_path.name,
                "coverage_full": sum(
                    1 for u in artifact.units if u.coverage_status == "full"
                ),
                "incomplete_batches": artifact.incomplete_batch_count,
                "permanent_errors": artifact.permanent_error_count,
                "usage": artifact.usage,
            }
        )
        index["total_units"] += len(readable)
        print(
            f"{doc_id}: {len(readable)} units -> {art_path.name}",
            flush=True,
        )

    index_path = args.output / "index.json"
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    # Flat review table for quick scanning.
    lines = [
        "# 5-doc Jev shadow review table",
        "",
        f"Provider: `{args.provider}`  ",
        f"Created: {index['created_at']}  ",
        f"Total units: {index['total_units']}",
        "",
        "| doc | unit_id | statement_type (p) | top nouls | text |",
        "|---|---|---|---|---|",
    ]
    for doc in index["documents"]:
        review = json.loads((args.output / doc["review_json"]).read_text(encoding="utf-8"))
        for unit in review["units"]:
            nouls = ", ".join(
                f"{n['id']}={n['p_yes']:.2f}" for n in unit["noul_yes"][:4]
            ) or "—"
            text = unit["text"].replace("|", "\\|").replace("\n", " ")
            if len(text) > 120:
                text = text[:117] + "…"
            st = unit["statement_type"] or "?"
            sp = unit["statement_type_p"]
            st_cell = f"{st}" if sp is None else f"{st} ({sp:.2f})"
            lines.append(
                f"| {doc['document_id']} | `{unit['unit_id']}` | {st_cell} | {nouls} | {text} |"
            )
    table_path = args.output / "REVIEW_TABLE.md"
    table_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote index: {index_path}")
    print(f"Wrote table: {table_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
