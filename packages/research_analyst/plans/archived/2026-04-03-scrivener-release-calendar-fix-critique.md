# Critique: 2026-04-03 Scrivener Release Calendar Fix Handoff

> **Note:** This is a code-verified critique of the handoff plan, not an implementation plan.
> Code references checked against `services/scrivener/src/fetchers/fred.py` and related files.

---

## What the Plan Gets Right

The core diagnosis is accurate and well-evidenced:

- **Single-page fetch confirmed.** `fetch_releases()` (line 232) and `fetch_release_dates()` (line 251) each make one `httpx.Client.get()` call with no pagination. `_api_request()` returns `response.json()` and never reads response headers.
- **Weak deletion guard confirmed.** The only guard before deletion (line 384) is `if desired_dates_by_release:` — it checks that _something_ was fetched, not that the fetch was complete. A partial result clears valid future rows for any release that appeared in the truncated set.
- **Read-path auto-sync risk confirmed.** `ReleaseQuery._auto_sync_release_calendar()` fires whenever a query returns empty. It calls `fetcher.sync_release_calendar()` which orchestrates `sync_releases()` then `sync_release_dates()`. Phase 0's recommendation to address the read-path trigger is valid.
- **ISM and Retail Sales are true coverage gaps.** `RELEASE_NAME_PATTERNS` in `calendar.py` maps only: CPI, PPI, NFP, JOLTS, Claims, GDP, PCE, FOMC. No ISM Manufacturing. No Retail Sales. These are confirmed absent from Scrivener's normalization layer.
- **Phase 0 → 1 → 2 → 3 sequencing is sound.** Contain deletion before fixing pagination before adding integrity checks before recovery.

---

## Issues Requiring Correction

### 1. Primary failure mode is insertion miss, not deletion

The plan frames the Employment Situation gap as a "destructive sync" that deleted a previously-valid row. The code evidence suggests the opposite is more likely.

The deletion loop (lines 384–398) is scoped to:
1. Only releases whose IDs appear in `desired_dates_by_release.keys()`
2. Only dates in `[today, today + days_ahead]`

If Employment Situation's April 3 date was on the second page of FRED results and never fetched, then:
- April 3 was **never inserted** into `release_dates`
- If Employment Situation appeared in the truncated result with other dates present, deletion would have **removed** a pre-existing April 3 row
- If Employment Situation did not appear at all in the truncated result, deletion would not touch it

The stored dates `2026-01-09`, `2026-03-06`, `2026-06-05` strongly suggest Employment Situation _did_ appear in the fetch (those dates were preserved) but April 3 was cut off at the page boundary. This means April 3 was likely **deleted** (it existed, appeared in `desired_dates_by_release` for that release, but April 3 wasn't in the fetched set for that release).

**Practical implication:** The fix still needs pagination and a completeness guard. The framing just needs adjustment — the deletion guard should protect individual release date sets, not just the whole fetch.

---

### 2. Content-Range evidence is misattributed to FRED

The plan cites `Content-Range: 0-999/1005` as evidence that FRED pagination cut off the response. This header format is **PostgREST/Supabase's** range header, not FRED's.

FRED's API returns pagination metadata in the **JSON body** (`count`, `limit`, `offset` fields), not response headers. The current `_api_request()` implementation never reads headers at all — `response.json()` is returned directly.

The `Content-Range: 0-999/1005` observation was almost certainly from a Scrivener API call (e.g., `/releases/upcoming` proxied through PostgREST) not from a direct FRED call. This doesn't invalidate the pagination concern — FRED does truncate at its default `limit` — but the pagination fix should use FRED's `limit`/`offset` query parameters and inspect the JSON body `count` field, not response headers.

**Practical implication:** Phase 1 implementation guidance should specify: loop incrementing `offset` until `len(page_results) < limit`, using FRED's `limit` query param (default 1000, max 1000).

---

### 3. Phase 4 target table is architecturally wrong

The plan suggests extending `economic_events` as the canonical analyst-facing calendar. The actual table schema (from `src/db/models.py` lines 149–172) makes clear this is the wrong home:

```python
class EconomicEvent(Base):
    __tablename__ = "economic_events"
    extraction_agent_id: Mapped[str]   # populated by an extraction agent
    run_id: Mapped[str]                # run provenance
    consensus: Mapped[str | None]      # analyst forecast, not a scheduled event
    actual_result: Mapped[str | None]  # post-release result
```

`economic_events` stores _extracted events from research documents_ — consensus estimates, actual results, agent provenance. It is not a source-of-truth calendar. Extending it to serve as a canonical release schedule would mix two fundamentally different data lineages.

The plan is correct that a new canonical layer is needed. It should be a **new table** (`calendar_events` or `canonical_releases`), not an extension of `economic_events`. The plan's "or extend `economic_events`" option should be dropped.

---

### 4. Scheduler regex patterns are not shared infrastructure

The plan says to "avoid keeping critical normalization logic only as regexes embedded in scheduler code" and implies these patterns could serve the analyst. They cannot today — `RELEASE_NAME_PATTERNS` in `calendar.py` is consumed only by `ReleaseCalendar`, which serves the APScheduler. The analyst pipeline has no code path to this normalization.

This doesn't change the recommendation, but the plan's framing suggests lifting existing patterns is an option. It isn't without architectural work to expose them. The patterns would need to be redesigned into a shared layer — they can serve as a starting vocabulary, not as ready-to-use infrastructure.

---

### 5. `fetch_releases()` pagination is low priority

The plan recommends paginating both `fetch_releases()` and `fetch_release_dates()` with equal weight. FRED has roughly 700 releases — well within a single-page response. The high-risk endpoint is `releases/dates`, which returns one row per upcoming date across all releases and is the one that produced the 1005-row overflow.

Phase 1 should prioritize paginating `fetch_release_dates()`. `fetch_releases()` pagination is a hygiene fix but not the live blocker.

---

## Missing Nuances

### Days-ahead window bounds deletion exposure

The `sync_release_dates(days_ahead=90)` call bounds deletion to `[today, today+90days]`. Dates beyond that window survive regardless of fetch completeness. The June 5 Employment Situation date persisted precisely because it was outside a 90-day window at sync time.

This matters for recovery planning (Phase 3): after fixing pagination and running a clean resync, the `days_ahead` value used for the recovery sync must be large enough to cover all affected dates. Using the default 90-day window may leave gaps if Employment Situation had additional future dates beyond that horizon.

### The scheduler depends on this data too

The plan notes this in the evidence section (§5) but does not incorporate it into the fix priority. `ReleaseCalendar` reads from `release_dates` to schedule ingestion. A sparse calendar doesn't just block analyst matching — it degrades Scrivener's own ingestion cadence. This strengthens the case for Phase 0 urgency.

---

## Recommended Adjustments to the Plan

| Section | Current wording | Suggested adjustment |
|---|---|---|
| Root cause | "deletes future rows based on incomplete snapshot" | Add: "more specifically, deletes rows for releases that appeared in the truncated result but whose individual date set was incomplete" |
| Evidence §4 | Content-Range from FRED | Clarify: this header is from PostgREST, not FRED. FRED pagination uses `limit`/`offset` in the JSON body. |
| Phase 1 | "paginate both fetch_releases and fetch_release_dates" | Prioritize `fetch_release_dates` as the live blocker; `fetch_releases` is hygiene |
| Phase 1 impl | No pagination mechanism specified | Specify: FRED uses `limit` + `offset` params; loop until `len(page) < limit` |
| Phase 3 | "run a manual Scrivener release sync" | Specify `days_ahead` large enough to cover all needed future dates (120+) |
| Phase 4 | "extend economic_events or add a dedicated table" | Drop the `economic_events` option; that table stores extracted document events, not scheduled releases |

---

## Overall Assessment

The plan is a solid diagnosis. The core bug is real, the evidence is valid, and the phased remediation sequence is correct. The two issues that matter most for implementation:

1. **FRED pagination uses `limit`/`offset` JSON params** — the fix writer needs this detail or will implement incorrectly
2. **`economic_events` is the wrong Phase 4 target** — this should be resolved now before architectural work begins, not after Phase 3

Everything else is clarification or reprioritization, not contradiction.
