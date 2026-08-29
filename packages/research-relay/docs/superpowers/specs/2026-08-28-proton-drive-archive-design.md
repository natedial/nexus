# Proton-native Drive archive

Date: 2026-08-28

## Problem

The Gmail Apps Script `processPDFAttachments` searched Gmail for `from:proton.me` (and other Proton domains) with attachments, saved PDFs to Drive folder `PDFs`, converted them to Google Docs in `PDFs_as_Docs`, and saved HTML when a thread had no PDF.

Proton-to-Proton mail now never reaches Gmail. research_relay drains Proton `Relay/pending`, reconstructs a new message, and sends it to colleagues. The Apps Script therefore sees nothing. Gmail-sourced candidate mail still arrives in Gmail first, but it is not `from:` Proton, so the script never archived it.

## Goal

On **Proton-native** mail only, write the same Drive artifacts the Apps Script produced, using already-redacted reconstructed content. Gmail is not a staging inbox. **SMTP to colleagues must not share a process, lock, or exit code with Drive.**

## Jobs

Two LaunchAgents, one binary, one SQLite ledger.

| Job | Label | Command | Interval | Lock | Drive | SMTP |
|---|---|---|---|---|---|---|
| Relay (existing) | `com.researchrelay.email` | `research-relay run --live --max-runtime 240` | 300s | `relay.lock` | No. Enqueue only. | Yes |
| Archive (new) | `com.researchrelay.archive` | `research-relay archive --live --max-runtime 3600` | **28800s (8 hours)** | `archive.lock` | Yes. Drain + retry. | No |

They may overlap in wall time. Separate locks so a long OCR run cannot skip a send, and a send cannot skip an archive. SQLite WAL; short transactions. Relay never opens Drive. Archive never calls SMTP and never trips the circuit breaker.

`archive.enabled = false` (or omitted `[archive]`): relay does not enqueue; the archive command exits 0 without contacting Drive. Do not load the archive plist until enabled.

Dry-run: `run --dry-run` logs “would enqueue” and does not write archive rows. `archive --dry-run` lists incomplete keys and does not FETCH or upload.

## Non-goals

- Copying or IMAP-appending mail into Gmail.
- Archiving Gmail-sourced (`X-GM-MSGID`) messages.
- Changing the Apps Script, Drive folder layout, or agent readers.
- Historical backfill of Proton mail that was sent before this feature and never given an archive row.
- Stripping PDF document metadata.
- Google client libraries; Drive calls use the existing `urllib` HTTP style.
- Calling Drive from `research-relay run`.

## Identity of Proton-native mail

A message is Proton-native when its ledger key starts with `proton:`. That key is assigned only by Proton IMAP intake.

Do **not** enqueue when:

- The source is Gmail IMAP.
- Proton IMAP classifies the message as a Gmail copy (`has_google_hops`) and dismisses it.
- The message is our own relay output (existing stamp / From / Message-ID checks).
- Reconstruct fails the domain allowlist (permanent error path).

Do **enqueue** after a successful Proton-native reconstruct even if SMTP is skipped (circuit breaker open, daily send cap). That matches the old script archiving on arrival, not on successful forward.

## Config

New optional section. Omitted section means archive is off.

```toml
[archive]
enabled = false
pdf_folder_id = ""
docs_folder_id = ""
# Max incomplete rows to fetch/upload per archive run. Defaults to 20.
max_retries_per_run = 20
# Consecutive IMAP misses before the row is marked unrecoverable (no further auto-fetch).
find_failure_threshold = 5
```

```toml
[paths]
lock_file = "/Users/YOU/Library/Application Support/research-relay/relay.lock"
archive_lock_file = "/Users/YOU/Library/Application Support/research-relay/archive.lock"
```

Rules:

- `enabled = false` (default): no enqueue, archive command is a no-op.
- `enabled = true`: both folder IDs must be non-empty Drive file IDs of the existing `PDFs` and `PDFs_as_Docs` folders. Missing IDs is a config error at load.
- `enabled = true` requires `auth.method = "oauth2"`. App-password Gmail auth cannot call Drive.
- `max_retries_per_run` and `find_failure_threshold` must be >= 1 when present.
- `archive_lock_file` defaults next to `lock_file` as `archive.lock` if omitted.

No extra convert toggle. Conversion is always on when archive is enabled.

## OAuth

Keep the existing Desktop OAuth client and token files. Both jobs may refresh the token; treat the token file as the existing single-writer refresh path (refresh then rewrite). A collision is rare at 5 min vs 8 h.

Authorization requests both scopes, space-separated:

- `https://mail.google.com/`
- `https://www.googleapis.com/auth/drive`

Full Drive scope is required so uploads can target folders the Apps Script already created. `drive.file` cannot write into those folders.

Enabling the Drive API in Google Cloud Console is a prerequisite (already done). The refresh token still needs a consent replay: `research-relay auth`. Until that runs, the **archive** job treats missing Drive scope as an auth failure. The relay job does not care.

`include_granted_scopes` stays true. `prompt=consent` stays so a new refresh token is issued with both scopes.

## Components

| Piece | Responsibility |
|---|---|
| `ArchiveConfig` | `enabled`, folder IDs, `max_retries_per_run`, `find_failure_threshold` |
| `archives` SQLite table | Queue + progress. Relay inserts. Archive job updates. Not mixed into SMTP `deliveries.status`. |
| Relay `run` | After a live Proton-native reconstruct, insert/ensure an archive row. No Drive. |
| `research-relay archive` | Drain incomplete rows: IMAP fetch by Message-ID, reconstruct, upload missing artifacts. |
| `drive_archive` module | Drive v3 multipart upload: PDF, PDF→Google Doc, HTML. |
| Proton IMAP | Fetch by stored RFC822 `Message-ID` from `Relay/sent`, then INBOX, then `Relay/pending`. Pending UID is not reused after `apply_sent`. |
| CLI | `archive` (job), `archive-status` (list). `--force --key` on `archive` re-uploads. |
| LaunchAgent | `launchd/com.researchrelay.archive.plist` — StartInterval 28800, `--max-runtime 3600`. |
| Health | Split: see Health. |

## Relay enqueue (no Drive)

On a live Proton-native reconstruct success, before SMTP (and before circuit / daily-cap skips):

If `archive.enabled` and not dry-run, upsert an `archives` row keyed by the Proton ledger key with:

- RFC822 `Message-ID` (needed after MOVE)
- Expected artifacts: sanitized PDF names, or `html` if there are no allowed PDFs
- Status incomplete if new

Idempotent: a second reconstruct of the same key does not reset Drive ids already stored.

Relay then continues SMTP/labels exactly as today. Drive HTTP errors cannot occur on this path. Relay exit code is unchanged by archive.

## Archive drain

`research-relay archive` (live):

1. Take `archive.lock` (not `relay.lock`). Exit 0 if lock held (same overlap rule as run).
2. Load incomplete, not-unrecoverable `archives` rows (cap `max_retries_per_run`).
3. For each row, `SEARCH HEADER Message-ID` in `folder_sent`, then `folder_inbox`, then `folder_pending`. Use the stored RFC822 Message-ID, not a pending UID.
4. On hit: `FETCH` full RFC822, reconstruct, upload **missing** artifacts only. No SMTP. No label changes.
5. On miss: increment find-failure count. At `find_failure_threshold`, mark unrecoverable and stop auto-fetch for that key. Typical cause: original mail had no Message-ID (`proton:uid-…` after MOVE).
6. Does not count toward the daily SMTP cap and does not read or trip the circuit breaker.

Upload rules (same artifact shape as the Apps Script):

1. Allowed reconstructed attachments whose sanitized name ends in `.pdf` (case-insensitive). Blocked or quarantined parts are not uploaded.
2. Each PDF without a stored Drive id → `pdf_folder_id`, name `{yyyy-MM-dd}_{sanitized_subject}_{filename}` (unique within the message via the existing attachment used-name set).
3. Each PDF without a Doc id → `docs_folder_id`, metadata `mimeType = application/vnd.google-apps.document`, name `{yyyy-MM-dd}_{sanitized_subject}_{stem}` (no `.pdf`). Drive v3 conversion/OCR is the metadata mimeType; do not send the v2 `convert` query flag.
4. If the expected plan is HTML: one file on `pdf_folder_id` named `{yyyy-MM-dd}_{sanitized_subject}.html`. Other non-PDF attachments are not written to Drive.

Date prefix uses the Mac mini local calendar date of the original `Date` header when parseable, otherwise the run’s local date. Subject sanitization reuses `sanitize_filename` / redaction. Names longer than 200 characters follow the Apps Script truncation rule.

HTML is **not** the original MIME HTML. Wrap the reconstructed plain body (quote-stripped, redacted) plus original sender, date, and subject in a small HTML document. Escape text for HTML. No inline images.

Archive is complete when every expected PDF has both a PDF id and a Doc id, or the HTML id exists.

Do not store attachment bytes in SQLite.

### Operator commands

- `research-relay archive-status` — incomplete and unrecoverable keys, last error, missing artifacts (PDF / Doc / HTML). No Drive writes. Does not need `--live`.
- `research-relay archive --dry-run` — list what the next drain would do.
- `research-relay archive --live` — drain (LaunchAgent).
- `research-relay archive --live --force --key proton:…` — clear stored Drive ids for that key and upload again (deleted Drive file, bad OCR). Still requires IMAP to find the message.

## Autoreprocess

Failed uploads wait for the next archive job (up to 8 hours) or an on-demand `archive --live`. The archive job always retries incomplete rows; it does not depend on `Relay/pending`. Partial success (PDF id present, Doc missing) retries conversion only.

## Errors

| Condition | Relay `run` | Archive job | Alerts / exit |
|---|---|---|---|
| Drive 5xx, timeout, rate limit | Unaffected | Temporary; retry next archive interval | Log on archive job. Archive exit 0 if only this. |
| 401, 403, token missing Drive scope | Unaffected | Operational | Archive job: live-run alert (`drive` kind), exit 1. Relay does not alert. |
| PDF upload ok, Doc conversion fails | Unaffected | Keep PDF id; retry conversion next interval | Log |
| HTML upload fails | Unaffected | Retry HTML next interval | Log |
| IMAP miss in sent/inbox/pending | Unaffected | Find-failure++; unrecoverable at threshold | Log; archive health fails while unrecoverable |
| Overlapping archive run | — | Skip, exit 0 | Same as overlapping send |
| `enabled` with empty folder IDs | Config error at load for both commands | — | Process does not start |
| `enabled` with app_password auth | Config error at load | — | Process does not start |

Logs may include Drive file ids, sanitized filenames, and HTTP status. Logs must not include access tokens, refresh tokens, or raw message bodies.

## Health

`research-relay health` always keeps existing relay checks. Archive extras apply only when `archive.enabled` is true:

- `GET` both folder IDs; mimeType must be a folder. Failure detail is HTTP class/status, not the token.
- **Unrecoverable count must be 0.**
- Incomplete count is **not** a health failure by itself (an 8 hour lag is expected). Incomplete rows whose `updated_at` (or `enqueued_at` if never attempted) is older than 9 hours (8h interval + 1h slack) **are** a health failure — the archive job is not catching up.

Health does not upload files. `archive-status` is the detailed check.

## Tests

No real Drive, Gmail, or Proton in CI. HTTP is mocked.

Required cases:

- Live Proton-native reconstruct **enqueues** an archive row and does not call Drive; Gmail-sourced does not enqueue.
- Circuit / daily-cap skip still enqueues.
- Dry-run `run` does not enqueue.
- Archive drain with a PDF uploads PDF then Doc; no SMTP.
- No PDF → one HTML upload; no Doc conversion.
- Dry-run `archive` does not call Drive.
- Same `proton:` key drained twice → second pass uploads nothing.
- Partial: PDF id present, Doc missing → only conversion is retried.
- Drive 500 on archive job → row stays incomplete; a mocked `run` in the same scenario still sends.
- Incomplete row after `labels_updated` is fetched from `Relay/sent` by Message-ID.
- IMAP miss five times → unrecoverable; further drain skips it.
- Overlap: archive lock held → archive command exit 0; relay lock is not taken.
- `archive-status` reports missing Doc vs missing PDF vs HTML.
- `--force` on a complete row uploads again (mocked).
- Health: incomplete row 1 hour old is ok; incomplete row 10 hours old fails; unrecoverable fails.
- Filename helper: date prefix, redacted subject, `.pdf` truncation at 200 characters.
- HTML helper: original sender/subject escaped; private address not present.
- Config: `enabled = true` without folder IDs raises; omitted `[archive]` loads with enabled false.
- OAuth authorization URL includes both Gmail IMAP and Drive scopes.

## Out of scope

- Backfill of Proton mail that never received an archive row.
- Uploading non-PDF allowed attachments.
- Creating the Drive folders if IDs are wrong.
- Service accounts; the user’s OAuth token is the only identity.
- Disabling or rewriting the Gmail Apps Script (it can keep running for any remaining Proton mail that still lands in Gmail).
- Tightening the 8 hour interval in the relay plist.
