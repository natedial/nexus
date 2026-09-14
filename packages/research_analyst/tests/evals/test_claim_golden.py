from __future__ import annotations

from pathlib import Path

from research_analysis_layer.services.claim_key_resolver import (
    ClaimKeyResolver,
    load_claim_golden,
    score_claim_golden,
)

GOLDEN_PATH = Path(__file__).resolve().parents[2] / "evals" / "golden" / "claims.jsonl"


def test_claim_golden_covers_multiple_publishers():
    rows = load_claim_golden(GOLDEN_PATH)
    assert len(rows) >= 15
    publishers = {row["publisher"] for row in rows}
    assert len(publishers) >= 2


def test_claim_golden_has_no_false_merges():
    rows = load_claim_golden(GOLDEN_PATH)
    report = score_claim_golden(rows, ClaimKeyResolver())
    assert report["false_merges"] == 0, report
    assert report["precision"] == 1.0, report
    assert report["recall"] >= 0.85, report
    assert report["contradiction_hits"] == report["contradiction_pairs"]
