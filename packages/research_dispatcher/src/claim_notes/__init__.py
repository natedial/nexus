"""Claim-note contract for the five product surfaces.

See Agent Store docs/claim-note-howto.md and docs/claim-note-products-plan.md.
Ops host steps: docs/morning-attention-ops.md
"""

from src.claim_notes.library import (
    LIBRARY_NOTION_DATABASE_ID,
    LIBRARY_NOTION_URL,
    LIBRARY_RESOURCE_TYPE_FILTER,
    FakeLibraryDigestReader,
    LibraryDigestInput,
    LibraryResearchNote,
    PrefilteredLibraryDigestReader,
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
from src.claim_notes.notion_library import (
    FakeNotionTransport,
    NotionLibraryDigestReader,
)
from src.claim_notes.ops import (
    MorningAttentionOps,
    intended_cron_expression,
    is_intended_weekday_slot,
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
from src.claim_notes.project_library import (
    project_library_research_note,
    project_library_research_notes,
)
from src.claim_notes.validate import (
    ClaimNoteValidationError,
    live_findings_allowed,
    require_live_findings,
    validate_claim_note,
)
from src.claim_notes.watermark import RunWatermarkStore

__all__ = [
    "CLAIM_NOTE_SCHEMA_VERSION",
    "LIBRARY_NOTION_DATABASE_ID",
    "LIBRARY_NOTION_URL",
    "LIBRARY_RESOURCE_TYPE_FILTER",
    "CauseEdge",
    "ClaimNote",
    "ClaimNoteValidationError",
    "DexterFinding",
    "DexterResearchPass",
    "DexterSource",
    "FakeLibraryDigestReader",
    "FakeNotionTransport",
    "LibraryDigestInput",
    "LibraryResearchNote",
    "PrefilteredLibraryDigestReader",
    "MorningAttentionOps",
    "NotionLibraryDigestReader",
    "RunWatermarkStore",
    "SpeakerWeight",
    "TimeWindow",
    "author_evolution",
    "build_morning_attention",
    "impromptu_study",
    "intended_cron_expression",
    "is_intended_weekday_slot",
    "live_findings_allowed",
    "load_claim_notes",
    "project_argument_map_batch",
    "project_argument_map_document",
    "project_library_research_note",
    "project_library_research_notes",
    "recent_ingest",
    "require_live_findings",
    "thematic_digest",
    "validate_claim_note",
]
