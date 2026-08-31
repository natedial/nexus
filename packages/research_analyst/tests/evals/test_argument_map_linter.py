"""Tests for the deterministic argument-map linter."""

from __future__ import annotations

from research_analysis_layer.evals.comparison import lint_argument_map


def _codes(violations) -> list[str]:
    return [v.code for v in violations]


def test_lint_argument_map_clean_map_has_no_violations():
    violations = lint_argument_map(
        [
            {
                "claim": "the Fed is done hiking",
                "stance": "dovish",
                "rationale": "dots dropped the last projected hike",
                "support_strength": "evidenced",
                "evidence": [
                    {"text": "December dots", "ref_key": "assertion:chunk-2:1"}
                ],
            },
            {
                "claim": "first cut comes in Q2",
                "stance": "dovish",
                "horizon": "Q2 2026",
                "rationale": "median dot implies an earlier move than priced",
                "support_strength": "reasoned",
                "evidence": [],
            },
        ]
    )
    assert violations == []


def test_lint_argument_map_flags_missing_rationale():
    violations = lint_argument_map(
        [
            {
                "claim": "the Fed is done hiking",
                "rationale": "",
                "support_strength": "asserted",
            }
        ]
    )
    assert len(violations) == 1
    assert violations[0].code == "MISSING_RATIONALE"
    assert violations[0].claim_index == 0


def test_lint_argument_map_flags_evidenced_without_ref_key():
    violations = lint_argument_map(
        [
            {
                "claim": "first cut in Q2",
                "rationale": "dots look dovish",
                "support_strength": "evidenced",
                "evidence": [{"text": "the dots look dovish", "ref_key": None}],
            }
        ]
    )
    assert any(v.code == "UNGROUNDED_EVIDENCED" for v in violations)
    ungrounded = [v for v in violations if v.code == "UNGROUNDED_EVIDENCED"][0]
    assert ungrounded.claim_index == 0


def test_lint_argument_map_flags_duplicate_claims():
    violations = lint_argument_map(
        [
            {
                "claim": "The Fed is done hiking",
                "stance": "dovish",
                "rationale": "dots dropped the hike",
                "support_strength": "reasoned",
            },
            {
                "claim": "the Fed is done hiking",
                "stance": "dovish",
                "rationale": "same conclusion restated",
                "support_strength": "asserted",
            },
        ]
    )
    assert "DUPLICATE_CLAIM" in _codes(violations)
    dup = [v for v in violations if v.code == "DUPLICATE_CLAIM"][0]
    assert dup.claim_index == 1


def test_lint_argument_map_flags_stopword_only_claim():
    violations = lint_argument_map(
        [
            {
                "claim": "the of and",
                "rationale": "not a real claim",
                "support_strength": "asserted",
            }
        ]
    )
    assert any(v.code == "NONSUBSTANTIVE_CLAIM" for v in violations)
    assert [v.claim_index for v in violations if v.code == "NONSUBSTANTIVE_CLAIM"] == [0]
