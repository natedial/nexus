# Proton Drive Archive Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD. No git commits unless the user asks.

**Goal:** Enqueue Proton-native mail from the relay job and upload PDFs/Google Docs/HTML to Drive from a separate 8-hour LaunchAgent, with ledger-backed retry after `apply_sent`.

**Architecture:** Relay `run` only upserts an `archives` SQLite row. `research-relay archive` takes `archive.lock`, fetches by Message-ID from Proton sent/inbox/pending, and uploads via Drive v3 multipart HTTP. Naming/HTML helpers are pure functions. OAuth adds the Drive scope.

**Tech Stack:** Python 3, pytest, urllib, SQLite WAL, existing Proton IMAP, LaunchAgent plist.

---

## Files

- Create: `src/research_relay/archive_format.py` — filenames + HTML wrapper
- Create: `src/research_relay/drive_archive.py` — Drive v3 upload
- Create: `src/research_relay/archive_job.py` — drain incomplete rows
- Create: `tests/test_archive_format.py`
- Create: `tests/test_drive_archive.py`
- Create: `tests/test_archive_job.py`
- Create: `launchd/com.researchrelay.archive.plist`
- Modify: `src/research_relay/config.py`, `ledger.py`, `runner.py`, `proton_imap.py`, `oauth.py`, `cli.py`, `health.py`, `alerts.py`, `exceptions.py`
- Modify: `tests/test_config.py`, `test_ledger.py`, `test_runner.py`, `test_oauth.py`, `test_cli.py`, `test_clients.py`, `test_alerts.py`
- Modify: `config.example.toml`, `README.md`

### Task 1: Config

- [ ] Tests: omitted `[archive]` → `enabled=False`; `enabled=true` without folder IDs raises; `enabled=true` with `app_password` raises; oauth2 + IDs loads; `archive_lock_file` defaults beside `lock_file`
- [ ] `ArchiveConfig` on `AppConfig`; parse optional `[archive]`; `PathsConfig.archive_lock_file`

### Task 2: Filenames and HTML

- [ ] Tests: date prefix, redacted subject, 200-char PDF truncation, HTML escapes sender/subject, private address absent
- [ ] `archive_pdf_name`, `archive_doc_name`, `archive_html_name`, `archive_html_document` in `archive_format.py`

### Task 3: Ledger `archives` table

- [ ] Tests: enqueue idempotent (does not wipe Drive ids); incomplete list; record pdf/doc/html ids; completeness; find-miss → unrecoverable at 5; force-clear ids; stale vs fresh incomplete
- [ ] `ArchiveRow` + ledger methods; JSON text for id maps

### Task 4: Drive HTTP

- [ ] Tests: mocked urlopen — PDF parent/name, Doc mimeType google-apps.document, 500 → TemporaryRelayError, 401 → DriveAuthError
- [ ] `drive_archive.py` multipart upload; no google client library

### Task 5: Proton fetch-by-Message-ID

- [ ] Tests: search sent then inbox then pending; miss raises TemporaryRelayError
- [ ] `ProtonImap.fetch_by_message_id(message_id: str) -> bytes`

### Task 6: Archive drain job

- [ ] Tests: PDF then Doc; HTML when no PDF; skip complete; retry Doc only; IMAP miss increments; 5 misses unrecoverable; dry-run no Drive; `--force` re-uploads; lock overlap exit 0; no SMTP
- [ ] `archive_job.process_archives`; reconstruct + `drive_archive`

### Task 7: Relay enqueue only

- [ ] Tests: live Proton-native reconstruct enqueues, does not call Drive; Gmail-sourced does not enqueue; circuit skip still enqueues; dry-run does not enqueue
- [ ] Hook in `runner._process_one` after reconstruct

### Task 8: OAuth, CLI, health, alerts, docs

- [ ] OAuth URL includes Drive scope
- [ ] `archive` / `archive-status` CLI; `drive` alert kind; health: unrecoverable fail, incomplete <9h ok, ≥9h fail; skip Drive GET when `connect_network=False`
- [ ] Example config, README, `launchd/com.researchrelay.archive.plist` (StartInterval 28800, max-runtime 3600)
- [ ] `python3 -m pytest` green

## Spec coverage

Jobs split, enqueue-on-reconstruct, drain-by-Message-ID, artifact rules, autoreprocess, health lag, operator commands, OAuth, plist interval.
