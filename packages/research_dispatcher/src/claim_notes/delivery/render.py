"""Render morning-attention own surface for delivery channels."""

from __future__ import annotations

from src.claim_notes.products.models import MorningAttentionSurface


def morning_attention_markdown(surface: MorningAttentionSurface, *, title: str) -> str:
    """Remarkdown-safe markdown for the own reMarkable notebook."""
    lines = [f"# {title}", ""]
    if not surface.points:
        lines.append("No morning-attention points for this run.")
        return "\n".join(lines)
    for point in surface.points:
        lines.append(f"- {point.text}")
    lines.append("")
    lines.append(
        "Own surface — not folded into G10 Calendar or Research From tablet pushes."
    )
    return "\n".join(lines)


def morning_attention_chat_line(surface: MorningAttentionSurface, *, as_of: str) -> str:
    """One-line chat ping (same brief pattern: short notice, not the full body)."""
    n = len(surface.points)
    return f"Morning attention ready ({as_of}): {n} point{'s' if n != 1 else ''}."
