"""Tests for morning_research.qc draft/receipt validation."""

from __future__ import annotations

import json
from pathlib import Path

from morning_research.qc import (
    REQUIRED_SECTION_HEADINGS,
    check_draft,
    check_draft_file,
    check_receipt,
    check_receipt_file,
    run_qc,
)


def _valid_draft(word_padding: int = 150) -> str:
    padding = " ".join(["word"] * word_padding)
    sections = "\n\n".join(f"# {heading}\n\n{padding}" for heading in REQUIRED_SECTION_HEADINGS)
    return f"Provided by Codex\n\n# Research from Jul 20 to Jul 24\n\n{sections}\n"


def _valid_receipt() -> dict:
    return {
        "page_title": "Research from Jul 20 to Jul 24",
        "documents_analyzed": ["file1", "file2"],
        "window_start": "2026-07-20T00:00:00+00:00",
        "window_end": "2026-07-24T00:00:00+00:00",
        "used_fallback_window": False,
    }


def test_check_draft_passes_with_all_sections_and_marker() -> None:
    result = check_draft(_valid_draft())

    assert result.ok is True
    assert result.errors == []


def test_check_draft_fails_without_provided_by_codex_marker() -> None:
    draft = _valid_draft().replace("Provided by Codex\n\n", "")

    result = check_draft(draft)

    assert result.ok is False
    assert any("Provided by Codex" in err for err in result.errors)


def test_check_draft_fails_on_missing_headings() -> None:
    draft = _valid_draft().replace("# Watchlist", "# Some Other Section")

    result = check_draft(draft)

    assert result.ok is False
    assert any("Watchlist" in err for err in result.errors)


def test_check_draft_recognizes_bold_headings() -> None:
    padding = " ".join(["word"] * 150)
    sections = "\n\n".join(f"**{heading}**\n\n{padding}" for heading in REQUIRED_SECTION_HEADINGS)
    draft = f"Provided by Codex\n\n{sections}\n"

    result = check_draft(draft)

    assert result.ok is True


def test_check_draft_fails_below_hard_minimum_word_count() -> None:
    sections = "\n\n".join(f"# {heading}\n\nshort" for heading in REQUIRED_SECTION_HEADINGS)
    draft = f"Provided by Codex\n\n{sections}\n"

    result = check_draft(draft)

    assert result.ok is False
    assert any("below hard-fail minimum" in err for err in result.errors)


def test_check_draft_warns_but_passes_between_400_and_1000_words() -> None:
    result = check_draft(_valid_draft(word_padding=80))

    assert result.ok is True
    assert any("below recommended minimum" in warning for warning in result.warnings)


def test_check_draft_fails_above_hard_maximum_without_justification() -> None:
    result = check_draft(_valid_draft(word_padding=3000))

    assert result.ok is False
    assert any("exceeds hard-fail maximum" in err for err in result.errors)


def test_check_draft_passes_above_max_with_exceptional_reason() -> None:
    result = check_draft(
        _valid_draft(word_padding=3000), exceptional_length_reason="Unusually large batch"
    )

    assert result.ok is True
    assert any("justified" in warning for warning in result.warnings)


def test_check_receipt_passes_with_required_fields() -> None:
    result = check_receipt(_valid_receipt())

    assert result.ok is True


def test_check_receipt_fails_on_missing_fields() -> None:
    receipt = _valid_receipt()
    del receipt["window_start"]

    result = check_receipt(receipt)

    assert result.ok is False
    assert any("window_start" in err for err in result.errors)


def test_check_receipt_fails_when_error_field_present() -> None:
    receipt = _valid_receipt()
    receipt["error"] = "could not parse PDFs"

    result = check_receipt(receipt)

    assert result.ok is False


def test_check_receipt_file_missing(tmp_path: Path) -> None:
    result = check_receipt_file(tmp_path / "receipt.json")

    assert result.ok is False
    assert any("not found" in err for err in result.errors)


def test_check_draft_file_missing(tmp_path: Path) -> None:
    result = check_draft_file(tmp_path / "draft.md")

    assert result.ok is False
    assert any("not found" in err for err in result.errors)


def test_run_qc_end_to_end_success(tmp_path: Path) -> None:
    (tmp_path / "draft.md").write_text(_valid_draft(), encoding="utf-8")
    (tmp_path / "receipt.json").write_text(json.dumps(_valid_receipt()), encoding="utf-8")

    result = run_qc(tmp_path)

    assert result.ok is True


def test_run_qc_end_to_end_failure_propagates_receipt_error(tmp_path: Path) -> None:
    (tmp_path / "draft.md").write_text(_valid_draft(), encoding="utf-8")
    receipt = _valid_receipt()
    receipt["error"] = "boom"
    (tmp_path / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")

    result = run_qc(tmp_path)

    assert result.ok is False
