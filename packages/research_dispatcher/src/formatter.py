from __future__ import annotations

from typing import Any
from datetime import datetime, timedelta, date
from collections import Counter, defaultdict
import hashlib
import re

from config import parse_trade_conviction_filter
from .report_models import DispatchBatch, DispatchDocument
from .trade_normalization import dedupe_text_items, normalize_trade_expression


class ReportFormatter:
    """Formats legacy rows or analyst batches into report-ready structures."""

    @staticmethod
    def _generate_item_id(text: str) -> str:
        """Generate a short hash ID for an item (theme/through-line)."""
        return hashlib.sha256(text.encode()).hexdigest()[:8]

    def format_report(
        self,
        data: list[dict[str, Any]] | DispatchBatch,
        active_filters: dict[str, Any] | None = None,
        conviction_filter: str = "all",
        input_mode: str | None = None,
        source_pipeline: str | None = None,
        analyst_batch_path: str | None = None,
    ) -> dict[str, Any]:
        """Format raw database rows or an analyst batch into report data."""
        normalized_conviction_filter = parse_trade_conviction_filter(
            conviction_filter,
            default="all",
        )
        resolved_input_mode = input_mode or (
            "analyst" if isinstance(data, DispatchBatch) else "parser"
        )
        resolved_source_pipeline = source_pipeline or (
            "research_analyst" if resolved_input_mode == "analyst" else "parsed_research"
        )
        documents = self._documents_for_reporting(data)
        summary = self._create_summary(data)
        summary["input_mode"] = resolved_input_mode
        summary["source_pipeline"] = resolved_source_pipeline
        if resolved_input_mode == "parser":
            summary["agent_inclusive"] = False
        elif resolved_input_mode == "analyst":
            summary["agent_inclusive"] = True
            if isinstance(data, DispatchBatch):
                summary["batch_key"] = data.batch_key
                if data.analysis_version:
                    summary["analysis_version"] = data.analysis_version

        metadata: dict[str, Any] = {
            "input_mode": resolved_input_mode,
            "source_pipeline": resolved_source_pipeline,
            "agent_inclusive": resolved_input_mode == "analyst",
        }
        if resolved_input_mode == "parser":
            metadata["date_range_days"] = (active_filters or {}).get("date_range_days")
            metadata["date_filters"] = {
                key: value
                for key, value in (active_filters or {}).items()
                if key
                in {
                    "date_range_days",
                    "region",
                    "asset_focus",
                    "sources",
                    "trade_conviction",
                }
            }
        elif isinstance(data, DispatchBatch):
            metadata["batch_key"] = data.batch_key
            if data.analysis_version:
                metadata["analysis_version"] = data.analysis_version
            if analyst_batch_path:
                metadata["analyst_batch_path"] = analyst_batch_path

        report = {
            "title": "Research Dispatch",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "input_mode": resolved_input_mode,
            "source_pipeline": resolved_source_pipeline,
            "agent_inclusive": resolved_input_mode == "analyst",
            "report_metadata": metadata,
            "active_filters": active_filters or {},
            "source_date_range": self._source_date_range(data),
            "summary": summary,
            "executive_summary": self._build_executive_summary(data),
            "document_digest": self._build_document_digest(data),
            "details": self._format_details(data),
            "themes_analysis": self._aggregate_themes(documents),
            "trades": self._aggregate_trades(documents, conviction_filter=normalized_conviction_filter),
            "through_lines": self._aggregate_through_lines(documents),
            "callouts": self._aggregate_callouts(documents),
        }
        if resolved_input_mode == "parser":
            report["date_filters"] = metadata["date_filters"]
        elif resolved_input_mode == "analyst" and isinstance(data, DispatchBatch):
            report["batch_key"] = data.batch_key
            if data.analysis_version:
                report["analysis_version"] = data.analysis_version
            if analyst_batch_path:
                report["analyst_batch_path"] = analyst_batch_path
        return report

    def _documents_for_reporting(
        self,
        data: list[dict[str, Any]] | DispatchBatch,
    ) -> list[dict[str, Any]]:
        if isinstance(data, DispatchBatch):
            return [document.to_legacy_record() for document in data.documents]
        return data

    def _source_date_range(
        self,
        data: list[dict[str, Any]] | DispatchBatch,
    ) -> dict[str, str] | None:
        """Get min/max source_date from included records."""
        records = self._documents_for_reporting(data)
        dates = []
        for record in records:
            source_date = record.get("source_date")
            if isinstance(source_date, datetime):
                dates.append(source_date.date())
            elif isinstance(source_date, date):
                dates.append(source_date)
            elif isinstance(source_date, str) and source_date.strip():
                try:
                    parsed = datetime.fromisoformat(source_date.replace("Z", "+00:00"))
                    dates.append(parsed.date())
                except ValueError:
                    continue
        if not dates:
            return None
        dates_sorted = sorted(dates)
        return {
            "start": dates_sorted[0].isoformat(),
            "end": dates_sorted[-1].isoformat(),
        }

    def _create_summary(
        self,
        data: list[dict[str, Any]] | DispatchBatch,
    ) -> dict[str, Any]:
        """Create summary statistics from legacy rows or an analyst batch."""
        if isinstance(data, DispatchBatch):
            return self._create_summary_from_batch(data)
        return self._create_summary_from_records(data)

    def _create_summary_from_records(self, data: list[dict[str, Any]]) -> dict[str, Any]:
        total_documents = len(data)
        seven_days_ago = datetime.now() - timedelta(days=7)
        date_range = f"{seven_days_ago.strftime('%Y-%m-%d')} to {datetime.now().strftime('%Y-%m-%d')}"

        summary = {
            "total_documents": total_documents,
            "date_range": date_range,
        }

        synthesis_status = {"synthesized": 0, "pending": 0}
        sources: dict[str, int] = {}
        publishers: dict[str, int] = {}

        for record in data:
            if record.get("synthesized"):
                synthesis_status["synthesized"] += 1
            else:
                synthesis_status["pending"] += 1

            source = record.get("source", "Unknown")
            sources[source] = sources.get(source, 0) + 1

            parsed_data = record.get("parsed_data", {})
            if parsed_data:
                metadata = parsed_data.get("metadata", {})
                publisher = metadata.get("publisher", "Unknown")
                if publisher and publisher != "Unknown":
                    publishers[publisher] = publishers.get(publisher, 0) + 1

        summary["synthesis_status"] = synthesis_status
        summary["by_source"] = sources
        if publishers:
            summary["by_publisher"] = publishers
        return summary

    def _create_summary_from_batch(self, batch: DispatchBatch) -> dict[str, Any]:
        total_documents = len(batch.documents)
        source_date_range = self._source_date_range(batch)
        if source_date_range:
            date_range = f"{source_date_range['start']} to {source_date_range['end']}"
        else:
            date_range = datetime.now().strftime("%Y-%m-%d")

        summary = {
            "total_documents": total_documents,
            "date_range": date_range,
            "synthesis_status": {"prepared": total_documents},
        }

        by_source: dict[str, int] = {}
        by_publisher: dict[str, int] = {}
        quality_scores = []
        warning_documents = 0

        for document in batch.documents:
            by_source[document.source] = by_source.get(document.source, 0) + 1
            if document.publisher:
                by_publisher[document.publisher] = by_publisher.get(document.publisher, 0) + 1
            if document.quality.score is not None:
                quality_scores.append(document.quality.score)
            if document.quality.warnings:
                warning_documents += 1

        summary["by_source"] = by_source
        if by_publisher:
            summary["by_publisher"] = by_publisher
        if quality_scores:
            summary["avg_quality_score"] = round(sum(quality_scores) / len(quality_scores), 1)
        if warning_documents:
            summary["warning_documents"] = warning_documents
        if batch.analysis_version:
            summary["analysis_version"] = batch.analysis_version
        return summary

    def _format_details(
        self,
        data: list[dict[str, Any]] | DispatchBatch,
    ) -> list[dict[str, Any]]:
        """Format individual records for the detailed section."""
        if isinstance(data, DispatchBatch):
            return self._format_batch_details(data)
        return self._format_record_details(data)

    def _format_record_details(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        formatted = []
        for record in data:
            parsed_data = record.get("parsed_data", {})
            metadata = parsed_data.get("metadata", {}) if parsed_data else {}
            themes = parsed_data.get("themes", []) if parsed_data else []
            trades = parsed_data.get("trades", []) if parsed_data else []

            formatted.append(
                {
                    "id": record.get("id"),
                    "document_name": record.get("document_name", "Untitled"),
                    "source": record.get("source", "Unknown"),
                    "source_date": record.get("source_date", ""),
                    "publisher": metadata.get("publisher", "N/A"),
                    "synthesized": "Yes" if record.get("synthesized") else "No",
                    "themes_count": len(themes) if isinstance(themes, list) else 0,
                    "trades_count": len(trades) if isinstance(trades, list) else 0,
                }
            )
        return formatted

    def _format_batch_details(self, batch: DispatchBatch) -> list[dict[str, Any]]:
        formatted = []
        for document in batch.documents:
            formatted.append(
                {
                    "id": document.research_id,
                    "document_name": document.document_name,
                    "source": document.source,
                    "source_date": document.source_date or "",
                    "publisher": document.publisher or "N/A",
                    "quality": (
                        f"{document.quality.score:.0f}"
                        if document.quality.score is not None
                        else "N/A"
                    ),
                    "themes_count": len(document.themes),
                    "trades_count": len(document.trades),
                    "assertions_count": len(document.assertions),
                }
            )
        return formatted

    def _build_executive_summary(
        self,
        data: list[dict[str, Any]] | DispatchBatch,
    ) -> list[str]:
        docs = self._report_documents(data)
        if not docs:
            return []

        summary: list[str] = []
        source_count = len({doc["source"] for doc in docs if doc.get("source")})
        date_range = self._source_date_range(data)
        summary_data = self._create_summary(data)
        source_counts = summary_data.get("by_source", {})
        if isinstance(source_counts, dict):
            top_sources = sorted(source_counts.items(), key=lambda item: item[1], reverse=True)[:3]
        else:
            top_sources = []

        # Build a compact opening that leads with signal, not inventory.
        # The header table already shows doc count / source count / date range.
        thematic_buckets = self._build_thematic_buckets(docs)
        overview = self._build_summary_overview_paragraph(thematic_buckets)

        if top_sources:
            source_text = ", ".join(f"{source} ({count})" for source, count in top_sources)
            if date_range:
                summary.append(
                    f"{overview} Over {date_range['start']} to {date_range['end']}, "
                    f"{len(docs)} notes across {source_count} sources were led by {source_text}."
                )
            else:
                summary.append(
                    f"{overview} The {len(docs)} notes across {source_count} sources were led by {source_text}."
                )
        else:
            if date_range:
                summary.append(
                    f"{overview} Over {date_range['start']} to {date_range['end']}, "
                    f"{len(docs)} notes across {source_count} sources drove the batch."
                )
            else:
                summary.append(overview)

        theme_counter: Counter[str] = Counter()
        theme_contexts: dict[str, str] = {}
        for doc in docs:
            seen_labels: set[str] = set()
            for label in doc.get("theme_labels", []):
                cleaned = str(label or "").strip()
                if cleaned and cleaned not in seen_labels:
                    theme_counter[cleaned] += 1
                    seen_labels.add(cleaned)
            for label, context in zip(doc.get("theme_labels", []), doc.get("theme_contexts", [])):
                cleaned_label = str(label or "").strip()
                cleaned_context = str(context or "").strip()
                if cleaned_label and cleaned_context and cleaned_label not in theme_contexts:
                    theme_contexts[cleaned_label] = cleaned_context

        trade_items = self._top_trade_items(docs)
        forecast_items = self._top_forecast_items(docs)
        if trade_items:
            summary.append(self._build_positioning_paragraph(trade_items, forecast_items))

        for paragraph in self._thematic_bucket_paragraphs(thematic_buckets, max_paragraphs=5):
            summary.append(paragraph)

        if len(summary) < 6:
            theme_clusters = self._build_theme_clusters(docs)
            for paragraph in self._theme_cluster_paragraphs(theme_clusters, max_paragraphs=3):
                if paragraph not in summary:
                    summary.append(paragraph)

        if len(summary) < 6:
            closing = self._build_executive_closing_paragraph(docs, theme_counter, trade_items)
            if closing:
                summary.append(closing)

        return summary[:10]

    def _build_document_digest(
        self,
        data: list[dict[str, Any]] | DispatchBatch,
    ) -> list[dict[str, Any]]:
        docs = self._report_documents(data)
        if not docs:
            return []

        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for doc in docs:
            grouped[self._digest_day_label(doc.get("source_date"))].append(doc)

        sort_keyed = sorted(
            grouped.items(),
            key=lambda item: self._digest_group_sort_key(item[1]),
            reverse=True,
        )

        digest = []
        for heading, entries in sort_keyed:
            sorted_entries = sorted(
                entries,
                key=lambda item: (
                    item.get("source_date") or "",
                    item.get("source") or "",
                    item.get("title") or "",
                ),
                reverse=True,
            )
            digest.append({"heading": heading, "entries": sorted_entries})
        return digest

    def _report_documents(
        self,
        data: list[dict[str, Any]] | DispatchBatch,
    ) -> list[dict[str, Any]]:
        if isinstance(data, DispatchBatch):
            return [self._batch_document_digest_item(document) for document in data.documents]
        return [self._record_document_digest_item(record) for record in data]

    def _batch_document_digest_item(self, document: DispatchDocument) -> dict[str, Any]:
        theme_dicts = [theme.to_legacy_dict() for theme in document.themes]
        trade_dicts = [trade.to_legacy_dict() for trade in document.trades]
        assertion_dicts = [
            {
                "summary_text": assertion.summary_text,
                "text": assertion.text,
            }
            for assertion in document.assertions
        ]
        theme_dicts = [theme.to_legacy_dict() for theme in document.themes]
        assertion_dicts = [
            {
                "summary_text": assertion.summary_text,
                "text": assertion.text,
            }
            for assertion in document.assertions
        ]
        title = self._display_digest_title(
            self._pretty_document_title(document.document_name),
            theme_dicts,
            assertion_dicts,
        )
        return {
            "research_id": document.research_id,
            "source": document.source,
            "source_date": document.source_date,
            "title": title,
            "document_name": document.document_name,
            "document_link": document.document_link,
            "publisher": document.publisher,
            "summary": self._digest_summary(theme_dicts, trade_dicts, assertion_dicts),
            "theme_labels": [str(theme.label).strip() for theme in document.themes if str(theme.label).strip()],
            "theme_contexts": [str(theme.context).strip() for theme in document.themes if str(theme.context).strip()],
            "trade_texts": [
                self._summary_trade_text(trade.text or trade.exposure or "")
                for trade in document.trades
                if self._summary_trade_text(trade.text or trade.exposure or "")
            ],
            "assertion_texts": [
                str(assertion.summary_text or assertion.text).strip()
                for assertion in document.assertions
                if str(assertion.summary_text or assertion.text).strip()
            ],
            "forecast_texts": [
                self._forecast_display_text(forecast.event_name, forecast.forecast_value_text)
                for forecast in document.forecast_candidates
                if self._forecast_display_text(forecast.event_name, forecast.forecast_value_text)
            ],
            "quality_score": document.quality.score,
        }

    def _record_document_digest_item(self, record: dict[str, Any]) -> dict[str, Any]:
        parsed_data = record.get("parsed_data", {})
        themes = parsed_data.get("themes", []) if isinstance(parsed_data, dict) else []
        trades = parsed_data.get("trades", []) if isinstance(parsed_data, dict) else []
        assertions = parsed_data.get("assertions", []) if isinstance(parsed_data, dict) else []
        metadata = parsed_data.get("metadata", {}) if isinstance(parsed_data, dict) else {}
        title = self._display_digest_title(
            self._pretty_document_title(
                record.get("document_title")
                or record.get("title")
                or record.get("document_name")
                or "Untitled"
            ),
            themes,
            assertions,
        )
        return {
            "research_id": record.get("id"),
            "source": record.get("source", "Unknown"),
            "source_date": record.get("source_date"),
            "title": title,
            "document_name": record.get("document_name", "Untitled"),
            "document_link": record.get("document_link") or metadata.get("document_link"),
            "publisher": record.get("publisher") or metadata.get("publisher"),
            "summary": self._digest_summary(themes, trades, assertions),
            "theme_labels": [
                str(theme.get("label") or "").strip()
                for theme in themes
                if isinstance(theme, dict) and str(theme.get("label") or "").strip()
            ],
            "theme_contexts": [
                str(theme.get("context") or "").strip()
                for theme in themes
                if isinstance(theme, dict) and str(theme.get("context") or "").strip()
            ],
            "trade_texts": [
                self._summary_trade_text(
                    (
                        trade.get("text")
                        or trade.get("exposure")
                        or ""
                    )
                )
                for trade in trades
                if isinstance(trade, dict)
                and self._summary_trade_text(trade.get("text") or trade.get("exposure") or "")
            ],
            "assertion_texts": [
                str(assertion.get("summary_text") or assertion.get("text") or "").strip()
                for assertion in assertions
                if isinstance(assertion, dict)
                and str(assertion.get("summary_text") or assertion.get("text") or "").strip()
            ],
            "forecast_texts": [
                self._forecast_display_text(
                    forecast.get("event_name"),
                    forecast.get("forecast_value_text"),
                )
                for forecast in (parsed_data.get("forecast_candidates", []) if isinstance(parsed_data, dict) else [])
                if isinstance(forecast, dict)
                and self._forecast_display_text(
                    forecast.get("event_name"),
                    forecast.get("forecast_value_text"),
                )
            ],
        }

    def _display_digest_title(
        self,
        title: str,
        themes: list[dict[str, Any]],
        assertions: list[dict[str, Any]],
    ) -> str:
        cleaned = " ".join(str(title or "").split()).strip()
        generic_prefixes = (
            "analysis of ",
            "research note",
            "untitled",
        )
        if cleaned and not cleaned.lower().startswith(generic_prefixes):
            return cleaned

        for assertion in assertions:
            if not isinstance(assertion, dict):
                continue
            text = str(assertion.get("summary_text") or assertion.get("text") or "").strip()
            if text:
                return self._truncate_title(text)

        for theme in themes:
            if not isinstance(theme, dict):
                continue
            label = str(theme.get("label") or "").strip()
            if label:
                return self._truncate_title(label)

        return cleaned or "Untitled"

    def _truncate_title(self, text: str, max_words: int = 9) -> str:
        words = [word for word in str(text or "").split() if word]
        if len(words) <= max_words:
            return " ".join(words)
        return " ".join(words[:max_words]) + "..."

    def _is_executable_trade_text(self, value: Any) -> bool:
        return bool(self._summary_trade_text(value))

    def _summary_trade_text(self, value: Any) -> str:
        text = normalize_trade_expression(str(value or "").strip())
        if not text:
            return ""

        lower = text.lower()
        if lower in {"medium", "large", "small", "high", "low", "n/a"}:
            return ""

        rewrite_prefixes = (
            ("be prepared for a potential oil price of", "Prepare for higher oil prices"),
            ("buy brent crude oil in anticipation of prices reaching", "Buy Brent crude"),
            ("buy consumer finance, where ytd movement implies", "Buy consumer finance"),
        )
        for prefix, replacement in rewrite_prefixes:
            if lower.startswith(prefix):
                return replacement

        if "," in text:
            lead = text.split(",", 1)[0].strip()
            if lead:
                text = lead
                lower = text.lower()

        text = self._clean_clause(text, max_words=14)
        if not text:
            return ""

        trailing_bad = {
            "chance", "moderate", "potential", "possible", "view", "prices", "movement",
        }
        final_word = text.split()[-1].lower().strip(",")
        if final_word in trailing_bad:
            return ""

        if len(text.split()) < 2:
            return ""

        return text

    def _digest_summary(
        self,
        themes: list[dict[str, Any]],
        trades: list[dict[str, Any]],
        assertions: list[dict[str, Any]],
    ) -> str:
        parts: list[str] = []

        for assertion in assertions[:2]:
            if not isinstance(assertion, dict):
                continue
            text = str(assertion.get("summary_text") or assertion.get("text") or "").strip()
            if text:
                parts.append(self._ensure_sentence(text))

        if not parts:
            for theme in themes[:2]:
                if not isinstance(theme, dict):
                    continue
                context = str(theme.get("context") or "").strip()
                if context:
                    parts.append(self._ensure_sentence(context))

        if trades:
            first_trade = trades[0] if isinstance(trades[0], dict) else {}
            trade_text = normalize_trade_expression(
                first_trade.get("exposure") or first_trade.get("text") or ""
            )
            if trade_text and trade_text.lower() not in {"medium", "large", "small", "n/a"}:
                parts.append(self._ensure_sentence(f"Trade framing: {trade_text}"))

        if not parts and themes:
            labels = [str(theme.get("label") or "").strip() for theme in themes[:3] if isinstance(theme, dict)]
            labels = [label for label in labels if label]
            if labels:
                parts.append(self._ensure_sentence(f"Main focus: {', '.join(labels)}"))

        return " ".join(parts[:3])

    def _pretty_document_title(self, raw: Any) -> str:
        text = str(raw or "").strip()
        if not text:
            return "Untitled"
        if text.lower().endswith(".pdf"):
            text = text[:-4]
        text = text.replace("__", " ").replace("_", " ")
        text = " ".join(text.split())
        if len(text) >= 10 and text[4] == "-" and text[7] == "-":
            text = text[10:].lstrip(" -_")
        parts = text.split()
        if parts and len(parts[0]) <= 10 and parts[0].upper() == parts[0]:
            text = " ".join(parts[1:]) or text
        return text

    def _digest_day_label(self, raw_date: Any) -> str:
        if not isinstance(raw_date, str) or not raw_date.strip():
            return "Undated"
        try:
            parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
        except ValueError:
            return raw_date
        today = datetime.now().date()
        delta_days = (today - parsed).days
        date_label = f"{parsed.strftime('%B')} {parsed.day}"
        if delta_days == 0:
            return f"TODAY ({date_label})"
        if delta_days == 1:
            return f"YESTERDAY ({date_label})"
        return f"{parsed.strftime('%A').upper()} ({date_label})"

    def _digest_group_sort_key(self, entries: list[dict[str, Any]]) -> str:
        dates = [entry.get("source_date") or "" for entry in entries]
        return max(dates) if dates else ""

    def _ensure_sentence(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return ""
        if cleaned[-1] in ".!?":
            return cleaned
        return f"{cleaned}."

    def _truncate_sentence(self, text: str, max_words: int = 24) -> str:
        words = [word for word in str(text or "").split() if word]
        if len(words) <= max_words:
            return self._ensure_sentence(" ".join(words))
        return self._ensure_sentence(" ".join(words[:max_words]))

    def _normalize_summary_key(self, text: Any) -> str:
        cleaned = " ".join(str(text or "").split()).strip().lower()
        if not cleaned:
            return ""
        cleaned = re.sub(r"[^a-z0-9%/ .-]", "", cleaned)
        return cleaned

    def _top_trade_items(self, docs: list[dict[str, Any]], limit: int = 5) -> list[str]:
        counter: Counter[str] = Counter()
        for doc in docs:
            seen: set[str] = set()
            for trade_text in doc.get("trade_texts", []):
                if not self._is_executable_trade_text(trade_text):
                    continue
                normalized = normalize_trade_expression(str(trade_text or ""))
                if normalized and normalized not in seen:
                    counter[normalized] += 1
                    seen.add(normalized)
        return [text for text, _ in counter.most_common(limit)]

    def _forecast_display_text(self, event_name: Any, forecast_value_text: Any) -> str:
        event = " ".join(str(event_name or "").split()).strip()
        value = " ".join(str(forecast_value_text or "").split()).strip()
        if event and value:
            return f"{event} ({value})"
        return event or value

    def _top_forecast_items(self, docs: list[dict[str, Any]], limit: int = 4) -> list[str]:
        counter: Counter[str] = Counter()
        for doc in docs:
            seen: set[str] = set()
            for item in doc.get("forecast_texts", []):
                cleaned = " ".join(str(item or "").split()).strip()
                if cleaned and cleaned not in seen:
                    counter[cleaned] += 1
                    seen.add(cleaned)
        return [text for text, _ in counter.most_common(limit)]

    def _build_theme_clusters(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        clusters: dict[str, dict[str, Any]] = {}
        for doc in docs:
            doc_theme_labels = [
                str(label or "").strip()
                for label in doc.get("theme_labels", [])
                if str(label or "").strip()
            ]
            if not doc_theme_labels:
                continue
            doc_contexts = [
                str(context or "").strip()
                for context in doc.get("theme_contexts", [])
                if str(context or "").strip()
            ]
            doc_assertions = [
                str(text or "").strip()
                for text in doc.get("assertion_texts", [])
                if str(text or "").strip()
            ]
            doc_trades = [
                normalize_trade_expression(str(text or "").strip())
                for text in doc.get("trade_texts", [])
                if normalize_trade_expression(str(text or "").strip())
            ]
            doc_forecasts = [
                str(text or "").strip()
                for text in doc.get("forecast_texts", [])
                if str(text or "").strip()
            ]
            for label in dict.fromkeys(doc_theme_labels):
                cluster = clusters.setdefault(
                    label,
                    {
                        "label": label,
                        "count": 0,
                        "sources": Counter(),
                        "contexts": [],
                        "assertions": [],
                        "trades": [],
                        "forecasts": [],
                        "examples": [],
                    },
                )
                cluster["count"] += 1
                source = str(doc.get("source") or "Unknown").strip()
                if source:
                    cluster["sources"][source] += 1
                cluster["contexts"].extend(doc_contexts[:2])
                cluster["assertions"].extend(doc_assertions[:2])
                cluster["trades"].extend(doc_trades[:2])
                cluster["forecasts"].extend(doc_forecasts[:2])
                cluster["examples"].append(
                    {
                        "source": source,
                        "title": str(doc.get("title") or doc.get("document_name") or "Untitled").strip(),
                        "summary": str(doc.get("summary") or "").strip(),
                    }
                )
        return sorted(
            clusters.values(),
            key=lambda item: (item["count"], sum(item["sources"].values()), item["label"]),
            reverse=True,
        )

    def _build_thematic_buckets(self, docs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        bucket_specs = [
            (
                "Energy shock and supply disruption",
                {
                    "oil", "energy", "crude", "brent", "hormuz", "gasoline", "diesel",
                    "spr", "opec", "commodity", "pump-price", "fuel", "strait", "iran",
                },
            ),
            (
                "Treasury market structure and funding",
                {
                    "treasury", "swap spread", "swap spreads", "repo", "sofr", "clearing",
                    "dealer", "dealers", "basis", "slr", "eslr", "gsib", "balance sheet",
                    "funding", "intermediation",
                },
            ),
            (
                "Inflation, central banks and rate paths",
                {
                    "inflation", "cpi", "fed", "fomc", "cuts", "hikes",
                    "hawkish", "dovish", "real yield", "central bank", "terminal",
                    "breakeven", "swaption",
                },
            ),
            (
                "Growth, labor and demand resilience",
                {
                    "growth", "labor", "labour", "wage", "wages", "payroll", "employment",
                    "consumer", "recession", "soft landing", "unemployment",
                },
            ),
            (
                "European and UK rates spillovers",
                {
                    "ecb", "boe", "gilt", "gilts", "sonia", "europe", "eur", "sterling",
                    "peripheral", "bund",
                },
            ),
        ]

        buckets: dict[str, dict[str, Any]] = {}
        for label, _ in bucket_specs:
            buckets[label] = {
                "label": label,
                "count": 0,
                "sources": Counter(),
                "contexts": [],
                "assertions": [],
                "trades": [],
                "forecasts": [],
                "examples": [],
                "theme_labels": [],
                "summary_points": [],
            }

        for doc in docs:
            text_parts = [
                str(doc.get("title") or ""),
                str(doc.get("summary") or ""),
                " ".join(doc.get("theme_labels", [])),
                " ".join(doc.get("theme_contexts", [])),
                " ".join(doc.get("assertion_texts", [])),
            ]
            haystack = " ".join(text_parts).lower()
            bucket_scores = []
            for label, keywords in bucket_specs:
                score = self._keyword_score(haystack, keywords)
                if score > 0:
                    bucket_scores.append((label, keywords, score))
            if not bucket_scores:
                continue

            bucket_scores.sort(key=lambda item: item[2], reverse=True)
            top_score = bucket_scores[0][2]
            matched_labels = [
                (label, keywords)
                for label, keywords, score in bucket_scores
                if score == top_score or (score >= 2 and score >= top_score - 1)
            ][:2]
            for label, keywords in matched_labels:
                bucket = buckets[label]
                bucket["count"] += 1
                source = str(doc.get("source") or "Unknown").strip()
                if source:
                    bucket["sources"][source] += 1
                bucket["contexts"].extend(
                    self._texts_matching_keywords(doc.get("theme_contexts", []), keywords, limit=2)
                )
                bucket["assertions"].extend(
                    self._texts_matching_keywords(doc.get("assertion_texts", []), keywords, limit=2)
                )
                bucket["trades"].extend(
                    self._texts_matching_keywords(doc.get("trade_texts", []), keywords, limit=2)
                )
                bucket["forecasts"].extend(
                    self._texts_matching_keywords(doc.get("forecast_texts", []), keywords, limit=2)
                )
                bucket["theme_labels"].extend(
                    self._texts_matching_keywords(doc.get("theme_labels", []), keywords, limit=2)
                )
                summary_point = self._best_matching_sentence(str(doc.get("summary") or ""), keywords)
                if summary_point:
                    bucket["summary_points"].append(summary_point)
                bucket["examples"].append(
                    {
                        "source": source,
                        "title": str(doc.get("title") or doc.get("document_name") or "Untitled").strip(),
                    }
                )

        filtered = [bucket for bucket in buckets.values() if bucket["count"] >= 2]
        return sorted(filtered, key=lambda item: (item["count"], item["label"]), reverse=True)

    _BUCKET_OPENERS = [
        lambda label, count, sources: (
            f"{label} appeared in {count} notes"
            + (f" across {sources}" if sources else "")
        ),
        lambda label, count, sources: (
            f"Across {sources}, {count} notes focused on {label}"
            if sources
            else f"{count} notes focused on {label}"
        ),
        lambda label, count, sources: (
            f"{label} ran through {count} notes"
            + (f" from {sources}" if sources else "")
        ),
        lambda label, count, sources: (
            f"On {label}, {count} notes"
            + (f" ({sources})" if sources else "")
            + " converged"
        ),
        lambda label, count, sources: (
            f"{label} drew {count} notes"
            + (f" spanning {sources}" if sources else "")
        ),
    ]

    _CLAIM_INTROS = [
        "The consensus view: {claim}",
        "Desks converged on the idea that {claim}",
        "The running thread was that {claim}",
        "The common read: {claim}",
        "The shared framing: {claim}",
    ]

    def _thematic_bucket_paragraphs(
        self,
        buckets: list[dict[str, Any]],
        max_paragraphs: int = 5,
    ) -> list[str]:
        paragraphs: list[str] = []
        for idx, bucket in enumerate(buckets[:max_paragraphs]):
            label = str(bucket.get("label") or "").strip()
            if not label:
                continue
            short_label = self._headline_label(self._summary_bucket_label(label))
            sources = [source for source, _ in bucket.get("sources", Counter()).most_common(3)]
            source_str = self._format_series(sources) if sources else ""

            opener_fn = self._BUCKET_OPENERS[idx % len(self._BUCKET_OPENERS)]
            sentences = [self._ensure_sentence(opener_fn(short_label, bucket["count"], source_str))]

            claim = self._bucket_claim_text(bucket)
            if claim:
                claim_template = self._CLAIM_INTROS[idx % len(self._CLAIM_INTROS)]
                sentences.append(self._ensure_sentence(claim_template.format(claim=claim)))

            trades = self._pick_distinct_text(bucket.get("trades", []), max_items=2, max_words=12)
            examples = []
            for example in bucket.get("examples", [])[:2]:
                source = str(example.get("source") or "Unknown").strip()
                title = str(example.get("title") or "Untitled").strip()
                if source and title:
                    examples.append(f"{source} ({title})")

            if examples and trades:
                sentences.append(
                    self._ensure_sentence(
                        f"{self._format_series(examples)} expressed this via {self._format_inline_series(trades)}"
                    )
                )
            elif examples:
                sentences.append(
                    self._ensure_sentence(
                        f"Key notes: {self._format_series(examples)}"
                    )
                )
            elif trades:
                sentences.append(
                    self._ensure_sentence(
                        f"Expressed via {self._format_inline_series(trades)}"
                    )
                )

            paragraphs.append(" ".join(sentence for sentence in sentences if sentence))
        return paragraphs

    def _keyword_score(self, haystack: str, keywords: set[str]) -> int:
        score = 0
        for keyword in keywords:
            pattern = re.escape(keyword.lower())
            if " " in keyword or "-" in keyword:
                if keyword.lower() in haystack:
                    score += 2
                continue
            if re.search(rf"\b{pattern}\b", haystack):
                score += 1
        return score

    def _texts_matching_keywords(
        self,
        values: list[str],
        keywords: set[str],
        limit: int = 2,
    ) -> list[str]:
        matches = []
        for value in values:
            cleaned = " ".join(str(value or "").split()).strip()
            if not cleaned:
                continue
            if self._keyword_score(cleaned.lower(), keywords) > 0:
                matches.append(cleaned)
            if len(matches) >= limit:
                break
        return matches

    def _best_matching_sentence(self, text: str, keywords: set[str]) -> str:
        sentences = [
            " ".join(sentence.split()).strip()
            for sentence in re.split(r"(?<=[.!?])\s+", str(text or "").strip())
            if " ".join(sentence.split()).strip()
        ]
        if not sentences:
            return ""
        scored = [
            (self._keyword_score(sentence.lower(), keywords), sentence)
            for sentence in sentences
        ]
        scored.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
        best_score, best_sentence = scored[0]
        if best_score <= 0:
            best_sentence = sentences[0]
        return self._clean_clause(best_sentence, max_words=24)

    def _clean_clause(self, text: str, max_words: int = 24) -> str:
        cleaned = " ".join(str(text or "").split()).strip(" .,:;")
        if not cleaned:
            return ""
        cleaned = re.sub(r"^[^A-Za-z0-9]+", "", cleaned)
        cleaned = re.sub(
            r"^(the core thesis is that|core thesis is that|the core claim is that|core claim is that|thesis is that|thesis:|positioning:|core message is that)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        words = cleaned.split()
        if len(words) > max_words:
            cleaned = " ".join(words[:max_words])
        trailing_fillers = {
            "a", "an", "the", "and", "or", "to", "of", "for", "in", "on", "at",
            "with", "by", "from", "as", "is", "are", "was", "were", "be", "into",
        }
        clipped = cleaned.split()
        while clipped and clipped[-1].lower().strip(",") in trailing_fillers:
            clipped.pop()
        cleaned = " ".join(clipped)
        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]
        return cleaned

    def _format_series(self, items: list[str]) -> str:
        cleaned = [" ".join(str(item or "").split()).strip() for item in items if str(item or "").strip()]
        if not cleaned:
            return ""
        if len(cleaned) == 1:
            return cleaned[0]
        if len(cleaned) == 2:
            return f"{cleaned[0]} and {cleaned[1]}"
        return f"{', '.join(cleaned[:-1])}, and {cleaned[-1]}"

    def _inline_fragment(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return ""
        first_token = cleaned.split()[0]
        alpha = re.sub(r"^[^A-Za-z]+|[^A-Za-z]+$", "", first_token)
        if alpha and alpha.isupper() and len(alpha) > 1:
            return cleaned
        if alpha and len(alpha) > 1 and alpha[0].isupper() and alpha[1:].islower():
            return cleaned[0].lower() + cleaned[1:]
        if cleaned[:1].isupper() and (len(cleaned) == 1 or cleaned[1].islower()):
            return cleaned[0].lower() + cleaned[1:]
        return cleaned

    def _format_inline_series(self, items: list[str]) -> str:
        return self._format_series([self._inline_fragment(item) for item in items])

    def _build_summary_overview_paragraph(self, buckets: list[dict[str, Any]]) -> str:
        top_labels = [self._summary_bucket_label(bucket.get("label")) for bucket in buckets[:4]]
        top_labels = [label for label in top_labels if label]
        if not top_labels:
            return self._ensure_sentence(
                "The batch was broad and cross-asset, with multiple desks covering the same macro shocks from different angles"
            )
        return self._ensure_sentence(
            f"The batch was dominated by {self._format_series(top_labels)}"
        )

    def _build_positioning_paragraph(
        self,
        trade_items: list[str],
        forecast_items: list[str],
    ) -> str:
        sentences = []
        if trade_items:
            primary = trade_items[:2]
            secondary = trade_items[2:4]
            if len(primary) == 1:
                sentences.append(
                    self._ensure_sentence(
                        f"The clearest positioning call was {self._inline_fragment(primary[0])}"
                    )
                )
            elif primary:
                sentences.append(
                    self._ensure_sentence(
                        f"On positioning, desks converged on {self._format_inline_series(primary)}"
                    )
                )
            if secondary:
                sentences.append(
                    self._ensure_sentence(
                        f"Several also flagged {self._format_inline_series(secondary)}"
                    )
                )
        if forecast_items:
            sentences.append(
                self._ensure_sentence(
                    f"Event attention centered on {self._format_inline_series(forecast_items[:2])}"
                )
            )
        return " ".join(sentence for sentence in sentences if sentence)

    def _summary_bucket_label(self, label: Any) -> str:
        mapping = {
            "Energy shock and supply disruption": "energy shock",
            "Treasury market structure and funding": "Treasury plumbing",
            "Inflation, central banks and rate paths": "inflation and Fed path",
            "Growth, labor and demand resilience": "growth and labor resilience",
            "European and UK rates spillovers": "European rates spillovers",
        }
        cleaned = str(label or "").strip()
        return mapping.get(cleaned, cleaned.lower())

    def _headline_label(self, text: str) -> str:
        cleaned = " ".join(str(text or "").split()).strip()
        if not cleaned:
            return ""
        return cleaned[0].upper() + cleaned[1:]

    def _bucket_editorial_claim(self, label: str) -> str:
        claims = {
            "Energy shock and supply disruption": (
                "the market is treating Hormuz and broader supply disruption as the key macro shock, with price risk increasingly tied to duration and severity rather than the initial headline"
            ),
            "Treasury market structure and funding": (
                "balance-sheet capacity, repo stability, clearing changes, and swap-spread mechanics are shaping rates pricing as much as the macro data itself"
            ),
            "Inflation, central banks and rate paths": (
                "the oil shock raises headline inflation risk, but the dominant read is still that central banks are unlikely to repeat a 2022-style tightening response"
            ),
            "Growth, labor and demand resilience": (
                "softer labor conditions and weaker demand are being treated as the main constraint on second-round inflation and the main channel for a future growth scare"
            ),
            "European and UK rates spillovers": (
                "the focus is on how gilt and continental rates moves spill into cross-market relative value, term premium, and ECB or BOE timing"
            ),
        }
        return claims.get(label, "")

    def _bucket_claim_text(self, bucket: dict[str, Any]) -> str:
        label = str(bucket.get("label") or "").strip()
        editorial = self._bucket_editorial_claim(label)
        if editorial:
            return editorial
        for source in ("assertions", "summary_points", "contexts"):
            candidates = self._pick_distinct_text(bucket.get(source, []), max_items=1, max_words=22)
            if candidates:
                claim = self._clean_clause(candidates[0], max_words=22)
                if not claim:
                    continue
                return self._inline_fragment(claim)
        return ""

    def _theme_cluster_paragraphs(
        self,
        clusters: list[dict[str, Any]],
        max_paragraphs: int = 5,
    ) -> list[str]:
        paragraphs: list[str] = []
        for cluster in clusters:
            if cluster.get("count", 0) < 2:
                continue
            label = str(cluster.get("label") or "").strip()
            if not label:
                continue
            parts = [f"A major strand of the dispatch was {label.lower()}, which appeared across {cluster['count']} notes"]

            source_bits = [source for source, _ in cluster.get("sources", Counter()).most_common(3)]
            if source_bits:
                parts.append(f"with contributions led by {', '.join(source_bits)}")

            context = self._pick_distinct_text(cluster.get("contexts", []), max_items=1, max_words=22)
            if context:
                parts.append(f"the underlying framing centered on {context[0][0].lower() + context[0][1:] if len(context[0]) > 1 else context[0].lower()}")

            assertion = self._pick_distinct_text(cluster.get("assertions", []), max_items=1, max_words=24)
            if assertion:
                parts.append(f"the common claim was that {assertion[0][0].lower() + assertion[0][1:] if len(assertion[0]) > 1 else assertion[0].lower()}")

            trades = self._pick_distinct_text(cluster.get("trades", []), max_items=2, max_words=12)
            if trades:
                parts.append(f"trade expression in that cluster included {', '.join(trades)}")

            forecasts = self._pick_distinct_text(cluster.get("forecasts", []), max_items=1, max_words=12)
            if forecasts:
                parts.append(f"with event attention on {forecasts[0]}")

            examples = []
            for example in cluster.get("examples", [])[:2]:
                source = str(example.get("source") or "Unknown").strip()
                title = str(example.get("title") or "Untitled").strip()
                if source and title:
                    examples.append(f"{source} on {title}")
            if examples:
                parts.append(f"representative notes included {' and '.join(examples[:2])}")

            paragraphs.append(self._ensure_sentence(", ".join(parts)))
            if len(paragraphs) >= max_paragraphs:
                break
        return paragraphs

    def _pick_distinct_text(
        self,
        values: list[str],
        max_items: int = 2,
        max_words: int = 18,
    ) -> list[str]:
        chosen: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._normalize_summary_key(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            chosen.append(self._truncate_sentence(value, max_words=max_words))
            if len(chosen) >= max_items:
                break
        return [item[:-1] if item.endswith(".") else item for item in chosen]

    def _source_focus_paragraphs(
        self,
        docs: list[dict[str, Any]],
        max_paragraphs: int = 2,
    ) -> list[str]:
        by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for doc in docs:
            source = str(doc.get("source") or "Unknown").strip()
            by_source[source].append(doc)

        paragraphs: list[str] = []
        sorted_sources = sorted(by_source.items(), key=lambda item: len(item[1]), reverse=True)
        for source, source_docs in sorted_sources[:max_paragraphs]:
            theme_counts: Counter[str] = Counter()
            for doc in source_docs:
                for label in dict.fromkeys(doc.get("theme_labels", [])):
                    cleaned = str(label or "").strip()
                    if cleaned:
                        theme_counts[cleaned] += 1
            top_themes = [label for label, _ in theme_counts.most_common(3)]
            top_titles = [
                str(doc.get("title") or doc.get("document_name") or "Untitled").strip()
                for doc in source_docs[:2]
            ]
            bits = [f"{source} was a major contributor to the batch with {len(source_docs)} notes"]
            if top_themes:
                bits.append(f"its coverage concentrated on {', '.join(top_themes)}")
            if top_titles:
                bits.append(f"notably {', '.join(top_titles)}")
            paragraphs.append(self._ensure_sentence(", ".join(bits)))
        return paragraphs

    def _heading_to_phrase(self, heading: str) -> str:
        cleaned = " ".join(str(heading or "").split()).strip()
        if not cleaned:
            return "In the window"
        match = re.search(r"\(([^)]+)\)", cleaned)
        if cleaned.startswith("TODAY"):
            return f"On {match.group(1) if match else 'today'}"
        if cleaned.startswith("YESTERDAY"):
            return f"On {match.group(1) if match else 'yesterday'}"
        if match:
            return f"On {match.group(1)}"
        return f"In {cleaned.title()}"

    def _summary_snippet(self, text: str, max_words: int = 26) -> str:
        first_sentence = str(text or "").split(".")[0].strip()
        snippet = first_sentence or str(text or "").strip()
        words = [word for word in snippet.split() if word]
        if not words:
            return ""
        if len(words) > max_words:
            snippet = " ".join(words[:max_words])
        return self._ensure_sentence(snippet)

    def _build_digest_group_summary(self, group: dict[str, Any]) -> str:
        entries = group.get("entries", [])
        if not entries:
            return ""
        phrase = self._heading_to_phrase(str(group.get("heading") or ""))
        fragments = []
        for entry in entries[:3]:
            source = str(entry.get("source") or "Unknown").strip()
            title = str(entry.get("title") or entry.get("document_name") or "Untitled").strip()
            summary = self._summary_snippet(str(entry.get("summary") or ""))
            if summary:
                summary = summary[:-1] if summary.endswith(".") else summary
                fragments.append(f"{source} on {title} argued that {summary[0].lower() + summary[1:] if len(summary) > 1 else summary.lower()}")
            else:
                fragments.append(f"{source} focused on {title}")
        if not fragments:
            return ""
        if len(fragments) == 1:
            return self._ensure_sentence(f"{phrase}, {fragments[0]}")
        return self._ensure_sentence(f"{phrase}, " + "; ".join(fragments[:3]))

    def _build_executive_closing_paragraph(
        self,
        docs: list[dict[str, Any]],
        theme_counter: Counter[str],
        trade_items: list[str],
    ) -> str:
        dominant_themes = [label for label, _ in theme_counter.most_common(3) if label]
        source_mix = ", ".join(
            sorted({str(doc.get('source') or '').strip() for doc in docs if str(doc.get('source') or '').strip()})[:4]
        )
        bits = []
        if dominant_themes:
            bits.append(f"the flow was anchored by {', '.join(dominant_themes)}")
        if trade_items:
            bits.append(f"the tactical overlay stayed focused on {', '.join(trade_items[:3])}")
        if source_mix:
            bits.append(f"the note set remained broad across {source_mix}")
        if not bits:
            return ""
        return self._ensure_sentence("Taken together, " + ", while ".join(bits))

    def _aggregate_themes(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Aggregate and format themes across all documents."""
        theme_counts: dict[str, int] = {}
        theme_examples: dict[str, list[dict[str, Any]]] = {}
        seen_documents = set()

        for record in data:
            parsed_data = record.get("parsed_data", {})
            themes = parsed_data.get("themes", []) if parsed_data else []
            if not themes or not isinstance(themes, list):
                continue

            doc_name = record.get("document_name", "Unknown Document")
            doc_id = record.get("id", "")

            for theme in themes:
                if not isinstance(theme, dict):
                    continue

                label = theme.get("label", "Unlabeled")
                context = theme.get("context", "")
                if label not in theme_counts:
                    theme_counts[label] = 0
                    theme_examples[label] = []
                theme_counts[label] += 1

                if len(theme_examples[label]) < 3:
                    theme_examples[label].append(
                        {
                            "document": doc_name,
                            "doc_id": doc_id,
                            "item_id": self._generate_item_id(f"{doc_id}:{label}:{context[:50]}"),
                            "context": context,
                            "show_document": doc_name not in seen_documents,
                            "strength": theme.get("strength", ""),
                            "confidence": theme.get("confidence", ""),
                        }
                    )
                    seen_documents.add(doc_name)

        sorted_themes = sorted(theme_counts.items(), key=lambda x: x[1], reverse=True)
        return [
            {"label": label, "count": count, "examples": theme_examples[label]}
            for label, count in sorted_themes
        ]

    def group_themes_by_through_lines(
        self,
        themes_analysis: list[dict[str, Any]],
        through_lines: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Group themes under synthesis through-lines for readability."""
        if not themes_analysis or not through_lines:
            return []

        themes_by_label = {
            theme.get("label"): theme
            for theme in themes_analysis
            if theme.get("label")
        }
        remaining = dict(themes_by_label)
        grouped = []

        for tl in through_lines:
            if not isinstance(tl, dict):
                continue
            labels = tl.get("supporting_themes") or []
            group_themes = []
            for label in labels:
                theme = remaining.pop(label, None)
                if theme:
                    group_themes.append(theme)
            if group_themes:
                grouped.append({"lead": tl.get("lead", "Theme Cluster"), "themes": group_themes})

        if remaining:
            remaining_list = sorted(
                remaining.values(),
                key=lambda t: t.get("count", 0),
                reverse=True,
            )
            cap = 6
            shown = remaining_list[:cap]
            overflow = len(remaining_list) - cap
            group = {"lead": "Other Themes", "themes": shown}
            if overflow > 0:
                group["overflow_count"] = overflow
            grouped.append(group)

        return grouped

    def _aggregate_trades(
        self,
        data: list[dict[str, Any]],
        conviction_filter: str = "all",
    ) -> list[dict[str, Any]]:
        """Aggregate and format trades across all documents."""
        normalized_conviction_filter = parse_trade_conviction_filter(
            conviction_filter,
            default="all",
        )
        all_trades = []

        for record in data:
            parsed_data = record.get("parsed_data", {})
            trades = parsed_data.get("trades", []) if parsed_data else []
            if not trades or not isinstance(trades, list):
                continue

            doc_name = record.get("document_name", "Unknown Document")
            source = record.get("source", "Unknown Source")
            source_date = record.get("source_date", "")

            for trade in trades:
                if not isinstance(trade, dict):
                    continue

                raw_conviction = trade.get("conviction", "N/A")
                conviction = raw_conviction.strip().lower() if isinstance(raw_conviction, str) else "n/a"

                if normalized_conviction_filter == "high" and conviction != "high":
                    continue
                if normalized_conviction_filter == "medium" and conviction not in ("high", "medium", "moderate"):
                    continue

                all_trades.append(
                    {
                        "text": normalize_trade_expression(
                            trade.get("exposure") or trade.get("text", "N/A")
                        )
                        or "N/A",
                        "exposure": trade.get("exposure", "N/A"),
                        "rationale": trade.get("rationale", ""),
                        "timeframe": trade.get("timeframe", "N/A"),
                        "conviction": conviction,
                        "trigger_levels": trade.get("trigger_levels"),
                        "document": doc_name,
                        "source": source,
                        "date": source_date,
                    }
                )
        return all_trades

    def _aggregate_through_lines(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Aggregate and format through_lines across all documents."""
        all_through_lines = []

        for record in data:
            parsed_data = record.get("parsed_data", {})
            through_lines = parsed_data.get("through_lines", []) if parsed_data else []
            if not through_lines or not isinstance(through_lines, list):
                continue

            doc_name = record.get("document_name", "Unknown Document")
            doc_id = record.get("id", "")
            source = record.get("source", "Unknown Source")

            for tl in through_lines:
                if not isinstance(tl, dict):
                    continue
                lead = tl.get("lead", "")
                raw_supporting_trades = tl.get("supporting_trades", [])
                all_through_lines.append(
                    {
                        "lead": lead,
                        "key_insight": tl.get("key_insight", ""),
                        "supporting_themes": dedupe_text_items(tl.get("supporting_themes"), limit=6),
                        "supporting_trades": dedupe_text_items(
                            [
                                normalize_trade_expression(item)
                                for item in raw_supporting_trades
                            ]
                            if isinstance(raw_supporting_trades, list)
                            else [],
                            limit=2,
                        ),
                        "document": doc_name,
                        "doc_id": doc_id,
                        "item_id": self._generate_item_id(f"{doc_id}:{lead[:50]}"),
                        "source": source,
                    }
                )
        return all_through_lines

    def _aggregate_callouts(self, data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Aggregate callouts across all documents."""
        all_callouts = []

        for record in data:
            parsed_data = record.get("parsed_data", {})
            if not parsed_data:
                continue

            callouts = parsed_data.get("callouts", [])
            if not callouts or not isinstance(callouts, list):
                continue

            source = record.get("source", "Unknown Source")
            doc_name = record.get("document_name", "Unknown Document")

            for callout in callouts:
                if not isinstance(callout, dict):
                    continue

                text = callout.get("text", "").strip()
                if not text:
                    continue

                all_callouts.append(
                    {
                        "text": text,
                        "source_through_line": callout.get("source_through_line", ""),
                        "source": source,
                        "document": doc_name,
                    }
                )
        return all_callouts

    def format_economic_calendar(self, events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Format economic events grouped by day of week."""
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for event in events:
            event_date = event.get("event_date")
            if not event_date:
                continue

            date_obj = datetime.fromisoformat(event_date).date()
            day_name = date_obj.strftime("%A")

            grouped[day_name].append(
                {
                    "time": event.get("time_ny", "N/A"),
                    "event": event.get("event_name", "N/A"),
                    "consensus": event.get("consensus", "—"),
                }
            )

        weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        return {day: grouped[day] for day in weekday_order if day in grouped}

    def format_supply_calendar(self, events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        """Format supply events grouped by day of week."""
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for event in events:
            event_date = event.get("event_date")
            if not event_date:
                continue

            date_obj = datetime.fromisoformat(event_date).date()
            day_name = date_obj.strftime("%A")

            grouped[day_name].append(
                {
                    "time": event.get("time_ny", "N/A"),
                    "description": event.get("description", "N/A"),
                    "size": event.get("size_bn", "—"),
                }
            )

        weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
        return {day: grouped[day] for day in weekday_order if day in grouped}
