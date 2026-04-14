"""Build synthesis input payloads from legacy rows or analyst batches."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .report_models import DispatchBatch
from .trade_normalization import normalize_trade_expression


class ThroughlineInputBuilder:
    """Convert dispatcher inputs into prompt-ready synthesis payloads."""

    def build_from_legacy_documents(self, documents: list[dict[str, Any]]) -> dict[str, Any]:
        themes: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        sources: set[str] = set()
        dates: list[date] = []

        for doc in documents:
            parsed_data = doc.get("parsed_data", {})
            if not isinstance(parsed_data, dict):
                continue

            source = str(doc.get("source") or "Unknown")
            doc_name = str(doc.get("document_name") or "Unknown Document")
            source_date = self._parse_source_date(doc.get("source_date"))

            sources.add(source)
            if source_date:
                dates.append(source_date)

            for theme in parsed_data.get("themes", []):
                if not isinstance(theme, dict):
                    continue
                theme_entry = {
                    "source": source,
                    "document": doc_name,
                    "label": theme.get("label", "Unlabeled"),
                    "context": theme.get("context", ""),
                    "strength": theme.get("strength", "Secondary"),
                    "confidence": theme.get("confidence", "Medium"),
                    "classification": theme.get("classification", "Description"),
                    "mention_count": theme.get("mention_count", 0),
                }
                excerpts = theme.get("excerpts")
                if isinstance(excerpts, list) and excerpts:
                    theme_entry["excerpts"] = excerpts
                directionality = theme.get("directionality")
                if isinstance(directionality, dict) and directionality:
                    theme_entry["directionality"] = directionality
                relevance = theme.get("relevance")
                if isinstance(relevance, list) and relevance:
                    theme_entry["relevance"] = relevance
                themes.append(theme_entry)

            for trade in parsed_data.get("trades", []):
                if not isinstance(trade, dict):
                    continue
                trade_text = normalize_trade_expression(
                    trade.get("exposure") or trade.get("text", "")
                )
                if not trade_text:
                    continue
                trades.append(
                    {
                        "source": source,
                        "document": doc_name,
                        "text": trade_text,
                        "conviction": trade.get("conviction", "Medium"),
                        "timeframe": trade.get("timeframe", "weeks"),
                        "rationale": trade.get("rationale", ""),
                    }
                )

        return {
            "themes": themes,
            "trades": trades,
            "document_count": len(documents),
            "sources": sorted(sources),
            "date_range": self._build_date_range(dates),
        }

    def build_from_batch(self, batch: DispatchBatch) -> dict[str, Any]:
        themes: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        trading_opportunities: list[dict[str, Any]] = []
        short_time_horizon_insights: list[dict[str, Any]] = []
        talking_points: list[dict[str, Any]] = []
        assertions: list[dict[str, Any]] = []
        forecasts: list[dict[str, Any]] = []
        world_nodes: list[dict[str, Any]] = []
        world_edges: list[dict[str, Any]] = []
        sources: set[str] = set()
        dates: list[date] = []

        for document in batch.documents:
            sources.add(document.source)
            parsed_date = self._parse_source_date(document.source_date)
            if parsed_date:
                dates.append(parsed_date)
            node_label_by_key = {
                node.node_key: node.canonical_label
                for node in document.world_nodes
                if node.node_key and node.canonical_label
            }

            for theme in document.themes:
                entry: dict[str, Any] = {
                    "source": document.source,
                    "document": document.document_name,
                    "label": theme.label,
                    "context": theme.context,
                    "strength": theme.strength,
                    "confidence": theme.confidence,
                    "classification": theme.classification,
                    "mention_count": theme.mention_count,
                    "quality_score": document.quality.score,
                }
                if theme.excerpts:
                    entry["excerpts"] = list(theme.excerpts)
                if theme.directionality:
                    entry["directionality"] = dict(theme.directionality)
                if theme.relevance:
                    entry["relevance"] = list(theme.relevance)
                themes.append(entry)

            for trade in document.trades:
                trade_text = normalize_trade_expression(trade.exposure or trade.text)
                if not trade_text:
                    continue
                trades.append(
                    {
                        "source": document.source,
                        "document": document.document_name,
                        "text": trade_text,
                        "conviction": trade.conviction,
                        "timeframe": trade.timeframe,
                        "rationale": trade.rationale,
                        "quality_score": document.quality.score,
                    }
                )

            for opportunity in document.trading_opportunities:
                trading_opportunities.append(
                    {
                        "source": document.source,
                        "document": document.document_name,
                        "thesis": opportunity.thesis,
                        "direction": opportunity.direction,
                        "instrument": opportunity.instrument,
                        "timeframe": opportunity.timeframe,
                        "conviction": opportunity.conviction,
                        "risk_reward_ratio": opportunity.risk_reward_ratio,
                        "key_levels": opportunity.key_levels,
                        "rationale": opportunity.rationale,
                        "supporting_excerpts": list(opportunity.supporting_excerpts),
                        "risks": list(opportunity.risks),
                        "quality_score": document.quality.score,
                    }
                )

            for insight in document.short_time_horizon_insights:
                short_time_horizon_insights.append(
                    {
                        "source": document.source,
                        "document": document.document_name,
                        "theme": insight.theme,
                        "insight": insight.insight,
                        "timeframe_ref": insight.timeframe_ref,
                        "confidence": insight.confidence,
                        "supporting_excerpt": insight.supporting_excerpt,
                        "relevance": list(insight.relevance),
                        "quality_score": document.quality.score,
                    }
                )

            for point in document.talking_points:
                talking_points.append(
                    {
                        "source": document.source,
                        "document": document.document_name,
                        "text": point.text,
                        "context": point.context,
                        "source_theme": point.source_theme,
                        "presentation_use": point.presentation_use,
                        "target_audience": point.target_audience,
                        "quality_score": document.quality.score,
                    }
                )

            for assertion in document.assertions:
                assertions.append(
                    {
                        "source": document.source,
                        "document": document.document_name,
                        "summary_text": assertion.summary_text,
                        "text": assertion.text,
                        "assertion_type": assertion.assertion_type,
                        "status": assertion.status,
                        "authority_band": assertion.authority_band,
                        "time_horizon": assertion.time_horizon,
                        "time_anchor": assertion.time_anchor,
                        "condition_text": assertion.condition_text,
                        "qualifier_text": assertion.qualifier_text,
                        "quality_score": document.quality.score,
                    }
                )

            for forecast in document.forecast_candidates:
                forecasts.append(
                    {
                        "source": document.source,
                        "document": document.document_name,
                        "indicator_key": forecast.indicator_key,
                        "event_name": forecast.event_name,
                        "release_date": forecast.release_date,
                        "forecast_value_text": forecast.forecast_value_text,
                        "match_status": forecast.match_status,
                        "matched_economic_event_id": forecast.matched_economic_event_id,
                        "review_status": forecast.review_status,
                        "extraction_confidence": forecast.extraction_confidence,
                    }
                )

            for node in document.world_nodes:
                world_nodes.append(
                    {
                        "source": document.source,
                        "document": document.document_name,
                        "node_key": node.node_key,
                        "node_type": node.node_type,
                        "canonical_label": node.canonical_label,
                        "status": node.status,
                        "authority_band": node.authority_band,
                        "support_count": node.support_count,
                    }
                )

            for edge in document.world_edges:
                world_edges.append(
                    {
                        "source": document.source,
                        "document": document.document_name,
                        "edge_key": edge.edge_key,
                        "from_node_key": edge.from_node_key,
                        "to_node_key": edge.to_node_key,
                        "from_label": node_label_by_key.get(edge.from_node_key, ""),
                        "to_label": node_label_by_key.get(edge.to_node_key, ""),
                        "edge_type": edge.edge_type,
                        "status": edge.status,
                        "authority_band": edge.authority_band,
                        "maturity": edge.maturity,
                        "support_count": edge.support_count,
                    }
                )

        return {
            "themes": themes,
            "trades": trades,
            "trading_opportunities": trading_opportunities,
            "short_time_horizon_insights": short_time_horizon_insights,
            "talking_points": talking_points,
            "assertions": assertions,
            "forecasts": forecasts,
            "world_nodes": world_nodes,
            "world_edges": world_edges,
            "document_count": len(batch.documents),
            "sources": sorted(sources),
            "date_range": self._build_date_range(dates),
            "scope": dict(batch.scope),
            "batch_key": batch.batch_key,
            "analysis_version": batch.analysis_version,
            "cross_document_signals": dict(batch.cross_document_signals),
        }

    @staticmethod
    def _parse_source_date(value: Any) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed.date()
            except ValueError:
                return None
        return None

    @staticmethod
    def _build_date_range(dates: list[date]) -> str:
        if not dates:
            return datetime.now().strftime("%Y-%m-%d")
        dates_sorted = sorted(dates)
        return f"{dates_sorted[0].isoformat()} to {dates_sorted[-1].isoformat()}"
