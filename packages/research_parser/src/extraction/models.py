"""Pydantic models for extraction results."""

from pydantic import BaseModel, Field, field_validator


class Excerpt(BaseModel):
    """A verbatim quote from the document."""

    text: str


class Theme(BaseModel):
    """An extracted theme from the document."""

    label: str
    excerpts: list[Excerpt]
    relevance: list[str]
    classification: str  # Opinion, Forecast, Description
    mention_count: int
    strength: str  # Primary, Secondary, Peripheral
    directionality: dict[str, int] | None = None
    confidence: str  # High, Medium, Low
    context: str


class Trade(BaseModel):
    """An extracted trade idea from the document."""

    text: str
    exposure: str  # Small, Medium, Large
    timeframe: str  # intraday, days, weeks, months
    conviction: str  # High, Medium, Low
    rationale: str
    trigger_levels: str | None = None


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
