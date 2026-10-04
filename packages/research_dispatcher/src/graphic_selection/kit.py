"""Load print-infographic kit manifest metadata used by the chooser."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import json

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
KIT_MANIFEST_PATH = (
    PACKAGE_ROOT / "styles" / "snippets" / "print-infographic-pattern-manifest.json"
)


@lru_cache(maxsize=1)
def load_kit_manifest() -> dict[str, Any]:
    with KIT_MANIFEST_PATH.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"invalid kit manifest at {KIT_MANIFEST_PATH}")
    return data


def kit_patterns() -> dict[str, dict[str, Any]]:
    patterns = load_kit_manifest().get("patterns") or []
    return {str(item["id"]): item for item in patterns if isinstance(item, dict)}


def kit_selector(pattern_id: str) -> str | None:
    if pattern_id == "prose":
        return None
    pattern = kit_patterns().get(pattern_id)
    if not pattern:
        return None
    selector = pattern.get("selector")
    return str(selector) if selector else None


def kit_required_fields(pattern_id: str) -> list[str]:
    if pattern_id == "prose":
        return []
    pattern = kit_patterns().get(pattern_id)
    if not pattern:
        return []
    fields = pattern.get("required_fields") or []
    return [str(item) for item in fields]


__all__ = [
    "KIT_MANIFEST_PATH",
    "kit_patterns",
    "kit_required_fields",
    "kit_selector",
    "load_kit_manifest",
]
