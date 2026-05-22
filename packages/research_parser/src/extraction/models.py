"""Pydantic models for extraction results."""

from pydantic import BaseModel, Field, field_validator


# Allowed values for enum-like fields. LLMs sometimes return variations,
# so we normalise to the canonical set and fall back to a default.

_CLASSIFICATION_VALUES = {"Opinion", "Forecast", "Description"}
_STRENGTH_VALUES = {"Primary", "Secondary", "Peripheral"}
_CONFIDENCE_VALUES = {"High", "Medium", "Low"}
_CONVICTION_VALUES = {"High", "Medium", "Low"}
_EXPOSURE_VALUES = {"Small", "Medium", "Large"}
_TIMEFRAME_VALUES = {"intraday", "days", "weeks", "months"}


def _normalise_enum(value: str | None, allowed: set[str], default: str) -> str:
    """Match a value to its canonical form (case-insensitive) or return default."""
    if not value:
        return default
    # Try exact match first
    if value in allowed:
        return value
    # Try case-insensitive match
    lower_map = {v.lower(): v for v in allowed}
    return lower_map.get(value.strip().lower(), default)


class Excerpt(BaseModel):
    """A verbatim quote from the document."""

    text: str


class ArgumentStructure(BaseModel):
    """Structured representation of the argument's architecture."""

    conditionals: list[str] = Field(default_factory=list)
    confidence_basis: str = ""
    dependencies: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)


class Theme(BaseModel):
    """An extracted theme from the document."""

    label: str
    excerpts: list[Excerpt]
    relevance: list[str]
    classification: str = "Description"
    mention_count: int = 0
    strength: str = "Secondary"
    directionality: dict[str, int] | None = None
    confidence: str = "Medium"
    context: str = ""
    argument_structure: ArgumentStructure | None = None

    @field_validator("classification", mode="before")
    @classmethod
    def validate_classification(cls, v):
        return _normalise_enum(v, _CLASSIFICATION_VALUES, "Description")

    @field_validator("strength", mode="before")
    @classmethod
    def validate_strength(cls, v):
        return _normalise_enum(v, _STRENGTH_VALUES, "Secondary")

    @field_validator("confidence", mode="before")
    @classmethod
    def validate_confidence(cls, v):
        return _normalise_enum(v, _CONFIDENCE_VALUES, "Medium")


class Trade(BaseModel):
    """An extracted trade idea from the document."""

    text: str
    exposure: str = "Medium"
    timeframe: str = "weeks"
    conviction: str = "Medium"
    rationale: str = ""
    trigger_levels: str | None = None

    @field_validator("exposure", mode="before")
    @classmethod
    def validate_exposure(cls, v):
        return _normalise_enum(v, _EXPOSURE_VALUES, "Medium")

    @field_validator("timeframe", mode="before")
    @classmethod
    def validate_timeframe(cls, v):
        return _normalise_enum(v, _TIMEFRAME_VALUES, "weeks")

    @field_validator("conviction", mode="before")
    @classmethod
    def validate_conviction(cls, v):
        return _normalise_enum(v, _CONVICTION_VALUES, "Medium")


class Metadata(BaseModel):
    """Document metadata."""

    source: str = "Unknown"
    source_date: str | None = None
    area: str = "Other"
    region: str = "Global"
    asset_focus: str = "multi-asset"
    publisher: str | None = None
    number_pages: int | str | None = None
    keywords: list[str] | str | None = None
    document_id: str | None = None
    document_uri: str | None = None
    document_link: str | None = None

    @field_validator("source", "area", "region", "asset_focus", mode="before")
    @classmethod
    def handle_null_strings(cls, v: str | None, info) -> str:
        """Convert null values to defaults for required string fields."""
        if v is None:
            defaults = {
                "source": "Unknown",
                "area": "Other",
                "region": "Global",
                "asset_focus": "multi-asset",
            }
            return defaults.get(info.field_name, "Unknown")
        return v


class ThroughLine(BaseModel):
    """A synthesized through-line connecting themes and trades."""

    lead: str
    supporting_themes: list[str]
    supporting_trades: list[str] = Field(default_factory=list)
    key_insight: str


class Callout(BaseModel):
    """A quotable callout for reports."""

    text: str
    source_through_line: str


class Synthesis(BaseModel):
    """Complete synthesis of a document."""

    title: str
    through_lines: list[ThroughLine]
    callouts: list[Callout] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Complete extraction result for a document.

    Note: Synthesis is performed downstream by research_dispatcher,
    which aggregates themes/trades across multiple documents.
    """

    metadata: Metadata
    themes: list[Theme]
    trades: list[Trade]
    full_text: str

    # Track which steps succeeded
    metadata_ok: bool = True
    themes_ok: bool = True
    trades_ok: bool = True
