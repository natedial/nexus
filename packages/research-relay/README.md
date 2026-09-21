# Research Relay

Privacy-preserving Gmail → Proton Mail Bridge SMTP relay for a Mac mini home server.

The job selects Gmail messages labeled `Relay/pending`, rebuilds a **new** email (it does not forward or attach the original), sends that message through Proton Mail Bridge, then records success in SQLite and moves the Gmail label to `Relay/sent`.

Live SMTP submission and Gmail label changes are **off by default**. Use dry-run until you explicitly enable delivery.

## What this does not do

- It does not forward the original RFC822 message or attach a `.eml`.
- It does not copy Gmail transport or threading headers (`Received`, `Delivered-To`, `Return-Path`, `Message-ID`, `References`, `In-Reply-To`, `Authentication-Results`, `X-Google-*`, `X-Gmail-*`, and similar).
- It does not store passwords in the config file, LaunchAgent plist, source, or logs.
- Allowed attachments are metadata-scrubbed before copy (PDF document properties, image EXIF, Office Open XML `docProps`). If scrubbing is required and fails, the attachment is skipped or quarantined per `on_prohibited` — the relay does not fall back to the original bytes.

## Requirements

- macOS with Python 3.11 or newer
- Proton Mail Bridge installed, running, and signed in
- A Gmail account with IMAP enabled
- Google OAuth Desktop credentials (recommended) or a Gmail app password
- Gmail labels `Relay/pending`, `Relay/sent`, and `Relay/error` (`Relay` is the parent)
- A Gmail filter that applies `Relay/pending` to incoming candidate mail

## Install

```bash
cd /path/to/research_relay
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
mkdir -p ~/.config/research-relay \
  ~/Library/Application\ Support/research-relay \
  ~/Library/Logs/research-relay
cp config.example.toml ~/.config/research-relay/config.toml
```

Edit `~/.config/research-relay/config.toml`. Put only non-secret settings there.

Use the venv's Python in the LaunchAgent (`…/research_relay/.venv/bin/python3`) so the installed package is found.

## Gmail OAuth (recommended)

Gmail IMAP uses XOAUTH2. Proton Bridge and the HMAC key still use Keychain.

1. In [Google Cloud Console](https://console.cloud.google.com/) create a project (or reuse one).
2. Enable the **Gmail API** and the **Google Drive API**.
3. Configure the OAuth consent screen (External is required for a normal @gmail.com account). Add your Gmail address as a test user while you are setting this up.
4. Create an OAuth client ID of type **Desktop app**. A Web client will be rejected.
5. Download the JSON and save it as the `credentials_file` path (for example `~/.config/research-relay/gmail-oauth-client.json`).
6. Copy these keys into `config.toml` from `config.example.toml`:

```toml
[auth]
method = "oauth2"
credentials_file = "/Users/YOU/.config/research-relay/gmail-oauth-client.json"
token_file = "/Users/YOU/.config/research-relay/gmail-oauth-token.json"
redirect_port = 0
```

7. On the Mac mini, with a GUI session available, run:

```bash
research-relay auth --config ~/.config/research-relay/config.toml
```

That opens a browser, requests Gmail IMAP (`https://mail.google.com/`) and Drive (`https://www.googleapis.com/auth/drive`) scopes, and writes a refresh token to `token_file` with mode `600`. LaunchAgent runs use the refresh token and do not open a browser. Re-run `research-relay auth` after adding Drive so the refresh token includes both scopes.

If Google is still in **Testing**, refresh tokens can expire after 7 days. For a standing home-server job, set the consent screen to **In production**. You will see an unverified-app warning once; after you continue, the token should persist. Re-run `research-relay auth` if IMAP auth starts failing.

Do not commit `gmail-oauth-client.json` or `gmail-oauth-token.json`.

## Keychain setup

Do **not** pass `-w 'the-password'` on the command line. Omit `-w` and let `security` prompt, so the secret is not stored in shell history.

Gmail app passwords are needed only if you set `auth.method = "app_password"`. With OAuth, skip the Gmail Keychain item.

```bash
# Optional: Gmail IMAP app password (only for auth.method = "app_password")
# security add-generic-password -s "research-relay-gmail" -a "YOUR_PRIVATE_GMAIL@gmail.com" -w

# Proton Mail Bridge SMTP mailbox password (from the Bridge app, not your Proton account password)
security add-generic-password -s "research-relay-proton-smtp" -a "YOUR_PROTON_ADDRESS@proton.me" -w

# HMAC key used only to derive outgoing Message-ID values (any long random string)
security add-generic-password -s "research-relay-hmac-key" -a "hmac" -w
```

To rotate an item later, delete it in Keychain Access or with `security delete-generic-password` and add it again.

On macOS 26, `security -w` and unsigned Python often cannot read these items (`-25308` / exit 36). For a one-shot Terminal run, export (use `read -s` so the values are not stored in shell history):

```bash
printf 'HMAC key: '; read -s RESEARCH_RELAY_HMAC_KEY; echo; export RESEARCH_RELAY_HMAC_KEY
printf 'Bridge mailbox password: '; read -s RESEARCH_RELAY_PROTON_PASSWORD; echo; export RESEARCH_RELAY_PROTON_PASSWORD
```

For LaunchAgent, do **not** put those variables in the plist. Write a mode-600 file next to the config:

```bash
./scripts/write-secrets.sh
# creates ~/.config/research-relay/secrets.env
```

`research-relay` loads that file automatically. Existing environment variables still win. The file must stay `chmod 600`.

## Proton Bridge TLS certificate

Bridge uses a local certificate. Export it from Proton Mail Bridge (Settings → Advanced / certificate export; the exact UI label varies by Bridge version) to a PEM file, then set `proton.ca_file` to that path.

Certificate verification stays enabled unless you set `allow_insecure_tls = true`. That flag is localhost-only and prints a warning. Do not use it in normal operation.

Default Bridge SMTP: `127.0.0.1:1025` with implicit TLS (`proton.mode = "tls"`). IMAP stays STARTTLS on `1143`. Older Bridge builds used SMTP STARTTLS; if connect hangs then fails with `SMTPServerDisconnected`, switch `mode`.

## Gmail labels and filter

Create nested labels:

- `Relay/pending`
- `Relay/sent`
- `Relay/error`

Keep your existing filter that applies `Relay/pending` to candidate-domain mail. The relay searches All Mail with:

```
label:relay/pending -label:relay/sent -in:spam -in:trash
```

using Gmail's `X-GM-RAW` IMAP extension. Messages are fetched with `BODY.PEEK[]` so read/unread state is unchanged.

Create the same three names as **labels** (not folders) in Proton Mail. Bridge IMAP addresses them as `Labels/Relay\/pending` (the slash in `Relay/pending` is escaped). A Proton filter that applies `Relay/pending` to allowlisted senders should wait until a `research-relay` build that drains that label is running; Gmail-connection copies of the same senders also get the label and are skipped (no send) then unlabeled.

The job processes Gmail `Relay/pending` first, then Proton `Relay/pending`. Proton messages with Google `Received` hops are treated as Gmail copies.

`relay.max_age_days` limits what is sent. Gmail search adds `newer_than:Nd`; Proton-native mail older than that window is skipped. `0` disables the limit.

`relay.max_messages_per_run` defaults to 10. `relay.max_messages_per_day` defaults to twice that (20). The daily count is successful SMTP accepts on the local calendar date.

Reconstructed mail is stamped (`X-Research-Relay`, `Auto-Submitted: auto-generated`, and the same token in the Sender/Date preamble). Copies that re-enter `Relay/pending` are skipped and dismissed even if Proton rewrote `From` / `Message-ID`.

If a live Proton pass sends mail and `Relay/pending` does not shrink, the circuit breaker opens: later live runs still dismiss copies but do not send until you run `research-relay breaker-reset`. Health reports the breaker as failed while it is open.

## Commands

Dry-run (default even if you forget a flag):

```bash
research-relay run --config ~/.config/research-relay/config.toml --dry-run
```

Health check (IMAP, Bridge SMTP, config, Keychain or OAuth files, labels, SQLite; does not send mail):

```bash
research-relay health --config ~/.config/research-relay/config.toml
```

Clear a tripped circuit breaker:

```bash
research-relay breaker-reset --config ~/.config/research-relay/config.toml
```

Send a one-shot ops alert (uses `alerts.to`, never `relay.colleagues`):

```bash
# First: alerts.dry_run = true, then run this and read the log.
research-relay alert-test --config ~/.config/research-relay/config.toml
```

Drive archive for Proton-native mail (separate job; does not send):

```bash
research-relay archive-status --config ~/.config/research-relay/config.toml
research-relay archive-enqueue --config ~/.config/research-relay/config.toml --hours 48 --dry-run
research-relay archive-enqueue --config ~/.config/research-relay/config.toml --hours 48
research-relay archive-enqueue --config ~/.config/research-relay/config.toml --since 2026-08-15
research-relay archive --config ~/.config/research-relay/config.toml --dry-run
research-relay archive --config ~/.config/research-relay/config.toml --live
research-relay archive --config ~/.config/research-relay/config.toml --live --force --key 'proton:<Message-ID>'
```

`archive-enqueue` scans Proton `Relay/sent` then `Relay/pending` for native mail and writes archive rows. Use `--hours N` (default 48) or `--since YYYY-MM-DD`. It does not upload to Drive and does not require `--live`. Optional `--limit` caps new rows; omit it to enqueue every match. Then run `archive --live` to upload (still capped at `archive.max_retries_per_run` per run).

One-time Google OAuth consent (browser):

```bash
research-relay auth --config ~/.config/research-relay/config.toml
```

Tests:

```bash
python3 -m pytest
# or
./scripts/run-tests.sh
```

Live delivery is **not** enabled until both of these are true:

1. `live_delivery = true` in `config.toml`
2. `research-relay run --live`

## Outgoing message shape

- `From`: configured Proton address
- `To`: `undisclosed-recipients:;`
- Envelope recipients: `relay.colleagues` (not written as `Bcc`)
- `Reply-To`: configured Proton relay address
- `Date`: original message date when parseable
- `Message-ID`: HMAC of Gmail `X-GM-MSGID` (does not embed your Gmail address)
- Body: newest unquoted content, plain text; HTML-only mail is converted locally without fetching images or links
- Allowed attachments are copied as new MIME parts with sanitized filenames

The original sender is included as a short `Sender:` / `Date:` preamble in the body, not via Gmail transport headers.

Every case-insensitive occurrence of `relay.private_address` is replaced with `[redacted]` in the subject, body, attachment filenames, and generated descriptive text.

Sender domains are matched exactly. Optional subdomains require `allow_subdomains = true`. Names such as `candidates.edu.attacker.example` are rejected.

## After a successful send

1. SQLite ledger records SMTP acceptance, keyed by `X-GM-MSGID`
2. Gmail label `Relay/sent` is added and `Relay/pending` is removed

If SMTP succeeds but Gmail labeling fails, the next run consults SQLite, **does not resend**, and retries only the label update.

### Duplicate-delivery window

There is a short window after Proton Bridge accepts the message and before the SQLite success row is committed. If the process is killed in that window, the next run will not see a success record and may send a second copy. This is unavoidable without a remote idempotency token from the SMTP server. The ledger exists to close the much larger window between SMTP success and Gmail label updates.

## Failures

- Temporary IMAP/SMTP/network errors leave `Relay/pending` in place and retry later with bounded exponential backoff.
- After `retry.permanent_failure_threshold` failures, or on a permanent SMTP 5xx / disallowed domain, the relay applies `Relay/error` and stores a short error string in SQLite. Logs never include passwords or full private bodies.
- Overlapping LaunchAgent runs are blocked with a `fcntl` file lock. A skipped overlapping run exits 0.
- The process exits nonzero when the run had operational or temporary failures.
- Live runs notify a dedicated ops address (not `relay.colleagues`) on a new failure kind, after `alerts.cooldown_seconds` for the same kind, and on recovery. Dry-runs and overlapping skips stay silent.

## Alerts

Silent live-run failure is not acceptable. Alerts are **off** until you add an `[alerts]` block and set a recipient. They never use `relay.colleagues`.

Copy the `[alerts]` section from `config.example.toml` into `~/.config/research-relay/config.toml`, then:

1. Set `enabled = true`
2. Set `to` to a dedicated inbox you read on your phone (your own Proton address, or a carrier email-to-SMS address). Do not put colleague addresses there.
3. Optional: set `imessage_to` to your iPhone number or Apple ID if Messages is signed in on this Mac mini. That is the fallback when Bridge SMTP itself is down.
4. Keep `dry_run = true` and run `research-relay alert-test` once. Confirm the log line. Then set `dry_run = false` and run `alert-test` again so you receive one real message.
5. Reload is not required; the LaunchAgent reads config each run.

| Knob | Default | Meaning |
|---|---|---|
| `alerts.enabled` | `false` | Master switch. Omitted section = off. |
| `alerts.channel` | `email` | `email`, `imessage`, or `both`. |
| `alerts.to` | empty | Ops email via Proton Bridge SMTP (`127.0.0.1:1025`). |
| `alerts.imessage_to` | empty | Messages.app destination. Also used if email send fails. |
| `alerts.cooldown_seconds` | `21600` (6h) | Same failure kind is silent until this elapses. |
| `alerts.dry_run` | `false` | Log the payload; do not SMTP or Messages. |

Notify immediately when the live run hits a **new** kind (`oauth`, `smtp_connect`, `imap_timeout`, `max_runtime`, `circuit`, `run_failed`, `config`) or when a failing kind **recovers**. Repeat of the same kind waits for the cooldown (so a days-long OAuth HTTP 400 is not an SMS every 5 minutes).

If Bridge is restarting, the email alert may also fail. Configure `imessage_to` for that case, or read `~/Library/Logs/research-relay/relay.log`.

Twilio/SMS vendors are not required. If you later want Twilio, add an optional sender behind `alerts.channel` and keep the account SID/token in `secrets.env` (never the plist). The current channels are local: Bridge SMTP and Messages.app.

## LaunchAgent

Secrets come from `~/.config/research-relay/secrets.env` (mode 600), not from Keychain and not from this plist.

1. `./scripts/write-secrets.sh`
2. Copy `launchd/com.researchrelay.email.plist` to `~/Library/LaunchAgents/`
3. Confirm the Python path is the project venv (`…/research_relay/.venv/bin/python3`)
4. Load it:

```bash
cp launchd/com.researchrelay.email.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.researchrelay.email.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.researchrelay.email.plist
```

The interval is 300 seconds. Each run is capped at `--max-runtime 240` so a blocked IMAP/SSL read cannot hold the lock past the next interval. Proton Mail Bridge must be running. Do not put passwords in the plist.

### Drive archive agent

Proton-native reconstructs enqueue a Drive row. A second LaunchAgent drains that queue every 8 hours (`StartInterval` 28800) with `--max-runtime 3600`. It uses `archive.lock`, not `relay.lock`.

1. Set `[archive] enabled = true` and the two Drive folder IDs in `config.toml`.
2. Re-run `research-relay auth` so the token includes Drive.
3. Load the archive plist only after that:

```bash
cp launchd/com.researchrelay.archive.plist ~/Library/LaunchAgents/
launchctl unload ~/Library/LaunchAgents/com.researchrelay.archive.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.researchrelay.archive.plist
```

`research-relay health` fails on unrecoverable archive rows, or incomplete rows older than 9 hours. `archive-status` lists missing PDFs/Docs/HTML. Mail processed before archive enqueue existed can be queued with `archive-enqueue --hours 48`.

## Upgrade

```bash
cd /path/to/research_relay
git pull
source .venv/bin/activate
python3 -m pip install -e ".[dev]"
python3 -m pytest
# keep your existing config.toml and Keychain items
launchctl unload ~/Library/LaunchAgents/com.researchrelay.email.plist
launchctl load ~/Library/LaunchAgents/com.researchrelay.email.plist
launchctl unload ~/Library/LaunchAgents/com.researchrelay.archive.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.researchrelay.archive.plist
```

## Configuration notes

- `allowed_domains` must be full DNS names (`example.edu`), not a TLD like `edu`.
- `allow_subdomains` permits `mail.example.edu` when `example.edu` is listed; it does not permit suffix spoofs.
- Attachment allow/block lists are extension-based. Archives, executables, scripts, and macro-enabled Office documents are blocked in the example config.
- `on_prohibited = "quarantine"` writes skipped payloads under `quarantine_dir`; `"skip"` drops them from the outgoing message.

## Authentication

Gmail IMAP uses `auth.method = "oauth2"` by default in the example config. `research-relay auth` performs the one-time Desktop OAuth consent and stores a refresh token. Subsequent runs call IMAP `AUTHENTICATE XOAUTH2` and refresh the access token as needed.

`auth.method = "app_password"` remains available and still reads the Gmail secret from Keychain. Proton Bridge SMTP and the HMAC key always use Keychain.
