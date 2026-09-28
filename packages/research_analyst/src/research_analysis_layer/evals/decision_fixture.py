"""Helpers for the hand-authored decision-shadow fixture."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_analysis_layer.evals.decision_metrics import GoldUnitLabel, load_gold_labels
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text

FIXTURE_DIR = (
    Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "decision_shadow"
)


def fixture_dir() -> Path:
    return FIXTURE_DIR


def load_fixture_units(path: Path | None = None) -> dict[str, Any]:
    target = path or (fixture_dir() / "units.json")
    return json.loads(target.read_text(encoding="utf-8"))


def load_fixture_labels(path: Path | None = None) -> list[GoldUnitLabel]:
    target = path or (fixture_dir() / "labels.json")
    return load_gold_labels(target)


def fixture_assertions(path: Path | None = None) -> list[AssertionDraft]:
    payload = load_fixture_units(path)
    assertions: list[AssertionDraft] = []
    for row in payload["units"]:
        text = str(row["text"])
        assertions.append(
            AssertionDraft(
                chunk_order=int(row["chunk_order"]),
                assertion_order=int(row["assertion_order"]),
                assertion_type=str(row["assertion_type"]),
                text=text,
                normalized_text=normalize_text(text),
                summary_text=text,
            )
        )
    return assertions


def fixture_provenance(path: Path | None = None) -> dict[str, dict[str, Any]]:
    payload = load_fixture_units(path)
    return {
        str(row["unit_id"]): dict(row.get("provenance") or {})
        for row in payload["units"]
    }


def fixture_section_context(path: Path | None = None) -> dict[str, str]:
    payload = load_fixture_units(path)
    return {
        str(row["unit_id"]): str(row["section_context"])
        for row in payload["units"]
        if row.get("section_context")
    }
