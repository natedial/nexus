# Parser Backlog Recovery Notes - 2026-05-04

## Situation

The dispatcher PDF was sparse because `parsed_research` was stale, not because the dispatcher query was wrong. The dispatcher correctly queried recent unsynthesized rows, but the parser had only successfully stored a small number of May-dated documents.

Current parser state at the time of this note:

- May-dated local parser rows: `26`
- Completed May rows: `4`
- Failed May rows: `22`
- `parsed_research` rows for `2026-04-30` through `2026-05-04`: at least `4` after the latest successful batch item
- Active detached batch: `tmux` session `qwen_may_batch3`
- Active batch log: `data/reprocess_qwen_may_batch3.log`

The recent parser failures were mostly caused by the old extraction config:

- Theme extraction pointed at an unavailable Anthropic model (`claude-3-5-haiku-20241022`).
- Trade extraction used Groq `openai/gpt-oss-120b`, which failed on request size / TPM limits.
- Failed rows did not reach storage, so they never appeared in `parsed_research`.

## What We Changed

The active parser config now routes structured extraction through OpenRouter Qwen models:

- `themes` primary: `qwen/qwen3-235b-a22b-2507`
- `themes` fallback: `qwen/qwen3-30b-a3b-instruct-2507`
- `trades` primary: `qwen/qwen3-235b-a22b-2507`
- `trades` fallback: `qwen/qwen3-30b-a3b-instruct-2507`
- `boilerplate` / `metadata`: `openai/gpt-oss-20b:free`

We also added `scripts/reprocess_failed_state.py`, which force reprocesses failed local state rows by `file_name` glob. This is currently the main recovery tool.

## Model Findings

### Kimi

`moonshotai/kimi-k2.6` is not a good fit for this parser path right now.

Observed behavior:

- OpenRouter charged/ran work, but the final answer often did not reach `message.content`.
- Raw response showed useful text in `message.reasoning`, `finish_reason=length`, and `message.content=null`.
- The parser correctly treated this as `Empty model response`.

Conclusion: avoid Kimi for strict structured extraction until we redesign the call pattern or output handling.

### MiniMax

`minimax/minimax-m2.7` can return valid final JSON, but it is too slow to clear the backlog as the primary model.

Observed behavior:

- Single chunk probe returned valid JSON in `message.content`.
- Full extraction runs progressed but were slow.
- On backlog work it sometimes returned empty chunks and had to fall back.

Conclusion: viable as a fallback or quality benchmark, not ideal as primary for bulk parser recovery.

### DeepSeek Flash

`deepseek/deepseek-v4-flash` was faster but unreliable on OpenRouter shared routing.

Observed behavior:

- Malformed JSON on structured extraction.
- Upstream `502` backend errors.
- Upstream `429` rate limits from shared providers.
- It eventually completed one document, but only after retries and fallback behavior.

Conclusion: not stable enough as primary via the shared OpenRouter route. It may be worth revisiting with BYOK/provider-specific routing.

### Qwen

`qwen/qwen3-235b-a22b-2507` is the best candidate tested so far.

Observed behavior:

- Completed the very large Citi euro rates document:
  - Text length: `114,972`
  - Theme chunks: `13`
  - Themes: `12`
  - Trades: `30`
  - Stored as `research_id=5250`
- Completed the smaller JPM ECB/BoE document:
  - Text length: `15,310`
  - Theme chunks: `3`
  - Themes: `12`
  - Trades: `10`
  - Stored as `research_id=5251`
- It can still produce malformed JSON on a chunk, but the retry wrapper recovered in the large-document test.

Conclusion: Qwen is viable for parser recovery. It is not fast on very large documents, but it is the best balance of cost, reliability, and structured-output behavior seen so far.

## Current Operational Commands

Check the active 3-document recovery batch:

```bash
tmux has-session -t qwen_may_batch3
tail -f data/reprocess_qwen_may_batch3.log
```

Check May parser state:

```bash
sqlite3 data/state.db "select status,count(*) from processed_files where file_name glob '2026-05-*' group by status;"
```

Preview rows available to the dispatcher:

```bash
cd /Users/ncdial/devwork/research_processing/research_dispatcher
.venv/bin/python reset_synthesized_range.py 2026-04-30 2026-05-04 --preview
```

Run the next bounded parser recovery batch:

```bash
cd /Users/ncdial/devwork/research_processing/research_parser
tmux new-session -d -s qwen_may_batchN "cd /Users/ncdial/devwork/research_processing/research_parser && PYTHONUNBUFFERED=1 PYTHONPATH=. .venv/bin/python scripts/reprocess_failed_state.py --name-glob '2026-05-*' --limit 3 2>&1 | tee data/reprocess_qwen_may_batchN.log"
```

## Proposed Next Steps

1. Let `qwen_may_batch3` finish.

   Do not start another parser batch while this is running. We want to avoid self-inflicted provider throttling and keep logs easy to reason about.

2. After each batch, record three numbers:

   - Completed May rows in `data/state.db`
   - Failed May rows in `data/state.db`
   - `parsed_research` rows in the dispatcher preview window

3. Continue with detached batches of `--limit 3`.

   This is a reasonable balance between throughput and debuggability. The large Citi euro rates document took about 33 minutes by itself; smaller documents can complete in minutes.

4. When May completed rows reach a useful threshold, regenerate the dispatcher PDF:

   ```bash
   cd /Users/ncdial/devwork/research_processing/research_dispatcher
   DATE_RANGE_DAYS=4 .venv/bin/python generate_pdf_only.py
   ```

5. Fix state hygiene bugs after the backlog is moving:

   - `mark_completed` should clear stale `error_message`.
   - Successful step updates should clear that step's stale error text, or the error model should become structured per-step state instead of one string.

6. Improve structured-output resilience:

   - Add a targeted JSON repair retry before falling back to another model.
   - If a chunk is all legal/disclaimer/table metadata, return an explicit empty-theme object deterministically instead of asking the model to produce a long audit note.
   - Add logging for chunk index success counts so progress is easier to monitor.

7. Consider reducing very large document pressure:

   - Route chart/table-heavy sections away from theme extraction when they contain no prose.
   - Consider larger chunk sizes only after confirming model context/cost behavior.
   - Consider a per-document timeout and automatic continuation strategy.

8. If Qwen remains too slow, test one paid/stable model for large docs only.

   Candidate criteria:

   - Non-reasoning / final-content model.
   - Strong JSON mode.
   - Low malformed-output rate.
   - Stable paid route, not shared free capacity.

   The current evidence says free/shared routes are the main operational risk.

## Working Recommendation

Keep Qwen as the primary parser recovery model for now and process the backlog in small detached batches. Once the May backlog is mostly stored in `parsed_research`, rerun dispatcher PDF generation and evaluate report quality. Do not spend more time on Kimi or free DeepSeek routes for this recovery unless the goal changes from clearing the backlog to model benchmarking.
