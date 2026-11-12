"""Score a human label queue and turn its answers into review records.

A human label queue (``decision-human-label-queue-v1``) is a JSON file of
sentences and yes/no questions that a person answers over time; an agent
appends one line per answer to ``answers.jsonl``. The queue carries no model
answers, so the person is never anchored on them.

This module does two things, both without spending money:

1. ``score_human_queue`` compares every answered question with Jev, with each
   reference model's blind first pass, and with the admitted reference. Model
   answers are read from the pilot run and the export, not from any hand-made
   key. It can run at any time; unanswered questions are counted as pending.
2. ``write_human_review_records`` snapshots the answers into an immutable
   approval file and writes ``decision-review-record-v2`` records that the
   gold-release validator accepts. A review record needs a human
   ``statement_type``, so an item is converted only once the person has
   answered a ``statement_type`` question for it; the rest are listed as
   blocked rather than given a guessed statement type.

Scores are written to a directory the queue agent does not read, so the
person does not see model answers while the queue is still open.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping, Sequence, get_args

from research_analysis_layer.evals.decision_agent_pilot_run import (
    _artifact_paths,
    _jev_values,
)
from research_analysis_layer.evals.decision_agent_references import (
    StatementType,
    load_agent_references,
)
from research_analysis_layer.evals.decision_artifacts import load_shadow_artifact
from research_analysis_layer.evals.decision_reviews import (
    DecisionReviewRecord,
    sha256_bytes,
    sha256_text,
)

QUEUE_SCHEMA = "decision-human-label-queue-v1"
SCORES_SCHEMA = "decision-human-queue-scores-v1"
STATEMENT_TYPES: tuple[str, ...] = get_args(StatementType)
BINARY_ANSWERS = {"yes": True, "no": False}
MODEL_ROLES = ("annotator", "reviewer")


@dataclass(frozen=True)
class HumanAnswer:
    item_id: str
    question_id: str
    answer: str
    note: str
    answered_at: str
    answered_by: str
    line_number: int


def load_queue(path: Path) -> dict[str, Any]:
    queue = json.loads(path.read_text(encoding="utf-8"))
    if queue.get("schema_version") != QUEUE_SCHEMA:
        raise ValueError(f"unsupported queue schema: {queue.get('schema_version')!r}")
    return queue


def load_answers(
    path: Path, queue: Mapping[str, Any]
) -> tuple[dict[tuple[str, str], HumanAnswer], list[dict[str, Any]]]:
    """Return the latest valid answer per (item, question) and any rejected lines.

    A later line for the same question replaces an earlier one, so the person
    can change their mind by answering again. Invalid lines are reported, never
    silently dropped or guessed at.
    """
    allowed: dict[tuple[str, str], set[str]] = {
        (item["item_id"], question["question_id"]): set(question["allowed_answers"])
        for item in queue["items"]
        for question in item["questions"]
    }
    latest: dict[tuple[str, str], HumanAnswer] = {}
    rejected: list[dict[str, Any]] = []
    if not path.is_file():
        return latest, rejected
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            key = (str(row["item_id"]), str(row["question_id"]))
            answer = str(row["answer"]).strip().lower()
        except (ValueError, KeyError, TypeError) as exc:
            rejected.append({"line": number, "reason": f"unreadable: {exc}"})
            continue
        if key not in allowed:
            rejected.append({"line": number, "reason": f"unknown item/question {key}"})
            continue
        if answer not in allowed[key]:
            rejected.append({"line": number, "reason": f"answer {answer!r} not allowed"})
            continue
        latest[key] = HumanAnswer(
            item_id=key[0],
            question_id=key[1],
            answer=answer,
            note=str(row.get("note") or ""),
            answered_at=str(row.get("answered_at") or ""),
            answered_by=str(row.get("answered_by") or ""),
            line_number=number,
        )
    return latest, rejected


def _model_answers(run_dir: Path, export_dir: Path) -> dict[str, dict[str, Any]]:
    """Per source_id: admitted/quarantined reference axes, blind passes, Jev."""
    jev = _jev_values(_artifact_paths(export_dir))
    by_source: dict[str, dict[str, Any]] = {}
    for ref in load_agent_references(run_dir / "references.jsonl"):
        blind = {
            judgment.role: {
                axis.axis_id: axis.value if axis.state == "labeled" else None
                for axis in judgment.axes
            }
            for judgment in ref.judgments
            if judgment.pass_kind == "blind_first_pass"
        }
        by_source[ref.source.source_id] = {
            "document_id": ref.source.document_id,
            "unit_id": ref.source.unit_id,
            "admitted": {axis.axis_id: axis.value for axis in ref.accepted_axes},
            "quarantined": dict(ref.quarantined_axes),
            "blind": blind,
            "jev": jev.get((ref.source.document_id, ref.source.unit_id), {}),
        }
    return by_source


def _selection_reason(models: Mapping[str, Any], axis_id: str) -> str:
    if axis_id in models["quarantined"]:
        return "models_split"
    admitted = models["admitted"].get(axis_id)
    jev_value = (models["jev"].get(axis_id) or {}).get("value")
    if admitted is None:
        return "no_admitted_reference"
    if jev_value is None:
        return "jev_abstained"
    return "jev_disagrees" if jev_value != admitted else "control_agreement"


def _human_value(answer: HumanAnswer) -> Any:
    if answer.question_id == "statement_type":
        return answer.answer
    return BINARY_ANSWERS.get(answer.answer)


def _new_tally() -> dict[str, Any]:
    tally: dict[str, Any] = {"answered": 0, "unsure": 0}
    for model in ("jev", *MODEL_ROLES, "admitted_reference"):
        tally[model] = {
            "agree": 0,
            "disagree": 0,
            "no_answer": 0,
            "said_yes_human_no": 0,
            "said_no_human_yes": 0,
        }
    return tally


def _add(tally: dict[str, Any], model: str, model_value: Any, human: Any) -> None:
    bucket = tally[model]
    if model_value is None:
        bucket["no_answer"] += 1
    elif model_value == human:
        bucket["agree"] += 1
    else:
        bucket["disagree"] += 1
        if model_value is True and human is False:
            bucket["said_yes_human_no"] += 1
        elif model_value is False and human is True:
            bucket["said_no_human_yes"] += 1


def score_human_queue(
    *,
    queue_path: Path,
    answers_path: Path,
    run_dir: Path,
    export_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Score every answered question; writes ``human_scores.json`` and ``.md``."""
    queue = load_queue(queue_path)
    answers, rejected = load_answers(answers_path, queue)
    models_by_source = _model_answers(run_dir, export_dir)

    per_axis: dict[str, dict[str, Any]] = {}
    per_reason: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    total_questions = 0
    missing_sources: list[str] = []
    for item in queue["items"]:
        source_id = item["provenance"]["source_id"]
        models = models_by_source.get(source_id)
        if models is None:
            missing_sources.append(item["item_id"])
        for question in item["questions"]:
            total_questions += 1
            axis_id = question["question_id"]
            answer = answers.get((item["item_id"], axis_id))
            if answer is None or models is None:
                continue
            reason = _selection_reason(models, axis_id)
            axis_tally = per_axis.setdefault(axis_id, _new_tally())
            reason_tally = per_reason.setdefault(f"{axis_id}/{reason}", _new_tally())
            human = _human_value(answer)
            row = {
                "item_id": item["item_id"],
                "axis_id": axis_id,
                "selection_reason": reason,
                "human": answer.answer,
                "note": answer.note,
                "jev": (models["jev"].get(axis_id) or {}).get("value"),
                "jev_probability": (models["jev"].get(axis_id) or {}).get("probability"),
                "annotator": models["blind"].get("annotator", {}).get(axis_id),
                "reviewer": models["blind"].get("reviewer", {}).get(axis_id),
                "admitted_reference": models["admitted"].get(axis_id),
            }
            rows.append(row)
            for tally in (axis_tally, reason_tally):
                tally["answered"] += 1
                if human is None:
                    tally["unsure"] += 1
                    continue
                for model in ("jev", *MODEL_ROLES, "admitted_reference"):
                    _add(tally, model, row[model], human)

    report = {
        "schema_version": SCORES_SCHEMA,
        "queue_id": queue.get("queue_id"),
        "question_set_version": queue.get("question_set_version"),
        "answers_sha256": sha256_bytes(answers_path.read_bytes())
        if answers_path.is_file()
        else None,
        "progress": {"answered": len(rows), "total": total_questions},
        "rejected_answer_lines": rejected,
        "items_without_model_answers": missing_sources,
        "per_axis": per_axis,
        "per_axis_and_reason": dict(sorted(per_reason.items())),
        "rows": rows,
        "caveats": [
            "The queue over-samples disagreements; these rates are not population accuracy.",
            "Unsure answers are counted but never scored.",
            "Human answers are one reviewer's judgment, not consensus.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "human_scores.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "HUMAN_SCORES.md").write_text(_markdown(report), encoding="utf-8")
    return report


def _rate(bucket: Mapping[str, int]) -> str:
    compared = bucket["agree"] + bucket["disagree"]
    return f"{bucket['agree']}/{compared}" if compared else "-"


def _markdown(report: Mapping[str, Any]) -> str:
    progress = report["progress"]
    lines = [
        f"# Human label scores: {report['queue_id']}",
        "",
        f"Answered {progress['answered']} of {progress['total']} questions "
        f"({report['question_set_version']}).",
        "",
        "Agreement is shown as agree/compared. \"Over\" counts a model yes where "
        "the person said no; \"under\" the reverse. Unsure answers are not scored.",
        "",
    ]

    def table(title: str, tallies: Mapping[str, Mapping[str, Any]]) -> None:
        lines.extend(
            [
                f"## {title}",
                "",
                "| Question | Answered | Unsure | Jev | Jev over / under | Annotator | Reviewer | Admitted reference |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for name, tally in tallies.items():
            jev = tally["jev"]
            lines.append(
                f"| {name} | {tally['answered']} | {tally['unsure']} | {_rate(jev)} "
                f"| {jev['said_yes_human_no']} / {jev['said_no_human_yes']} "
                f"| {_rate(tally['annotator'])} | {_rate(tally['reviewer'])} "
                f"| {_rate(tally['admitted_reference'])} |"
            )
        lines.append("")

    table("By question", report["per_axis"])
    table("By question and why it was queued", report["per_axis_and_reason"])
    if report["rejected_answer_lines"]:
        lines.append("## Rejected answer lines")
        lines.append("")
        lines.extend(
            f"- line {row['line']}: {row['reason']}"
            for row in report["rejected_answer_lines"]
        )
        lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.extend(f"- {caveat}" for caveat in report["caveats"])
    return "\n".join(lines) + "\n"


def _approval_note(item_id: str, question_id: str) -> str:
    return f"## {item_id} / {question_id}"


def write_human_review_records(
    *,
    queue_path: Path,
    answers_path: Path,
    export_dir: Path,
    artifact_root: Path,
    output_path: Path,
    reviewer: str,
    review_date: date,
) -> dict[str, Any]:
    """Write agreed review records for items with a human statement type.

    The approval file is a content-addressed snapshot of the answers, written
    under ``artifact_root`` so the release validator can check every record's
    trace. ``unsure`` answers become unreviewed axes, never ``false``.
    """
    queue = load_queue(queue_path)
    answers, rejected = load_answers(answers_path, queue)
    artifact_root = artifact_root.resolve()
    artifacts = {}
    for path in _artifact_paths(export_dir):
        artifact = load_shadow_artifact(path)
        artifacts[artifact.document_key] = (path.resolve(), artifact)

    snapshot_lines = [f"# Human answers for {queue['queue_id']}", ""]
    for (item_id, question_id), answer in sorted(answers.items()):
        snapshot_lines.extend(
            [
                _approval_note(item_id, question_id),
                "",
                f"- answer: {answer.answer}",
                f"- answered_by: {answer.answered_by}",
                f"- answered_at: {answer.answered_at}",
                f"- note: {answer.note}",
                "",
            ]
        )
    snapshot_text = "\n".join(snapshot_lines)
    snapshot_sha = sha256_text(snapshot_text)
    approvals_dir = queue_path.parent.resolve() / "approvals"
    approvals_dir.mkdir(exist_ok=True)
    approval_path = approvals_dir / f"APPROVALS-{snapshot_sha[:12]}.md"
    approval_path.write_text(snapshot_text, encoding="utf-8")
    approval_relative = _relative_under(approval_path, artifact_root)

    records: list[DecisionReviewRecord] = []
    blocked: list[dict[str, str]] = []
    for item in queue["items"]:
        item_id = item["item_id"]
        statement = answers.get((item_id, "statement_type"))
        binary = {
            question["question_id"]: answers.get((item_id, question["question_id"]))
            for question in item["questions"]
            if question["question_id"] != "statement_type"
        }
        if not any(binary.values()) and statement is None:
            continue
        if statement is None or statement.answer not in STATEMENT_TYPES:
            blocked.append({"item_id": item_id, "reason": "statement_type not answered"})
            continue
        provenance = item["provenance"]
        found = artifacts.get(provenance["document_id"])
        unit = None
        if found is not None:
            unit = next(
                (row for row in found[1].units if row.unit_id == provenance["unit_id"]),
                None,
            )
        if found is None or unit is None:
            blocked.append({"item_id": item_id, "reason": "unit not in export artifacts"})
            continue
        artifact_path, artifact = found
        if item["sentence"] not in unit.source_text:
            blocked.append({"item_id": item_id, "reason": "sentence not in stored model input"})
            continue
        labels = {
            question_id: BINARY_ANSWERS[answer.answer]
            for question_id, answer in binary.items()
            if answer is not None and answer.answer in BINARY_ANSWERS
        }
        answered = [a for a in (statement, *binary.values()) if a is not None]
        notes = [f"{a.question_id}: {a.note}" for a in answered if a.note]
        record = DecisionReviewRecord(
            review_id=f"review-{queue['queue_id']}-{item_id}-{snapshot_sha[:12]}",
            document_id=provenance["document_id"],
            unit_id=provenance["unit_id"],
            reviewed_text=item["sentence"],
            reviewed_text_sha256=sha256_text(item["sentence"]),
            stored_model_input=unit.source_text,
            stored_model_input_sha256=sha256_text(unit.source_text),
            question_set_version=artifact.question_set_version,
            question_set_content_hash=(
                artifact.question_set.content_hash if artifact.question_set else "missing"
            ),
            provider=artifact.provider,
            model_version=artifact.model_version,
            adapter_version=artifact.adapter_version,
            labels={"statement_type": statement.answer, "noul_labels": labels},
            reviewer=reviewer,
            review_date=review_date,
            status="agreed",
            rationale=(
                "Human answers from label queue "
                f"{queue['queue_id']}."
                + (" Notes: " + "; ".join(notes) if notes else "")
            ),
            issue_tags=["human-label-queue"],
            source_artifact={
                "path": _relative_under(artifact_path, artifact_root),
                "sha256": sha256_bytes(artifact_path.read_bytes()),
            },
            approval_trace={
                "source_path": approval_relative,
                "source_sha256": snapshot_sha,
                "note_reference": _approval_note(item_id, "statement_type"),
            },
        )
        records.append(record)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "".join(
            json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
    return {
        "records": len(records),
        "blocked": blocked,
        "rejected_answer_lines": rejected,
        "approval_path": approval_relative,
        "output": str(output_path),
    }


def _relative_under(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"{path} is not under artifact root {root}") from exc


__all__: Sequence[str] = (
    "load_answers",
    "load_queue",
    "score_human_queue",
    "write_human_review_records",
)
