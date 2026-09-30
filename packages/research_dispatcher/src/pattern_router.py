"""Resolve which print-infographic patterns to apply for a report.

Routing is declarative in ``styles/pattern_routing.yaml``. The kit manifest
supplies pattern definitions; this module decides slot → pattern | prose | omit
for the current ``report_data``. Chart-vs-text judgement beyond these hard
routes is deferred.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_ROUTING = _PACKAGE_ROOT / "styles" / "pattern_routing.yaml"
_DEFAULT_MANIFEST = (
    _PACKAGE_ROOT / "styles" / "snippets" / "print-infographic-pattern-manifest.json"
)


class PatternRouter:
    """Load routing + manifest; resolve patterns for report slots."""

    def __init__(
        self,
        routing_path: str | Path | None = None,
        manifest: dict[str, Any] | None = None,
        styles_dir: str | Path | None = None,
    ):
        styles = Path(styles_dir) if styles_dir else _PACKAGE_ROOT / "styles"
        self.routing_path = Path(routing_path) if routing_path else styles / "pattern_routing.yaml"
        self.routing = self._load_routing(self.routing_path)
        if manifest is not None:
            self.manifest = manifest
        else:
            manifest_rel = self.routing.get("manifest") or "snippets/print-infographic-pattern-manifest.json"
            manifest_path = styles / manifest_rel
            self.manifest = self._load_json(manifest_path)
        self._patterns_by_id = {
            str(p["id"]): p
            for p in self.manifest.get("patterns", [])
            if isinstance(p, dict) and p.get("id")
        }

    @staticmethod
    def _load_routing(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {"routes": [], "prose_slots": [], "selection_rules": []}
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            return {"routes": [], "prose_slots": [], "selection_rules": []}
        return data

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        import json

        if not path.is_file():
            return {"patterns": []}
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {"patterns": []}

    def pattern_def(self, pattern_id: str) -> dict[str, Any] | None:
        return self._patterns_by_id.get(pattern_id)

    def route_for_slot(self, slot: str) -> dict[str, Any] | None:
        for route in self.routing.get("routes") or []:
            if isinstance(route, dict) and route.get("slot") == slot:
                return route
        return None

    def resolve(
        self,
        slot: str,
        *,
        report_data: dict[str, Any] | None = None,
        **context: Any,
    ) -> dict[str, Any]:
        """Return ``{slot, pattern, fallback, applied, reason, status}``.

        ``applied`` is the pattern id to emit, or ``None`` when using fallback.
        """
        route = self.route_for_slot(slot)
        if route is None:
            return {
                "slot": slot,
                "pattern": None,
                "fallback": "prose",
                "applied": None,
                "reason": "no route defined; treat as prose",
                "status": "unrouted",
            }

        pattern_id = route.get("pattern")
        fallback = route.get("fallback") or "prose"
        status = route.get("status") or "active"
        when = route.get("when") or {}

        if status == "deferred" and not context.get("force"):
            # Deferred routes stay on fallback until chart-ready fields exist
            # and an agent enables them (force=True or status flipped to active).
            return {
                "slot": slot,
                "pattern": pattern_id,
                "fallback": fallback,
                "applied": fallback if fallback in self._patterns_by_id else None,
                "reason": "deferred: keep fallback until chart-ready fields + explicit enable",
                "status": status,
            }

        ok, detail = self._when_satisfied(slot, when, report_data or {}, context)
        if not ok:
            applied = None
            if fallback == "omit":
                applied = None
            elif fallback in self._patterns_by_id:
                applied = fallback
            # prose / omit → applied None
            return {
                "slot": slot,
                "pattern": pattern_id,
                "fallback": fallback,
                "applied": applied if fallback in self._patterns_by_id else None,
                "reason": detail,
                "status": status,
            }

        if pattern_id not in self._patterns_by_id:
            return {
                "slot": slot,
                "pattern": pattern_id,
                "fallback": fallback,
                "applied": None,
                "reason": f"unknown pattern id {pattern_id!r}",
                "status": status,
            }

        return {
            "slot": slot,
            "pattern": pattern_id,
            "fallback": fallback,
            "applied": pattern_id,
            "reason": "when conditions satisfied",
            "status": status,
        }

    def resolve_report(self, report_data: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """Resolve every defined route against ``report_data``."""
        summary = report_data.get("summary") or {}
        sources = summary.get("by_source") or {}
        through_lines = report_data.get("through_lines") or []
        metrics_count = 0
        if summary.get("total_documents") is not None:
            metrics_count += 1
        if isinstance(sources, dict):
            metrics_count += 1
        if (report_data.get("source_date_range") or {}).get("start"):
            metrics_count += 1
        if through_lines:
            metrics_count += 1

        theme_groups = [
            g
            for g in (report_data.get("themes_by_through_line") or [])
            if isinstance(g, dict) and (g.get("themes") or [])
        ]

        callouts = [
            c
            for c in (report_data.get("callouts") or [])
            if isinstance(c, dict)
            and str(c.get("content") or c.get("text") or "").strip()
            and str(c.get("source_through_line") or "").strip()
        ]

        economic = report_data.get("economic_calendar") or {}
        economic_rows = sum(
            len(v) for v in economic.values() if isinstance(v, list)
        ) if isinstance(economic, dict) else 0

        supply = report_data.get("supply_calendar") or {}
        supply_rows = sum(
            len(v) for v in supply.values() if isinstance(v, list)
        ) if isinstance(supply, dict) else 0

        details = report_data.get("details") or []
        trades = report_data.get("trades") or []
        delta = report_data.get("synthesis_delta") or {}
        street = report_data.get("street_agrees_splits") or {}

        contexts = {
            "cover_metrics": {"metrics_count": metrics_count},
            "theme_density": {"groups_count": len(theme_groups)},
            "throughline_callout": {
                "has_content": bool(callouts),
                "tied_to_through_line": bool(callouts),
            },
            "economic_calendar": {"row_count": economic_rows},
            "supply_calendar": {"row_count": supply_rows},
            "details_table": {"row_count": len(details) if isinstance(details, list) else 0},
            "synthesis_delta": {
                "has_signed_category_changes": self._delta_has_signed_changes(delta),
                "shared_unit": False,
            },
            "street_agrees_splits": {
                "has_share_components": self._street_has_shares(street),
            },
            "conviction_mix": {
                "trade_count": len(trades) if isinstance(trades, list) else 0,
                "conviction_counts_available": False,
            },
            "event_milestones": {
                "use_timeline_instead_of_table": False,
            },
        }

        resolved: dict[str, dict[str, Any]] = {}
        for route in self.routing.get("routes") or []:
            if not isinstance(route, dict):
                continue
            slot = str(route.get("slot") or "")
            if not slot:
                continue
            resolved[slot] = self.resolve(
                slot,
                report_data=report_data,
                **contexts.get(slot, {}),
            )
        return resolved

    def applied_patterns(self, resolved: dict[str, dict[str, Any]]) -> set[str]:
        return {
            str(decision["applied"])
            for decision in resolved.values()
            if decision.get("applied")
        }

    def _when_satisfied(
        self,
        slot: str,
        when: dict[str, Any],
        report_data: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[bool, str]:
        del report_data  # reserved for deeper field checks
        if not when:
            return True, "no when constraints"

        if "min_metrics" in when:
            count = int(context.get("metrics_count") or 0)
            if count < int(when["min_metrics"]):
                return False, f"metrics_count {count} < min_metrics {when['min_metrics']}"
        if "max_metrics" in when:
            count = int(context.get("metrics_count") or 0)
            if count > int(when["max_metrics"]):
                return False, f"metrics_count {count} > max_metrics {when['max_metrics']}"

        if "min_groups" in when:
            count = int(context.get("groups_count") or 0)
            if count < int(when["min_groups"]):
                return False, f"groups_count {count} < min_groups {when['min_groups']}"
        if "max_groups" in when:
            count = int(context.get("groups_count") or 0)
            if count > int(when["max_groups"]):
                # Cap is soft for theme density — still apply pattern, truncate in view
                pass

        if when.get("has_content") and not context.get("has_content"):
            return False, "missing callout content"
        if when.get("tied_to_through_line") and not context.get("tied_to_through_line"):
            return False, "callout not tied to through-line"

        if when.get("has_rows") and int(context.get("row_count") or 0) < 1:
            return False, "no rows"

        if when.get("has_signed_category_changes") and not context.get(
            "has_signed_category_changes"
        ):
            return False, "no signed category changes in data"
        if when.get("shared_unit") and not context.get("shared_unit"):
            return False, "no shared unit/domain"

        if when.get("has_share_components") and not context.get("has_share_components"):
            return False, "no share components"

        if "min_trades" in when:
            if int(context.get("trade_count") or 0) < int(when["min_trades"]):
                return False, "too few trades"
        if when.get("conviction_counts_available") and not context.get(
            "conviction_counts_available"
        ):
            return False, "conviction mix not prepared"

        if when.get("use_timeline_instead_of_table") and not context.get(
            "use_timeline_instead_of_table"
        ):
            return False, "timeline not selected; prefer table"

        return True, "when conditions satisfied"

    @staticmethod
    def _delta_has_signed_changes(delta: Any) -> bool:
        if not isinstance(delta, dict):
            return False
        # Future: look for structured signed changes. Narrative sections alone ≠ chart.
        changes = delta.get("signed_changes") or delta.get("category_changes")
        return isinstance(changes, list) and len(changes) > 0

    @staticmethod
    def _street_has_shares(street: Any) -> bool:
        if not isinstance(street, dict):
            return False
        shares = street.get("shares") or street.get("composition")
        return isinstance(shares, list) and len(shares) > 0
