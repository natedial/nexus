from __future__ import annotations

from pathlib import Path

from research_analysis_layer.services.evidence_referent_resolver import (
    EvidenceReferentResolver,
    load_referent_golden,
    score_referent_golden,
)

GOLDEN_PATH = (
    Path(__file__).resolve().parents[2] / "evals" / "golden" / "referents.jsonl"
)


def test_referent_golden_exists_and_covers_multiple_publishers():
    rows = load_referent_golden(GOLDEN_PATH)
    assert len(rows) >= 30
    publishers = {row["publisher"] for row in rows}
    assert len(publishers) >= 2
    labeled = [row for row in rows if row.get("coarse_key")]
    assert len(labeled) >= 15


def test_referent_golden_coarse_has_no_false_merges():
    rows = load_referent_golden(GOLDEN_PATH)
    report = score_referent_golden(rows, EvidenceReferentResolver(granularity="coarse"))
    assert report["false_merges"] == 0, report
    assert report["precision"] == 1.0, report
    assert report["recall"] >= 0.85, report
    assert report["publisher_count"] >= 2


def test_referent_golden_fine_has_no_false_merges():
    rows = load_referent_golden(GOLDEN_PATH)
    report = score_referent_golden(rows, EvidenceReferentResolver(granularity="fine"))
    assert report["false_merges"] == 0, report
    assert report["precision"] == 1.0, report
