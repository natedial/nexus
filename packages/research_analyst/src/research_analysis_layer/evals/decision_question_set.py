"""Versioned shadow-classification question set (v1)."""

from __future__ import annotations

from research_analysis_layer.models.decision_models import (
    QUESTION_SET_VERSION,
    STATEMENT_TYPE_OPTIONS,
    SUBTYPE_NOUL_IDS,
    SUPPORT_NOUL_IDS,
    DecisionQuestion,
    DecisionUnit,
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
        "Does the target unit contain verifiable evidence such as data, a quote, "
        "a citation, or a chart reference?"
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


def build_questions_for_unit(
    unit: DecisionUnit,
    *,
    question_set_version: str = QUESTION_SET_VERSION,
) -> list[DecisionQuestion]:
    """Build the independent v1 question set for one assertion unit."""
    questions: list[DecisionQuestion] = [
        DecisionQuestion(
            question_id=STATEMENT_TYPE_QUESTION_ID,
            target_unit_id=unit.unit_id,
            question_kind="choice",
            wording=STATEMENT_TYPE_WORDING,
            question_set_version=question_set_version,
            options=list(STATEMENT_TYPE_OPTIONS),
        )
    ]
    for question_id in SUBTYPE_NOUL_IDS:
        questions.append(
            DecisionQuestion(
                question_id=question_id,
                target_unit_id=unit.unit_id,
                question_kind="noul",
                wording=SUBTYPE_WORDINGS[question_id],
                question_set_version=question_set_version,
            )
        )
    for question_id in SUPPORT_NOUL_IDS:
        questions.append(
            DecisionQuestion(
                question_id=question_id,
                target_unit_id=unit.unit_id,
                question_kind="noul",
                wording=SUPPORT_WORDINGS[question_id],
                question_set_version=question_set_version,
            )
        )
    return questions


def expected_question_ids() -> tuple[str, ...]:
    """Stable ordered list of question IDs in the v1 set."""
    return (STATEMENT_TYPE_QUESTION_ID, *SUBTYPE_NOUL_IDS, *SUPPORT_NOUL_IDS)
