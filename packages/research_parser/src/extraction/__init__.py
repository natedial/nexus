"""LLM-based content extraction modules.

Note: Synthesis is performed downstream by research_dispatcher,
which aggregates themes/trades across multiple documents.
"""

from .boilerplate import strip_boilerplate
from .metadata import extract_metadata
from .models import (
    ExtractionResult,
    Metadata,
    Theme,
    Trade,
)
from .themes import extract_themes
from .trades import extract_trades

__all__ = [
    "strip_boilerplate",
    "extract_metadata",
    "extract_themes",
    "extract_trades",
    "ExtractionResult",
    "Metadata",
    "Theme",
    "Trade",
]
