"""Five claim-note product surfaces (fixture-driven, deterministic)."""

from src.claim_notes.products.author_evolution import author_evolution
from src.claim_notes.products.impromptu_study import impromptu_study
from src.claim_notes.products.morning_attention import build_morning_attention
from src.claim_notes.products.recent_ingest import recent_ingest
from src.claim_notes.products.thematic_digest import thematic_digest

__all__ = [
    "author_evolution",
    "build_morning_attention",
    "impromptu_study",
    "recent_ingest",
    "thematic_digest",
]
