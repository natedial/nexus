# Morning attention ops (Proey-canonical)

Cadence: **weekdays ~06:25 America/New_York**, after the 06:10 digest.  
Does **not** change 5:55 / 6:10 tablet pushes.  
Empty day = **silent** (no reMarkable notebook, no Grok Bot ping) — same as the 6:40 handwritten pass.

## Merge path (#49)

**Merge #49 alone** (it already contains #48’s ops wiring). Then **close #48**. Do **not** roll back #48. Do **not** reopen the SMTP delivery path.

## Canonical path (Proey-owned)

Proey’s weekday ~6:25 routine (same connector family as 5:55 / 6:10):

1. Run morning attention with local handoff delivery → markdown + one-line Grok Bot ping artifacts  
2. Push the notebook via the **same reMarkable connector** the 5:55 and 6:10 routines already use  
3. Send the **one-line Grok Bot chat ping** to **Nate’s 1:1 chat with Proey** — same place as the 5:55 and 6:10 pings (**not** SMTP email / inbox)

### Locked delivery destinations (Proey)

| Channel | Default |
| --- | --- |
| **Grok Bot chat ping** | Nate’s **1:1 chat with Proey** (same destination as 5:55 / 6:10 pings) |
| **reMarkable notebook title** | `Morning Attention YYYY-MM-DD` (unless Nate overrides) |
| **reMarkable placement** | **Next to** the G10 Calendar and Research From notebooks — **own** notebook, **not** folded into those pushes |

```bash
cd packages/research_dispatcher
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --argument-map-json fixtures/claim_notes/argument_map_documents.json \
  --library-json /path/to/library_research_notes.json \
  --handoff-dir /path/to/morning-attention-handoff
```

Handoff dir contents (non-silent day):

| File | Role |
| --- | --- |
| `morning-attention.md` | Own-surface notebook for reMarkable connector |
| `notebook-title.txt` | Default: `Morning Attention YYYY-MM-DD` |
| `chat-ping.txt` | One-line Grok Bot ping → Nate↔Proey 1:1 |
| `handoff.json` | Manifest (`silent`, point_count, channel_chat=`grok_bot`, fold-in flags false) |

Silent day: `handoff.json` with `"silent": true` — **no** markdown, **no** chat-ping file, **no** connector push.

## LIBRARY inputs

| Item | Rule |
| --- | --- |
| Filter | Resource Type = Research Note only |
| Window | Saved **since last run** (watermark), not last-night-only |
| Link | https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9 |

Prefer Proey injecting Research Notes via `--library-json` (already filtered). Optional live Notion reader remains available but is **not** the primary ops path.

## Env (optional / demoted)

| Variable | Role |
| --- | --- |
| `RESEARCH_DISPATCHER_MORNING_HANDOFF_DIR` | Default `--handoff-dir` |
| `RESEARCH_DISPATCHER_MORNING_WATERMARK` | Since-last-run watermark path |
| `RESEARCH_DISPATCHER_NOTION_TOKEN` | **Demoted** — only if Proey wants in-process Notion fetch |
| `RESEARCH_DISPATCHER_GROK_BOT_PING_URL` | **Optional** webhook; default is handoff file for Proey connector |
| `RESEARCH_DISPATCHER_REMARKABLE_PUSH_URL` | **Demoted** — Proey connector is canonical |

**Do not use** `CHAT_PING_TO` / `EMAIL_TO` / SMTP for morning-attention chat ping.

## Host cron / launchd

**Demoted.** Prefer Proey’s owned 6:25 routine. `schedule_morning_attention.sh` and `launchd/…` are fallback samples only — do not invent a second tablet push schedule.

## What Nate vs Proey configure

| Who | What |
| --- | --- |
| **Proey** | Own the ~6:25 ET weekday routine; wire handoff → reMarkable connector (place notebook **next to** G10 Calendar / Research From) + Grok Bot ping to **Nate’s 1:1 with Proey** (same as 5:55/6:10); supply LIBRARY Research Notes since last run |
| **Nate** | Optional override of notebook title (default `Morning Attention YYYY-MM-DD`); otherwise destinations are locked above |

## Dry run (no secrets)

```bash
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --argument-map-json fixtures/claim_notes/argument_map_documents.json \
  --dry-run --fake-delivery
```
