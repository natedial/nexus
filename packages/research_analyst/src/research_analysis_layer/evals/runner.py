"""Eval runner for analysis agents."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from research_analysis_layer.evals.comparison import (
    compare_outputs,
    compute_confidence,
)
from research_analysis_layer.models.agent_inputs import (
    AgentInputDocument,
    AgentInputTheme,
    AgentInputAssertion,
    DeterministicAnalysisPayload,
    AgentInputPayload,
)
from research_analysis_layer.models.agent_outputs import DocumentAnalysis

if TYPE_CHECKING:
    from research_analysis_layer.evals.judge import LLMJudge
    from research_analysis_layer.evals.db import EvalDatabase
    from research_analysis_layer.evals.training_capture import TrainingCaptureManager


@dataclass
class EvalResult:
    """Result of evaluating a single agent on a single document."""

    document_id: str
    agent_type: str
    output: dict
    expected: dict
    schema_valid: bool
    field_scores: dict[str, float]
    confidence: float
    judge_scores: dict[str, float] | None = None
    judge_reasoning: str | None = None
    latency_ms: int = 0
    error: str | None = None


@dataclass
class EvalSummary:
    """Summary of eval run across multiple documents."""

    total_docs: int
    schema_validity_rate: float
    field_scores: dict[str, float]
    confidence_avg: float
    judge_scores: dict[str, float] | None = None
    latency_p95_ms: int = 0
    latency_avg_ms: int = 0
    results: list[EvalResult] = field(default_factory=list)


@dataclass
class RegressionReport:
    """Report comparing current run to baseline."""

    baseline_name: str
    changes: dict[str, float]
    regressions: list[str]
    new_failures: list[str]


def load_golden_annotations(golden_path: Path) -> dict[str, dict]:
    """Load golden annotations from annotations.jsonl.

    Returns:
        Dict mapping document_id -> annotation dict
    """
    annotations_path = golden_path / "annotations.jsonl"
    if not annotations_path.exists():
        raise FileNotFoundError(f"Annotations not found: {annotations_path}")

    annotations = {}
    with open(annotations_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            doc = json.loads(line)
            annotations[doc["document_id"]] = doc

    return annotations


def load_golden_document(golden_path: Path, document_id: str) -> dict:
    """Load a single golden document by ID.

    Returns:
        Document content as dict
    """
    annotations = load_golden_annotations(golden_path)
    if document_id not in annotations:
        raise ValueError(f"Document {document_id} not found in golden set")

    doc_info = annotations[document_id]
    doc_path = golden_path / doc_info["document_path"]

    if not doc_path.exists():
        raise FileNotFoundError(f"Golden document not found: {doc_path}")

    content = doc_path.read_text(encoding="utf-8")
    return {
        "document_id": document_id,
        "content": content,
        "expected": doc_info.get("expected", {}),
        "source_type": doc_info.get("source_type", "unknown"),
    }


def validate_schema(output: dict) -> bool:
    """Validate that output matches expected schema."""
    required_fields = ["thesis", "confidence"]
    for field in required_fields:
        if field not in output:
            return False

    if not isinstance(output.get("confidence"), (int, float)):
        return False

    return True


def _extract_golden_input(content: str) -> dict:
    """Extract structured input fields from a golden document.

    Golden documents contain embedded JSON blocks for themes and assertions
    that mirror what the parser produces. This helper extracts them to match
    the structured payload agents actually receive.

    Args:
        content: Raw markdown content from golden document

    Returns:
        Dict with document_text, themes, and assertions
    """
    import re

    text_match = re.search(
        r"## Full Text Excerpt\n(.*?)(?=\n---|\n## Themes)",
        content,
        re.DOTALL,
    )
    full_text = text_match.group(1).strip() if text_match else content

    themes_match = re.search(
        r"## Themes.*?```json\n(.*?)```",
        content,
        re.DOTALL,
    )
    themes = []
    if themes_match:
        try:
            themes = json.loads(themes_match.group(1))
        except json.JSONDecodeError:
            pass

    assertions_match = re.search(
        r"## Assertions.*?```json\n(.*?)```",
        content,
        re.DOTALL,
    )
    assertions = []
    if assertions_match:
        try:
            assertions = json.loads(assertions_match.group(1))
        except json.JSONDecodeError:
            pass

    return {
        "document_text": full_text,
        "themes": themes,
        "assertions": assertions,
    }


class AgentEvalRunner:
    """Runner for evaluating analysis agents against golden dataset.

    This runner:
    1. Loads golden documents and annotations
    2. Runs specified agents on each document
    3. Compares outputs to expected using field-level similarity
    4. Optionally runs LLM judge for semantic evaluation
    5. Returns summary metrics and per-doc results
    """

    def __init__(
        self,
        llm_client: Any,
        golden_path: Path,
        output_dir: Path,
        agent_registry: Any = None,
        judge_client: Any = None,
        judge_model: str = "claude-haiku-4-5-20251001",
        llm_judge: "LLMJudge | None" = None,
        eval_db: "EvalDatabase | None" = None,
        training_capture: "TrainingCaptureManager | None" = None,
    ):
        """Initialize eval runner.

        Args:
            llm_client: Client for running agent evaluations
            golden_path: Path to golden dataset
            output_dir: Directory for writing eval results
            agent_registry: Optional registry for loading agent prompts
            judge_client: Optional separate client for LLM judge
            judge_model: Model to use for LLM judge
            llm_judge: Optional LLMJudge instance (preferred over judge_client)
            eval_db: Optional EvalDatabase for persisting results
            training_capture: Optional TrainingCaptureManager for capturing outputs
        """
        self.llm_client = llm_client
        self.golden_path = Path(golden_path)
        self.output_dir = Path(output_dir)
        self.agent_registry = agent_registry
        self.judge_client = judge_client or llm_client
        self.judge_model = judge_model
        self.llm_judge = llm_judge
        self.eval_db = eval_db
        self.training_capture = training_capture
        self._run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        if self.agent_registry is None:
            from research_analysis_layer.services.agent_registry import AgentRegistry

            self.agent_registry = AgentRegistry()

        self.output_dir.mkdir(parents=True, exist_ok=True)

    def run_single(
        self,
        document_id: str,
        agent_types: list[str] | None = None,
        use_judge: bool = False,
    ) -> EvalResult:
        """Run evaluation for a single document.

        Args:
            document_id: ID of golden document to evaluate
            agent_types: List of agent types to run (default: all)
            use_judge: Whether to run LLM judge

        Returns:
            EvalResult with output, field scores, and metrics
        """
        agent_types = agent_types or ["synthesizer"]

        golden_doc = load_golden_document(self.golden_path, document_id)
        expected = golden_doc["expected"]

        errors = []
        outputs = {}
        latencies = {}

        for agent_type in agent_types:
            try:
                start = time.time()
                output = self._run_agent(agent_type, golden_doc)
                latency_ms = int((time.time() - start) * 1000)

                outputs[agent_type] = output
                latencies[agent_type] = latency_ms
            except Exception as e:
                errors.append(f"{agent_type}: {type(e).__name__}: {e}")
                outputs[agent_type] = {}
                latencies[agent_type] = 0

        primary_output = outputs.get("synthesizer", outputs.get(agent_types[0], {}))
        schema_valid = validate_schema(primary_output)

        field_scores = compare_outputs(primary_output, expected)
        confidence = compute_confidence(field_scores)

        judge_scores = None
        judge_reasoning = None
        if use_judge:
            source_document = golden_doc.get("content", "")[:8000]
            judge_scores, judge_reasoning = self._run_judge(
                primary_output, expected, source_document
            )

        total_latency = sum(latencies.values())

        result = EvalResult(
            document_id=document_id,
            agent_type=",".join(agent_types),
            output=primary_output,
            expected=expected,
            schema_valid=schema_valid,
            field_scores=field_scores,
            confidence=confidence,
            judge_scores=judge_scores,
            judge_reasoning=judge_reasoning,
            latency_ms=total_latency,
            error="; ".join(errors) if errors else None,
        )

        if self.eval_db is not None:
            self.eval_db.insert_eval_run(
                run_id=self._run_id,
                document_id=document_id,
                agent_type=",".join(agent_types),
                schema_valid=schema_valid,
                field_scores=field_scores,
                confidence=confidence,
                judge_scores=judge_scores,
                judge_reasoning=judge_reasoning,
                latency_ms=total_latency,
            )

        if self.training_capture is not None and schema_valid:
            quality = {}
            if judge_scores:
                quality["judge_score"] = sum(judge_scores.values()) / len(judge_scores)
            quality["golden_score"] = confidence

            structured_input = _extract_golden_input(golden_doc.get("content", ""))

            config = self.agent_registry.get_agent(
                "synthesizer"
            ) or self.agent_registry.get_agent(agent_types[0])
            model_name = config.model if config else "claude-sonnet-4-20250514"

            self.training_capture.capture(
                document_id=document_id,
                input_data=structured_input,
                output_data=primary_output,
                metadata={
                    "agent_type": ",".join(agent_types),
                    "model": model_name,
                    "confidence": confidence,
                    "schema_valid": schema_valid,
                    "latency_ms": total_latency,
                },
                quality=quality,
            )

        return result

    def run_golden(
        self,
        limit: int | None = None,
        agent_types: list[str] | None = None,
        use_judge: bool = False,
    ) -> EvalSummary:
        """Run evaluation on all golden documents.

        Args:
            limit: Optional limit on number of docs to evaluate
            agent_types: Agent types to run
            use_judge: Whether to run LLM judge

        Returns:
            EvalSummary with aggregated metrics
        """
        annotations = load_golden_annotations(self.golden_path)
        doc_ids = list(annotations.keys())

        if limit:
            doc_ids = doc_ids[:limit]

        results = []
        for doc_id in doc_ids:
            result = self.run_single(doc_id, agent_types, use_judge)
            results.append(result)

        return self._summarize_results(results)

    def _run_agent(self, agent_type: str, golden_doc: dict) -> dict:
        """Run a single agent on a golden document."""
        config = self.agent_registry.get_agent(agent_type)
        if config is None:
            raise ValueError(f"unknown agent '{agent_type}'")

        prompt = self.agent_registry.load_prompt(agent_type)
        if prompt is None:
            raise RuntimeError(f"prompt missing for '{agent_type}'")

        structured_input = _extract_golden_input(golden_doc["content"])

        themes = []
        for i, t in enumerate(structured_input["themes"]):
            theme_data = {"theme_id": i, "theme_order": i, "confidence": "medium", **t}
            try:
                themes.append(AgentInputTheme(**theme_data))
            except Exception:
                pass

        assertions = []
        for i, a in enumerate(structured_input["assertions"]):
            assertion_data = {
                "chunk_order": 0,
                "assertion_order": i,
                "assertion_type": "claim",
                **a,
            }
            try:
                assertions.append(AgentInputAssertion(**assertion_data))
            except Exception:
                pass

        payload = AgentInputPayload(
            agent_type=agent_type,
            document=AgentInputDocument(
                research_id=0,
                document_name=golden_doc["document_id"],
                source=golden_doc.get("source_type"),
                full_text_excerpt=structured_input["document_text"][:12000],
            ),
            themes=themes,
            deterministic_analysis=DeterministicAnalysisPayload(
                assertions=assertions,
            ),
        )

        payload_dict = payload.model_dump(mode="python")

        try:
            result = self.llm_client.generate_structured(
                system_prompt=prompt,
                user_payload=payload_dict,
                model=config.model,
                timeout_seconds=config.timeout_seconds,
            )
            return result
        except Exception as e:
            return {
                "thesis": f"Error: {type(e).__name__}",
                "confidence": 0.0,
                "error": str(e),
            }

    def _run_judge(
        self,
        actual: dict,
        expected: dict,
        source_document: str = "",
    ) -> tuple[dict[str, float], str]:
        """Run LLM judge to evaluate output quality.

        Returns:
            Tuple of (scores dict, reasoning string)
        """
        if self.llm_judge is not None:
            score = self.llm_judge.evaluate(actual, expected, source_document)
            return score.scores_dict, score.reasoning

        judge_prompt_path = (
            Path(__file__).parent.parent.parent.parent
            / "prompts"
            / "evals"
            / "judge.md"
        )

        if judge_prompt_path.exists():
            judge_prompt = judge_prompt_path.read_text()
        else:
            judge_prompt = "You are evaluating AI research agent outputs."

        formatted_prompt = judge_prompt.replace("{{source_document}}", source_document)
        formatted_prompt = formatted_prompt.replace(
            "{{agent_output}}", json.dumps(actual, indent=2)
        )
        formatted_prompt = formatted_prompt.replace(
            "{{golden_output}}", json.dumps(expected, indent=2)
        )

        try:
            result = self.judge_client.generate_structured(
                system_prompt=formatted_prompt,
                user_payload={},
                model=self.judge_model,
                timeout_seconds=60,
            )

            scores = result.get("scores", {})
            reasoning = result.get("reasoning", "")

            return scores, reasoning
        except Exception as e:
            return {"error": str(e)}, f"Judge failed: {type(e).__name__}"

    def _summarize_results(self, results: list[EvalResult]) -> EvalSummary:
        """Aggregate results into summary."""
        if not results:
            return EvalSummary(
                total_docs=0,
                schema_validity_rate=0.0,
                field_scores={},
                confidence_avg=0.0,
            )

        total_docs = len(results)
        schema_valid_count = sum(1 for r in results if r.schema_valid)
        schema_validity_rate = schema_valid_count / total_docs

        all_field_scores = {}
        for r in results:
            for field, score in r.field_scores.items():
                if field not in all_field_scores:
                    all_field_scores[field] = []
                all_field_scores[field].append(score)

        field_scores_avg = {
            field: sum(scores) / len(scores)
            for field, scores in all_field_scores.items()
        }

        confidences = [r.confidence for r in results]
        confidence_avg = sum(confidences) / len(confidences) if confidences else 0.0

        latencies = [r.latency_ms for r in results]
        latency_avg = sum(latencies) / len(latencies) if latencies else 0.0
        latencies_sorted = sorted(latencies)
        p95_idx = int(len(latencies_sorted) * 0.95)
        latency_p95 = latencies_sorted[p95_idx] if latencies_sorted else 0

        judge_scores = None
        judge_results = [r.judge_scores for r in results if r.judge_scores]
        if judge_results:
            judge_scores = {}
            for key in judge_results[0].keys():
                values = [
                    j.get(key, 0) for j in judge_results if j.get(key) is not None
                ]
                if values:
                    judge_scores[key] = sum(values) / len(values)

        return EvalSummary(
            total_docs=total_docs,
            schema_validity_rate=schema_validity_rate,
            field_scores=field_scores_avg,
            confidence_avg=confidence_avg,
            judge_scores=judge_scores,
            latency_p95_ms=latency_p95,
            latency_avg_ms=int(latency_avg),
            results=results,
        )

    def save_results(self, summary: EvalSummary, run_id: str | None = None) -> Path:
        """Save eval results to output directory.

        Returns:
            Path to saved results file
        """
        run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        output_path = self.output_dir / f"eval_{run_id}.json"

        data = {
            "run_id": run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_docs": summary.total_docs,
            "schema_validity_rate": summary.schema_validity_rate,
            "field_scores": summary.field_scores,
            "confidence_avg": summary.confidence_avg,
            "judge_scores": summary.judge_scores,
            "latency_p95_ms": summary.latency_p95_ms,
            "latency_avg_ms": summary.latency_avg_ms,
            "results": [
                {
                    "document_id": r.document_id,
                    "agent_type": r.agent_type,
                    "schema_valid": r.schema_valid,
                    "field_scores": r.field_scores,
                    "confidence": r.confidence,
                    "judge_scores": r.judge_scores,
                    "latency_ms": r.latency_ms,
                    "error": r.error,
                }
                for r in summary.results
            ],
        }

        output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return output_path

    def compare_to_baseline(
        self,
        baseline_path: Path | str,
    ) -> RegressionReport:
        """Compare current results to a baseline.

        Args:
            baseline_path: Path to baseline JSON file, or baseline name (str) for DB lookup

        Returns:
            RegressionReport with changes and regressions
        """
        if isinstance(baseline_path, str):
            if not baseline_path.endswith(".json"):
                raise ValueError(
                    f"Baseline '{baseline_path}' looks like a DB baseline name. "
                    f"DB-backed baselines are not yet implemented. "
                    f"Please provide a path to a baseline JSON file."
                )
            baseline_path = Path(baseline_path)

        if not baseline_path.exists():
            raise FileNotFoundError(f"Baseline not found: {baseline_path}")

        baseline_data = json.loads(baseline_path.read_text())

        current_path = self._get_latest_results()
        if not current_path:
            raise RuntimeError("No current results to compare")

        current_data = json.loads(current_path.read_text())

        baseline_metrics = {
            "schema_validity_rate": baseline_data.get("schema_validity_rate", 0),
            "confidence_avg": baseline_data.get("confidence_avg", 0),
            "latency_avg_ms": baseline_data.get("latency_avg_ms", 0),
        }

        current_metrics = {
            "schema_validity_rate": current_data.get("schema_validity_rate", 0),
            "confidence_avg": current_data.get("confidence_avg", 0),
            "latency_avg_ms": current_data.get("latency_avg_ms", 0),
        }

        changes = {}
        for key in baseline_metrics:
            baseline_val = baseline_metrics[key]
            current_val = current_metrics[key]
            if baseline_val > 0:
                changes[key] = (current_val - baseline_val) / baseline_val
            else:
                changes[key] = current_val - baseline_val

        regressions = []
        for key, delta in changes.items():
            if delta < -0.10:
                regressions.append(f"{key}: {delta:.1%}")

        new_failures = []

        return RegressionReport(
            baseline_name=baseline_path.stem,
            changes=changes,
            regressions=regressions,
            new_failures=new_failures,
        )

    def _get_latest_results(self) -> Path | None:
        """Get path to most recent results file."""
        results = list(self.output_dir.glob("eval_*.json"))
        if not results:
            return None
        return max(results, key=lambda p: p.stat().st_mtime)
