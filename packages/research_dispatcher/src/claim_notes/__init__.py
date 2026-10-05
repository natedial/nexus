"""Claim-note contract for the five product surfaces.

See Agent Store docs/claim-note-howto.md and docs/claim-note-products-plan.md.
"""

from src.claim_notes.library import (
    LIBRARY_NOTION_URL,
    LIBRARY_RESOURCE_TYPE_FILTER,
    FakeLibraryDigestReader,
    LibraryDigestInput,
    LibraryResearchNote,
)
from src.claim_notes.load import load_claim_notes
from src.claim_notes.models import (
    CLAIM_NOTE_SCHEMA_VERSION,
    CauseEdge,
    ClaimNote,
    DexterFinding,
    DexterResearchPass,
    DexterSource,
    SpeakerWeight,
    TimeWindow,
)
from src.claim_notes.products import (
    author_evolution,
    build_morning_attention,
    impromptu_study,
    recent_ingest,
    thematic_digest,
)
from src.claim_notes.project import (
    project_argument_map_batch,
    project_argument_map_document,
)
from src.claim_notes.validate import (
    ClaimNoteValidationError,
    live_findings_allowed,
    require_live_findings,
    validate_claim_note,
)

__all__ = [
    "CLAIM_NOTE_SCHEMA_VERSION",
    "LIBRARY_NOTION_URL",
    "LIBRARY_RESOURCE_TYPE_FILTER",
    "CauseEdge",
    "ClaimNote",
    "ClaimNoteValidationError",
    "DexterFinding",
    "DexterResearchPass",
    "DexterSource",
    "FakeLibraryDigestReader",
    "LibraryDigestInput",
    "LibraryResearchNote",
    "SpeakerWeight",
    "TimeWindow",
    "author_evolution",
    "build_morning_attention",
    "impromptu_study",
    "live_findings_allowed",
    "load_claim_notes",
    "project_argument_map_batch",
    "project_argument_map_document",
    "recent_ingest",
    "require_live_findings",
    "thematic_digest",
    "validate_claim_note",
]
