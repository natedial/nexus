"""Stateful synthesis delta tracking across recurring report runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any


HISTORY_FILE = Path(__file__).parent.parent / "state" / "synthesis_history.json"
MAX_HISTORY = 48
MAX_SECTION_ITEMS = 3


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_text(value: Any) -> str:
    return _clean_text(value).lower()


def _normalize_list(values: Any, *, limit: int = 6) -> list[str]:
    if not isinstance(values, list):
        return []

    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _canonical_filters(filters: dict[str, Any]) -> dict[str, Any]:
    canonical: dict[str, Any] = {}
    for key in sorted(filters):
        value = filters[key]
        if value in (None, "", [], {}):
            continue
        canonical[key] = value
    return canonical


def _scope_key(filters: dict[str, Any]) -> str:
    payload = json.dumps(_canonical_filters(filters), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _through_line_fingerprint(through_line: dict[str, Any]) -> str:
    payload = {
        "lead": through_line["lead"],
        "consensus_level": through_line.get("consensus_level", ""),
        "consensus_anchor": through_line.get("consensus_anchor", ""),
        "key_insight": through_line.get("key_insight", ""),
        "supporting_themes": through_line.get("supporting_themes", []),
        "supporting_trades": through_line.get("supporting_trades", []),
        "supporting_sources": through_line.get("supporting_sources", []),
    }
    packed = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode("utf-8")).hexdigest()[:12]


def _prepare_through_line(through_line: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(through_line, dict):
        return None

    lead = _clean_text(through_line.get("lead"))
    if not lead:
        return None

    prepared = {
        "lead": lead,
        "lead_key": lead.lower(),
        "consensus_level": _clean_text(through_line.get("consensus_level")),
        "consensus_anchor": _clean_text(through_line.get("consensus_anchor")),
        "key_insight": _clean_text(through_line.get("key_insight")),
        "supporting_themes": _normalize_list(through_line.get("supporting_themes"), limit=6),
        "supporting_trades": _normalize_list(through_line.get("supporting_trades"), limit=3),
        "supporting_sources": _normalize_list(through_line.get("supporting_sources"), limit=6),
    }
    prepared["fingerprint"] = _through_line_fingerprint(prepared)
    return prepared


def _prepare_callout(callout: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(callout, dict):
        return None

    text = _clean_text(callout.get("text"))
    if not text:
        return None

    return {
        "text": text,
        "source_through_line": _clean_text(callout.get("source_through_line")),
        "source": _clean_text(callout.get("source")),
    }


def _date_range_label(snapshot: dict[str, Any]) -> str:
    source_date_range = snapshot.get("source_date_range") or {}
    start = source_date_range.get("start")
    end = source_date_range.get("end")
    if start and end:
        return f"{start} to {end}"
    generated_at = _clean_text(snapshot.get("generated_at"))
    return generated_at or "prior run"


def _parse_generated_at(value: Any) -> datetime | None:
    """Parse the generated_at timestamp used in report snapshots."""
    text = _clean_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _same_source_date_range(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Return True when two snapshots represent the same underlying report window."""
    left_range = left.get("source_date_range") or {}
    right_range = right.get("source_date_range") or {}
    return (
        left_range.get("start") == right_range.get("start")
        and left_range.get("end") == right_range.get("end")
        and bool(left_range.get("start"))
        and bool(left_range.get("end"))
    )


def _too_close_in_time(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Return True when two runs are too close together to make a useful comparison."""
    left_dt = _parse_generated_at(left.get("generated_at"))
    right_dt = _parse_generated_at(right.get("generated_at"))
    if left_dt is None or right_dt is None:
        return False
    if left_dt.date() == right_dt.date():
        return True
    return abs((right_dt - left_dt).total_seconds()) < 18 * 60 * 60


def _format_consensus(level: str) -> str:
    mapping = {
        "strong_consensus": "strong consensus",
        "moderate_consensus": "moderate consensus",
        "mixed_views": "mixed views",
        "contrarian": "contrarian",
    }
    return mapping.get(level, level.replace("_", " ").strip() or "unclear")


def _truncate_words(text: str, limit: int) -> str:
    words = _clean_text(text).split()
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]) + "..."


def _short_label(through_line: dict[str, Any]) -> str:
    lead = _clean_text(through_line.get("lead"))
    if ":" in lead:
        prefix, suffix = lead.split(":", 1)
        prefix = prefix.strip()
        suffix = suffix.strip()
        if 3 <= len(prefix.split()) <= 8:
            return f"{prefix}: {_truncate_words(suffix, 5)}"
    return _truncate_words(lead, 9)


def _format_change_item(current: dict[str, Any], previous: dict[str, Any] | None = None) -> str:
    label = _short_label(current)
    if previous is None:
        anchor = current.get("consensus_anchor") or current.get("key_insight") or current.get("lead")
        return f"{label}: {_truncate_words(anchor, 16)}"

    notes: list[str] = []
    if current.get("consensus_level") != previous.get("consensus_level"):
        notes.append(
            f"consensus now {_format_consensus(current.get('consensus_level', ''))}"
        )
    if current.get("supporting_trades") != previous.get("supporting_trades"):
        trades = ", ".join(current.get("supporting_trades") or [])
        if trades:
            notes.append(f"trade expression now {trades}")
    if current.get("consensus_anchor") != previous.get("consensus_anchor"):
        anchor = current.get("consensus_anchor")
        if anchor:
            notes.append(f"anchor shifted to {anchor}")
    if not notes and current.get("key_insight") != previous.get("key_insight"):
        notes.append("framing changed materially")

    if not notes:
        notes.append("support shifted without changing the headline")
    return f"{label}: {'; '.join(notes)}."


def _format_persisted_item(through_line: dict[str, Any]) -> str:
    parts = [_short_label(through_line)]
    anchor = through_line.get("consensus_anchor")
    trades = ", ".join(through_line.get("supporting_trades") or [])
    if anchor:
        parts.append(f"anchor still: {_truncate_words(anchor, 12)}")
    if trades:
        parts.append(f"expression: {trades}")
    return ". ".join(parts) + "."


def _extract_watchpoint(through_line: dict[str, Any]) -> str:
    key_insight = through_line.get("key_insight", "")
    clauses = [
        _clean_text(part)
        for part in key_insight.replace(";", ".").split(".")
        if _clean_text(part)
    ]
    markers = ("if ", "unless ", "until ", "however", "but ", "risk", "watch", "break", "flip")
    for clause in clauses:
        lower = clause.lower()
        if any(marker in lower for marker in markers):
            if lower.startswith(("if ", "unless ", "until ")):
                return clause[0].lower() + clause[1:]
            return f"the clause '{clause}' starts to dominate"

    anchor = through_line.get("consensus_anchor")
    if anchor:
        return f"the anchor '{anchor}' stops holding"

    trades = ", ".join(through_line.get("supporting_trades") or [])
    if trades:
        return f"the expression '{trades}' stops fitting the incoming evidence"

    return "the supporting evidence flips the current narrative"


class SynthesisDeltaTracker:
    """Compare current synthesis results with prior matching report runs."""

    def __init__(self, history_file: Path | None = None, max_history: int = MAX_HISTORY):
        self.history_file = history_file or HISTORY_FILE
        self.max_history = max_history

    def create_snapshot(self, synthesis_result: Any, report_data: dict[str, Any]) -> dict[str, Any]:
        active_filters = _canonical_filters(report_data.get("active_filters") or {})
        through_lines = []
        for through_line in getattr(synthesis_result, "through_lines", []):
            prepared = _prepare_through_line(through_line)
            if prepared is not None:
                through_lines.append(prepared)

        callouts = []
        for callout in getattr(synthesis_result, "callouts", []):
            prepared = _prepare_callout(callout)
            if prepared is not None:
                callouts.append(prepared)

        return {
            "generated_at": report_data.get("generated_at"),
            "active_filters": active_filters,
            "scope_key": _scope_key(active_filters),
            "source_date_range": report_data.get("source_date_range"),
            "document_count": getattr(synthesis_result, "document_count", 0),
            "title": _clean_text(getattr(synthesis_result, "title", "")),
            "through_lines": through_lines,
            "callouts": callouts,
        }

    def load_history(self) -> list[dict[str, Any]]:
        if not self.history_file.exists():
            return []
        try:
            data = json.loads(self.history_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        if not isinstance(data, list):
            return []
        return [item for item in data if isinstance(item, dict)]

    def find_previous_snapshot(
        self,
        current_snapshot: dict[str, Any],
        history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        history = history if history is not None else self.load_history()
        current_scope = current_snapshot.get("scope_key")
        for snapshot in reversed(history):
            if snapshot.get("scope_key") != current_scope:
                continue
            if snapshot.get("generated_at") == current_snapshot.get("generated_at"):
                continue
            if _same_source_date_range(snapshot, current_snapshot):
                continue
            if _too_close_in_time(snapshot, current_snapshot):
                continue
            return snapshot
        return None

    def build_delta_report(
        self,
        previous_snapshot: dict[str, Any] | None,
        current_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        current_lines = current_snapshot.get("through_lines", [])
        current_by_key = {item["lead_key"]: item for item in current_lines}

        if previous_snapshot is None:
            return {
                "baseline_available": False,
                "baseline_label": "",
                "summary": "",
                "sections": [],
            }

        previous_lines = previous_snapshot.get("through_lines", [])
        previous_by_key = {item["lead_key"]: item for item in previous_lines}

        current_keys = set(current_by_key)
        previous_keys = set(previous_by_key)
        new_keys = sorted(current_keys - previous_keys)
        retired_keys = sorted(previous_keys - current_keys)
        shared_keys = sorted(current_keys & previous_keys)

        evolved_keys = [
            key for key in shared_keys
            if current_by_key[key].get("fingerprint") != previous_by_key[key].get("fingerprint")
        ]
        persisted_keys = [
            key for key in shared_keys
            if current_by_key[key].get("fingerprint") == previous_by_key[key].get("fingerprint")
        ]

        changed_items = [
            f"New: {_format_change_item(current_by_key[key])}"
            for key in new_keys[:MAX_SECTION_ITEMS]
        ]
        changed_items.extend(
            f"Evolved: {_format_change_item(current_by_key[key], previous_by_key[key])}"
            for key in evolved_keys[: max(0, MAX_SECTION_ITEMS - len(changed_items))]
        )
        if not changed_items:
            changed_items = ["No material narrative changes versus the prior matching dispatch."]

        persisted_items = [
            _format_persisted_item(current_by_key[key])
            for key in persisted_keys[:MAX_SECTION_ITEMS]
        ]

        retired_items = [
            f"{_short_label(previous_by_key[key])}: dropped from the current synthesis."
            for key in retired_keys[:MAX_SECTION_ITEMS]
        ]

        trade_items = []
        priority_keys = new_keys + evolved_keys + persisted_keys
        for key in priority_keys:
            item = current_by_key[key]
            trades = item.get("supporting_trades") or []
            if not trades:
                continue
            prefix = "New expression" if key in new_keys else "Keep on" if key in persisted_keys else "Reframe with"
            trade_items.append(
                f"{_short_label(item)}: {prefix.lower()} {', '.join(trades)}."
            )
            if len(trade_items) >= MAX_SECTION_ITEMS:
                break
        if not trade_items and retired_items:
            trade_items = retired_items[:1]

        watch_items = [
            f"{_short_label(item)}: watch whether {_extract_watchpoint(item)}."
            for item in current_lines[:MAX_SECTION_ITEMS]
        ]

        sections = [{"title": "What Changed", "items": changed_items}]
        if persisted_items:
            sections.append({"title": "What Persisted", "items": persisted_items})
        if retired_items:
            sections.append({"title": "Retired Or Faded", "items": retired_items})
        if trade_items:
            sections.append({"title": "Trade Implications", "items": trade_items})
        if watch_items:
            sections.append({"title": "Invalidation Watch", "items": watch_items})

        return {
            "baseline_available": True,
            "baseline_label": _date_range_label(previous_snapshot),
            "summary": (
                f"Versus { _date_range_label(previous_snapshot) }: "
                f"{len(new_keys)} new, {len(evolved_keys)} evolved, "
                f"{len(persisted_keys)} persisted, {len(retired_keys)} retired."
            ),
            "sections": sections,
        }

    def prepare_report(
        self,
        synthesis_result: Any,
        report_data: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current_snapshot = self.create_snapshot(synthesis_result, report_data)
        previous_snapshot = self.find_previous_snapshot(current_snapshot)
        delta = self.build_delta_report(previous_snapshot, current_snapshot)
        return current_snapshot, delta

    def save_snapshot(self, snapshot: dict[str, Any]) -> None:
        history = self.load_history()
        history.append(snapshot)
        trimmed = history[-self.max_history :]
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        self.history_file.write_text(
            json.dumps(trimmed, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
