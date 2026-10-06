# Morning attention ops (Proey-canonical)

Cadence: **weekdays ~06:25 America/New_York**, after the 06:10 digest.  
Does **not** change 5:55 / 6:10 tablet pushes.  
Empty day = **silent** (no reMarkable notebook, no Grok Bot ping) — same as the 6:40 handwritten pass.

## Claim source lock (2026-10-06)

**One claim source:** research_analyst `argument_map` / ClaimNodes → `project.py` → claim-note-v1.  
**Not** LIBRARY body extraction (`project_library`, draft PR #51 — closed/superseded).  

Gerhard validators on projection (under-extract OK): one idea per claim; speaker never `LIBRARY desk`; no desk merges; `cause_edges` only when stated; no invented numbers.

Coverage gap (acknowledged): only docs that already ran parser→analyst appear. LIBRARY-only digests enter the analyst pipe later — not a parallel extract.

**Do not invent live ClaimNodes.** If overnight parser→analyst did not write `document_analysis` rows with `argument_map` for the since-watermark window, export is empty and MA is **silent**. That is correct behavior — not a bug to patch with fixtures or LIBRARY extract.

## Minimum env for live MA feed (Proey)

Export reads the **analysis store** only.

| Variable | Role |
| --- | --- |
| `RESEARCH_ANALYST_ANALYSIS_DB_URL` | Analysis DB with `argmap-v1` `document_analysis` rows that already contain `argument_map`. Falls back to `NEXUS_DATABASE_URL` / root `DATABASE_URL` when set and the default sqlite URL would otherwise apply. |
| `NEXUS_DATABASE_URL` | Acceptable substitute when it is the same Postgres that holds analyst `document_analysis`. |
| `RESEARCH_ANALYST_BATCH_OUT_DIR` | Directory for `dispatch-batch-*.json` and `latest.json` symlink (default `/var/research/analyst`). |

Unrelated / not this path:

| Item | Note |
| --- | --- |
| Empty Proton `research_claims` | **Unrelated** to the MA argument_map feed. Do not treat an empty claims table as an export blocker. |
| Fixtures / invented ClaimNodes | **Forbidden** for live dry-run sign-off. Use analysis-DB-backed export only. |

Hold merge of the argument_map MA PR until Gerhard signs a **live or analysis-DB-backed** dry-run (fixture-only dry-run is insufficient for 6:25 resume).

## Canonical live path (Proey routine)

### 1) Export overnight analyst batch (since watermark)

Watermark file holds the last successful MA run UTC timestamp. Use its **date** (or yesterday) as `--date-from`:

```bash
cd packages/research_analyst
# Minimum env: ANALYSIS_DB_URL (or NEXUS_DATABASE_URL) + BATCH_OUT_DIR
# Example: since last watermark date 2026-10-05
PYTHONPATH=src python -m research_analysis_layer.main export-dispatch-batch \
  --batch-key morning-2026-10-06 \
  --date-from 2026-10-05 \
  --out "${RESEARCH_ANALYST_BATCH_OUT_DIR:-/var/research/analyst}/dispatch-batch-morning-2026-10-06.json"
# Also updates BATCH_OUT_DIR/latest.json → that file
```

Shape: `{ "batch_key", "documents": [ { document_key, source, publisher, source_date, argument_map: [...] }, ... ] }`.

If `documents` is `[]` for the window → overnight pipe produced no argmap rows → MA will be silent. Fix the parser→analyst drain; do not fabricate claims.

### 2) Morning Attention → handoff

```bash
cd packages/research_dispatcher
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --argument-map-json /var/research/analyst/dispatch-batch-morning-2026-10-06.json \
  --since-watermark \
  --handoff-dir /path/to/morning-attention-handoff \
  --watermark state/morning_attention_last_run.json
```

Thin flag (reads `latest.json` from the analyst batch out dir):

```bash
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --analyst-batch-dir "${RESEARCH_ANALYST_BATCH_OUT_DIR:-/var/research/analyst}" \
  --since-watermark \
  --handoff-dir /path/to/morning-attention-handoff \
  --watermark state/morning_attention_last_run.json
```

Optional date bounds on top of the export window:

| Flag | Role |
| --- | --- |
| `--since YYYY-MM-DD` | Keep docs with `source_date >= since` |
| `--until YYYY-MM-DD` | Keep docs with `source_date <= until` |
| `--since-watermark` | Use watermark date as `--since` when `--since` omitted |

Then Proey’s connectors (same as 5:55 / 6:10):

1. Push `morning-attention.md` as notebook **`Morning Attention YYYY-MM-DD`**, placed **next to** G10 Calendar / Research From (own notebook, not folded in)  
2. Send `chat-ping.txt` one-liner to **Nate’s 1:1 chat with Proey**

Zero projected claims → **silent** (`handoff.json` `"silent": true`; no markdown, no ping).

### Demoted: `--library-json`

Accepted for diagnostics / counts only. **Does not** project Research Notes into claim notes. Do not use for the live 6:25 claim feed.

## Locked delivery destinations (Proey)

| Channel | Default |
| --- | --- |
| **Grok Bot chat ping** | Nate’s **1:1 chat with Proey** (same destination as 5:55 / 6:10 pings) |
| **reMarkable notebook title** | `Morning Attention YYYY-MM-DD` (unless Nate overrides) |
| **reMarkable placement** | **Next to** the G10 Calendar and Research From notebooks — **own** notebook, **not** folded into those pushes |

Handoff dir contents (non-silent day):

| File | Role |
| --- | --- |
| `morning-attention.md` | Own-surface notebook for reMarkable connector |
| `notebook-title.txt` | Default: `Morning Attention YYYY-MM-DD` |
| `chat-ping.txt` | One-line Grok Bot ping → Nate↔Proey 1:1 |
| `handoff.json` | Manifest (`silent`, point_count, channel_chat=`grok_bot`, fold-in flags false) |

## Env (dispatcher handoff)

| Variable | Role |
| --- | --- |
| `RESEARCH_DISPATCHER_MORNING_ARGUMENT_MAP_JSON` | Path to export-dispatch-batch JSON (live) |
| `RESEARCH_DISPATCHER_MORNING_ANALYST_BATCH_DIR` | Dir with `latest.json` (alt to explicit JSON path) |
| `RESEARCH_DISPATCHER_MORNING_HANDOFF_DIR` | Default `--handoff-dir` |
| `RESEARCH_DISPATCHER_MORNING_WATERMARK` | Watermark path (advanced after each run) |
| `RESEARCH_DISPATCHER_MORNING_LIBRARY_JSON` | **Demoted** — diagnostics only |
| `RESEARCH_DISPATCHER_NOTION_TOKEN` | **Demoted** — not MA claim source |
| `RESEARCH_DISPATCHER_GROK_BOT_PING_URL` | **Optional** webhook; default is handoff file |
| `RESEARCH_DISPATCHER_REMARKABLE_PUSH_URL` | **Demoted** — Proey connector is canonical |

**Do not use** `CHAT_PING_TO` / `EMAIL_TO` / SMTP for morning-attention chat ping.

## Host cron / launchd

**Demoted.** Prefer Proey’s owned 6:25 routine. `schedule_morning_attention.sh` requires `MORNING_ARGUMENT_MAP_JSON` or `MORNING_ANALYST_BATCH_DIR`.

## What Nate vs Proey configure

| Who | What |
| --- | --- |
| **Proey** | Own ~6:25 ET routine; set analyst ANALYSIS_DB_URL + BATCH_OUT_DIR; run export-dispatch-batch since watermark; run MA with `--argument-map-json` / `--analyst-batch-dir`; wire handoff → reMarkable + Grok Bot 1:1 |
| **Nate** | Optional notebook title override; chat destination and placement locked above |
| **Gerhard** | Sign-off on projection validators **and** an analysis-DB-backed dry-run before 6:25 resume |

## Fixture dry run (local only — not merge gate)

```bash
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --argument-map-json fixtures/claim_notes/argument_map_documents.json \
  --handoff-dir /tmp/ma-handoff \
  --dry-run --fake-delivery
```

Fixture path proves CLI/projection wiring. **Merge / 6:25 resume** needs Gerhard sign-off on a live or analysis-DB-backed export → MA dry-run.
