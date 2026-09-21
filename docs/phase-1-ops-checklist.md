# Phase 1 ops checklist (Mac mini — Nate)

Nexus Phase 1 removes `morning_research` and `research-store` from the monorepo.
These steps are **not** done by the agent; run on the mini when ready.

## morning_research (killed)

- [ ] Remove cron entry: `research_processing/morning_research/schedule/run_daily.sh` (Sun–Fri 06:10)
- [ ] Unload LaunchAgent if installed: `com.ncdial.morning-research.plist`
- [ ] Stop using legacy checkout `research_processing/morning_research` on branch `cursor/author-argument-prompt-split`

## research-store indexer

- [ ] Stop container `research-store-indexer-1` (`distill-index-supabase --continuous`)
- [ ] Confirm nothing depends on `parsed_research` index columns written by the indexer
- [ ] Retire `research_processing/research-store` checkout

## After repoint (Phase 0 decision 1, later)

- [ ] Analyst `ToolRegistry` loads `schemas/corpus_tool_schema.json` from Nexus
- [ ] `research_search` invocations fail loudly until Phase 2/3 canonical retrieval (expected)
