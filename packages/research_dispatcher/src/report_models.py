"""Typed report and analyst batch models for dispatcher inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


@dataclass(slots=True)
class DispatchQuality:
    score: float | None = None
    passed: bool = True
    warnings: list[str] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "DispatchQuality":
        if not isinstance(data, dict):
            return cls()
        score = data.get("score")
        if score is not None:
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = None
        return cls(
            score=score,
            passed=bool(data.get("passed", True)),
            warnings=_string_list(data.get("warnings")),
            blocking_issues=_string_list(data.get("blocking_issues")),
        )


@dataclass(slots=True)
class DispatchTheme:
    label: str
    context: str = ""
    strength: str = "Secondary"
    confidence: str = "Medium"
    classification: str = "Description"
    relevance: list[str] = field(default_factory=list)
    directionality: dict[str, Any] | None = None
    excerpts: list[str] = field(default_factory=list)
    theme_order: int | None = None
    mention_count: int = 0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchTheme":
        theme_order = data.get("theme_order")
        if theme_order is not None:
            try:
                theme_order = int(theme_order)
            except (TypeError, ValueError):
                theme_order = None
        mention_count = data.get("mention_count", 0)
        try:
            mention_count = int(mention_count)
        except (TypeError, ValueError):
            mention_count = 0
        directionality = data.get("directionality")
        if not isinstance(directionality, dict):
            directionality = None
        return cls(
            label=str(data.get("label") or "Unlabeled"),
            context=str(data.get("context") or ""),
            strength=str(data.get("strength") or "Secondary"),
            confidence=str(data.get("confidence") or "Medium"),
            classification=str(data.get("classification") or "Description"),
            relevance=_string_list(data.get("relevance")),
            directionality=directionality,
            excerpts=_string_list(data.get("excerpts")),
            theme_order=theme_order,
            mention_count=mention_count,
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "label": self.label,
            "context": self.context,
            "strength": self.strength,
            "confidence": self.confidence,
            "classification": self.classification,
            "mention_count": self.mention_count,
        }
        if self.relevance:
            data["relevance"] = list(self.relevance)
        if self.directionality:
            data["directionality"] = dict(self.directionality)
        if self.excerpts:
            data["excerpts"] = list(self.excerpts)
        if self.theme_order is not None:
            data["theme_order"] = self.theme_order
        return data


@dataclass(slots=True)
class DispatchTrade:
    text: str = ""
    exposure: str = ""
    rationale: str = ""
    timeframe: str = "N/A"
    conviction: str = "N/A"
    trigger_levels: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchTrade":
        trigger_levels = data.get("trigger_levels")
        if not isinstance(trigger_levels, dict):
            trigger_levels = None
        return cls(
            text=str(data.get("text") or ""),
            exposure=str(data.get("exposure") or ""),
            rationale=str(data.get("rationale") or ""),
            timeframe=str(data.get("timeframe") or "N/A"),
            conviction=str(data.get("conviction") or "N/A"),
            trigger_levels=trigger_levels,
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "text": self.text,
            "exposure": self.exposure,
            "rationale": self.rationale,
            "timeframe": self.timeframe,
            "conviction": self.conviction,
        }
        if self.trigger_levels:
            data["trigger_levels"] = dict(self.trigger_levels)
        return data


@dataclass(slots=True)
class DispatchAssertion:
    chunk_order: int | None = None
    assertion_order: int | None = None
    assertion_type: str = "observation"
    summary_text: str = ""
    text: str = ""
    status: str = "proposed"
    authority_band: str = "seed"
    time_horizon: str = "unknown"
    time_anchor: str | None = None
    condition_text: str | None = None
    qualifier_text: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchAssertion":
        def _maybe_int(value: Any) -> int | None:
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return cls(
            chunk_order=_maybe_int(data.get("chunk_order")),
            assertion_order=_maybe_int(data.get("assertion_order")),
            assertion_type=str(data.get("assertion_type") or "observation"),
            summary_text=str(data.get("summary_text") or ""),
            text=str(data.get("text") or ""),
            status=str(data.get("status") or "proposed"),
            authority_band=str(data.get("authority_band") or "seed"),
            time_horizon=str(data.get("time_horizon") or "unknown"),
            time_anchor=data.get("time_anchor"),
            condition_text=data.get("condition_text"),
            qualifier_text=data.get("qualifier_text"),
        )


@dataclass(slots=True)
class DispatchWorldNode:
    node_key: str
    node_type: str = "concept"
    canonical_label: str = ""
    status: str = "proposed"
    authority_band: str = "seed"
    support_count: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchWorldNode":
        support_count = data.get("support_count", 1)
        try:
            support_count = int(support_count)
        except (TypeError, ValueError):
            support_count = 1
        return cls(
            node_key=str(data.get("node_key") or ""),
            node_type=str(data.get("node_type") or "concept"),
            canonical_label=str(data.get("canonical_label") or ""),
            status=str(data.get("status") or "proposed"),
            authority_band=str(data.get("authority_band") or "seed"),
            support_count=support_count,
        )


@dataclass(slots=True)
class DispatchWorldEdge:
    edge_key: str
    from_node_key: str = ""
    to_node_key: str = ""
    edge_type: str = "related_to"
    status: str = "proposed"
    authority_band: str = "seed"
    maturity: str = "trace"
    support_count: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchWorldEdge":
        support_count = data.get("support_count", 1)
        try:
            support_count = int(support_count)
        except (TypeError, ValueError):
            support_count = 1
        return cls(
            edge_key=str(data.get("edge_key") or ""),
            from_node_key=str(data.get("from_node_key") or ""),
            to_node_key=str(data.get("to_node_key") or ""),
            edge_type=str(data.get("edge_type") or "related_to"),
            status=str(data.get("status") or "proposed"),
            authority_band=str(data.get("authority_band") or "seed"),
            maturity=str(data.get("maturity") or "trace"),
            support_count=support_count,
        )


@dataclass(slots=True)
class DispatchForecastCandidate:
    indicator_key: str = ""
    event_name: str = ""
    release_date: str | None = None
    forecast_value_text: str = ""
    match_status: str = "unmatched"
    matched_economic_event_id: str | None = None
    review_status: str = "pending"
    extraction_confidence: str = "medium"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchForecastCandidate":
        return cls(
            indicator_key=str(data.get("indicator_key") or ""),
            event_name=str(data.get("event_name") or ""),
            release_date=data.get("release_date"),
            forecast_value_text=str(data.get("forecast_value_text") or ""),
            match_status=str(data.get("match_status") or "unmatched"),
            matched_economic_event_id=data.get("matched_economic_event_id"),
            review_status=str(data.get("review_status") or "pending"),
            extraction_confidence=str(data.get("extraction_confidence") or "medium"),
        )


@dataclass(slots=True)
class DispatchTradingOpportunity:
    thesis: str = ""
    direction: str = "neutral"
    instrument: str = ""
    timeframe: str = "weeks"
    conviction: str = "medium"
    risk_reward_ratio: str | None = None
    key_levels: str | None = None
    rationale: str = ""
    supporting_excerpts: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchTradingOpportunity":
        return cls(
            thesis=str(data.get("thesis") or ""),
            direction=str(data.get("direction") or "neutral"),
            instrument=str(data.get("instrument") or ""),
            timeframe=str(data.get("timeframe") or "weeks"),
            conviction=str(data.get("conviction") or "medium"),
            risk_reward_ratio=data.get("risk_reward_ratio"),
            key_levels=data.get("key_levels"),
            rationale=str(data.get("rationale") or ""),
            supporting_excerpts=_string_list(data.get("supporting_excerpts")),
            risks=_string_list(data.get("risks")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "thesis": self.thesis,
            "direction": self.direction,
            "instrument": self.instrument,
            "timeframe": self.timeframe,
            "conviction": self.conviction,
            "rationale": self.rationale,
            "supporting_excerpts": list(self.supporting_excerpts),
            "risks": list(self.risks),
        }
        if self.risk_reward_ratio is not None:
            data["risk_reward_ratio"] = self.risk_reward_ratio
        if self.key_levels is not None:
            data["key_levels"] = self.key_levels
        return data


@dataclass(slots=True)
class DispatchShortTimeHorizonInsight:
    theme: str = ""
    insight: str = ""
    timeframe_ref: str = "days"
    confidence: str = "medium"
    supporting_excerpt: str = ""
    relevance: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchShortTimeHorizonInsight":
        return cls(
            theme=str(data.get("theme") or ""),
            insight=str(data.get("insight") or ""),
            timeframe_ref=str(data.get("timeframe_ref") or "days"),
            confidence=str(data.get("confidence") or "medium"),
            supporting_excerpt=str(data.get("supporting_excerpt") or ""),
            relevance=_string_list(data.get("relevance")),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "theme": self.theme,
            "insight": self.insight,
            "timeframe_ref": self.timeframe_ref,
            "confidence": self.confidence,
            "supporting_excerpt": self.supporting_excerpt,
        }
        if self.relevance:
            data["relevance"] = list(self.relevance)
        return data


@dataclass(slots=True)
class DispatchTalkingPoint:
    text: str = ""
    context: str = ""
    source_theme: str | None = None
    presentation_use: str = "supporting"
    target_audience: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchTalkingPoint":
        return cls(
            text=str(data.get("text") or ""),
            context=str(data.get("context") or ""),
            source_theme=data.get("source_theme"),
            presentation_use=str(data.get("presentation_use") or "supporting"),
            target_audience=data.get("target_audience"),
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "text": self.text,
            "context": self.context,
            "presentation_use": self.presentation_use,
        }
        if self.source_theme is not None:
            data["source_theme"] = self.source_theme
        if self.target_audience is not None:
            data["target_audience"] = self.target_audience
        return data


@dataclass(slots=True)
class DispatchCorpusReference:
    chunk_id: str = ""
    source_path: str = ""
    source_date: str | None = None
    text: str = ""
    relevance_score: float | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchCorpusReference":
        relevance_score = data.get("relevance_score")
        if relevance_score is not None:
            try:
                relevance_score = float(relevance_score)
            except (TypeError, ValueError):
                relevance_score = None
        return cls(
            chunk_id=str(data.get("chunk_id") or ""),
            source_path=str(data.get("source_path") or ""),
            source_date=data.get("source_date"),
            text=str(data.get("text") or ""),
            relevance_score=relevance_score,
        )

    def to_legacy_dict(self) -> dict[str, Any]:
        data = {
            "chunk_id": self.chunk_id,
            "source_path": self.source_path,
            "source_date": self.source_date,
            "text": self.text,
        }
        if self.relevance_score is not None:
            data["relevance_score"] = self.relevance_score
        return data


@dataclass(slots=True)
class DispatchDocument:
    research_id: int
    document_hash: str | None = None
    file_id: str | None = None
    document_name: str = "Untitled"
    source: str = "Unknown"
    source_date: str | None = None
    publisher: str | None = None
    region: str | None = None
    asset_focus: str | None = None
    document_link: str | None = None
    quality: DispatchQuality = field(default_factory=DispatchQuality)
    themes: list[DispatchTheme] = field(default_factory=list)
    trades: list[DispatchTrade] = field(default_factory=list)
    assertions: list[DispatchAssertion] = field(default_factory=list)
    world_nodes: list[DispatchWorldNode] = field(default_factory=list)
    world_edges: list[DispatchWorldEdge] = field(default_factory=list)
    forecast_candidates: list[DispatchForecastCandidate] = field(default_factory=list)
    thesis: str | None = None
    contrarian_view: str | None = None
    recommended_positioning: str | None = None
    trading_opportunities: list[DispatchTradingOpportunity] = field(default_factory=list)
    short_time_horizon_insights: list[DispatchShortTimeHorizonInsight] = field(
        default_factory=list
    )
    talking_points: list[DispatchTalkingPoint] = field(default_factory=list)
    cross_document_references: list[DispatchCorpusReference] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchDocument":
        research_id = data.get("research_id")
        try:
            research_id = int(research_id)
        except (TypeError, ValueError):
            raise ValueError("DispatchDocument requires integer research_id")
        return cls(
            research_id=research_id,
            document_hash=data.get("document_hash"),
            file_id=data.get("file_id"),
            document_name=str(data.get("document_name") or "Untitled"),
            source=str(data.get("source") or "Unknown"),
            source_date=data.get("source_date"),
            publisher=data.get("publisher"),
            region=data.get("region"),
            asset_focus=data.get("asset_focus"),
            document_link=data.get("document_link"),
            quality=DispatchQuality.from_dict(data.get("quality")),
            themes=[
                DispatchTheme.from_dict(item) for item in _dict_list(data.get("themes"))
            ],
            trades=[
                DispatchTrade.from_dict(item) for item in _dict_list(data.get("trades"))
            ],
            assertions=[
                DispatchAssertion.from_dict(item)
                for item in _dict_list(data.get("assertions"))
            ],
            world_nodes=[
                DispatchWorldNode.from_dict(item)
                for item in _dict_list(data.get("world_nodes"))
            ],
            world_edges=[
                DispatchWorldEdge.from_dict(item)
                for item in _dict_list(data.get("world_edges"))
            ],
            forecast_candidates=[
                DispatchForecastCandidate.from_dict(item)
                for item in _dict_list(data.get("forecast_candidates"))
            ],
            thesis=data.get("thesis"),
            contrarian_view=data.get("contrarian_view"),
            recommended_positioning=data.get("recommended_positioning"),
            trading_opportunities=[
                DispatchTradingOpportunity.from_dict(item)
                for item in _dict_list(data.get("trading_opportunities"))
            ],
            short_time_horizon_insights=[
                DispatchShortTimeHorizonInsight.from_dict(item)
                for item in _dict_list(data.get("short_time_horizon_insights"))
            ],
            talking_points=[
                DispatchTalkingPoint.from_dict(item)
                for item in _dict_list(data.get("talking_points"))
            ],
            cross_document_references=[
                DispatchCorpusReference.from_dict(item)
                for item in _dict_list(data.get("cross_document_references"))
            ],
        )

    def to_legacy_record(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if self.publisher:
            metadata["publisher"] = self.publisher
        if self.region:
            metadata["region"] = self.region
        if self.asset_focus:
            metadata["asset_focus"] = self.asset_focus
        if self.document_link:
            metadata["document_link"] = self.document_link
        if self.file_id:
            metadata["document_id"] = self.file_id

        parsed_data: dict[str, Any] = {
            "metadata": metadata,
            "themes": [theme.to_legacy_dict() for theme in self.themes],
            "trades": [trade.to_legacy_dict() for trade in self.trades],
            "assertions": [
                {
                    "chunk_order": assertion.chunk_order,
                    "assertion_order": assertion.assertion_order,
                    "assertion_type": assertion.assertion_type,
                    "summary_text": assertion.summary_text,
                    "text": assertion.text,
                    "status": assertion.status,
                    "authority_band": assertion.authority_band,
                    "time_horizon": assertion.time_horizon,
                    "time_anchor": assertion.time_anchor,
                    "condition_text": assertion.condition_text,
                    "qualifier_text": assertion.qualifier_text,
                }
                for assertion in self.assertions
            ],
            "world_nodes": [
                {
                    "node_key": node.node_key,
                    "node_type": node.node_type,
                    "canonical_label": node.canonical_label,
                    "status": node.status,
                    "authority_band": node.authority_band,
                    "support_count": node.support_count,
                }
                for node in self.world_nodes
            ],
            "world_edges": [
                {
                    "edge_key": edge.edge_key,
                    "from_node_key": edge.from_node_key,
                    "to_node_key": edge.to_node_key,
                    "edge_type": edge.edge_type,
                    "status": edge.status,
                    "authority_band": edge.authority_band,
                    "maturity": edge.maturity,
                    "support_count": edge.support_count,
                }
                for edge in self.world_edges
            ],
            "forecast_candidates": [
                {
                    "indicator_key": forecast.indicator_key,
                    "event_name": forecast.event_name,
                    "release_date": forecast.release_date,
                    "forecast_value_text": forecast.forecast_value_text,
                    "match_status": forecast.match_status,
                    "matched_economic_event_id": forecast.matched_economic_event_id,
                    "review_status": forecast.review_status,
                    "extraction_confidence": forecast.extraction_confidence,
                }
                for forecast in self.forecast_candidates
            ],
            "trading_opportunities": [
                opportunity.to_dict() for opportunity in self.trading_opportunities
            ],
            "short_time_horizon_insights": [
                insight.to_dict()
                for insight in self.short_time_horizon_insights
            ],
            "talking_points": [
                point.to_dict() for point in self.talking_points
            ],
        }

        result = {
            "id": self.research_id,
            "document_hash": self.document_hash,
            "document_name": self.document_name,
            "source": self.source,
            "source_date": self.source_date,
            "publisher": self.publisher,
            "region": self.region,
            "asset_focus": self.asset_focus,
            "document_link": self.document_link,
            "synthesized": False,
            "parsed_data": parsed_data,
            "dispatch_quality": {
                "score": self.quality.score,
                "passed": self.quality.passed,
                "warnings": list(self.quality.warnings),
                "blocking_issues": list(self.quality.blocking_issues),
            },
        }
        if self.thesis:
            result["thesis"] = self.thesis
        if self.contrarian_view:
            result["contrarian_view"] = self.contrarian_view
        if self.recommended_positioning:
            result["recommended_positioning"] = self.recommended_positioning
        if self.trading_opportunities:
            result["trading_opportunities"] = [
                opportunity.to_dict() for opportunity in self.trading_opportunities
            ]
        if self.short_time_horizon_insights:
            result["short_time_horizon_insights"] = [
                insight.to_dict()
                for insight in self.short_time_horizon_insights
            ]
        if self.talking_points:
            result["talking_points"] = [
                point.to_dict() for point in self.talking_points
            ]
        if self.cross_document_references:
            result["cross_document_references"] = [
                item.to_legacy_dict() for item in self.cross_document_references
            ]
        return result


@dataclass(slots=True)
class DispatchBatch:
    batch_key: str
    analysis_version: str | None = None
    generated_at: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)
    documents: list[DispatchDocument] = field(default_factory=list)
    cross_document_signals: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DispatchBatch":
        if not isinstance(data, dict):
            raise ValueError("DispatchBatch payload must be an object")
        return cls(
            batch_key=str(data.get("batch_key") or ""),
            analysis_version=data.get("analysis_version"),
            generated_at=data.get("generated_at"),
            scope=data.get("scope") if isinstance(data.get("scope"), dict) else {},
            documents=[
                DispatchDocument.from_dict(item)
                for item in _dict_list(data.get("documents"))
            ],
            cross_document_signals=(
                data.get("cross_document_signals")
                if isinstance(data.get("cross_document_signals"), dict)
                else {}
            ),
        )

    def to_legacy_records(self) -> list[dict[str, Any]]:
        return [document.to_legacy_record() for document in self.documents]
