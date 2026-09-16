# Environment variables

Nexus keeps environment configuration in two layers: one shared file at the repo
root, and one file per package that owns settings of its own.

## Loading order

Every package that reads a `.env` loads the repo-root file first and its own file
second, so a package value always wins over a shared value:

```text
process environment        (highest precedence)
packages/<pkg>/.env
.env                       (repo root, lowest precedence)
```

Copy the examples once per checkout:

```bash
cp .env.example .env
cp packages/<pkg>/.env.example packages/<pkg>/.env
```

Only `.env.example` files are committed. Real `.env` files are ignored at every
level.

## Naming convention

| Name shape | Meaning | Lives in |
| --- | --- | --- |
| `SUPABASE_URL`, `GOOGLE_*`, `NOTION_*`, `OPENAI_API_KEY`, `RESEARCH_PROCESSING_ROOT` | shared: one value per service or account, used by the pipeline as a whole | repo-root `.env` |
| `RESEARCH_PARSER_*` | owned by `packages/research_parser` | that package's `.env` |
| `RESEARCH_ANALYST_*` | owned by `packages/research_analyst` | that package's `.env` |
| `RESEARCH_DISPATCHER_*` | owned by `packages/research_dispatcher` | that package's `.env` |
| `RESEARCH_STORE_*` | owned by `packages/research-store` (none needed yet) | that package's `.env` |
| `RESEARCH_RELAY_*` | owned by `packages/research-relay` | secrets file / keychain, see below |
| `MORNING_RESEARCH_*` | owned by `packages/morning_research` | that package's `.env` |

Two rules follow from the table, and they are the whole convention:

1. **Unprefixed means shared.** An unprefixed variable is a third-party
   credential or endpoint with exactly one sensible value per account, so it is
   set once at the root. Provider keys stay unprefixed even where only one
   package reads them today, because the credential belongs to the account
   rather than to the package.
2. **Prefixed means owned.** Anything a single package decides for itself —
   behaviour flags, thresholds, local paths, pacing, and per-package overrides of
   a shared service — carries that package's prefix and lives in that package's
   file.

A package that needs its own view of a shared service prefixes the override and
falls back to the shared value: `RESEARCH_ANALYST_PARSED_DB_URL` defaults to
`SUPABASE_URL`, and `RESEARCH_ANALYST_STATE_DB_PATH` defaults to
`RESEARCH_PARSER_STATE_DB_PATH`.

Where the old unprefixed name already carried a package word, the prefix
replaces it instead of stacking: `MODE` became `RESEARCH_DISPATCHER_MODE`,
`DISPATCH_INPUT_MODE` became `RESEARCH_DISPATCHER_INPUT_MODE`, and
`ANALYST_DEBATE_MODE` became `RESEARCH_ANALYST_DEBATE_MODE`.

## Migration and deprecated names

Every loader reads the prefixed name first and falls back to the pre-monorepo
unprefixed name, so an existing deployment keeps running unchanged. The
fallbacks are deprecated: new configuration should use prefixed names, and the
fallbacks can be deleted once every deployment has moved.

## What lives where

### Repo root — `.env.example`

| Variable | Consumers |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_KEY` | parser, analyst, dispatcher, store, morning_research |
| `GOOGLE_CREDENTIALS_PATH`, `GOOGLE_DRIVE_FOLDER_ID` | parser, morning_research |
| `RESEARCH_PROCESSING_ROOT` | parser, analyst, store |
| `NOTION_TOKEN`, `NOTION_DATABASE_ID`, `NOTION_AREA_PAGE_ID` | morning_research |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `DEEPINFRA_API_KEY` | dispatcher |

### `packages/research_parser/.env.example`

Drive polling and catch-up, local state and artifact paths, the MinerU fallback,
Docling OCR retry, and retry pacing. All `RESEARCH_PARSER_*`.

### `packages/research_analyst/.env.example`

Analysis and calendar stores, the upstream parser state DB, batch behaviour,
quality gates, pipeline versions, agent LLM provider and limits, round/tool/debate
switches, resolution and consensus thresholds, the Tholos client, eval captures,
and hourly-runner pacing. All `RESEARCH_ANALYST_*`.

### `packages/research_dispatcher/.env.example`

Synthesis switches, SMTP and recipients, report title, input mode and dispatch
ledger path, run mode, filters, and the feedback/document-viewer links. All
`RESEARCH_DISPATCHER_*`.

### `packages/morning_research/.env.example`

Run-state path, per-run work directory, Codex CLI settings, prefilter threshold,
and the dry-run switch. All `MORNING_RESEARCH_*`.

### `packages/research-store` — no env file

The distill tool reads only `SUPABASE_URL`, `SUPABASE_KEY`, and
`RESEARCH_PROCESSING_ROOT`, which are all shared, so this package has no `.env`
of its own. Its CLI loads the root file (and a package file if one is created).
Future store-owned settings would be `RESEARCH_STORE_*`.

### `packages/research-relay` — no env file

The relay keeps non-secret settings in `config.toml` and reads its secrets from
the macOS Keychain or a mode-600 secrets file, not from a `.env`. Its variables
(`RESEARCH_RELAY_CONFIG`, `RESEARCH_RELAY_SECRETS_FILE`,
`RESEARCH_RELAY_PROTON_PASSWORD`, `RESEARCH_RELAY_HMAC_KEY`) already follow the
prefix convention.

## Adding a variable

1. Decide whether it is shared (one value per service or account) or owned by one
   package.
2. Shared: add it to the root `.env.example` with a note about which packages
   consume it.
3. Owned: prefix it with the package prefix and add it to that package's
   `.env.example` next to its default.
4. Read it through the package's env helper so the prefixed name and its
   fallback behave consistently.
