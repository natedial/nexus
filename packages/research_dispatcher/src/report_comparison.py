"""JSON-first comparison helpers for dispatcher report outputs."""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
from typing import Any


def compare_reports(
    parser_report: dict[str, Any],
    analyst_report: dict[str, Any],
    baseline_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare parser-exclusive and agent-inclusive report JSON payloads."""
    comparison = {
        "summary": _summary_metrics(parser_report, analyst_report, baseline_report),
        "document_coverage": _coverage_comparison(parser_report, analyst_report),
        "source_coverage": _counter_comparison(
            _source_counter(parser_report),
            _source_counter(analyst_report),
        ),
        "date_coverage": {
            "parser": parser_report.get("source_date_range"),
            "analyst": analyst_report.get("source_date_range"),
            "matches": parser_report.get("source_date_range")
            == analyst_report.get("source_date_range"),
        },
        "theme_labels": _text_item_comparison(
            _theme_labels(parser_report),
            _theme_labels(analyst_report),
        ),
        "trade_texts": _text_item_comparison(
            _trade_texts(parser_report),
            _trade_texts(analyst_report),
        ),
        "through_lines": _text_item_comparison(
            _through_line_texts(parser_report),
            _through_line_texts(analyst_report),
        ),
        "callouts": _text_item_comparison(
            _callout_texts(parser_report),
            _callout_texts(analyst_report),
        ),
        "talking_points": _text_item_comparison(
            _talking_point_texts(parser_report),
            _talking_point_texts(analyst_report),
        ),
        "analyst_only_fields": _analyst_only_field_comparison(
            parser_report,
            analyst_report,
        ),
        "representative_text_diffs": _representative_text_diffs(
            parser_report,
            analyst_report,
        ),
    }
    if baseline_report is not None:
        comparison["baseline"] = {
            "parser": _summary_metrics(baseline_report, parser_report),
            "analyst": _summary_metrics(baseline_report, analyst_report),
        }
    return comparison


def _summary_metrics(
    left: dict[str, Any],
    right: dict[str, Any],
    baseline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "parser_document_count": _document_count(left),
        "analyst_document_count": _document_count(right),
        "document_count_delta": _document_count(right) - _document_count(left),
        "parser_theme_count": len(_theme_labels(left)),
        "analyst_theme_count": len(_theme_labels(right)),
        "parser_trade_count": len(_trade_texts(left)),
        "analyst_trade_count": len(_trade_texts(right)),
        "parser_through_line_count": len(_through_line_texts(left)),
        "analyst_through_line_count": len(_through_line_texts(right)),
        "parser_callout_count": len(_callout_texts(left)),
        "analyst_callout_count": len(_callout_texts(right)),
        "parser_talking_point_count": len(_talking_point_texts(left)),
        "analyst_talking_point_count": len(_talking_point_texts(right)),
    }
    if baseline is not None:
        result["baseline_document_count"] = _document_count(baseline)
    return result


def _coverage_comparison(
    parser_report: dict[str, Any],
    analyst_report: dict[str, Any],
) -> dict[str, Any]:
    parser_docs = _document_keys(parser_report)
    analyst_docs = _document_keys(analyst_report)
    return {
        "parser_count": len(parser_docs),
        "analyst_count": len(analyst_docs),
        "common_count": len(parser_docs & analyst_docs),
        "missing_from_analyst": sorted(parser_docs - analyst_docs),
        "added_by_analyst": sorted(analyst_docs - parser_docs),
    }


def _counter_comparison(left: Counter[str], right: Counter[str]) -> dict[str, Any]:
    return {
        "parser": dict(sorted(left.items())),
        "analyst": dict(sorted(right.items())),
        "missing_from_analyst": dict(sorted((left - right).items())),
        "added_by_analyst": dict(sorted((right - left).items())),
    }


def _text_item_comparison(
    parser_items: list[str],
    analyst_items: list[str],
) -> dict[str, Any]:
    parser_keys = {_normalize_text(item): item for item in parser_items if item}
    analyst_keys = {_normalize_text(item): item for item in analyst_items if item}
    missing_keys = sorted(set(parser_keys) - set(analyst_keys))
    added_keys = sorted(set(analyst_keys) - set(parser_keys))
    return {
        "parser_count": len(parser_keys),
        "analyst_count": len(analyst_keys),
        "common_count": len(set(parser_keys) & set(analyst_keys)),
        "missing_from_analyst": [parser_keys[key] for key in missing_keys],
        "added_by_analyst": [analyst_keys[key] for key in added_keys],
    }


def _analyst_only_field_comparison(
    parser_report: dict[str, Any],
    analyst_report: dict[str, Any],
) -> dict[str, Any]:
    field_paths = [
        "assertions",
        "world_nodes",
        "world_edges",
        "forecast_candidates",
        "trading_opportunities",
        "short_time_horizon_insights",
        "talking_points",
        "cross_document_references",
    ]
    parser_details = parser_report.get("details", [])
    analyst_details = analyst_report.get("details", [])
    parser_records = _records(parser_report)
    analyst_records = _records(analyst_report)
    return {
        "detail_fields": {
            "parser": _field_presence(parser_details, field_paths),
            "analyst": _field_presence(analyst_details, field_paths),
        },
        "record_fields": {
            "parser": _field_presence(parser_records, field_paths),
            "analyst": _field_presence(analyst_records, field_paths),
        },
    }


def _representative_text_diffs(
    parser_report: dict[str, Any],
    analyst_report: dict[str, Any],
) -> list[dict[str, Any]]:
    pairs = [
        ("executive_summary", _paragraphs(parser_report), _paragraphs(analyst_report)),
        ("through_lines", _through_line_texts(parser_report), _through_line_texts(analyst_report)),
        ("callouts", _callout_texts(parser_report), _callout_texts(analyst_report)),
    ]
    diffs: list[dict[str, Any]] = []
    for label, parser_items, analyst_items in pairs:
        for parser_text, analyst_text in zip(parser_items[:3], analyst_items[:3]):
            ratio = SequenceMatcher(None, parser_text, analyst_text).ratio()
            if ratio < 0.92:
                diffs.append(
                    {
                        "section": label,
                        "similarity": round(ratio, 3),
                        "parser_excerpt": _truncate(parser_text),
                        "analyst_excerpt": _truncate(analyst_text),
                    }
                )
    return diffs


def _document_count(report: dict[str, Any]) -> int:
    summary = report.get("summary")
    if isinstance(summary, dict) and isinstance(summary.get("total_documents"), int):
        return summary["total_documents"]
    return len(report.get("details", []) if isinstance(report.get("details"), list) else [])


def _document_keys(report: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for detail in report.get("details", []) if isinstance(report.get("details"), list) else []:
        if not isinstance(detail, dict):
            continue
        keys.add(str(detail.get("id") or detail.get("document_name") or ""))
    return {key for key in keys if key}


def _source_counter(report: dict[str, Any]) -> Counter[str]:
    details = report.get("details", [])
    counter: Counter[str] = Counter()
    if isinstance(details, list):
        for detail in details:
            if isinstance(detail, dict):
                counter[str(detail.get("source") or "Unknown")] += 1
    if not counter and isinstance(report.get("summary"), dict):
        by_source = report["summary"].get("by_source")
        if isinstance(by_source, dict):
            counter.update({str(key): int(value) for key, value in by_source.items()})
    return counter


def _theme_labels(report: dict[str, Any]) -> list[str]:
    return [
        str(item.get("label"))
        for item in report.get("themes_analysis", [])
        if isinstance(item, dict) and item.get("label")
    ]


def _trade_texts(report: dict[str, Any]) -> list[str]:
    return [
        str(item.get("text") or item.get("thesis"))
        for item in report.get("trades", [])
        if isinstance(item, dict) and (item.get("text") or item.get("thesis"))
    ]


def _through_line_texts(report: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for item in report.get("through_lines", []):
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, dict):
            texts.append(str(item.get("lead") or item.get("key_insight") or item.get("text") or ""))
    return [text for text in texts if text]


def _callout_texts(report: dict[str, Any]) -> list[str]:
    return [
        str(item.get("text") if isinstance(item, dict) else item)
        for item in report.get("callouts", [])
        if item
    ]


def _talking_point_texts(report: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for item in report.get("talking_points", []):
        if isinstance(item, dict):
            texts.append(str(item.get("text") or ""))
        elif isinstance(item, str):
            texts.append(item)
    for record in _records(report):
        parsed_data = record.get("parsed_data") if isinstance(record, dict) else None
        if isinstance(parsed_data, dict):
            for point in parsed_data.get("talking_points", []):
                if isinstance(point, dict) and point.get("text"):
                    texts.append(str(point["text"]))
        for point in record.get("talking_points", []) if isinstance(record, dict) else []:
            if isinstance(point, dict) and point.get("text"):
                texts.append(str(point["text"]))
    return [text for text in texts if text]


def _records(report: dict[str, Any]) -> list[dict[str, Any]]:
    records = report.get("records") or report.get("documents") or report.get("raw_records")
    return records if isinstance(records, list) else []


def _paragraphs(report: dict[str, Any]) -> list[str]:
    value = report.get("executive_summary", [])
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value if item]


def _field_presence(records: list[Any], field_paths: list[str]) -> dict[str, int]:
    counts = {field: 0 for field in field_paths}
    for record in records:
        if not isinstance(record, dict):
            continue
        for field in field_paths:
            value = record.get(field)
            if isinstance(value, list):
                counts[field] += len(value)
            elif value:
                counts[field] += 1
    return counts


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def _truncate(value: str, limit: int = 280) -> str:
    value = " ".join(value.split())
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."
