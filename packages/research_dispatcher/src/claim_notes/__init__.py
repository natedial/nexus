"""Claim-note contract for the five product surfaces.

See Agent Store docs/claim-note-howto.md and docs/claim-note-products-plan.md.
"""

from src.claim_notes.load import load_claim_notes
from src.claim_notes.models import (
    CLAIM_NOTE_SCHEMA_VERSION,
    CauseEdge,
    ClaimNote,
    DexterFinding,
    DexterResearchPass,
    DexterSource,
    TimeWindow,
)
from src.claim_notes.validate import (
    ClaimNoteValidationError,
    live_findings_allowed,
    require_live_findings,
    validate_claim_note,
)

__all__ = [
    "CLAIM_NOTE_SCHEMA_VERSION",
    "CauseEdge",
    "ClaimNote",
    "ClaimNoteValidationError",
    "DexterFinding",
    "DexterResearchPass",
    "DexterSource",
    "TimeWindow",
    "live_findings_allowed",
    "load_claim_notes",
    "require_live_findings",
    "validate_claim_note",
]
