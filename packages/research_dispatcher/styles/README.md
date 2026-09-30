# Print HTML styles + pattern routing

## Files

| Path | Role |
| --- | --- |
| `pattern_routing.yaml` | **When to use which kit pattern** (source of truth for agents + generator) |
| `snippets/print-infographic-pattern-manifest.json` | Pattern definitions (question, data_shape, required_fields, avoid_when) |
| `snippets/print-infographic-patterns.css` | Kit BASE + pattern CSS |
| `snippets/print-infographic-patterns.html` | Visual specimen |
| `report_sections.css` | Prose / through-line / trade chrome on kit tokens |

## How agents should choose patterns

1. Open `pattern_routing.yaml` and find the **slot** (e.g. `cover_metrics`, `economic_calendar`).
2. Read `pattern`, `when`, `fallback`, and `status`.
3. Confirm the pattern id exists in the kit manifest and that `required_fields` can be filled from **validated** `report_data`.
4. If `status: deferred` or `when` fails → use `fallback` (`prose` / `omit` / another pattern). **Do not invent numbers for a chart.**
5. Chart-vs-text judgement for borderline cases is **not** implemented yet — do not expand deferred routes without an explicit product decision.

`HtmlReportGenerator` loads this YAML via `PatternRouter` and only emits pattern markup when `applied` is set.

## Active vs deferred (today)

**Active (emit kit markup):** `cover_metrics`, `theme_density` → `metric_strip`; calendars/details → `context_table`; linked callouts → `annotation`.

**Deferred (prose until chart-ready fields exist):** `synthesis_delta` → future `diverging_bars`; `street_agrees_splits` / `conviction_mix` → future `composition_bars`; optional `event_timeline`.

**Always prose:** executive summary, market analysis, through-line cards, document digest, trade list.
