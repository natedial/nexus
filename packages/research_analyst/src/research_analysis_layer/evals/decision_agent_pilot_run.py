"""Prepare, run, and report a real-document agent-reference pilot.

Three steps, each writing to its own directory:

1. ``prepare_real_pilot`` selects units from a real-units export, resolves the
   role models from the catalog, and writes a frozen preparation bundle plus a
   no-spend dry run. The resolved catalog entries are frozen too, so a later
   catalog edit cannot change a prepared pilot.
2. ``run_prepared_pilot`` runs the blind annotator/reviewer harness on the
   frozen sources (all of them, or the first N for a smoke run).
3. ``build_jev_comparison`` compares admitted references with Jev, per
   question, and applies the frozen outcome rules.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from research_analysis_layer.evals.decision_agent_models import (
    CatalogModel,
    ModelCatalog,
    ResolvedRoleModels,
    build_role_clients,
    is_retryable_transport_error,
    resolve_role_models,
)
from research_analysis_layer.evals.decision_agent_pilot import (
    PilotSelection,
    PilotSpecification,
    build_pilot_specification,
    load_pilot_candidates,
    select_stratified_pilot,
    source_inventory_sha256,
    write_pilot_preparation,
)
from research_analysis_layer.evals.decision_agent_provider import (
    StructuredJudgmentProvider,
)
from research_analysis_layer.evals.decision_agent_reference_run import (
    HarnessConfig,
    ReferenceBatchHarness,
    ResourceLimits,
)
from research_analysis_layer.evals.decision_agent_references import (
    AXIS_IDS,
    AgentReferenceRecord,
    AgentReferenceSource,
    load_agent_references,
)
from research_analysis_layer.evals.decision_artifacts import load_shadow_artifact
from research_analysis_layer.evals.decision_codex_assessments import (
    _jev_answers,
    _jev_axis_value,
)
from research_analysis_layer.evals.decision_real_units import PREFIX_TRANSFORMATION

PILOT_GATE_VERSION = "decision-agent-gate-v1"
COMPARISON_SCHEMA = "decision-agent-jev-comparison-v1"
OUTCOME_RULES_VERSION = "decision-agent-outcome-rules-v1"

# Frozen before results (plan 2026-11-09). Applied in this order.
MIN_ADMITTED = 10
MIN_EACH_SIDE = 2
SOUND_AGREEMENT = 0.90
WORDING_DISAGREEMENT = 0.20
WORDING_QUARANTINE_SHARE = 0.40


def _artifact_paths(export_dir: Path) -> list[Path]:
    paths = sorted((export_dir / "artifacts").glob("shadow_*.json"))
    if not paths:
        raise ValueError(f"no shadow artifacts under {export_dir / 'artifacts'}")
    return paths


def _taxonomy_from_artifacts(paths: Sequence[Path]) -> tuple[str, str]:
    snapshots = {}
    for path in paths:
        artifact = load_shadow_artifact(path)
        if artifact.question_set is None:
            raise ValueError(f"artifact lacks a question-set snapshot: {path}")
        snapshots[artifact.question_set.content_hash] = artifact.question_set
    if len(snapshots) != 1:
        raise ValueError("export artifacts use more than one question set")
    snapshot = next(iter(snapshots.values()))
    text = json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True)
    return snapshot.version, text


def prepare_real_pilot(
    *,
    export_dir: Path,
    output_dir: Path,
    pilot_id: str,
    seed: str,
    max_units: int,
    catalog: ModelCatalog,
    role_overrides: Mapping[str, str] | None = None,
    max_usd: float,
    max_requests: int | None = None,
    max_elapsed_seconds: float = 4 * 3600,
) -> dict[str, Any]:
    """Freeze selection, models, caps, and taxonomy; no network calls."""

    artifact_paths = _artifact_paths(export_dir)
    candidates, excluded_count = load_pilot_candidates(
        artifact_root=export_dir,
        artifact_paths=artifact_paths,
        document_types={
            load_shadow_artifact(path).document_key: "sell_side_research"
            for path in artifact_paths
        },
        transformations=[PREFIX_TRANSFORMATION],
    )
    selection = select_stratified_pilot(
        candidates=candidates,
        max_units=max_units,
        seed=seed,
        excluded_reviewed_count=excluded_count,
    )
    resolved = resolve_role_models(catalog, role_overrides)  # type: ignore[arg-type]
    taxonomy_version, taxonomy_text = _taxonomy_from_artifacts(artifact_paths)
    units = len(selection.selected)
    # Two first-pass calls per unit, each with up to two transport retries
    # and one schema repair.
    request_cap = max_requests or units * 2 * 4
    config = HarnessConfig(
        run_id=pilot_id,
        execution_mode="live",
        taxonomy_version=taxonomy_version,
        taxonomy_text=taxonomy_text,
        taxonomy_sha256=hashlib.sha256(taxonomy_text.encode("utf-8")).hexdigest(),
        gate_version=PILOT_GATE_VERSION,
        role_models=resolved.role_models,
        sampling_by_role=resolved.sampling_by_role,
        limits=ResourceLimits(
            max_requests=request_cap,
            max_input_tokens=request_cap * 20_000,
            max_output_tokens=request_cap * 16_000,
            max_elapsed_seconds=max_elapsed_seconds,
            max_estimated_usd=max_usd,
        ),
        adjudicate_disagreements=False,
        continue_on_invalid_source=True,
    )
    specification = build_pilot_specification(
        pilot_id=pilot_id,
        selection=selection,
        harness_config=config,
        pricing_by_role=resolved.pricing_by_role,
    )
    report = write_pilot_preparation(
        output_dir=output_dir, selection=selection, specification=specification
    )
    frozen_models = {
        role: entry.model_dump(mode="json") for role, entry in resolved.entries.items()
    }
    (output_dir / "role_models.json").write_text(
        json.dumps(frozen_models, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "dry_run": report.model_dump(mode="json"),
        "role_models": resolved.describe(),
        "selected_units": units,
        "candidates": len(candidates),
    }


def _load_preparation(
    preparation_dir: Path,
) -> tuple[PilotSpecification, PilotSelection, list[AgentReferenceSource], ResolvedRoleModels]:
    specification = PilotSpecification.model_validate_json(
        (preparation_dir / "pilot_spec.json").read_text(encoding="utf-8")
    )
    selection = PilotSelection.model_validate_json(
        (preparation_dir / "selection.json").read_text(encoding="utf-8")
    )
    if source_inventory_sha256(selection) != specification.source_inventory_sha256:
        raise ValueError("prepared selection no longer matches the frozen specification")
    sources = [item.source for item in selection.selected]
    stored = json.loads((preparation_dir / "role_models.json").read_text(encoding="utf-8"))
    entries = {role: CatalogModel.model_validate(entry) for role, entry in stored.items()}
    resolved = ResolvedRoleModels(entries=entries)  # type: ignore[arg-type]
    if resolved.role_models != {
        role: specification.harness_config.role_models[role] for role in entries
    }:
        raise ValueError("frozen role models do not match the pilot specification")
    return specification, selection, sources, resolved


def run_prepared_pilot(
    *,
    preparation_dir: Path,
    run_dir: Path,
    smoke_units: int | None = None,
    smoke_max_usd: float = 0.50,
    resume: bool = False,
    client_factory: Callable[[ResolvedRoleModels], Mapping[str, Any]] | None = None,
    timeout_seconds: int = 300,
) -> Path:
    """Run the harness on the frozen preparation; spends money."""

    specification, _, sources, resolved = _load_preparation(preparation_dir)
    config = specification.harness_config
    if smoke_units is not None:
        if smoke_units <= 0:
            raise ValueError("smoke_units must be positive")
        sources = sources[:smoke_units]
        cap = min(smoke_max_usd, config.limits.max_estimated_usd or smoke_max_usd)
        config = config.model_copy(
            update={
                "run_id": f"{config.run_id}-smoke{smoke_units}",
                "limits": config.limits.model_copy(
                    update={
                        "max_estimated_usd": cap,
                        "max_requests": smoke_units * 2 * 4,
                    }
                ),
            }
        )
    clients = (client_factory or build_role_clients)(resolved)
    provider = StructuredJudgmentProvider(
        clients_by_role=clients,
        role_models=config.role_models,
        pricing_by_role=specification.pricing_by_role,
        is_retryable=is_retryable_transport_error,
        timeout_seconds=timeout_seconds,
    )
    return ReferenceBatchHarness(provider).run(
        output_dir=run_dir, sources=sources, config=config, resume=resume
    )


# --- Jev comparison ----------------------------------------------------------


def _jev_values(artifact_paths: Iterable[Path]) -> dict[tuple[str, str], dict[str, Any]]:
    values: dict[tuple[str, str], dict[str, Any]] = {}
    for path in artifact_paths:
        artifact = load_shadow_artifact(path)
        for unit in artifact.units:
            answers = _jev_answers(unit)
            values[(artifact.document_key or "", unit.unit_id)] = {
                axis_id: {
                    "value": _jev_axis_value(answers.get(axis_id), axis_id),
                    "probability": (answers.get(axis_id) or {}).get("raw_probability"),
                }
                for axis_id in AXIS_IDS
            }
    return values


def _outcome(stats: Mapping[str, Any], axis_id: str) -> tuple[str, str]:
    admitted = stats["admitted"]
    addressed = stats["addressed"]
    disagree_share = (
        stats["quarantined_model_disagreement"] / addressed if addressed else 0.0
    )
    if addressed >= MIN_ADMITTED and disagree_share > WORDING_QUARANTINE_SHARE:
        return (
            "wording_needs_work",
            f"{disagree_share:.0%} of addressed units quarantined for model disagreement",
        )
    if admitted < MIN_ADMITTED:
        return "needs_human_labels", f"only {admitted} admitted labels (< {MIN_ADMITTED})"
    comparable = stats["jev_agree"] + stats["jev_disagree"]
    if comparable == 0:
        return "needs_human_labels", "no Jev answers comparable with admitted labels"
    disagree_rate = stats["jev_disagree"] / comparable
    if disagree_rate > WORDING_DISAGREEMENT:
        return "wording_needs_work", f"Jev disagrees on {disagree_rate:.0%} of admitted labels"
    values = Counter(stats["admitted_values"])
    if axis_id == "statement_type":
        diverse = sum(count >= MIN_EACH_SIDE for count in values.values()) >= 2
    else:
        diverse = values.get("true", 0) >= MIN_EACH_SIDE and values.get("false", 0) >= MIN_EACH_SIDE
    if diverse and (1 - disagree_rate) >= SOUND_AGREEMENT:
        return (
            "looks_sound_so_far",
            f"{admitted} admitted, Jev agrees on {1 - disagree_rate:.0%}",
        )
    if not diverse:
        return "needs_human_labels", "admitted labels lack both answers in enough numbers"
    return "needs_human_labels", f"Jev agreement {1 - disagree_rate:.0%} is between the rule bands"


def _audit_sample(
    references: Sequence[AgentReferenceRecord], *, seed: str, rate: float
) -> list[dict[str, Any]]:
    with_labels = [ref for ref in references if ref.accepted_axes]
    count = math.ceil(len(with_labels) * rate) if with_labels else 0
    ranked = sorted(
        with_labels,
        key=lambda ref: hashlib.sha256(f"{seed}:{ref.reference_id}".encode()).hexdigest(),
    )
    sample: list[dict[str, Any]] = []
    for ref in ranked[:count]:
        quotes = {
            judgment.role: {
                axis.axis_id: [span.text for span in axis.supporting_spans]
                for axis in judgment.axes
            }
            for judgment in ref.judgments
        }
        sample.append(
            {
                "reference_id": ref.reference_id,
                "unit_id": ref.source.unit_id,
                "document_id": ref.source.document_id,
                "text": ref.source.target_text,
                "accepted": {
                    axis.axis_id: axis.value for axis in ref.accepted_axes
                },
                "quotes_by_role": quotes,
            }
        )
    return sample


def build_jev_comparison(
    *,
    run_dir: Path,
    export_dir: Path,
    audit_rate: float = 0.10,
) -> dict[str, Any]:
    """Compare admitted references with Jev per question; writes the report."""

    references = load_agent_references(run_dir / "references.jsonl")
    jev = _jev_values(_artifact_paths(export_dir))
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    per_axis: dict[str, dict[str, Any]] = {}
    for axis_id in AXIS_IDS:
        stats: dict[str, Any] = {
            "addressed": 0,
            "admitted": 0,
            "quarantined": 0,
            "quarantined_model_disagreement": 0,
            "quarantine_reasons": Counter(),
            "admitted_values": [],
            "jev_agree": 0,
            "jev_disagree": 0,
            "jev_not_comparable": 0,
            "disagreements": [],
        }
        for ref in references:
            accepted = {axis.axis_id: axis for axis in ref.accepted_axes}
            if axis_id in ref.quarantined_axes:
                reason = ref.quarantined_axes[axis_id]
                stats["addressed"] += 1
                stats["quarantined"] += 1
                stats["quarantine_reasons"][reason] += 1
                if reason.startswith("blind first passes disagreed"):
                    stats["quarantined_model_disagreement"] += 1
                continue
            if axis_id not in accepted:
                continue
            stats["addressed"] += 1
            stats["admitted"] += 1
            value = accepted[axis_id].value
            stats["admitted_values"].append(
                json.dumps(value) if isinstance(value, bool) else str(value)
            )
            jev_answer = jev.get((ref.source.document_id, ref.source.unit_id), {}).get(
                axis_id, {}
            )
            jev_value = jev_answer.get("value")
            if jev_value is None:
                stats["jev_not_comparable"] += 1
            elif jev_value == value:
                stats["jev_agree"] += 1
            else:
                stats["jev_disagree"] += 1
                stats["disagreements"].append(
                    {
                        "document_id": ref.source.document_id,
                        "unit_id": ref.source.unit_id,
                        "text": ref.source.target_text,
                        "reference_value": value,
                        "jev_value": jev_value,
                        "jev_probability": jev_answer.get("probability"),
                    }
                )
        outcome, why = _outcome(stats, axis_id)
        stats["outcome"] = outcome
        stats["outcome_reason"] = why
        stats["quarantine_reasons"] = dict(stats["quarantine_reasons"])
        stats["admitted_values"] = dict(Counter(stats["admitted_values"]))
        per_axis[axis_id] = stats

    failed = [
        json.loads(line)
        for line in (run_dir / "failed_sources.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if (run_dir / "failed_sources.jsonl").is_file() else []
    usage = manifest.get("usage") or {}
    requests = usage.get("requests") or 0
    report = {
        "schema_version": COMPARISON_SCHEMA,
        "outcome_rules_version": OUTCOME_RULES_VERSION,
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "stop_reason": manifest.get("stop_reason"),
        "role_models": {
            role: f"{identity['provider']}:{identity['model']}"
            for role, identity in (manifest.get("config") or {}).get("role_models", {}).items()
        },
        "references": len(references),
        "failed_sources": failed,
        "usage": usage,
        "usd_per_request": (
            (usage.get("estimated_usd") or 0) / requests if requests else None
        ),
        "per_axis": per_axis,
        "audit_sample": _audit_sample(references, seed=str(manifest.get("run_id")), rate=audit_rate),
        "caveats": [
            "Agreement between two models is evidence, not truth; shared blind spots remain.",
            "All labels are provisional agent references, never human gold.",
            "Claude and GPT both influenced the v3-v6 question wording.",
        ],
    }
    (run_dir / "jev_comparison.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    (run_dir / "JEV_COMPARISON.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# Jev vs agent references",
        "",
        f"- Run: `{report['run_id']}` ({report['status']})",
        f"- Models: {', '.join(f'{role} `{model}`' for role, model in report['role_models'].items())}",
        f"- Units with references: {report['references']}; failed after repair: {len(report['failed_sources'])}",
        f"- Requests: {report['usage'].get('requests')}; estimated USD: {report['usage'].get('estimated_usd')}",
        "",
        "| Question | Addressed | Admitted | Quarantined (model disagreement) | Jev agree | Jev disagree | Outcome |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for axis_id, stats in report["per_axis"].items():
        lines.append(
            f"| `{axis_id}` | {stats['addressed']} | {stats['admitted']} | "
            f"{stats['quarantined']} ({stats['quarantined_model_disagreement']}) | "
            f"{stats['jev_agree']} | {stats['jev_disagree']} | {stats['outcome']} |"
        )
    lines += ["", "## Jev disagreements", ""]
    for axis_id, stats in report["per_axis"].items():
        for item in stats["disagreements"]:
            lines.append(
                f"- `{axis_id}` {item['document_id']} {item['unit_id']}: reference "
                f"`{item['reference_value']}`, Jev `{item['jev_value']}` - {item['text'][:200]}"
            )
    lines += ["", "## Caveats", "", *(f"- {item}" for item in report["caveats"]), ""]
    return "\n".join(lines)


__all__ = [
    "build_jev_comparison",
    "prepare_real_pilot",
    "run_prepared_pilot",
]


def compare_jev_exports(
    *, before_dir: Path, after_dir: Path, band_margin: float = 0.07
) -> dict[str, Any]:
    """How far Jev's answers moved between two exports of the same units.

    Run it on two exports with the same question set to measure repeat noise,
    or across a wording change to see what moved. Units whose batch changed
    are counted separately, because Jev answers a whole batch at once and
    neighbouring units can shift each other's answers.
    """

    def load(export_dir: Path) -> tuple[dict, dict, set]:
        batches: dict[tuple[str, str], tuple[str, ...]] = {}
        versions: set[tuple[str, str | None, str]] = set()
        for path in _artifact_paths(export_dir):
            artifact = load_shadow_artifact(path)
            versions.add(
                (
                    artifact.question_set_version,
                    artifact.question_set.content_hash if artifact.question_set else None,
                    artifact.model_version,
                )
            )
            for batch in artifact.batch_results:
                members = tuple(sorted({r.target_unit_id for r in batch.results}))
                for unit_id in members:
                    batches[(artifact.document_key or "", unit_id)] = members
        return _jev_values(_artifact_paths(export_dir)), batches, versions

    before, before_batches, before_versions = load(before_dir)
    after, after_batches, after_versions = load(after_dir)
    shared = sorted(set(before) & set(after))
    per_axis: dict[str, dict[str, Any]] = {}
    for axis_id in AXIS_IDS:
        moves: list[float] = []
        changes: list[dict[str, Any]] = []
        same_batch_changes = 0
        for key in shared:
            old, new = before[key][axis_id], after[key][axis_id]
            if old["probability"] is not None and new["probability"] is not None:
                moves.append(abs(old["probability"] - new["probability"]))
            if old["value"] != new["value"]:
                same_batch = before_batches.get(key) == after_batches.get(key)
                same_batch_changes += same_batch
                changes.append(
                    {
                        "document_id": key[0],
                        "unit_id": key[1],
                        "before": old,
                        "after": new,
                        "same_batch": same_batch,
                    }
                )
        moves.sort()
        per_axis[axis_id] = {
            "compared": len(shared),
            "value_changes": len(changes),
            "value_changes_same_batch": same_batch_changes,
            "yes_no_reversals": sum(
                {c["before"]["value"], c["after"]["value"]} == {True, False}
                for c in changes
            ),
            "mean_probability_move": sum(moves) / len(moves) if moves else None,
            "p95_probability_move": moves[int(len(moves) * 0.95)] if moves else None,
            "max_probability_move": moves[-1] if moves else None,
            "changes": changes,
        }
    return {
        "before": {"export_dir": str(before_dir), "versions": sorted(map(list, before_versions))},
        "after": {"export_dir": str(after_dir), "versions": sorted(map(list, after_versions))},
        "same_question_set": before_versions == after_versions,
        "shared_units": len(shared),
        "units_in_same_batch": sum(
            before_batches.get(key) == after_batches.get(key) for key in shared
        ),
        "per_axis": per_axis,
    }
