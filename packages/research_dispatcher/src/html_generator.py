"""Print-oriented HTML report generator for research dispatch."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

from .pattern_router import PatternRouter

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_STYLES_DIR = _PACKAGE_ROOT / "styles"
_DEFAULT_TEMPLATES_DIR = _PACKAGE_ROOT / "templates"
_KIT_CSS = "snippets/print-infographic-patterns.css"
_KIT_MANIFEST = "snippets/print-infographic-pattern-manifest.json"
_SECTION_CSS = "report_sections.css"
_ROUTING = "pattern_routing.yaml"


class HtmlReportGenerator:
    """Renders formatted report_data to a self-contained print HTML file."""

    def __init__(
        self,
        output_dir: str = ".",
        styles_dir: str | Path | None = None,
        templates_dir: str | Path | None = None,
        routing_path: str | Path | None = None,
    ):
        self.output_dir = output_dir
        self.styles_dir = Path(styles_dir) if styles_dir else _DEFAULT_STYLES_DIR
        self.templates_dir = (
            Path(templates_dir) if templates_dir else _DEFAULT_TEMPLATES_DIR
        )
        self.manifest = self._load_manifest()
        self.router = PatternRouter(
            routing_path=routing_path or (self.styles_dir / _ROUTING),
            manifest=self.manifest,
            styles_dir=self.styles_dir,
        )
        self.env = Environment(
            loader=FileSystemLoader(str(self.templates_dir)),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )

    def _load_manifest(self) -> dict[str, Any]:
        path = self.styles_dir / _KIT_MANIFEST
        if not path.is_file():
            return {"patterns": [], "selection_rules": []}
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def _read_css(self, relative: str) -> str:
        path = self.styles_dir / relative
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def compose_css(self, used_patterns: set[str] | None = None) -> str:
        """Compose kit CSS plus dispatcher section chrome.

        Full kit stylesheet is embedded for now (unused pattern rules are inert
        without markup). ``used_patterns`` comes from ``PatternRouter`` and is
        exposed on the view for tests / future selective extraction.
        """
        self._last_used_patterns = set(used_patterns or ())
        parts = [
            self._read_css(_KIT_CSS),
            self._read_css(_SECTION_CSS),
        ]
        return "\n\n".join(part for part in parts if part.strip())

    def pattern_ids(self) -> list[str]:
        return [str(p.get("id", "")) for p in self.manifest.get("patterns", []) if p.get("id")]

    @staticmethod
    def _format_date_range(start: str, end: str) -> str:
        try:
            start_dt = datetime.strptime(start, "%Y-%m-%d")
            end_dt = datetime.strptime(end, "%Y-%m-%d")
        except ValueError:
            return f"{start} – {end}" if start != end else start
        if start_dt == end_dt:
            return start_dt.strftime("%b %d, %Y")
        if start_dt.year == end_dt.year and start_dt.month == end_dt.month:
            return f"{start_dt.strftime('%b %d')}–{end_dt.strftime('%d, %Y')}"
        if start_dt.year == end_dt.year:
            return f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"
        return f"{start_dt.strftime('%b %d, %Y')} – {end_dt.strftime('%b %d, %Y')}"

    @staticmethod
    def _format_trigger_levels(raw: Any) -> str:
        if raw is None:
            return ""
        if isinstance(raw, str):
            return raw.strip()
        if isinstance(raw, dict):
            parts = []
            for key, value in raw.items():
                if value is None or value == "":
                    continue
                parts.append(f"{key}: {value}")
            return "; ".join(parts)
        if isinstance(raw, list):
            return "; ".join(str(item) for item in raw if item not in (None, ""))
        return str(raw)

    @staticmethod
    def _conviction_class(conviction: str) -> str:
        value = (conviction or "").strip().lower()
        if value in {"high", "h"}:
            return "high"
        if value in {"medium", "med", "m"}:
            return "medium"
        if value in {"low", "l"}:
            return "low"
        return "low"

    @staticmethod
    def _strength_class(strength: str) -> str:
        value = (strength or "").strip().lower()
        if value in {"strong", "high"}:
            return "strong"
        if value in {"moderate", "medium"}:
            return "moderate"
        return "weak"

    def _callouts_by_through_line(
        self,
        callouts: list[dict[str, Any]],
    ) -> dict[str, dict[str, str]]:
        mapped: dict[str, dict[str, str]] = {}
        for callout in callouts:
            lead = str(callout.get("source_through_line") or "").strip()
            content = str(callout.get("content") or callout.get("text") or "").strip()
            if not lead or not content:
                continue
            source = str(callout.get("source") or "").strip()
            mapped[lead] = {
                "content": content,
                "attribution": source,
            }
        return mapped

    def _build_metrics(self, report_data: dict[str, Any]) -> list[dict[str, str]]:
        summary = report_data.get("summary") or {}
        metrics: list[dict[str, str]] = []
        total_docs = summary.get("total_documents")
        if total_docs is not None:
            metrics.append(
                {
                    "label": "Documents",
                    "value": str(total_docs),
                    "context": "",
                }
            )
        sources = summary.get("by_source") or {}
        if isinstance(sources, dict):
            metrics.append(
                {
                    "label": "Sources",
                    "value": str(len(sources)),
                    "context": "",
                }
            )
        source_date_range = report_data.get("source_date_range") or {}
        start = source_date_range.get("start")
        end = source_date_range.get("end")
        if start and end:
            metrics.append(
                {
                    "label": "Date Range",
                    "value": self._format_date_range(str(start), str(end)),
                    "context": "",
                }
            )
        through_lines = report_data.get("through_lines") or []
        if through_lines:
            metrics.append(
                {
                    "label": "Through Lines",
                    "value": str(len(through_lines)),
                    "context": "",
                }
            )
        return metrics

    def _build_view_model(
        self,
        report_data: dict[str, Any],
    ) -> tuple[dict[str, Any], set[str]]:
        routing = self.router.resolve_report(report_data)
        used = self.router.applied_patterns(routing)

        def applies(slot: str, pattern_id: str) -> bool:
            decision = routing.get(slot) or {}
            return decision.get("applied") == pattern_id

        title = str(report_data.get("title") or "Research Dispatch")
        through_lines_raw = report_data.get("through_lines") or []
        subtitle_prefix = (
            "Weekly Synthesis"
            if through_lines_raw
            else "Research Digest"
        )

        source_date_range = report_data.get("source_date_range") or {}
        date_range_label = ""
        start = source_date_range.get("start")
        end = source_date_range.get("end")
        if start and end:
            date_range_label = self._format_date_range(str(start), str(end))

        active_filters = report_data.get("active_filters") or {}
        filter_parts = []
        if active_filters.get("region"):
            filter_parts.append(f"Region: {active_filters['region']}")
        if active_filters.get("asset_focus"):
            filter_parts.append(f"Asset: {active_filters['asset_focus']}")
        if active_filters.get("sources"):
            filter_parts.append(f"Sources: {active_filters['sources']}")
        if active_filters.get("date_range_days"):
            filter_parts.append(f"Date Range: {active_filters['date_range_days']} days")
        if active_filters.get("trade_conviction"):
            filter_parts.append(f"Conviction: {active_filters['trade_conviction']}")

        metrics = self._build_metrics(report_data)
        if not applies("cover_metrics", "metric_strip"):
            metrics = []

        executive_summary = [
            str(item).strip()
            for item in (report_data.get("executive_summary") or [])
            if str(item or "").strip()
        ]

        market_analysis = []
        for paragraph in report_data.get("analysis_paragraphs") or []:
            if isinstance(paragraph, dict):
                text = str(paragraph.get("text") or "").strip()
            else:
                text = str(paragraph or "").strip()
            if text:
                market_analysis.append(text)

        street = report_data.get("street_agrees_splits")
        street_lines: list[str] = []
        if isinstance(street, dict):
            street_lines = [
                str(item).strip()
                for item in (street.get("lines") or [])
                if str(item or "").strip()
            ]

        delta = report_data.get("synthesis_delta") or {}
        delta_sections = []
        for section in delta.get("sections") or []:
            items = [
                str(item).strip()
                for item in (section.get("items") or [])
                if str(item or "").strip()
            ]
            title_text = str(section.get("title") or "").strip()
            if not title_text and not items:
                continue
            delta_sections.append({"title": title_text, "bullets": items})
        delta_summary = str(delta.get("summary") or "").strip()
        delta_baseline = ""
        if delta.get("baseline_available") and delta.get("baseline_label"):
            delta_baseline = str(delta.get("baseline_label")).strip()

        callouts_by_tl = self._callouts_by_through_line(
            list(report_data.get("callouts") or [])
        )
        through_lines = []
        for tl in through_lines_raw:
            if not isinstance(tl, dict):
                continue
            lead = str(tl.get("lead") or "").strip()
            if not lead:
                continue
            detail = str(tl.get("detail") or "").strip()
            meta_bits = []
            if tl.get("source"):
                meta_bits.append(str(tl["source"]))
            if tl.get("document"):
                meta_bits.append(str(tl["document"]))
            callout = callouts_by_tl.get(lead)
            if callout and not applies("throughline_callout", "annotation"):
                callout = None
            through_lines.append(
                {
                    "lead": lead,
                    "detail": detail,
                    "meta": " · ".join(meta_bits),
                    "callout": callout,
                }
            )

        document_digest = []
        digest = report_data.get("document_digest") or []
        if isinstance(digest, list):
            for day in digest:
                if not isinstance(day, dict):
                    continue
                date_label = str(
                    day.get("heading") or day.get("date") or day.get("source_date") or ""
                ).strip()
                entries_raw = day.get("entries") or day.get("documents") or []
                entries = []
                for entry in entries_raw:
                    if not isinstance(entry, dict):
                        continue
                    entries.append(
                        {
                            "source": str(entry.get("source") or "Unknown").strip(),
                            "document": str(
                                entry.get("title")
                                or entry.get("document")
                                or entry.get("document_name")
                                or "Untitled"
                            ).strip(),
                            "summary": str(entry.get("summary") or "").strip(),
                        }
                    )
                if date_label and entries:
                    document_digest.append({"date": date_label, "entries": entries})

        theme_groups = []
        theme_density = []
        for group in report_data.get("themes_by_through_line") or []:
            if not isinstance(group, dict):
                continue
            lead = str(group.get("lead") or "Theme Cluster").strip()
            themes = []
            for theme in group.get("themes") or []:
                if not isinstance(theme, dict):
                    continue
                strength = str(theme.get("strength") or "").strip()
                themes.append(
                    {
                        "label": str(theme.get("label") or "").strip(),
                        "context": str(theme.get("context") or "").strip(),
                        "source": str(theme.get("source") or "").strip(),
                        "strength": strength,
                        "strength_class": self._strength_class(strength),
                    }
                )
            if not themes:
                continue
            theme_groups.append(
                {
                    "lead": lead,
                    "themes": themes,
                    "overflow_count": int(group.get("overflow_count") or 0),
                }
            )
            theme_density.append(
                {
                    "label": lead[:40] + ("…" if len(lead) > 40 else ""),
                    "value": str(len(themes)),
                }
            )
        if theme_density and applies("theme_density", "metric_strip"):
            # Soft-cap display per routing max_groups (default 6).
            theme_density = theme_density[:6]
        else:
            theme_density = []

        themes_flat = []
        if not theme_groups:
            for theme in report_data.get("themes_analysis") or []:
                if not isinstance(theme, dict):
                    continue
                strength = str(theme.get("strength") or "").strip()
                themes_flat.append(
                    {
                        "label": str(theme.get("label") or "").strip(),
                        "context": str(theme.get("context") or "").strip(),
                        "strength": strength,
                        "strength_class": self._strength_class(strength),
                    }
                )

        trades = []
        for trade in report_data.get("trades") or []:
            if not isinstance(trade, dict):
                continue
            text = str(trade.get("text") or "").strip()
            if not text:
                continue
            conviction = str(trade.get("conviction") or "").strip()
            doc = str(trade.get("document") or "")
            if len(doc) > 80:
                doc = doc[:80] + "…"
            trades.append(
                {
                    "text": text,
                    "conviction_label": conviction.upper() if conviction else "N/A",
                    "conviction_class": self._conviction_class(conviction),
                    "exposure": str(trade.get("exposure") or "n/a"),
                    "timeframe": str(trade.get("timeframe") or "n/a"),
                    "rationale": str(trade.get("rationale") or "").strip(),
                    "triggers": self._format_trigger_levels(trade.get("trigger_levels")),
                    "source_line": (
                        f"{trade.get('source', '')} - {doc} ({trade.get('date', '')})"
                    ).strip(" -"),
                }
            )

        economic_calendar = []
        for day, events in (report_data.get("economic_calendar") or {}).items():
            rows = []
            for event in events or []:
                if not isinstance(event, dict):
                    continue
                rows.append(
                    {
                        "time": str(event.get("time") or ""),
                        "event": str(event.get("event") or ""),
                        "consensus": str(event.get("consensus") or ""),
                    }
                )
            if rows:
                economic_calendar.append({"label": str(day), "rows": rows})
        if not applies("economic_calendar", "context_table"):
            economic_calendar = []

        supply_calendar = []
        for day, events in (report_data.get("supply_calendar") or {}).items():
            rows = []
            for event in events or []:
                if not isinstance(event, dict):
                    continue
                rows.append(
                    {
                        "time": str(event.get("time") or ""),
                        "description": str(event.get("description") or ""),
                        "size": str(event.get("size") or ""),
                    }
                )
            if rows:
                supply_calendar.append({"label": str(day), "rows": rows})
        if not applies("supply_calendar", "context_table"):
            supply_calendar = []

        details = report_data.get("details") or []
        details_headers: list[str] = []
        details_rows: list[list[str]] = []
        if details and isinstance(details[0], dict):
            headers = list(details[0].keys())
            details_headers = [h.replace("_", " ").title() for h in headers]
            for record in details:
                row = []
                for key in headers:
                    value = str(record.get(key, ""))
                    if key == "document_name" and len(value) > 40:
                        value = value[:40] + "…"
                    row.append(value)
                details_rows.append(row)
        if not applies("details_table", "context_table"):
            details_headers = []
            details_rows = []

        # Recompute used from what we actually emit (router + gating).
        used = set()
        if metrics:
            used.add("metric_strip")
        if theme_density:
            used.add("metric_strip")
        if any(tl.get("callout") for tl in through_lines):
            used.add("annotation")
        if economic_calendar or supply_calendar or details_rows:
            used.add("context_table")

        view = {
            "title": title,
            "subtitle_prefix": subtitle_prefix,
            "generated_at": str(report_data.get("generated_at") or ""),
            "date_range_label": date_range_label,
            "filter_line": " | ".join(filter_parts),
            "metrics": metrics,
            "executive_summary": executive_summary,
            "market_analysis": market_analysis,
            "street_lines": street_lines,
            "delta_sections": delta_sections,
            "delta_summary": delta_summary,
            "delta_baseline": delta_baseline,
            "through_lines": through_lines,
            "document_digest": document_digest,
            "theme_groups": theme_groups,
            "theme_density": theme_density,
            "themes_flat": themes_flat,
            "trades": trades,
            "economic_calendar": economic_calendar,
            "supply_calendar": supply_calendar,
            "details_headers": details_headers,
            "details_rows": details_rows,
            "used_patterns": sorted(used),
            "pattern_routing": routing,
        }
        return view, used

    def render(self, report_data: dict[str, Any]) -> str:
        """Return the full HTML document as a string."""
        view, used = self._build_view_model(report_data)
        view["composed_css"] = Markup(self.compose_css(used))
        template = self.env.get_template("report.html.j2")
        return template.render(**view)

    def generate(
        self,
        report_data: dict[str, Any],
        filename: str = "report.html",
    ) -> str:
        """Write HTML to ``output_dir`` and return the filepath."""
        html = self.render(report_data)
        filepath = os.path.join(self.output_dir, filename)
        os.makedirs(self.output_dir, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as handle:
            handle.write(html)
        return filepath
