"""Deterministic claim-note helpers beyond pydantic construction.

Cause edges are stored as said — no world-model checks here.
Live numbers may only be surfaced from a completed Dexter pass.
"""

from __future__ import annotations

from typing import Any

from src.claim_notes.models import ClaimNote


class ClaimNoteValidationError(ValueError):
    """Raised when a product rule fails for a claim note."""


def validate_claim_note(note: ClaimNote | dict[str, Any]) -> ClaimNote:
    """Parse (if needed) and return a structurally valid ClaimNote.

    Accepts live_data notes whose Dexter pass is still commissioned or failed.
    Use ``live_findings_allowed`` / ``require_live_findings`` before surfacing
    numbers so products never invent or fill figures.
    """
    if isinstance(note, ClaimNote):
        # Re-validate to catch mutated instances.
        return ClaimNote.model_validate(note.model_dump(mode="json"))
    return ClaimNote.model_validate(note)


def live_findings_allowed(note: ClaimNote) -> bool:
    """True only when products may surface Dexter findings as live numbers."""
    if note.support_kind != "live_data" or note.dexter_pass is None:
        return False
    pass_ = note.dexter_pass
    return (
        pass_.status == "completed"
        and bool(pass_.findings)
        and bool(pass_.sources)
    )


def require_live_findings(note: ClaimNote) -> None:
    """Fail closed if a product tries to use live numbers without Dexter."""
    if note.support_kind != "live_data":
        raise ClaimNoteValidationError(
            "require_live_findings only applies to live_data notes"
        )
    if note.dexter_pass is None:
        raise ClaimNoteValidationError("live_data requires dexter_pass")
    if note.dexter_pass.status == "commissioned":
        raise ClaimNoteValidationError(
            "Dexter pass still commissioned; products must not invent numbers"
        )
    if note.dexter_pass.status == "failed":
        raise ClaimNoteValidationError(
            "Dexter pass failed; products must not invent or fill numbers"
        )
    if not live_findings_allowed(note):
        raise ClaimNoteValidationError(
            "completed Dexter pass must include sourced findings"
        )
