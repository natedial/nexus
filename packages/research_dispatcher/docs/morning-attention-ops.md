# Morning attention ops (Proey-canonical)

Cadence: **weekdays ~06:25 America/New_York**, after the 06:10 digest.  
Does **not** change 5:55 / 6:10 tablet pushes.  
Empty day = **silent** (no reMarkable notebook, no Grok Bot ping) — same as the 6:40 handwritten pass.

## Canonical live path (no fixtures)

Proey supplies LIBRARY Research Notes **since last run** (Resource Type = Research Note only), including the **full page `body`**.  
`--library-json` runs **Gerhard body extraction** → N claim-note-v1 records per note → morning attention + handoff.

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

Zero Research Notes (or no extractable claims) → **silent**.

### `--library-json` shape (full body required)

Proey **must** supply the full page `body` (title/Description alone are scaffolding and will not extract). Optional note-level `speaker` / `publisher` when the page header lacks them.

```json
[
  {
    "title": "JPM rates morning",
    "note_id": "optional-stable-id",
    "speaker": "JPM Rates",
    "publisher": "JPMorgan",
    "body": "Speaker: JPM Rates\nPublisher: JPMorgan\n\nClaim: the Fed is done hiking this cycle\nThread: assert\n\nClaim: first cut comes in Q2\nThread: extend\nThread_target: cn-assert-gs-fed-done\nStance: earlier_cuts\nCause: cooling services -> earlier cut (supports)\n",
    "saved_at": "2026-10-05T12:00:00+00:00",
    "source_date": "2026-10-05",
    "url": "https://notion.so/..."
  }
]
```

### Gerhard extraction locks (do not reopen)

| Rule | Behavior |
| --- | --- |
| Scope | One Research Note → **N claims** from **full body** |
| `speaker` | Attributed desk/author (JPM, Barclays, …) — **never** `LIBRARY desk` |
| `publisher` | Notion LIBRARY, or source publisher when the note has one |
| `thread_role` | assert \| extend \| break from framing; **default assert** when no prior thread / no `Thread_target` |
| `stance` (side) | Only when stated (`Stance:`); otherwise **null** — no invented hawk/dove |
| Claim text | One idea **as stated** — never invent numbers |
| `support_kind` | `ingested_document_text`; `dexter_pass` null unless the note marks a live-number need |
| `cause_edges` | Only when the note **explicitly** asserts A causes B (`Cause:`); otherwise empty |
| Citation skip | `**Title:**` / `**Authors:**` / Sources rows are never speakers or claims |
| No note-level blanket | Do **not** assign one speaker to every line of a prose digest |
| Morning attention filter | “Claims that change risk into today’s prints” stays the **product surface**, not the extractor |

Prose digests (no `Claim:` markers) extract via numbered takeaways, inline `Desk: …` lines, and paper-finding bullets (`**Authors:**` → speaker; Key findings / Pass-through only).

### Local-only golden check (not in git)

Real LIBRARY digests + Proey ~11-claim diagnostic live **outside the repo** in the Project Agent Store (`internal/ma-sample51-local-only/`). Use them only to reproduce empty extraction and check speaker/idea-count shape. **Never commit or copy those bodies into `tests/` or `fixtures/`** — committed coverage uses synthetic invented desks/numbers under `fixtures/claim_notes/library_bodies/`.

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
| Body | **Required** — full Notion page body for Gerhard extraction |
| Link | https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9 |

## Env (optional / demoted)

| Variable | Role |
| --- | --- |
| `RESEARCH_DISPATCHER_MORNING_LIBRARY_JSON` | Path to Proey Research Notes JSON (live, with `body`) |
| `RESEARCH_DISPATCHER_MORNING_HANDOFF_DIR` | Default `--handoff-dir` |
| `RESEARCH_DISPATCHER_MORNING_WATERMARK` | Watermark path (advanced after each run) |
| `RESEARCH_DISPATCHER_NOTION_TOKEN` | **Demoted** — prefer `--library-json` with full body |

**Do not use** `CHAT_PING_TO` / `EMAIL_TO` / SMTP for morning-attention chat ping.

## What Nate vs Proey configure

| Who | What |
| --- | --- |
| **Proey** | Own ~6:25 ET routine; export Research Notes **with full `body`** since last run into `--library-json`; run the command above; wire handoff → reMarkable + Grok Bot 1:1 |
| **Nate** | Optional notebook title override; chat destination and placement locked above |
