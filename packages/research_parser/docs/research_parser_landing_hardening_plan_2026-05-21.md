# Research Parser Landing Hardening Plan

## Summary

The current `research_parser` changes are directionally sound: they introduce the first durable research-memory substrate, improve retry/resumption behavior, and add OpenAI/OpenRouter reasoning controls. Before landing, harden the diff around three risks: the OpenAI Responses structured-output bug, state-machine terminal semantics, and backfill idempotency.

This plan is intentionally scoped to landing safety. It does not roll the memory substrate into live parser writes or downstream analyst/dispatcher flows yet.

## Key Improvements

- Fix OpenAI Responses structured output.
  `_generate_openai_responses()` currently passes `response_format=` to `responses.create()`, which is a Chat Completions parameter. Convert requested structured output into the Responses API `text={"format": ...}` shape so structured extraction is preserved on the first call instead of being silently dropped by the TypeError fallback.

- Preserve structured extraction during compatibility retries.
  For OpenRouter, retry reasoning rejections by removing `extra_body.reasoning` first while keeping `response_format`; only drop `response_format` if the provider still rejects the request. This intentionally spends one extra network round-trip on the common reasoning-rejection path to avoid degrading extraction quality unnecessarily.

- Make storage terminal-state handling consistent.
  `insert_research()` is idempotent for document rows through `upsert(..., on_conflict="document_id")`; `document_hash` is only a content fingerprint for duplicate detection and unchanged-content checks. A crash before the local `storage_ok` update should not create duplicate `parsed_research` rows. Still fix the real state inconsistency: if `storage_ok=1`, either `StateStore.is_processed()` should treat the file as processed or `update_step("storage", True)` should transition to `completed`. This prevents needless retries after storage has already succeeded.

- Harden memory backfill idempotency.
  Before upserting spans/chunks, detect existing rows for the same `research_id + version + order` with different keys. Fail with a clear message unless `--replace` is explicitly set.

- Make destructive backfill replacement explicit.
  Require `--confirm-replace` alongside `--replace`, print affected row counts before deletion, and show a runtime warning that replacement must not be used after evidence/claim tables reference these rows. This warning matters because `research_evidence_units.span_key` uses `ON DELETE SET NULL`, so replacement can silently erase evidence provenance instead of failing loudly.

- Validate migration 004.
  Prefer a scratch Postgres/Supabase smoke test that actually applies migration 004 and checks table order, FK targets, unique constraints, JSON/array defaults, and compatibility with existing `parsed_research`. Use static SQL validation only as a fallback when a disposable database is unavailable.

- Expand metadata source-alias tests.
  Keep the filename-based stale metadata check, but add coverage for unknown prefixes, known aliases, and ambiguous `YYYY-MM-DD_PREFIX_...` filenames.

## Tracked Follow-Up

- Add a retrieval integrity guard for `research_retrieval_chunks.span_keys`.
  `span_keys` is a `TEXT[]` with no FK to `research_spans`, so chunks can reference nonexistent spans and span re-keying can orphan chunk references. This is not a landing blocker because live downstream retrieval is deferred, but it should be handled before retrieval consumers trust that array.

## Test Plan

- Existing targeted suite:
  `uv run pytest tests/test_research_memory_spans.py tests/test_research_memory_backfill.py tests/test_state_store.py tests/test_pipeline_resumption.py tests/test_llm_providers.py`
- New tests:
  - OpenAI Responses API sends structured output via `text.format`, not `response_format`, and receives structured output successfully.
  - LLM retry preserves JSON response format after reasoning rejection.
  - LLM retry drops JSON response format only after a second compatibility failure.
  - Storage success is treated as terminal after a simulated crash.
  - Backfill rerun succeeds with identical keys and fails on same-version key drift.
  - `--replace` requires `--confirm-replace`.
  - Migration 004 validates cleanly against a disposable database when available, with static validation as a fallback.

## Assumptions

- Scope is landing hardening only.
- Live parser writes to `research_spans` and `research_retrieval_chunks` are deferred.
- The new substrate schema remains additive and backward-compatible.
- OpenAI reasoning behavior follows the Responses API docs.
- OpenRouter reasoning behavior follows OpenRouter reasoning-token docs.
