"""Pydantic models for agent analysis outputs."""

from datetime import datetime, timezone
from pydantic import BaseModel, Field


class AgentExecutionMetadata(BaseModel):
    """Shared execution metadata for persisted agent outputs."""

    research_id: int
    document_hash: str
    analysis_version: str
    agent_type: str
    model_requested: str
    model_used: str
    prompt_path: str
    prompt_version: str
    run_id: int
    attempt_count: int
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TradingOpportunity(BaseModel):
    """A trading opportunity derived from document analysis."""

    thesis: str = Field(..., max_length=100)
    direction: str = Field(..., pattern="^(long|short|neutral)$")
    instrument: str = Field(
        ..., description="e.g., EUR/USD, 10Y Treasury, NASDAQ, Gold"
    )
    timeframe: str = Field(..., pattern="^(intraday|days|weeks)$")
    conviction: str = Field(..., pattern="^(high|medium|low)$")
    risk_reward_ratio: str | None = Field(None, description="e.g., 1:2")
    key_levels: str | None = Field(None, description="entry/stop/target levels")
    rationale: str = Field(..., max_length=200)
    supporting_excerpts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class TradingAnalysis(BaseModel):
    """Complete trading analysis for a document."""

    metadata: AgentExecutionMetadata
    opportunities: list[TradingOpportunity] = Field(default_factory=list)
    no_opportunity_reason: str | None = None


class ShortTimeHorizonInsight(BaseModel):
    """Insight relevant to short-term (days/weeks) positioning."""

    theme: str = Field(..., max_length=50)
    insight: str = Field(..., max_length=300)
    timeframe_ref: str = Field(..., pattern="^(days|weeks|intraday)$")
    confidence: str = Field(..., pattern="^(high|medium|low)$")
    supporting_excerpt: str
    relevance: list[str] = Field(default_factory=list)


class ShortTimeHorizonAnalysis(BaseModel):
    """Complete short-term analysis for a document."""

    metadata: AgentExecutionMetadata
    insights: list[ShortTimeHorizonInsight] = Field(default_factory=list)
    summary: str = Field(..., max_length=300)


class TalkingPoint(BaseModel):
    """A quotable, presentation-ready insight."""

    text: str = Field(..., max_length=500)
    context: str = Field(..., max_length=200)
    source_theme: str | None = None
    presentation_use: str = Field(..., pattern="^(headline|supporting|footnote)$")
    target_audience: str | None = Field(None, pattern="^(internal|client|all)$")


class TalkingPointsAnalysis(BaseModel):
    """Complete talking points for a document."""

    metadata: AgentExecutionMetadata
    talking_points: list[TalkingPoint] = Field(default_factory=list)
    primary_headline: str | None = Field(None, max_length=200)
