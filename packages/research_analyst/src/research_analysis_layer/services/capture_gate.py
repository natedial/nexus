"""Pure quality gate deciding whether to capture an analysis output."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CaptureDecision:
    capture: bool
    reason: str


def should_capture(
    doc_analysis: dict[str, Any],
    debate_session: dict[str, Any] | None,
    *,
    min_confidence: float = 0.75,
) -> CaptureDecision:
    """Gate capture on confidence + forum-level acceptance signals."""
    thesis = (doc_analysis.get("thesis") or "").strip()
    if not thesis:
        return CaptureDecision(capture=False, reason="missing thesis")

    confidence = float(doc_analysis.get("confidence", 0.0) or 0.0)
    if confidence < min_confidence:
        return CaptureDecision(
            capture=False,
            reason=f"confidence {confidence:.2f} below {min_confidence:.2f}",
        )

    verdicts = (debate_session or {}).get("verdicts") or []
    accepted = sum(
        1 for v in verdicts if str(v.get("verdict_label", "")).lower() == "accepted"
    )
    if accepted == 0:
        return CaptureDecision(capture=False, reason="no accepted forum verdicts")

    return CaptureDecision(capture=True, reason="ok")
