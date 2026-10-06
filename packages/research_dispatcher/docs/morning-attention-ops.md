# Morning attention ops (Proey-canonical)

Cadence: **weekdays ~06:25 America/New_York**, after the 06:10 digest.  
Does **not** change 5:55 / 6:10 tablet pushes.  
Empty day = **silent** (no reMarkable notebook, no Grok Bot ping) — same as the 6:40 handwritten pass.

## Canonical live path (no fixtures)

Proey supplies LIBRARY Research Notes **since last run** (Resource Type = Research Note only).  
`--library-json` **projects into claim notes on its own** — no `--notes-jsonl`, no `--argument-map-json`, no fixture files.

```bash
cd packages/research_dispatcher
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --library-json /path/to/library_research_notes.json \
  --handoff-dir /path/to/morning-attention-handoff \
  --watermark state/morning_attention_last_run.json
```

Then Proey’s connectors (same as 5:55 / 6:10):

1. Push `morning-attention.md` as notebook **`Morning Attention YYYY-MM-DD`**, placed **next to** G10 Calendar / Research From (own notebook, not folded in)  
2. Send `chat-ping.txt` one-liner to **Nate’s 1:1 chat with Proey**

Zero Research Notes in the JSON → **silent** (`handoff.json` `"silent": true`; no markdown, no ping).

### `--library-json` shape

JSON array (or `{"notes":[...]}`) of Research Note rows Proey already filtered:

```json
[
  {
    "title": "Services cool",
    "note_id": "optional-stable-id",
    "summary": "as stated in the Research Note — never invent numbers",
    "saved_at": "2026-10-05T12:00:00+00:00",
    "source_date": "2026-10-05",
    "url": "https://notion.so/..."
  }
]
```

Projection rules: copy title/summary as stated → claim-note-v1 (`support_kind=ingested_document_text`, no Dexter, empty `cause_edges`). Speaker=`LIBRARY desk`, publisher=`Notion LIBRARY` (distinct).

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

## LIBRARY inputs

| Item | Rule |
| --- | --- |
| Filter | Resource Type = Research Note only |
| Window | Saved **since last run** (Proey filters before inject; watermark advances after run) |
| Link | https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9 |

Offline fixtures (`--notes-jsonl` / `--argument-map-json`) are **optional** for local tests only — not the weekday live path.

## Env (optional / demoted)

| Variable | Role |
| --- | --- |
| `RESEARCH_DISPATCHER_MORNING_LIBRARY_JSON` | Path to Proey Research Notes JSON (live) |
| `RESEARCH_DISPATCHER_MORNING_HANDOFF_DIR` | Default `--handoff-dir` |
| `RESEARCH_DISPATCHER_MORNING_WATERMARK` | Watermark path (advanced after each run) |
| `RESEARCH_DISPATCHER_NOTION_TOKEN` | **Demoted** — only if Proey wants in-process Notion fetch |
| `RESEARCH_DISPATCHER_GROK_BOT_PING_URL` | **Optional** webhook; default is handoff file |
| `RESEARCH_DISPATCHER_REMARKABLE_PUSH_URL` | **Demoted** — Proey connector is canonical |

**Do not use** `CHAT_PING_TO` / `EMAIL_TO` / SMTP for morning-attention chat ping.

## Host cron / launchd

**Demoted.** Prefer Proey’s owned 6:25 routine. `schedule_morning_attention.sh` requires `RESEARCH_DISPATCHER_MORNING_LIBRARY_JSON` (no fixture default).

## What Nate vs Proey configure

| Who | What |
| --- | --- |
| **Proey** | Own ~6:25 ET routine; write `--library-json` (Research Notes since last run); run the command above; wire handoff → reMarkable (next to G10 / Research From) + Grok Bot 1:1 ping |
| **Nate** | Optional notebook title override; chat destination and placement locked above |

## Dry run (no secrets)

```bash
# Empty library → silent
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --library-json /path/to/empty.json \
  --handoff-dir /tmp/ma-handoff \
  --dry-run --fake-delivery
```
