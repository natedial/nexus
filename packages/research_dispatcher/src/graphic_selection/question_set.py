"""Versioned graphic-selection question set (Choice + eligibility Nouls)."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from src.graphic_selection.models import (
    QUESTION_SET_VERSION,
    DecisionQuestion,
    DecisionUnit,
    FrozenQuestionSpec,
    QuestionSetSnapshot,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
QUESTION_SET_PATH = (
    PACKAGE_ROOT / "styles" / "graphic_selection" / "graphic-question-set-v1.yaml"
)
REPRESENTATION_QUESTION_ID = "representation"


@lru_cache(maxsize=1)
def load_question_set_raw() -> dict[str, Any]:
    """Load the YAML question set once."""
    with QUESTION_SET_PATH.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"invalid question set at {QUESTION_SET_PATH}")
    return data


def pattern_options() -> list[str]:
    choice = load_question_set_raw().get("choice") or {}
    options = choice.get("options") or []
    return [str(item) for item in options]


PATTERN_OPTIONS = pattern_options()


def shape_preference() -> dict[str, str]:
    raw = load_question_set_raw().get("shape_preference") or {}
    return {str(k): str(v) for k, v in raw.items()}


def data_shapes() -> list[str]:
    raw = load_question_set_raw().get("data_shapes") or []
    return [str(item) for item in raw]


def noul_ids() -> list[str]:
    return [str(item["question_id"]) for item in load_question_set_raw().get("nouls") or []]


def question_templates() -> list[FrozenQuestionSpec]:
    """Unit-independent question templates."""
    raw = load_question_set_raw()
    choice = raw["choice"]
    questions: list[FrozenQuestionSpec] = [
        FrozenQuestionSpec(
            question_id=str(choice["question_id"]),
            question_kind="choice",
            wording=str(choice["wording"]).strip(),
            options=[str(opt) for opt in choice["options"]],
        )
    ]
    for noul in raw.get("nouls") or []:
        questions.append(
            FrozenQuestionSpec(
                question_id=str(noul["question_id"]),
                question_kind="noul",
                wording=str(noul["wording"]).strip(),
            )
        )
    return questions


def snapshot_question_set(
    *,
    question_set_version: str = QUESTION_SET_VERSION,
) -> QuestionSetSnapshot:
    """Freeze the exact questions asked for artifact / A/B provenance."""
    questions = question_templates()
    canonical = [
        {
            "question_id": q.question_id,
            "question_kind": q.question_kind,
            "wording": q.wording,
            "options": q.options,
            "noul_criteria": q.noul_criteria,
        }
        for q in questions
    ]
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return QuestionSetSnapshot(
        version=question_set_version,
        content_hash=digest,
        questions=questions,
    )


def build_questions_for_unit(
    unit: DecisionUnit,
    *,
    question_set_version: str = QUESTION_SET_VERSION,
) -> list[DecisionQuestion]:
    """Build the independent graphic-selection questions for one concept unit."""
    return [
        DecisionQuestion(
            question_id=spec.question_id,
            target_unit_id=unit.unit_id,
            question_kind=spec.question_kind,
            wording=spec.wording,
            question_set_version=question_set_version,
            options=list(spec.options) if spec.options else None,
            noul_criteria=dict(spec.noul_criteria) if spec.noul_criteria else None,
        )
        for spec in question_templates()
    ]


def expected_question_ids() -> list[str]:
    return [spec.question_id for spec in question_templates()]


__all__ = [
    "PATTERN_OPTIONS",
    "QUESTION_SET_PATH",
    "QUESTION_SET_VERSION",
    "REPRESENTATION_QUESTION_ID",
    "build_questions_for_unit",
    "data_shapes",
    "expected_question_ids",
    "load_question_set_raw",
    "noul_ids",
    "pattern_options",
    "question_templates",
    "shape_preference",
    "snapshot_question_set",
]
