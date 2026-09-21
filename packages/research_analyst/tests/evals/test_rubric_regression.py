"""Tests for the Slice 3 golden rubric regression report."""

from __future__ import annotations

import json
from pathlib import Path

from research_analysis_layer.evals.rubric_regression import (
    build_rubric_regression_report,
    load_golden_argument_maps,
    load_golden_consensus_points,
)


GOLDEN = Path(__file__).resolve().parents[2] / "evals" / "golden"


class StubRubricJudge:
    def evaluate_claim(self, claim, source_document=""):
        return {
            "scores": {
                "rationale_fidelity": 0.9,
                "substantive_vs_framing": 1.0,
                "groundedness": 0.8,
                "phantom_counterparty": 1.0,
            }
        }

    def evaluate_point(self, point, source_document=""):
        return {
            "scores": {
                "rationale_fidelity": 0.85,
                "substantive_vs_framing": 0.7,
                "groundedness": 0.8,
                "phantom_counterparty": 1.0,
            }
        }


def test_golden_set_includes_labeled_maps_and_points():
    maps = load_golden_argument_maps(GOLDEN)
    points = load_golden_consensus_points(GOLDEN)
    assert len(maps) >= 2
    assert {row["document_id"] for row in maps} >= {"doc_001", "doc_002"}
    assert all(row["argument_map"] for row in maps)
    assert len(points) >= 2
    kinds = {point.get("kind") for point in points}
    assert "consensus" in kinds
    assert "divergence" in kinds


def test_rubric_regression_report_shape_over_golden_set():
    report = build_rubric_regression_report(GOLDEN, judge=StubRubricJudge())
    payload = report.as_dict()
    for key in (
        "total_claims",
        "total_maps",
        "total_points",
        "map_violation_rate",
        "map_violation_counts",
        "point_violation_rate",
        "point_violation_counts",
        "point_linter",
        "judge_scores",
        "delta_vs_previous",
        "regressions",
    ):
        assert key in payload
    assert payload["total_maps"] >= 2
    assert payload["total_claims"] >= 4
    assert payload["total_points"] >= 2
    assert payload["map_violation_rate"] == 0.0
    assert payload["map_violation_counts"] == {}
    assert payload["point_violation_rate"] == 0.0
    assert payload["point_violation_counts"] == {}
    assert payload["point_linter"] == "lint_consensus_divergence"
    assert payload["judge_scores"] is not None
    assert "rationale_fidelity" in payload["judge_scores"]
    assert payload["delta_vs_previous"] == {}
    assert payload["regressions"] == []


def test_golden_consensus_points_pass_the_cross_author_linter():
    from research_analysis_layer.evals.comparison import lint_consensus_divergence

    points = load_golden_consensus_points(GOLDEN)
    assert lint_consensus_divergence(points) == []


def test_rubric_regression_averages_argument_judge_score_bundles():
    from research_analysis_layer.evals.judge import (
        DEFAULT_ARGUMENT_JUDGE_WEIGHTS,
        ArgumentJudgeScore,
    )

    class ScoreJudge:
        def evaluate_claim(self, claim, source_document=""):
            return ArgumentJudgeScore(
                rationale_fidelity=0.4,
                substantive_vs_framing=1.0,
                groundedness=0.8,
                phantom_counterparty=1.0,
                reasoning="claim",
                errors=[],
                weights=dict(DEFAULT_ARGUMENT_JUDGE_WEIGHTS),
            )

        def evaluate_point(self, point, source_document=""):
            return ArgumentJudgeScore(
                rationale_fidelity=0.6,
                substantive_vs_framing=1.0,
                groundedness=0.8,
                phantom_counterparty=1.0,
                reasoning="point",
                errors=[],
                weights=dict(DEFAULT_ARGUMENT_JUDGE_WEIGHTS),
            )

    report = build_rubric_regression_report(GOLDEN, judge=ScoreJudge())
    assert report.judge_scores is not None
    assert 0.4 <= report.judge_scores["rationale_fidelity"] <= 0.6
    assert report.point_linter == "lint_consensus_divergence"


def test_rubric_regression_flags_judge_score_drop():
    judged = build_rubric_regression_report(GOLDEN, judge=StubRubricJudge())
    previous = judged.as_dict()
    previous["judge_scores"] = dict(previous["judge_scores"] or {})
    previous["judge_scores"]["rationale_fidelity"] = 0.99
    dropped = build_rubric_regression_report(
        GOLDEN,
        previous=previous,
        judge=StubRubricJudge(),
    )
    assert "rationale_fidelity" in dropped.delta_vs_previous
    assert any("rationale_fidelity fell" in item for item in dropped.regressions)


def test_rubric_regression_flags_map_violation_rate_rise(tmp_path: Path):
    golden = tmp_path / "golden"
    (golden / "documents").mkdir(parents=True)
    (golden / "documents" / "doc.md").write_text("the Fed held rates.", encoding="utf-8")
    (golden / "annotations.jsonl").write_text(
        json.dumps(
            {
                "document_id": "doc_bad",
                "document_path": "documents/doc.md",
                "source_type": "rates",
                "expected": {
                    "thesis": "hold",
                    "key_claims": [],
                    "trading_opportunities": [],
                    "talking_points": [],
                    "argument_map": [
                        {
                            "claim": "the Fed held",
                            "rationale": "",
                            "support_strength": "asserted",
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (golden / "consensus.jsonl").write_text("", encoding="utf-8")
    report = build_rubric_regression_report(
        golden,
        previous={"map_violation_rate": 0.0},
    )
    assert report.map_violation_rate == 1.0
    assert "MISSING_RATIONALE" in report.map_violation_counts
    assert any("map_violation_rate rose" in item for item in report.regressions)


def test_rubric_report_cli_runs_the_point_linter_offline():
    from research_analysis_layer.evals.cli import main

    code = main(["rubric-report", "--golden", str(GOLDEN)])
    assert code == 0
