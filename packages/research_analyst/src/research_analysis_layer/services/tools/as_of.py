"""As-of limits for agent tools.

While a scope is active a tool may only show material dated on or before the
document under analysis. Undated material is withheld, because it cannot be
shown to be earlier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Callable


@dataclass(frozen=True, slots=True)
class AsOfScope:
    """What one run may see. ``as_of=None`` means the document date is unknown."""

    as_of: date | None
    exclude_research_id: int | None = None

    def allows(self, value: Any) -> bool:
        day = parse_day(value)
        return self.as_of is not None and day is not None and day <= self.as_of

    def clamp(self, requested: str | None) -> str | None:
        """The earlier of the requested upper bound and the scope's date."""
        day = parse_day(requested)
        bounds = [item for item in (day, self.as_of) if item is not None]
        return min(bounds).isoformat() if bounds else None


def parse_day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def as_of_aware(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a handler that accepts ``as_of`` and enforces it."""
    handler.as_of_aware = True  # type: ignore[attr-defined]
    return handler


def bounded_search(
    results: list[dict[str, Any]], scope: AsOfScope | None
) -> list[dict[str, Any]] | dict[str, Any]:
    """Withhold results a scope does not allow. Do not trust the backend's filter."""
    if scope is None:
        return results
    kept = [
        item
        for item in results
        if isinstance(item, dict) and scope.allows(item.get("source_date"))
    ]
    return {
        "results": kept,
        "as_of": scope.as_of.isoformat() if scope.as_of else None,
        "withheld_count": len(results) - len(kept),
    }
