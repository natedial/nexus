"""Quality review models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DocumentQualityReport:
    """Deterministic quality assessment for one hydrated document."""

    score: float
    blocking_issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, float | int | str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.blocking_issues
