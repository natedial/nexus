"""Prefilter heuristic tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from morning_research.models import CandidateDoc
from morning_research.prefilter import prefilter


def _doc(name: str, size: int = 10_000) -> CandidateDoc:
    now = datetime(2026, 7, 24, tzinfo=timezone.utc)
    return CandidateDoc(
        file_id=name,
        name=name,
        mime_type="application/pdf",
        modified_time=now,
        created_time=now,
        size_bytes=size,
        content_hash=f"sha256:{name}",
        local_path=Path(f"/tmp/{name}"),
    )


def test_rejects_small_and_disclosure_names() -> None:
    kept, excluded = prefilter(
        [
            _doc("2026-07-01_GS_rates.pdf", 50_000),
            _doc("important_information.pdf", 50_000),
            _doc("tiny.pdf", 100),
        ],
        min_pdf_bytes=2048,
    )
    assert len(kept) == 1
    assert kept[0].name.endswith("GS_rates.pdf")
    reasons = {doc.name: doc.exclusion_reason or "" for doc in excluded}
    assert "disclosure" in reasons["important_information.pdf"]
    assert "size_bytes" in reasons["tiny.pdf"]
