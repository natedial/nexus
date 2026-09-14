"""Quality control checks for Codex output (draft.md + receipt.json)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

REQUIRED_SECTION_HEADINGS = [
    "Executive Takeaways",
    "What Changed Versus Recent Research",
    "Changes in Views, Forecasts, or Recommendations",
    "Key Themes and Evidence",
    "Contrarian Views and Disagreements",
    "Watchlist",
    "Report Index",
]

REQUIRED_RECEIPT_FIELDS = [
    "page_title",
    "documents_analyzed",
    "window_start",
    "window_end",
    "used_fallback_window",
]

MIN_WORD_COUNT_HARD_FAIL = 400
MIN_WORD_COUNT_WARN = 1000
MAX_WORD_COUNT_HARD_FAIL = 2500


@dataclass
class QCResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    word_count: int = 0

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise QCFailure(self.errors)


class QCFailure(Exception):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def _normalize_heading_text(line: str) -> str:
    """Strip markdown heading/bold markers and surrounding whitespace."""
    stripped = line.strip()
    stripped = re.sub(r"^#+\s*", "", stripped)
    stripped = stripped.strip("*").strip()
    return stripped


def _extract_headings(markdown: str) -> set[str]:
    headings = set()
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or (stripped.startswith("**") and stripped.endswith("**")):
            headings.add(_normalize_heading_text(stripped).lower())
    return headings


def _word_count(markdown: str) -> int:
    return len(re.findall(r"\S+", markdown))


def check_draft(draft_markdown: str, *, exceptional_length_reason: str | None = None) -> QCResult:
    errors: list[str] = []
    warnings: list[str] = []

    head = draft_markdown.strip().splitlines()[:5]
    if not any("provided by codex" in line.lower() for line in head):
        errors.append('First lines of draft.md must include "Provided by Codex"')

    headings = _extract_headings(draft_markdown)
    missing_headings = [
        heading for heading in REQUIRED_SECTION_HEADINGS if heading.lower() not in headings
    ]
    if missing_headings:
        errors.append(f"Missing required section headings: {missing_headings}")

    word_count = _word_count(draft_markdown)
    if word_count < MIN_WORD_COUNT_HARD_FAIL:
        errors.append(f"Word count {word_count} is below hard-fail minimum {MIN_WORD_COUNT_HARD_FAIL}")
    elif word_count < MIN_WORD_COUNT_WARN:
        warnings.append(f"Word count {word_count} is below recommended minimum {MIN_WORD_COUNT_WARN}")

    if word_count > MAX_WORD_COUNT_HARD_FAIL and not exceptional_length_reason:
        errors.append(
            f"Word count {word_count} exceeds hard-fail maximum {MAX_WORD_COUNT_HARD_FAIL} "
            "and receipt.json does not provide exceptional_length_reason"
        )
    elif word_count > MAX_WORD_COUNT_HARD_FAIL:
        warnings.append(
            f"Word count {word_count} exceeds {MAX_WORD_COUNT_HARD_FAIL} but was justified: "
            f"{exceptional_length_reason}"
        )

    ok = not errors
    if not ok:
        logger.error("Draft QC failed", errors=errors)
    elif warnings:
        logger.warning("Draft QC passed with warnings", warnings=warnings)
    return QCResult(ok=ok, errors=errors, warnings=warnings, word_count=word_count)


def check_receipt(receipt: dict[str, Any]) -> QCResult:
    errors: list[str] = []
    warnings: list[str] = []

    missing_fields = [field_name for field_name in REQUIRED_RECEIPT_FIELDS if field_name not in receipt]
    if missing_fields:
        errors.append(f"receipt.json missing required fields: {missing_fields}")

    if receipt.get("error"):
        errors.append(f"receipt.json reports an error: {receipt['error']}")

    documents_analyzed = receipt.get("documents_analyzed")
    if documents_analyzed is not None and not isinstance(documents_analyzed, list):
        errors.append("receipt.json documents_analyzed must be a list")

    used_fallback = receipt.get("used_fallback_window")
    if used_fallback is not None and not isinstance(used_fallback, bool):
        errors.append("receipt.json used_fallback_window must be a boolean")

    ok = not errors
    if not ok:
        logger.error("Receipt QC failed", errors=errors)
    return QCResult(ok=ok, errors=errors, warnings=warnings)


def check_receipt_file(receipt_path: Path) -> QCResult:
    if not receipt_path.exists():
        return QCResult(ok=False, errors=[f"receipt.json not found at {receipt_path}"])
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return QCResult(ok=False, errors=[f"receipt.json is not valid JSON: {exc}"])
    return check_receipt(receipt)


def check_draft_file(draft_path: Path, *, exceptional_length_reason: str | None = None) -> QCResult:
    if not draft_path.exists():
        return QCResult(ok=False, errors=[f"draft.md not found at {draft_path}"])
    markdown = draft_path.read_text(encoding="utf-8")
    return check_draft(markdown, exceptional_length_reason=exceptional_length_reason)


def run_qc(work_dir: Path) -> QCResult:
    """Run both draft and receipt QC checks against a run's work_dir."""
    receipt_result = check_receipt_file(work_dir / "receipt.json")
    exceptional_reason = None
    if receipt_result.ok:
        receipt = json.loads((work_dir / "receipt.json").read_text(encoding="utf-8"))
        exceptional_reason = receipt.get("exceptional_length_reason")

    draft_result = check_draft_file(work_dir / "draft.md", exceptional_length_reason=exceptional_reason)

    combined = QCResult(
        ok=receipt_result.ok and draft_result.ok,
        errors=receipt_result.errors + draft_result.errors,
        warnings=receipt_result.warnings + draft_result.warnings,
        word_count=draft_result.word_count,
    )
    return combined
