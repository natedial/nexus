# Loop controls and send caps

Date: 2026-08-21

## Problem

Reconstructed mail can re-enter Proton `Relay/pending` after SMTP. Proton may rewrite `From` and `Message-ID`, so the existing From / `@relay.local` skip misses those copies. The ledger key is new each time, so the same content is sent again. A live LaunchAgent run every 5 minutes with `max_messages_per_run = 20` sent 460 copies while pending stayed at 55.

## Goal

Keep unattended live delivery. Make a repeat of that burst impossible:

1. Never send our own output, even after header rewrite.
2. Cap successful sends per local calendar day.
3. Trip a circuit breaker if a live Proton send does not shrink `Relay/pending`.

## Identity stamp

Every reconstructed message carries an install-specific token:

```
token = HMAC-SHA256(hmac_key, "research-relay-stamp-v1")[:16 hex]
value = v1=<token>
```

The token is constant per HMAC key, not per message. Proton rewrites Message-ID, so a per-message MAC would not match on the way back.

Place the value in three locations:

- Header `X-Research-Relay: v1=<token>`
- Header `Auto-Submitted: auto-generated`
- Last line of the existing Sender/Date body preamble: `X-Research-Relay: v1=<token>`

On intake, skip and dismiss (same path as current own-output handling: `apply_sent` + ledger `labels_updated`) if any of:

- `From` or `Reply-To` is `proton.from_address` or `proton.reply_to`
- `Message-ID` host is `relay.message_id_domain`
- `Auto-Submitted` is present and is not `no`
- `X-Research-Relay` header matches this install’s token
- Body contains `X-Research-Relay: v1=<token>`

Proton classify must peek a short body prefix when headers alone are not conclusive, so stamped copies are dismissed before they enter the send list.

Gmail intake still fetches the full message in `process_one`; the same checks apply there.

## Send caps

| Knob | Default | Rule |
|---|---|---|
| `relay.max_messages_per_run` | `10` | Must be >= 1 |
| `relay.max_messages_per_day` | `2 * max_messages_per_run` | Must be >= 1. If omitted, derive from per-run. |

Daily count is successful SMTP accepts only, keyed by the machine’s local calendar date, stored in the SQLite ledger. Hitting the cap logs a warning, stops further SMTP for the rest of that day, and leaves remaining pending mail in place. Exit 0 if nothing else failed. The count resets at the next local midnight. No manual reset.

`--max-messages` still overrides only the per-run cap.

## Circuit breaker

Applies to Proton IMAP only (stable Gmail `X-GM-MSGID` already prevents same-key resend).

After a live Proton pass that sent at least one message, `SEARCH ALL` on `Relay/pending` again. If the UID count is greater than or equal to the count from the start of that pass, trip.

While open:

- Still connect, classify, dismiss Gmail copies and own output
- Do not SMTP send
- Health reports the breaker as failed
- Live `run` exits 1

Reset is manual: `research-relay breaker-reset`. No timed auto-reset.

## Dry-run

Dry-run never increments the daily count, never trips or resets the breaker, never SMTP sends, and never changes labels.

## Errors and tests

- Own-output / stamp match: skip + dismiss. Not a failure.
- Daily cap: warning, no send, exit 0 if otherwise clean.
- Breaker open or newly tripped: error log, no SMTP, health fail, exit 1.

Required tests:

- Reconstructed mail has header token, body token, and `Auto-Submitted: auto-generated`.
- Proton rewrite (new From, new Message-ID, no `X-` header) still matches the body token and is not sent.
- 11th message in a run with cap 10 is not sent.
- 21st successful send in a day with cap 20 is not sent.
- Unchanged Proton pending count after a live send trips the breaker; the next live run sends nothing until `breaker-reset`.
- Dry-run leaves cap and breaker untouched.

## Out of scope

- Proton filter changes (recommended operationally: exclude `from_address` / `@relay.local`, but not required for this change).
- Pausing LaunchAgent `--live`.
- Changing allowlists or colleague lists.
