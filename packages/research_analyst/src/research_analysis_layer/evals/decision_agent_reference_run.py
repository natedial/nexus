"""Checkpointed harness for building agent-reviewed decision references.

The harness deliberately knows nothing about a specific model API. Providers
receive a narrow request object and return a structured ``AgentJudgment``. This
keeps blind first passes testable and prevents annotation workers from gaining
database, delivery, gold-approval, or release-promotion capabilities.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from research_analysis_layer.evals.decision_agent_references import (
    AXIS_IDS,
    AcceptedAxis,
    AgentJudgment,
    AgentReferenceRecord,
    AgentReferenceSource,
    AxisJudgment,
    ModelIdentity,
    canonical_record_hash,
    role_prompt_path,
    role_prompt_sha256,
)

HARNESS_SCHEMA_VERSION = "decision-agent-reference-run-v1"
Role = Literal["annotator", "reviewer", "adjudicator"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceLimits(StrictModel):
    max_requests: int = Field(gt=0)
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    max_elapsed_seconds: float = Field(gt=0)
    max_estimated_usd: float | None = Field(default=None, gt=0)


class HarnessConfig(StrictModel):
    run_id: str = Field(min_length=1)
    execution_mode: Literal["scripted", "live"] = "scripted"
    taxonomy_version: str = Field(min_length=1)
    taxonomy_text: str = Field(min_length=1)
    taxonomy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_version: str = Field(min_length=1)
    role_models: dict[Role, ModelIdentity]
    sampling_by_role: dict[Role, dict[str, Any]] = Field(default_factory=dict)
    limits: ResourceLimits
    max_transport_retries: int = Field(default=2, ge=0, le=2)
    max_schema_repairs: int = Field(default=1, ge=0, le=1)
    adjudicate_disagreements: bool = True

    @model_validator(mode="after")
    def _validate_config(self) -> HarnessConfig:
        digest = hashlib.sha256(self.taxonomy_text.encode("utf-8")).hexdigest()
        if digest != self.taxonomy_sha256:
            raise ValueError("taxonomy_sha256 does not match taxonomy_text")
        missing = {"annotator", "reviewer"} - set(self.role_models)
        if missing:
            raise ValueError(f"role_models missing required roles: {sorted(missing)}")
        if self.adjudicate_disagreements and "adjudicator" not in self.role_models:
            raise ValueError("adjudication requires a pinned adjudicator model")
        if self.execution_mode == "live" and self.limits.max_estimated_usd is None:
            raise ValueError("live runs require max_estimated_usd")
        return self


class JudgmentRequest(StrictModel):
    """Capability-limited input for exactly one model call."""

    run_id: str
    role: Role
    attempt_kind: Literal["initial", "transport_retry", "schema_repair"]
    source: AgentReferenceSource
    role_instructions: str
    role_prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    taxonomy_version: str
    taxonomy_text: str
    taxonomy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sampling: dict[str, Any] = Field(default_factory=dict)
    disputed_axis_ids: list[str] = Field(default_factory=list)
    comparison_judgments: list[AgentJudgment] = Field(default_factory=list)
    previous_error: str | None = None

    @model_validator(mode="after")
    def _enforce_blind_roles(self) -> JudgmentRequest:
        if self.role in {"annotator", "reviewer"}:
            if self.disputed_axis_ids or self.comparison_judgments:
                raise ValueError("blind first-pass requests cannot include other labels")
        elif not self.disputed_axis_ids or len(self.comparison_judgments) < 2:
            raise ValueError("adjudicator requests require the disputed axes and judgments")
        return self


class JudgmentProvider(Protocol):
    def generate(self, request: JudgmentRequest) -> AgentJudgment | Mapping[str, Any]:
        """Return one structured judgment without mutating harness state."""


class RetryableProviderError(RuntimeError):
    """A transport failure that the harness may retry within its fixed bound."""


class BudgetExhausted(RuntimeError):
    """Raised internally when another call would violate a frozen run cap."""


class UsageState(StrictModel):
    requests: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    estimated_usd: float | None = Field(default=0.0, ge=0)
    elapsed_seconds: float = Field(default=0.0, ge=0)


def _json_line(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), sort_keys=True) + "\n"


def _append_json(path: Path, payload: Mapping[str, Any] | BaseModel) -> None:
    value = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True) + "\n")


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.replace(path)


def _config_hash(config: HarnessConfig) -> str:
    return canonical_record_hash(config)


def _source_inventory_hash(sources: Sequence[AgentReferenceSource]) -> str:
    rows = [source.model_dump(mode="json") for source in sources]
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _validate_sources(sources: Sequence[AgentReferenceSource]) -> None:
    source_ids = [source.source_id for source in sources]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("source inventory contains duplicate source_id values")
    source_keys = [source.source_key for source in sources]
    if len(source_keys) != len(set(source_keys)):
        raise ValueError("source inventory contains duplicate document/unit/text targets")
    lineage_targets = [
        (source.source_lineage_id, source.target_text_sha256) for source in sources
    ]
    if len(lineage_targets) != len(set(lineage_targets)):
        raise ValueError("source inventory contains duplicate lineage targets")


def _load_jsonl(path: Path, model_type: type[BaseModel]) -> list[BaseModel]:
    if not path.is_file():
        return []
    records: list[BaseModel] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(model_type.model_validate_json(line))
        except ValidationError as exc:
            raise ValueError(f"invalid {path.name} line {line_number}: {exc}") from exc
    return records


class ReferenceBatchHarness:
    """Run or resume one immutable-input agent-reference batch."""

    def __init__(self, provider: JudgmentProvider) -> None:
        self.provider = provider
        self._session_started = 0.0
        self._elapsed_base = 0.0

    def run(
        self,
        *,
        output_dir: Path,
        sources: Sequence[AgentReferenceSource],
        config: HarnessConfig,
        resume: bool = False,
    ) -> Path:
        _validate_sources(sources)
        started_monotonic = time.monotonic()
        if resume:
            manifest = self._resume_manifest(output_dir, sources, config)
        else:
            manifest = self._initialize_run(output_dir, sources, config)

        usage = UsageState.model_validate(manifest.get("usage") or {})
        self._session_started = started_monotonic
        self._elapsed_base = usage.elapsed_seconds
        judgments = self._load_judgments(output_dir)
        completed_source_ids = self._completed_source_ids(output_dir)

        try:
            for source in sources:
                if source.source_id in completed_source_ids:
                    continue
                for role in ("annotator", "reviewer"):
                    key = (source.source_id, role)
                    if key in judgments:
                        continue
                    judgment = self._obtain_judgment(
                        output_dir=output_dir,
                        source=source,
                        role=role,
                        config=config,
                        usage=usage,
                        manifest=manifest,
                    )
                    judgments[key] = judgment

                first_passes = [
                    judgments[(source.source_id, "annotator")],
                    judgments[(source.source_id, "reviewer")],
                ]
                disputed = _disputed_axes(first_passes)
                if disputed and config.adjudicate_disagreements:
                    key = (source.source_id, "adjudicator")
                    if key not in judgments:
                        judgment = self._obtain_judgment(
                            output_dir=output_dir,
                            source=source,
                            role="adjudicator",
                            config=config,
                            usage=usage,
                            manifest=manifest,
                            disputed_axis_ids=disputed,
                            comparison_judgments=first_passes,
                        )
                        judgments[key] = judgment
                        _append_json(output_dir / "adjudications.jsonl", judgment)

                source_judgments = [
                    judgment
                    for (source_id, _), judgment in judgments.items()
                    if source_id == source.source_id
                ]
                record = curate_reference(
                    source=source,
                    judgments=source_judgments,
                    gate_version=config.gate_version,
                    run_id=config.run_id,
                )
                _append_json(output_dir / "references.jsonl", record)
                if record.quarantined_axes or not record.accepted_axes:
                    _append_json(
                        output_dir / "quarantine.jsonl",
                        {
                            "reference_id": record.reference_id,
                            "source_id": source.source_id,
                            "axes": record.quarantined_axes,
                            "reason": (
                                "axis disagreements or unresolved judgments"
                                if record.quarantined_axes
                                else "no axes were eligible for admission"
                            ),
                        },
                    )
                completed_source_ids.add(source.source_id)
                manifest["completed_source_ids"] = sorted(completed_source_ids)
                self._checkpoint(output_dir, manifest, usage)
        except BudgetExhausted as exc:
            manifest["status"] = "incomplete"
            manifest["stop_reason"] = f"budget_exhausted: {exc}"
            self._checkpoint(output_dir, manifest, usage)
            self._write_reporting_outputs(output_dir, manifest, usage, sources)
            return output_dir
        except Exception as exc:
            manifest["status"] = "incomplete"
            manifest["stop_reason"] = f"interrupted: {type(exc).__name__}: {exc}"
            self._checkpoint(output_dir, manifest, usage)
            self._write_reporting_outputs(output_dir, manifest, usage, sources)
            raise

        manifest["status"] = "complete"
        manifest["stop_reason"] = None
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        self._checkpoint(output_dir, manifest, usage)
        self._write_reporting_outputs(output_dir, manifest, usage, sources)
        self._finalize_hashes(output_dir, manifest)
        return output_dir

    def _initialize_run(
        self,
        output_dir: Path,
        sources: Sequence[AgentReferenceSource],
        config: HarnessConfig,
    ) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=False)
        (output_dir / "sources.jsonl").write_text(
            "".join(_json_line(source) for source in sources), encoding="utf-8"
        )
        for name in (
            "attempts.jsonl",
            "judgments.jsonl",
            "adjudications.jsonl",
            "references.jsonl",
            "quarantine.jsonl",
        ):
            (output_dir / name).write_text("", encoding="utf-8")
        (output_dir / "escalations.json").write_text("[]\n", encoding="utf-8")
        manifest: dict[str, Any] = {
            "schema_version": HARNESS_SCHEMA_VERSION,
            "run_id": config.run_id,
            "status": "running",
            "stop_reason": None,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": config.model_dump(mode="json"),
            "config_sha256": _config_hash(config),
            "source_inventory_sha256": _source_inventory_hash(sources),
            "source_count": len(sources),
            "completed_source_ids": [],
            "usage": UsageState().model_dump(mode="json"),
            "artifact_sha256": {},
        }
        _write_json_atomic(output_dir / "manifest.json", manifest)
        return manifest

    def _resume_manifest(
        self,
        output_dir: Path,
        sources: Sequence[AgentReferenceSource],
        config: HarnessConfig,
    ) -> dict[str, Any]:
        manifest_path = output_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("cannot resume without manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("schema_version") != HARNESS_SCHEMA_VERSION:
            raise ValueError("cannot resume an unknown harness schema")
        if manifest.get("status") == "complete":
            raise ValueError("finalized runs are immutable and cannot be resumed")
        try:
            stored_config = HarnessConfig.model_validate(manifest.get("config"))
        except ValidationError as exc:
            raise ValueError("stored run config is invalid") from exc
        if _config_hash(stored_config) != manifest.get("config_sha256"):
            raise ValueError("stored run config no longer matches its frozen hash")
        if manifest.get("config_sha256") != _config_hash(config):
            raise ValueError("resume config differs from the frozen run config")
        stored_sources = [
            AgentReferenceSource.model_validate(record)
            for record in _load_jsonl(
                output_dir / "sources.jsonl", AgentReferenceSource
            )
        ]
        stored_source_hash = _source_inventory_hash(stored_sources)
        if stored_source_hash != manifest.get("source_inventory_sha256"):
            raise ValueError("stored source inventory no longer matches its frozen hash")
        if stored_source_hash != _source_inventory_hash(sources):
            raise ValueError("resume source inventory differs from the frozen inventory")
        manifest["status"] = "running"
        manifest["stop_reason"] = None
        return manifest

    def _load_judgments(self, output_dir: Path) -> dict[tuple[str, str], AgentJudgment]:
        loaded = _load_jsonl(output_dir / "judgments.jsonl", AgentJudgment)
        result: dict[tuple[str, str], AgentJudgment] = {}
        for raw in loaded:
            judgment = AgentJudgment.model_validate(raw)
            key = (judgment.source_id, judgment.role)
            if key in result:
                raise ValueError(f"duplicate persisted judgment for {key}")
            result[key] = judgment
        return result

    def _completed_source_ids(self, output_dir: Path) -> set[str]:
        loaded = _load_jsonl(output_dir / "references.jsonl", AgentReferenceRecord)
        return {
            AgentReferenceRecord.model_validate(record).source.source_id
            for record in loaded
        }

    def _obtain_judgment(
        self,
        *,
        output_dir: Path,
        source: AgentReferenceSource,
        role: Role,
        config: HarnessConfig,
        usage: UsageState,
        manifest: dict[str, Any],
        disputed_axis_ids: Sequence[str] = (),
        comparison_judgments: Sequence[AgentJudgment] = (),
    ) -> AgentJudgment:
        transport_failures = 0
        schema_repairs = 0
        previous_error: str | None = None
        while True:
            self._check_pre_call_budget(config, usage)
            if schema_repairs:
                attempt_kind = "schema_repair"
            elif transport_failures:
                attempt_kind = "transport_retry"
            else:
                attempt_kind = "initial"
            request = JudgmentRequest(
                run_id=config.run_id,
                role=role,
                attempt_kind=attempt_kind,
                source=source,
                role_instructions=role_prompt_path(
                    "reviewer" if role == "adjudicator" else role
                ).read_text(encoding="utf-8"),
                role_prompt_sha256=role_prompt_sha256(
                    "reviewer" if role == "adjudicator" else role
                ),
                taxonomy_version=config.taxonomy_version,
                taxonomy_text=config.taxonomy_text,
                taxonomy_sha256=config.taxonomy_sha256,
                sampling=config.sampling_by_role.get(role, {}),
                disputed_axis_ids=list(disputed_axis_ids),
                comparison_judgments=list(comparison_judgments),
                previous_error=previous_error,
            )
            usage.requests += 1
            self._checkpoint(output_dir, manifest, usage)
            try:
                raw = self.provider.generate(request)
            except RetryableProviderError as exc:
                _append_json(
                    output_dir / "attempts.jsonl",
                    _attempt_row(request, "retryable_error", str(exc)),
                )
                if transport_failures >= config.max_transport_retries:
                    raise
                transport_failures += 1
                previous_error = str(exc)
                continue
            except Exception as exc:
                _append_json(
                    output_dir / "attempts.jsonl",
                    _attempt_row(request, "fatal_error", str(exc)),
                )
                raise

            try:
                judgment = AgentJudgment.model_validate(raw)
                self._validate_judgment(judgment, request, config)
                self._validate_unique_call_identity(output_dir, judgment)
            except (ValidationError, ValueError) as exc:
                _append_json(
                    output_dir / "attempts.jsonl",
                    _attempt_row(request, "schema_error", str(exc)),
                )
                if schema_repairs >= config.max_schema_repairs:
                    raise
                schema_repairs += 1
                previous_error = str(exc)
                continue

            _append_json(output_dir / "attempts.jsonl", _attempt_row(request, "success"))
            _append_json(output_dir / "judgments.jsonl", judgment)
            usage.input_tokens += judgment.usage.input_tokens or 0
            usage.output_tokens += judgment.usage.output_tokens or 0
            if judgment.usage.estimated_usd is None:
                usage.estimated_usd = None
            elif usage.estimated_usd is not None:
                usage.estimated_usd += judgment.usage.estimated_usd
            self._checkpoint(output_dir, manifest, usage)
            self._check_post_call_budget(config, usage)
            return judgment

    def _validate_judgment(
        self,
        judgment: AgentJudgment,
        request: JudgmentRequest,
        config: HarnessConfig,
    ) -> None:
        if judgment.source_id != request.source.source_id:
            raise ValueError("provider returned judgment for the wrong source")
        if judgment.role != request.role:
            raise ValueError("provider returned judgment for the wrong role")
        expected_pass = "comparison" if request.role == "adjudicator" else "blind_first_pass"
        if judgment.pass_kind != expected_pass:
            raise ValueError("provider returned the wrong pass_kind")
        if judgment.model != config.role_models[request.role]:
            raise ValueError("provider model identity differs from the frozen pin")
        if judgment.taxonomy_version != config.taxonomy_version:
            raise ValueError("provider used the wrong taxonomy version")
        if judgment.taxonomy_sha256 != config.taxonomy_sha256:
            raise ValueError("provider used the wrong taxonomy hash")
        if judgment.role_prompt_sha256 != request.role_prompt_sha256:
            raise ValueError("provider used the wrong role prompt hash")
        judgment.validate_spans(request.source)

    def _validate_unique_call_identity(
        self, output_dir: Path, judgment: AgentJudgment
    ) -> None:
        existing = _load_jsonl(output_dir / "judgments.jsonl", AgentJudgment)
        for raw in existing:
            prior = AgentJudgment.model_validate(raw)
            if prior.judgment_id == judgment.judgment_id:
                raise ValueError(
                    f"provider reused judgment_id {judgment.judgment_id!r}"
                )
            if prior.call_id == judgment.call_id:
                raise ValueError(f"provider reused call_id {judgment.call_id!r}")

    def _check_pre_call_budget(
        self,
        config: HarnessConfig,
        usage: UsageState,
    ) -> None:
        if usage.requests >= config.limits.max_requests:
            raise BudgetExhausted("request cap reached")
        if usage.input_tokens >= config.limits.max_input_tokens:
            raise BudgetExhausted("input-token cap reached")
        if usage.output_tokens >= config.limits.max_output_tokens:
            raise BudgetExhausted("output-token cap reached")
        if self._current_elapsed() >= config.limits.max_elapsed_seconds:
            raise BudgetExhausted("elapsed-time cap reached")
        dollar_cap = config.limits.max_estimated_usd
        if dollar_cap is not None:
            if usage.estimated_usd is None:
                raise BudgetExhausted("dollar usage became unknown")
            if usage.estimated_usd >= dollar_cap:
                raise BudgetExhausted("dollar cap reached")

    def _check_post_call_budget(
        self,
        config: HarnessConfig,
        usage: UsageState,
    ) -> None:
        if usage.input_tokens > config.limits.max_input_tokens:
            raise BudgetExhausted("input-token cap exceeded by completed call")
        if usage.output_tokens > config.limits.max_output_tokens:
            raise BudgetExhausted("output-token cap exceeded by completed call")
        if self._current_elapsed() > config.limits.max_elapsed_seconds:
            raise BudgetExhausted("elapsed-time cap exceeded by completed call")
        dollar_cap = config.limits.max_estimated_usd
        if dollar_cap is not None:
            if usage.estimated_usd is None:
                raise BudgetExhausted("dollar usage became unknown")
            if usage.estimated_usd > dollar_cap:
                raise BudgetExhausted("dollar cap exceeded by completed call")

    def _checkpoint(
        self,
        output_dir: Path,
        manifest: dict[str, Any],
        usage: UsageState,
    ) -> None:
        usage.elapsed_seconds = self._current_elapsed()
        manifest["usage"] = usage.model_dump(mode="json")
        manifest["checkpointed_at"] = datetime.now(timezone.utc).isoformat()
        _write_json_atomic(output_dir / "manifest.json", manifest)

    def _current_elapsed(self) -> float:
        if self._session_started == 0.0:
            return self._elapsed_base
        return self._elapsed_base + (time.monotonic() - self._session_started)

    def _write_reporting_outputs(
        self,
        output_dir: Path,
        manifest: Mapping[str, Any],
        usage: UsageState,
        sources: Sequence[AgentReferenceSource],
    ) -> None:
        _write_json_atomic(
            output_dir / "cost_and_latency.json",
            {
                "usage": usage.model_dump(mode="json"),
                "limits": (manifest.get("config") or {}).get("limits"),
                "status": manifest.get("status"),
                "note": "Unknown model pricing remains null rather than zero.",
            },
        )
        completed = len(manifest.get("completed_source_ids") or [])
        summary = [
            "# Agent-reviewed reference batch",
            "",
            f"- Status: **{manifest.get('status')}**",
            f"- Sources completed: {completed}/{len(sources)}",
            f"- Stop reason: {manifest.get('stop_reason') or 'none'}",
            f"- Requests used: {usage.requests}",
            f"- Estimated USD: {usage.estimated_usd}",
            "",
            "Agent-reviewed references are not human gold and cannot authorize production routing.",
            "Unresolved or disputed axes remain quarantined while unrelated axes may proceed.",
            "",
        ]
        (output_dir / "SUMMARY.md").write_text("\n".join(summary), encoding="utf-8")

    def _finalize_hashes(
        self, output_dir: Path, manifest: dict[str, Any]
    ) -> None:
        artifacts = {}
        for path in sorted(output_dir.iterdir()):
            if path.is_file() and path.name != "manifest.json":
                artifacts[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest["artifact_sha256"] = artifacts
        _write_json_atomic(output_dir / "manifest.json", manifest)


def _attempt_row(
    request: JudgmentRequest, status: str, error: str | None = None
) -> dict[str, Any]:
    return {
        "source_id": request.source.source_id,
        "role": request.role,
        "attempt_kind": request.attempt_kind,
        "status": status,
        "error": error,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _axis_by_id(judgment: AgentJudgment) -> dict[str, AxisJudgment]:
    return {axis.axis_id: axis for axis in judgment.axes}


def _disputed_axes(judgments: Sequence[AgentJudgment]) -> list[str]:
    if len(judgments) < 2:
        return []
    left, right = (_axis_by_id(judgment) for judgment in judgments[:2])
    disputed: list[str] = []
    for axis_id in AXIS_IDS:
        first = left.get(axis_id)
        second = right.get(axis_id)
        if first is None and second is None:
            continue
        if first is None or second is None:
            disputed.append(axis_id)
        elif first.state != "labeled" or second.state != "labeled":
            disputed.append(axis_id)
        elif first.value != second.value:
            disputed.append(axis_id)
    return disputed


def curate_reference(
    *,
    source: AgentReferenceSource,
    judgments: Sequence[AgentJudgment],
    gate_version: str,
    run_id: str,
) -> AgentReferenceRecord:
    """Apply the conservative deterministic Slice 2 admission gate."""

    for judgment in judgments:
        judgment.validate_spans(source)
    by_role = {judgment.role: judgment for judgment in judgments}
    if len(by_role) != len(judgments):
        raise ValueError("curation cannot contain duplicate role judgments")
    annotator = by_role.get("annotator")
    reviewer = by_role.get("reviewer")
    if annotator is None or reviewer is None:
        raise ValueError("curation requires annotator and reviewer judgments")
    left = _axis_by_id(annotator)
    right = _axis_by_id(reviewer)
    accepted: list[AcceptedAxis] = []
    quarantined: dict[str, str] = {}
    correlated = annotator.model.model_family == reviewer.model.model_family
    for axis_id in AXIS_IDS:
        first = left.get(axis_id)
        second = right.get(axis_id)
        if first is None and second is None:
            continue
        if first is None or second is None:
            quarantined[axis_id] = "only one blind first pass addressed this axis"
            continue
        if first.state != "labeled" or second.state != "labeled":
            quarantined[axis_id] = "one or both blind first passes withheld a label"
            continue
        if not first.supporting_spans or not second.supporting_spans:
            quarantined[axis_id] = "one or both blind first passes omitted source spans"
            continue
        if first.value != second.value:
            adjudicator = by_role.get("adjudicator")
            suffix = (
                "; third judgment recorded but cannot replace first-pass agreement"
                if adjudicator is not None
                else ""
            )
            quarantined[axis_id] = f"blind first passes disagreed{suffix}"
            continue
        accepted.append(
            AcceptedAxis(
                axis_id=axis_id,  # type: ignore[arg-type]
                value=first.value,  # type: ignore[arg-type]
                tier="provisional",
                supporting_judgment_ids=[
                    annotator.judgment_id,
                    reviewer.judgment_id,
                ],
                gate_version=gate_version,
                admission_reason="matching blind first-pass labels with valid source spans",
                correlated_models=correlated,
            )
        )
    reference_seed = f"{run_id}:{source.source_id}:{source.target_text_sha256}"
    reference_id = "agent-ref-" + hashlib.sha256(reference_seed.encode()).hexdigest()[:20]
    return AgentReferenceRecord(
        reference_id=reference_id,
        source=source,
        judgments=list(judgments),
        accepted_axes=accepted,
        quarantined_axes=quarantined,
        lifecycle="provisional" if accepted else "quarantined",
        release_id=run_id,
    )


__all__ = [
    "BudgetExhausted",
    "HARNESS_SCHEMA_VERSION",
    "HarnessConfig",
    "JudgmentProvider",
    "JudgmentRequest",
    "ReferenceBatchHarness",
    "ResourceLimits",
    "RetryableProviderError",
    "UsageState",
    "curate_reference",
]
