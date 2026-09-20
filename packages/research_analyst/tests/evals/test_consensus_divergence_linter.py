"""Tests for the deterministic cross-author consensus/divergence linter."""

from __future__ import annotations

from research_analysis_layer.evals.comparison import lint_consensus_divergence
from research_analysis_layer.models.consensus_models import (
    ConsensusPoint,
    ConsensusSnapshot,
    DivergencePoint,
    DivergenceSide,
    GroundedReason,
)


def _codes(violations) -> list[str]:
    return [v.code for v in violations]


def _reason(**overrides) -> dict:
    data = {"text": "payrolls slowed", "ref_key": "span:gs-1"}
    data.update(overrides)
    return data


def _side(position: str = "Goldman Sachs", **overrides) -> dict:
    data = {
        "position": position,
        "claim": "a September hike is unlikely",
        "polarity": "down",
        "reasons": [_reason()],
    }
    data.update(overrides)
    return data


def _divergence(**overrides) -> dict:
    data = {
        "point": "Fed hike path",
        "sides": [
            _side("Goldman Sachs"),
            _side(
                "Barclays",
                claim="a September hike is likely",
                polarity="up",
                reasons=[_reason(text="hawkish Jackson Hole", ref_key="span:barc-1")],
            ),
        ],
        "verdict": "contested",
        "favored_position": None,
    }
    data.update(overrides)
    return data


def _consensus(**overrides) -> dict:
    data = {
        "point": "labor has cooled",
        "positions": ["Goldman Sachs", "Citi"],
        "reasons": [_reason(text="payrolls slowed", ref_key="span:gs-1")],
    }
    data.update(overrides)
    return data


def test_lint_consensus_divergence_clean_points_have_no_violations():
    violations = lint_consensus_divergence([_consensus(), _divergence()])
    assert violations == []


def test_lint_consensus_divergence_clean_snapshot_has_no_violations():
    snapshot = ConsensusSnapshot(
        agreements=[
            ConsensusPoint(
                point="labor has cooled",
                positions=["Goldman Sachs", "Citi"],
                reasons=[GroundedReason(text="payrolls slowed", ref_key="span:gs-1")],
                confidence=0.8,
                subject="labor",
                predicate="cooled",
                polarity="down",
                horizon_bucket="meeting_2026_09",
                source_diversity=2,
            )
        ],
        disagreements=[
            DivergencePoint(
                point="Fed hike path",
                sides=[
                    DivergenceSide(
                        position="Goldman Sachs",
                        claim="hike is unlikely",
                        polarity="down",
                        reasons=[GroundedReason(text="payrolls slowed", ref_key="span:gs-1")],
                    ),
                    DivergenceSide(
                        position="Barclays",
                        claim="hike is likely",
                        polarity="up",
                        reasons=[
                            GroundedReason(
                                text="hawkish Jackson Hole",
                                ref_key="span:barc-1",
                            )
                        ],
                    ),
                ],
                subject="fed_policy",
                predicate="hike",
                horizon_bucket="meeting_2026_09",
                source_diversity=2,
            )
        ],
    )
    assert lint_consensus_divergence(snapshot) == []


def test_lint_consensus_divergence_flags_too_few_sides():
    violations = lint_consensus_divergence(
        [_divergence(sides=[_side("Goldman Sachs")])]
    )
    assert "TOO_FEW_SIDES" in _codes(violations)
    too_few = [v for v in violations if v.code == "TOO_FEW_SIDES"][0]
    assert too_few.claim_index == 0


def test_lint_consensus_divergence_flags_non_distinct_side_publishers():
    violations = lint_consensus_divergence(
        [
            _divergence(
                sides=[
                    _side("Goldman Sachs"),
                    _side(
                        "Goldman Sachs",
                        claim="hike is likely",
                        polarity="up",
                        reasons=[_reason(ref_key="span:gs-2")],
                    ),
                ]
            )
        ]
    )
    assert "NON_DISTINCT_SIDES" in _codes(violations)


def test_lint_consensus_divergence_flags_ungrounded_side():
    violations = lint_consensus_divergence(
        [
            _divergence(
                sides=[
                    _side("Goldman Sachs", reasons=[]),
                    _side(
                        "Barclays",
                        claim="hike is likely",
                        polarity="up",
                        reasons=[_reason(ref_key="span:barc-1")],
                    ),
                ]
            )
        ]
    )
    assert "UNGROUNDED_SIDE" in _codes(violations)
    ungrounded = [v for v in violations if v.code == "UNGROUNDED_SIDE"][0]
    assert ungrounded.claim_index == 0
    assert "Goldman Sachs" in ungrounded.detail


def test_lint_consensus_divergence_flags_side_reason_without_ref_key():
    violations = lint_consensus_divergence(
        [
            _divergence(
                sides=[
                    _side("Goldman Sachs", reasons=[{"text": "payrolls slowed", "ref_key": ""}]),
                    _side(
                        "Barclays",
                        claim="hike is likely",
                        polarity="up",
                        reasons=[_reason(ref_key="span:barc-1")],
                    ),
                ]
            )
        ]
    )
    assert "UNGROUNDED_SIDE" in _codes(violations)


def test_lint_consensus_divergence_flags_missing_verdict():
    point = _divergence()
    del point["verdict"]
    violations = lint_consensus_divergence([point])
    assert "MISSING_VERDICT" in _codes(violations)
    missing = [v for v in violations if v.code == "MISSING_VERDICT"][0]
    assert missing.claim_index == 0


def test_lint_consensus_divergence_flags_favored_position_without_favored_verdict():
    violations = lint_consensus_divergence(
        [_divergence(verdict="contested", favored_position="Goldman Sachs")]
    )
    assert "BAD_FAVORED_POSITION" in _codes(violations)
    bad = [v for v in violations if v.code == "BAD_FAVORED_POSITION"][0]
    assert bad.claim_index == 0


def test_lint_consensus_divergence_flags_position_favored_without_favored_position():
    violations = lint_consensus_divergence(
        [_divergence(verdict="position_favored", favored_position=None)]
    )
    assert "BAD_FAVORED_POSITION" in _codes(violations)


def test_lint_consensus_divergence_allows_favored_position_with_position_favored():
    violations = lint_consensus_divergence(
        [_divergence(verdict="position_favored", favored_position="Goldman Sachs")]
    )
    assert "BAD_FAVORED_POSITION" not in _codes(violations)
    assert violations == []


def test_lint_consensus_divergence_flags_too_few_consensus_publishers():
    violations = lint_consensus_divergence(
        [_consensus(positions=["Goldman Sachs"])]
    )
    assert "TOO_FEW_PUBLISHERS" in _codes(violations)
    too_few = [v for v in violations if v.code == "TOO_FEW_PUBLISHERS"][0]
    assert too_few.claim_index == 0


def test_lint_consensus_divergence_flags_duplicate_consensus_publishers():
    violations = lint_consensus_divergence(
        [_consensus(positions=["Goldman Sachs", "Goldman Sachs"])]
    )
    assert "TOO_FEW_PUBLISHERS" in _codes(violations)


def test_lint_consensus_divergence_flags_missing_shared_reason():
    violations = lint_consensus_divergence([_consensus(reasons=[])])
    assert "MISSING_SHARED_REASON" in _codes(violations)
    missing = [v for v in violations if v.code == "MISSING_SHARED_REASON"][0]
    assert missing.claim_index == 0


def test_lint_consensus_divergence_flags_ungrounded_shared_reason():
    violations = lint_consensus_divergence(
        [_consensus(reasons=[{"text": "payrolls slowed", "ref_key": None}])]
    )
    assert "MISSING_SHARED_REASON" in _codes(violations)


def test_lint_consensus_divergence_flags_lens_as_divergence_side():
    violations = lint_consensus_divergence(
        [
            _divergence(
                sides=[
                    _side("thesis"),
                    _side(
                        "Barclays",
                        claim="hike is likely",
                        polarity="up",
                        reasons=[_reason(ref_key="span:barc-1")],
                    ),
                ]
            )
        ]
    )
    assert "LENS_AS_POSITION" in _codes(violations)
    lens = [v for v in violations if v.code == "LENS_AS_POSITION"][0]
    assert lens.claim_index == 0
    assert "thesis" in lens.detail


def test_lint_consensus_divergence_flags_lens_as_consensus_position():
    violations = lint_consensus_divergence(
        [_consensus(positions=["contrarian", "positioning"])]
    )
    codes = _codes(violations)
    assert codes.count("LENS_AS_POSITION") == 2
    details = " ".join(v.detail for v in violations if v.code == "LENS_AS_POSITION")
    assert "contrarian" in details
    assert "positioning" in details
