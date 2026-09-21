"""Tests for Slice 3 rubric-rate aggregation and the promotion gate."""

from __future__ import annotations

import json
from pathlib import Path

from research_analysis_layer.evals.rubric_metrics import (
    RubricRates,
    aggregate_rubric_metrics,
    evaluate_promotion_gate,
    load_rubric_baseline,
)
from research_analysis_layer.models.consensus_models import (
    ConsensusPoint,
    ConsensusSnapshot,
    DivergencePoint,
    DivergenceSide,
    GroundedReason,
)


def _claim(**overrides) -> dict:
    data = {
        "claim": "the Fed is done hiking",
        "stance": "dovish",
        "rationale": "dots dropped the last projected hike",
        "support_strength": "evidenced",
        "evidence": [{"text": "December dots", "ref_key": "span:gs-1"}],
    }
    data.update(overrides)
    return data


def _reason(text: str = "payrolls slowed", ref_key: str = "span:gs-1") -> GroundedReason:
    return GroundedReason(text=text, ref_key=ref_key)


def _side(position: str, *, grounded: bool = True) -> DivergenceSide:
    return DivergenceSide(
        position=position,
        claim="hike call",
        polarity="down",
        reasons=[_reason()] if grounded else [],
    )


def _snapshot(
    *,
    positions: list[str] | None = None,
    sides: list[DivergenceSide] | None = None,
) -> ConsensusSnapshot:
    agreements = []
    if positions is not None:
        agreements.append(
            ConsensusPoint(
                point="labor cooled",
                positions=positions,
                reasons=[_reason()],
                confidence=0.8,
                subject="labor",
                predicate="cooled",
                polarity="down",
                horizon_bucket="meeting_2026_09",
                source_diversity=len(set(positions)),
            )
        )
    disagreements = []
    if sides is not None:
        disagreements.append(
            DivergencePoint(
                point="Fed hike path",
                sides=sides,
                subject="fed_policy",
                predicate="hike",
                horizon_bucket="meeting_2026_09",
                source_diversity=len(sides),
            )
        )
    return ConsensusSnapshot(agreements=agreements, disagreements=disagreements)


def test_clean_linted_docs_have_full_rates():
    rates = aggregate_rubric_metrics(
        [[_claim()], [_claim(claim="first cut in Q2", support_strength="reasoned", evidence=[])]],
        _snapshot(
            positions=["Goldman Sachs", "Citi"],
            sides=[_side("Goldman Sachs"), _side("Barclays", grounded=True)],
        ),
    )
    assert rates.claim_rationale_rate == 1.0
    assert rates.claim_evidenced_rate == 1.0
    assert rates.divergence_grounded_rate == 1.0
    assert rates.divergence_attributed_rate == 1.0
    assert rates.consensus_multi_source_rate == 1.0


def test_missing_rationale_lowers_claim_rationale_rate():
    rates = aggregate_rubric_metrics(
        [[_claim(), _claim(rationale="", support_strength="asserted", evidence=[])]]
    )
    assert rates.claim_count == 2
    assert rates.claim_rationale_rate == 0.5


def test_ungrounded_evidenced_lowers_claim_evidenced_rate():
    rates = aggregate_rubric_metrics(
        [
            [
                _claim(),
                _claim(
                    claim="wages cracked",
                    support_strength="evidenced",
                    evidence=[{"text": "no key", "ref_key": None}],
                ),
            ]
        ]
    )
    assert rates.evidenced_claim_count == 2
    assert rates.claim_evidenced_rate == 0.5


def test_ungrounded_side_lowers_divergence_grounded_rate():
    rates = aggregate_rubric_metrics(
        points=_snapshot(
            sides=[_side("Goldman Sachs"), _side("Barclays", grounded=False)]
        )
    )
    assert rates.divergence_side_count == 2
    assert rates.divergence_grounded_rate == 0.5


def test_lens_as_position_lowers_divergence_attributed_rate():
    rates = aggregate_rubric_metrics(
        points=_snapshot(sides=[_side("thesis"), _side("Barclays")])
    )
    assert rates.divergence_attributed_rate == 0.5


def test_single_publisher_lowers_consensus_multi_source_rate():
    rates = aggregate_rubric_metrics(
        points={
            "agreements": [
                {"positions": ["Goldman Sachs", "Citi"], "reasons": []},
                {"positions": ["Goldman Sachs", "Goldman Sachs"], "reasons": []},
            ],
            "disagreements": [],
        }
    )
    assert rates.consensus_point_count == 2
    assert rates.consensus_multi_source_rate == 0.5


def test_empty_corpus_is_vacuously_full():
    rates = aggregate_rubric_metrics([], None)
    assert rates.as_dict()["claim_rationale_rate"] == 1.0
    assert rates.consensus_multi_source_rate == 1.0


def test_store_rows_are_flattened():
    rows = [
        {
            "source": "Goldman Sachs",
            "payload_json": {"argument_map": [_claim(rationale="")]},
        }
    ]
    rates = aggregate_rubric_metrics(rows)
    assert rates.claim_count == 1
    assert rates.claim_rationale_rate == 0.0


def _rates(**overrides) -> RubricRates:
    values = {
        "claim_rationale_rate": 1.0,
        "claim_evidenced_rate": 1.0,
        "divergence_grounded_rate": 1.0,
        "divergence_attributed_rate": 1.0,
        "consensus_multi_source_rate": 1.0,
    }
    values.update(overrides)
    return RubricRates(**values)


def test_gate_allows_at_floor_when_baseline_exists():
    decision = evaluate_promotion_gate(
        _rates(divergence_grounded_rate=0.8, divergence_attributed_rate=0.8),
        floors={"divergence_grounded_rate": 0.8, "divergence_attributed_rate": 0.8},
        baseline={"divergence_grounded_rate": 0.9},
        mode="blocking",
    )
    assert decision.action == "allow"
    assert decision.failures == []


def test_gate_blocks_below_floor_when_blocking_and_baseline_exists():
    decision = evaluate_promotion_gate(
        _rates(divergence_grounded_rate=0.5),
        floors={"divergence_grounded_rate": 0.8},
        baseline={"divergence_grounded_rate": 0.9},
        mode="blocking",
    )
    assert decision.action == "block"
    assert "divergence_grounded_rate" in decision.failures


def test_gate_warns_when_advisory_and_below_floor():
    decision = evaluate_promotion_gate(
        _rates(divergence_attributed_rate=0.4),
        floors={"divergence_attributed_rate": 0.8},
        baseline={"divergence_attributed_rate": 0.9},
        mode="advisory",
    )
    assert decision.action == "warn"
    assert decision.baseline_present is True


def test_gate_allows_below_floor_when_baseline_missing():
    decision = evaluate_promotion_gate(
        _rates(divergence_grounded_rate=0.1),
        floors={"divergence_grounded_rate": 0.8},
        baseline=None,
        mode="blocking",
    )
    assert decision.action == "allow"
    assert decision.baseline_present is False
    assert "divergence_grounded_rate" in decision.failures


def test_load_rubric_baseline_missing_file_is_none(tmp_path: Path):
    assert load_rubric_baseline(tmp_path / "missing.json") is None


def test_load_rubric_baseline_reads_metrics(tmp_path: Path):
    path = tmp_path / "rubric_rates.json"
    path.write_text(
        json.dumps({"metrics": {"claim_rationale_rate": 0.91, "ignored": 1}}),
        encoding="utf-8",
    )
    baseline = load_rubric_baseline(path)
    assert baseline == {"claim_rationale_rate": 0.91}
