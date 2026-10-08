"""One-command standardized decision-model evaluation run directory."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from research_analysis_layer.config import Settings
from research_analysis_layer.evals.decision_artifacts import (
    load_shadow_artifact,
    write_shadow_artifact,
)
from research_analysis_layer.evals.decision_classifier import ShadowDecisionClassifier
from research_analysis_layer.evals.decision_consistency import (
    ConsistencyReport,
    run_consistency_suite,
)
from research_analysis_layer.evals.decision_fixture import (
    fixture_assertions,
    fixture_dir,
    fixture_provenance,
    fixture_section_context,
    load_fixture_labels,
    load_fixture_units,
)
from research_analysis_layer.evals.decision_metrics import (
    estimate_usage_cost,
    evaluate_shadow_artifact,
)
from research_analysis_layer.evals.decision_question_set import snapshot_question_set
from research_analysis_layer.evals.decision_review_queue import (
    ReviewCandidate,
    build_review_queue,
    review_packet_markdown,
)
from research_analysis_layer.evals.decision_reviews import sha256_bytes, sha256_text
from research_analysis_layer.evals.decision_silver import (
    SilverAgreementReport,
    evaluate_silver_agreement,
)
from research_analysis_layer.models.decision_models import (
    ShadowClassificationArtifact,
    UnitClassificationRecord,
)
from research_analysis_layer.services.decision_model_factory import (
    DecisionModelConfigError,
    build_decision_model,
)

RUN_MANIFEST_SCHEMA = "decision-eval-run-manifest-v1"
TOP_LEVEL_OUTPUTS = (
    "run_manifest.json",
    "question_set.json",
    "gold_metrics.json",
    "silver_agreement.json",
    "consistency_report.json",
    "cost_and_latency.json",
    "review_queue.jsonl",
    "review_packet.md",
    "SUMMARY.md",
)


def code_revision(cwd: Path | None = None) -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd or Path(__file__).resolve().parents[3],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return output.strip() or "unknown"


def load_live_artifacts(root: Path) -> list[tuple[Path, ShadowClassificationArtifact]]:
    paths = sorted(root.glob("shadow_*.json"))
    loaded: list[tuple[Path, ShadowClassificationArtifact]] = []
    for path in paths:
        loaded.append((path, load_shadow_artifact(path)))
    return loaded


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _copy_artifact(artifact: ShadowClassificationArtifact, dest_dir: Path, prefix: str) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    return write_shadow_artifact(artifact, dest_dir, prefix=prefix)


def build_summary(
    *,
    gold: Mapping[str, Any],
    silver: SilverAgreementReport,
    consistency: ConsistencyReport,
    cost: Mapping[str, Any],
    queue: Sequence[ReviewCandidate],
    previous: Mapping[str, Any] | None,
    output_dir: Path,
) -> str:
    fixture_gold = gold.get("fixture") or {}
    gold_acc = fixture_gold.get("choice_accuracy")
    gold_support = fixture_gold.get("choice_support")
    prev_acc = None
    if previous and isinstance(previous.get("gold_metrics"), dict):
        prev_acc = ((previous["gold_metrics"] or {}).get("fixture") or {}).get(
            "choice_accuracy"
        )
    changed = "no comparison run supplied"
    if prev_acc is not None and gold_acc is not None:
        delta = gold_acc - prev_acc
        changed = f"fixture choice accuracy {prev_acc:.3f} -> {gold_acc:.3f} (delta {delta:+.3f})"
    elif gold_acc is not None:
        changed = f"fixture choice accuracy {gold_acc:.3f} on {gold_support} labeled units"

    regressions: list[str] = []
    if consistency.invariance_failures:
        regressions.append(
            f"{consistency.invariance_failures} invariance failures "
            f"across {consistency.case_count} consistency cases"
        )
    if silver.disagreements:
        regressions.append(
            f"{len(silver.disagreements)} silver disagreements on {silver.compared} compared labels"
        )

    top_cases = queue[:5]
    lines = [
        "# Decision-model evaluation summary",
        "",
        "This file is the entry point for another agent. Numbers include denominators.",
        "Observed facts are separated from hypotheses.",
        "",
        "## What changed",
        "",
        changed,
        "",
        "## Passes, regressions, unresolved",
        "",
        f"- Gold fixture units scored: {fixture_gold.get('unit_count', 0)} "
        f"(choice support {gold_support or 0})",
        f"- Silver agreement: {silver.agreements}/{silver.compared} included labels "
        f"(rate {silver.agreement_rate})",
        f"- Consistency invariance failures: {consistency.invariance_failures}/"
        f"{consistency.case_count}",
        "",
    ]
    if regressions:
        lines.append("Regressions / concerns:")
        lines.extend(f"- {item}" for item in regressions)
        lines.append("")
    else:
        lines.extend(["No invariance or silver regressions recorded in this run.", ""])
    lines.extend(
        [
            "## Cost and latency",
            "",
            f"- Estimated USD: {cost.get('estimated_usd')}",
            f"- Pricing source: {cost.get('pricing_source')}",
            f"- Usage: `{json.dumps(cost.get('usage') or {}, sort_keys=True)}`",
            "",
            "## Highest-priority review cases",
            "",
        ]
    )
    if not top_cases:
        lines.append("None.")
    for item in top_cases:
        lines.append(
            f"- P{item.priority} `{item.document_id or '-'}` / `{item.unit_id}`: "
            f"{', '.join(item.reasons)}"
        )
    lines.extend(
        [
            "",
            "## Promotion gate",
            "",
            "Unchanged and ineligible. This run does not alter production routing.",
            "",
            "## Supporting outputs",
            "",
            f"- `{output_dir / 'gold_metrics.json'}`",
            f"- `{output_dir / 'silver_agreement.json'}`",
            f"- `{output_dir / 'consistency_report.json'}`",
            f"- `{output_dir / 'cost_and_latency.json'}`",
            f"- `{output_dir / 'review_queue.jsonl'}`",
            f"- `{output_dir / 'review_packet.md'}`",
            f"- `{output_dir / 'run_manifest.json'}`",
            "",
            "## Facts versus hypotheses",
            "",
            "- Fact: gold, silver, and consistency remain separate files.",
            "- Fact: candidates cannot be promoted to gold by this command.",
            "- Hypothesis: a contaminated prefix caused a recommendation label "
            "(requires the context-isolation family, not assumed here).",
            "",
        ]
    )
    return "\n".join(lines)


def run_decision_eval(
    *,
    output_dir: Path,
    provider: str = "fake",
    fixture_path: Path | None = None,
    live_artifact_root: Path | None = None,
    previous_dir: Path | None = None,
    batch_size: int = 4,
    packet_size: int = 20,
    repeatability_runs: int = 3,
    input_usd_per_million: float | None = None,
    output_usd_per_million: float | None = None,
    command_arguments: Mapping[str, Any] | None = None,
) -> Path:
    """Write one immutable run directory. Never promotes gold or routing."""
    if packet_size > 20:
        raise ValueError("packet_size defaults must not exceed 20")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir = output_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    settings = Settings.from_env()
    model = build_decision_model(settings, provider=provider)
    fixture_root = fixture_path or fixture_dir()
    units_payload = load_fixture_units(fixture_root / "units.json")
    assertions = fixture_assertions(fixture_root / "units.json")
    gold_labels = load_fixture_labels(fixture_root / "labels.json")
    classifier = ShadowDecisionClassifier(model, batch_size=batch_size)
    fixture_artifact = classifier.classify_assertions(
        assertions,
        document_key=units_payload.get("document_key"),
        document_hash=units_payload.get("document_hash"),
        shared_context=str(units_payload.get("shared_context") or ""),
        provenance_by_unit=fixture_provenance(fixture_root / "units.json"),
        section_context_by_unit=fixture_section_context(fixture_root / "units.json"),
    )
    _copy_artifact(fixture_artifact, artifacts_dir / "fixture", prefix="fixture")

    live_artifacts: list[ShadowClassificationArtifact] = []
    if live_artifact_root is not None:
        live_dir = artifacts_dir / "live"
        live_dir.mkdir(parents=True, exist_ok=True)
        for path, artifact in load_live_artifacts(live_artifact_root):
            shutil.copy2(path, live_dir / path.name)
            live_artifacts.append(artifact)

    gold_report = evaluate_shadow_artifact(fixture_artifact, gold_labels)
    live_units = [unit for artifact in live_artifacts for unit in artifact.units]
    live_gold = {
        "artifact_count": len(live_artifacts),
        "unit_count": len(live_units),
        "labeled_unit_count": 0,
        "note": "no approved gold attached to live corpus units",
    }
    gold_payload = {
        "schema_version": "decision-gold-metrics-v1",
        "fixture": gold_report.as_dict(),
        "live": live_gold,
    }

    all_units: list[UnitClassificationRecord] = list(fixture_artifact.units) + live_units
    silver = evaluate_silver_agreement(all_units)
    consistency = run_consistency_suite(
        model,
        fixture_drafts=assertions,
        repeatability_runs=repeatability_runs,
    )
    queue = build_review_queue(
        all_units,
        gold_labels=gold_labels,
        silver=silver,
        consistency_cases=consistency.cases,
        packet_size=packet_size,
    )
    packet = review_packet_markdown(queue)

    usage: dict[str, float] = {}
    for artifact in [fixture_artifact, *live_artifacts]:
        for key, value in (artifact.usage or {}).items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                usage[key] = usage.get(key, 0.0) + float(value)
    latencies = [
        float(unit.latency_ms)
        for unit in all_units
        if unit.latency_ms is not None
    ]
    cost = estimate_usage_cost(
        usage,
        provider=fixture_artifact.provider,
        input_usd_per_million=input_usd_per_million,
        output_usd_per_million=output_usd_per_million,
    )
    cost["latency_ms_count"] = len(latencies)
    cost["latency_p50_ms"] = gold_report.latency_p50_ms
    cost["latency_p95_ms"] = gold_report.latency_p95_ms
    cost["schema_version"] = "decision-cost-and-latency-v1"

    question_set = snapshot_question_set()
    previous_payload = None
    if previous_dir is not None:
        previous_gold = previous_dir / "gold_metrics.json"
        if previous_gold.is_file():
            previous_payload = {
                "gold_metrics": json.loads(previous_gold.read_text(encoding="utf-8"))
            }

    summary = build_summary(
        gold=gold_payload,
        silver=silver,
        consistency=consistency,
        cost=cost,
        queue=queue,
        previous=previous_payload,
        output_dir=output_dir,
    )

    _write_json(output_dir / "question_set.json", question_set.model_dump(mode="json"))
    _write_json(output_dir / "gold_metrics.json", gold_payload)
    _write_json(output_dir / "silver_agreement.json", silver.as_dict())
    _write_json(output_dir / "consistency_report.json", consistency.as_dict())
    _write_json(output_dir / "cost_and_latency.json", cost)
    (output_dir / "review_queue.jsonl").write_text(
        "".join(json.dumps(item.as_dict(), sort_keys=True) + "\n" for item in queue),
        encoding="utf-8",
    )
    (output_dir / "review_packet.md").write_text(packet, encoding="utf-8")
    (output_dir / "SUMMARY.md").write_text(summary, encoding="utf-8")

    output_hashes = {
        name: sha256_bytes((output_dir / name).read_bytes())
        for name in TOP_LEVEL_OUTPUTS
        if name != "run_manifest.json" and (output_dir / name).is_file()
    }
    output_hashes["artifacts"] = sha256_text(
        json.dumps(
            sorted(path.relative_to(output_dir).as_posix() for path in artifacts_dir.rglob("*") if path.is_file()),
            separators=(",", ":"),
        )
    )
    created_at = datetime.now(timezone.utc).isoformat()
    manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA,
        "created_at": created_at,
        "code_revision": code_revision(),
        "provider": fixture_artifact.provider,
        "model_version": fixture_artifact.model_version,
        "adapter_version": fixture_artifact.adapter_version,
        "question_set_version": question_set.version,
        "question_set_hash": question_set.content_hash,
        "dataset_versions": {
            "fixture": str(units_payload.get("document_hash") or fixture_root.name),
            "live_artifact_root": None if live_artifact_root is None else str(live_artifact_root),
            "live_artifact_count": len(live_artifacts),
            "live_unit_count": len(live_units),
        },
        "command_arguments": {
            key: str(value) if isinstance(value, Path) else value
            for key, value in dict(command_arguments or {}).items()
        },
        "output_hashes": output_hashes,
        "safety": {
            "gold_silver_consistency_separated": True,
            "candidates_not_promoted_to_gold": True,
            "production_routing_changed": False,
        },
    }
    _write_json(output_dir / "run_manifest.json", manifest)
    return output_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run gold, silver, and consistency evals into one versioned directory"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--provider", choices=["fake", "jev"], default="fake")
    parser.add_argument("--fixture", type=Path, default=None)
    parser.add_argument("--live-artifact-root", type=Path, default=None)
    parser.add_argument("--previous", type=Path, default=None)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--packet-size", type=int, default=20)
    parser.add_argument("--repeatability-runs", type=int, default=3)
    parser.add_argument("--input-usd-per-million", type=float, default=None)
    parser.add_argument("--output-usd-per-million", type=float, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.packet_size > 20:
        print("Error: --packet-size must be <= 20", file=sys.stderr)
        return 2
    try:
        output = run_decision_eval(
            output_dir=args.output,
            provider=args.provider,
            fixture_path=args.fixture,
            live_artifact_root=args.live_artifact_root,
            previous_dir=args.previous,
            batch_size=args.batch_size,
            packet_size=args.packet_size,
            repeatability_runs=args.repeatability_runs,
            input_usd_per_million=args.input_usd_per_million,
            output_usd_per_million=args.output_usd_per_million,
            command_arguments=vars(args),
        )
    except (DecisionModelConfigError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote decision eval run: {output}")
    print(f"Summary: {output / 'SUMMARY.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
