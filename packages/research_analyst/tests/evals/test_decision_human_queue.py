"""Human label queue scoring and review-record conversion (no network)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from test_decision_real_pilot import AgreeingClient, _export

from research_analysis_layer.evals.decision_agent_models import load_model_catalog
from research_analysis_layer.evals.decision_agent_pilot_run import (
    prepare_real_pilot,
    run_prepared_pilot,
)
from research_analysis_layer.evals.decision_agent_references import (
    load_agent_references,
)
from research_analysis_layer.evals.decision_human_queue import (
    STATEMENT_TYPES,
    score_human_queue,
    write_human_review_records,
)
from research_analysis_layer.evals.decision_reviews import (
    load_review_records,
    validate_review_records,
)
from research_analysis_layer.services.agent_llm_client import AgentCallResult


class ComparativeReviewer(AgreeingClient):
    """Agrees on everything except is_comparative, which it always calls yes."""

    def generate_with_tools(self, **kwargs) -> AgentCallResult:
        result = super().generate_with_tools(**kwargs)
        body = result.parsed_output
        for axis in body["axes"]:
            if axis["axis_id"] == "is_comparative":
                axis["value"] = True
        return AgentCallResult(
            raw_text=json.dumps(body),
            parsed_output=body,
            token_usage=result.token_usage,
            model_used=result.model_used,
            stop_reason=result.stop_reason,
        )


def _clients(resolved):
    return {
        role: (ComparativeReviewer if role == "reviewer" else AgreeingClient)(entry.sampling)
        for role, entry in resolved.entries.items()
    }


def _question(question_id: str) -> dict:
    allowed = list(STATEMENT_TYPES) if question_id == "statement_type" else ["yes", "no", "unsure"]
    return {"question_id": question_id, "ask": f"{question_id}?", "allowed_answers": allowed}


def _pilot(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "pilot"
    export_dir = _export(root)
    prep = root / "prep"
    prepare_real_pilot(
        export_dir=export_dir,
        output_dir=prep,
        pilot_id="pilot-hq",
        seed="seed-1",
        max_units=6,
        catalog=load_model_catalog(),
        role_overrides={},
        max_usd=4.5,
    )
    run_dir = run_prepared_pilot(preparation_dir=prep, run_dir=root / "run", client_factory=_clients)
    references = load_agent_references(run_dir / "references.jsonl")[:3]
    questions = [
        ["is_forecast", "is_comparative"],
        ["is_forecast", "statement_type"],
        ["is_comparative"],
    ]
    queue_dir = root / "queue"
    queue_dir.mkdir()
    queue = {
        "schema_version": "decision-human-label-queue-v1",
        "queue_id": "hq-test",
        "question_set_version": "decision-question-set-v6",
        "items": [
            {
                "item_id": f"hq-{n:03d}",
                "sentence": ref.source.target_text,
                "questions": [_question(q) for q in qs],
                "provenance": {
                    "document_id": ref.source.document_id,
                    "unit_id": ref.source.unit_id,
                    "source_id": ref.source.source_id,
                    "target_text_sha256": ref.source.target_text_sha256,
                },
            }
            for n, (ref, qs) in enumerate(zip(references, questions), 1)
        ],
    }
    (queue_dir / "queue.json").write_text(json.dumps(queue), encoding="utf-8")
    answers = [
        ("hq-001", "is_forecast", "yes", ""),
        ("hq-001", "is_comparative", "no", ""),
        ("hq-002", "is_forecast", "yes", ""),
        ("hq-002", "is_forecast", "no", "changed my mind"),
        ("hq-002", "statement_type", "assertion", ""),
        ("hq-003", "is_comparative", "unsure", "depends on the exhibit"),
        ("hq-003", "is_comparative", "maybe", ""),
        ("hq-999", "is_forecast", "yes", ""),
    ]
    (queue_dir / "answers.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "item_id": item,
                    "question_id": question,
                    "answer": answer,
                    "note": note,
                    "answered_at": "2026-11-12T09:00:00-05:00",
                    "answered_by": "Tester",
                }
            )
            + "\n"
            for item, question, answer, note in answers
        ),
        encoding="utf-8",
    )
    return root, export_dir, run_dir


def test_scores_compare_each_model_with_the_latest_human_answer(tmp_path: Path) -> None:
    root, export_dir, run_dir = _pilot(tmp_path)
    report = score_human_queue(
        queue_path=root / "queue" / "queue.json",
        answers_path=root / "queue" / "answers.jsonl",
        run_dir=run_dir,
        export_dir=export_dir,
        output_dir=run_dir / "human_scores",
    )

    assert report["progress"] == {"answered": 5, "total": 5}
    assert [row["line"] for row in report["rejected_answer_lines"]] == [7, 8]

    forecast = report["per_axis"]["is_forecast"]
    assert forecast["answered"] == 2
    # Both models say yes to is_forecast; the person said yes once, then no once.
    for model in ("annotator", "reviewer", "admitted_reference"):
        assert forecast[model]["agree"] == 1
        assert forecast[model]["said_yes_human_no"] == 1

    comparative = report["per_axis"]["is_comparative"]
    assert comparative == {**comparative, "answered": 2, "unsure": 1}
    assert comparative["annotator"]["agree"] == 1
    assert comparative["reviewer"]["said_yes_human_no"] == 1
    assert comparative["admitted_reference"]["no_answer"] == 1
    assert "is_comparative/models_split" in report["per_axis_and_reason"]

    jev = forecast["jev"]
    assert jev["agree"] + jev["disagree"] + jev["no_answer"] == 2
    markdown = (run_dir / "human_scores" / "HUMAN_SCORES.md").read_text()
    assert "Answered 5 of 5 questions" in markdown
    assert "line 7: answer 'maybe' not allowed" in markdown


def test_only_items_with_a_human_statement_type_become_review_records(tmp_path: Path) -> None:
    root, export_dir, _ = _pilot(tmp_path)
    output = root / "reviews" / "human_reviews.jsonl"
    result = write_human_review_records(
        queue_path=root / "queue" / "queue.json",
        answers_path=root / "queue" / "answers.jsonl",
        export_dir=export_dir,
        artifact_root=root,
        output_path=output,
        reviewer="Tester",
        review_date=date(2026, 11, 12),
    )

    assert result["records"] == 1
    assert {row["item_id"] for row in result["blocked"]} == {"hq-001", "hq-003"}
    [record] = load_review_records(output)
    assert record.status == "agreed"
    assert record.labels.statement_type == "assertion"
    # The person's latest answer wins; unsure and unasked axes stay unreviewed.
    assert record.labels.noul_labels == {"is_forecast": False}
    assert record.label_completeness == "partial"

    validation = validate_review_records([record], artifact_root=root)
    assert validation.valid, validation.issues
    assert validation.sources_verified

    approval = (root / result["approval_path"]).read_text()
    assert "## hq-002 / statement_type" in approval
    assert "changed my mind" in approval
