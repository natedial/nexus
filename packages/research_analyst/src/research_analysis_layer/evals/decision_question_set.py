"""Versioned shadow-classification question set."""

from __future__ import annotations

import hashlib
import json

from research_analysis_layer.models.decision_models import (
    QUESTION_SET_VERSION,
    STATEMENT_TYPE_OPTIONS,
    SUBTYPE_NOUL_IDS,
    SUPPORT_NOUL_IDS,
    DecisionQuestion,
    DecisionUnit,
    FrozenQuestionSpec,
    QuestionSetSnapshot,
)

STATEMENT_TYPE_QUESTION_ID = "statement_type"

STATEMENT_TYPE_WORDING = (
    "What is the primary statement type of the target unit? Choose exactly one: "
    "assertion (author presents a proposition as true or likely), "
    "evidence_report (concrete datum, quote, chart/citation, or prior event), "
    "question (genuinely unresolved or interrogative), "
    "recommendation (action, policy, position, or trade), "
    "background_methodology (framing, definitions, method, or scene-setting), "
    "or other_or_unclear."
)

SUBTYPE_WORDINGS: dict[str, str] = {
    "is_observation": (
        "Does the target unit primarily report an observation or description "
        "of a current or past state?"
    ),
    "is_forecast": "Does the target unit make a forward-looking forecast or projection?",
    "is_causal": "Does the target unit assert a causal relationship?",
    "is_market_impact": (
        "Does the target unit claim an impact on markets, prices, yields, or spreads?"
    ),
    "is_policy_claim": (
        "Does the target unit make a claim about policy, regulation, or central-bank action?"
    ),
    "is_risk_or_scenario": (
        "Does the target unit describe a risk, contingency, or conditional scenario?"
    ),
    "is_comparative": (
        "Does the target unit make an explicit comparison across entities, periods, or views?"
    ),
    "is_trade_or_action": (
        "Does the target unit recommend or describe a trade, positioning, or concrete action?"
    ),
}

SUPPORT_WORDINGS: dict[str, str] = {
    "contains_verifiable_evidence": (
        "Does the target unit report verifiable evidence? Answer yes if it includes "
        "a concrete statistic or measured figure, quoted source text, an external "
        "citation, a chart/table/figure reference, or a named data release. Answer "
        "no for pure interpretation, forecast, or recommendation without such content."
    ),
    "contains_reasoning_bridge": (
        "Does the target unit contain an explicit reasoning bridge linking evidence "
        "or premises to a conclusion?"
    ),
    "is_substantive_author_claim": (
        "Is the target unit a substantive author claim rather than non-substantive "
        "background or boilerplate?"
    ),
}

# Optional Noul true/false criteria passed through Jev for sharper boundaries.
SUPPORT_NOUL_CRITERIA: dict[str, dict[str, str]] = {
    "contains_verifiable_evidence": {
        "true": (
            "Contains checkable factual content: statistic/figure, quote, citation, "
            "chart/table reference, or named data release."
        ),
        "false": (
            "No checkable factual content; only interpretation, forecast, question, "
            "recommendation, or background."
        ),
    },
}


def question_templates() -> list[FrozenQuestionSpec]:
    """Unit-independent question templates (wording/options/criteria)."""
    questions: list[FrozenQuestionSpec] = [
        FrozenQuestionSpec(
            question_id=STATEMENT_TYPE_QUESTION_ID,
            question_kind="choice",
            wording=STATEMENT_TYPE_WORDING,
            options=list(STATEMENT_TYPE_OPTIONS),
        )
    ]
    for question_id in SUBTYPE_NOUL_IDS:
        questions.append(
            FrozenQuestionSpec(
                question_id=question_id,
                question_kind="noul",
                wording=SUBTYPE_WORDINGS[question_id],
            )
        )
    for question_id in SUPPORT_NOUL_IDS:
        questions.append(
            FrozenQuestionSpec(
                question_id=question_id,
                question_kind="noul",
                wording=SUPPORT_WORDINGS[question_id],
                noul_criteria=SUPPORT_NOUL_CRITERIA.get(question_id),
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
    """Build the independent question set for one assertion unit."""
    return [
        DecisionQuestion(
            question_id=spec.question_id,
            target_unit_id=unit.unit_id,
            question_kind=spec.question_kind,
            wording=spec.wording,
            question_set_version=question_set_version,
            options=list(spec.options) if spec.options is not None else None,
            noul_criteria=dict(spec.noul_criteria) if spec.noul_criteria else None,
        )
        for spec in question_templates()
    ]


def expected_question_ids() -> tuple[str, ...]:
    """Stable ordered list of question IDs in the active set."""
    return (STATEMENT_TYPE_QUESTION_ID, *SUBTYPE_NOUL_IDS, *SUPPORT_NOUL_IDS)
