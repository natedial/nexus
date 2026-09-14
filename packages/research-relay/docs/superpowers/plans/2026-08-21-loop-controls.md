# Loop Controls Implementation Plan

> **For agentic workers:** Implement task-by-task with TDD. No git commits unless the user asks.

**Goal:** Stamp reconstructed mail, skip/dismiss own output after Proton header rewrite, cap sends at 10/run and 20/day, and trip a Proton pending-count circuit breaker.

**Architecture:** Add `stamp.py` for the HMAC token. Extend the ledger with `send_counts` and `relay_state`. Reconstruct writes the stamp. Runner and Proton IMAP refuse stamped mail. Caps and breaker live in the runner/ledger, with a `breaker-reset` CLI.

**Tech Stack:** Python 3, pytest, SQLite ledger, existing IMAP/SMTP clients.

---

## Files

- Create: `src/research_relay/stamp.py`
- Create: `tests/test_stamp.py`
- Modify: `src/research_relay/ledger.py`
- Modify: `tests/test_runner.py` (and add `tests/test_ledger.py` if ledger tests are not already there)
- Modify: `src/research_relay/reconstruct.py`
- Modify: `src/research_relay/config.py`
- Modify: `src/research_relay/runner.py`
- Modify: `src/research_relay/proton_imap.py`
- Modify: `src/research_relay/cli.py`
- Modify: `src/research_relay/health.py`
- Modify: `tests/test_reconstruct.py`, `tests/test_config.py`, `tests/test_clients.py`, `tests/test_cli.py`
- Modify: `config.example.toml`, `README.md`
- Modify: `~/.config/research-relay/config.toml` (live knobs only)

### Task 1: Stamp helper

- [ ] Failing tests in `tests/test_stamp.py` for token stability, header/body detection, `Auto-Submitted: no` vs `auto-generated`
- [ ] Implement `src/research_relay/stamp.py`

### Task 2: Ledger day count + breaker

- [ ] Failing tests for `sent_today`, increment, local-day isolation, trip/reset
- [ ] Extend `Ledger._init` with `send_counts` and `relay_state`

### Task 3: Config defaults 10 / 2×

- [ ] Failing tests: omitted day cap is `2 * per_run`; default per_run is 10; reject `< 1`
- [ ] Update `RelayConfig` and `load_config`

### Task 4: Reconstruct writes stamp

- [ ] Failing reconstruct tests for `X-Research-Relay`, `Auto-Submitted`, body preamble line
- [ ] Add headers + preamble line; keep them through `_drop_forbidden_headers`

### Task 5: Skip rewritten Proton copies

- [ ] Failing runner test: From/Message-ID rewritten, body token present, not sent, pending cleared
- [ ] Proton classify peeks body prefix and dismisses stamped mail
- [ ] Expand `_is_own_relay_message` / `_header_is_own_relay`

### Task 6: Caps + breaker in runner

- [ ] Failing tests: 11th in a run of 10 not sent; 21st in a day of 20 not sent; unchanged `count_pending` trips; next live send blocked; dry-run does not count or trip
- [ ] Runner checks day cap before SMTP; Proton `count_pending`; trip when `after >= before` and `sent > 0`
- [ ] `RunResult.exit_code()` is 1 when breaker is open or just tripped

### Task 7: CLI, health, docs, live config

- [ ] `research-relay breaker-reset`; health check `circuit`
- [ ] Example config + README; live `max_messages_per_run = 10`, `max_messages_per_day = 20`
- [ ] `python3 -m pytest` green
