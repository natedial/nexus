# Repository Guidelines

## Project Structure & Module Organization

This repository now contains both planning documents and the bootstrap `research_analysis_layer` implementation. Planning content lives in [`plans/`](/Users/ncdial/devwork/research_processing/research_analyst/plans), while the Python package lives under [`src/research_analysis_layer/`](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer) with tests in [`tests/`](/Users/ncdial/devwork/research_processing/research_analyst/tests).

Use clear, date-prefixed filenames for new specs when they describe a concrete proposal, for example:

- `plans/2026-03-22-theme-link-enrichment-spec.md`
- `plans/2026-03-22-theme-normalization-migration-plan.md`

Keep one topic per file. If a document depends on external repos, link to the exact file paths referenced by the plan.

## Build, Test, and Development Commands

Typical contributor commands:

- `rg --files plans src tests` lists planning and implementation files.
- `python -m research_analysis_layer.main doctor` checks config and upstream connectivity.
- `python -m research_analysis_layer.main run --limit 5` runs one local batch.
- `PYTHONPATH=src python3 -m unittest discover -s tests` runs the unit test suite.
- `uv run pytest` runs tests in the project environment.

If tooling is added later, update this section with the canonical commands rather than ad hoc alternatives.

## Coding Style & Naming Conventions

Write in Markdown with short sections, explicit headings, and direct prose. Prefer sentence case inside sections and keep bullets flat and scannable. Use backticks for repo names, paths, table names, CLI commands, and schema fields such as `research_theme_links`.

For plan files:

- use `YYYY-MM-DD-topic-name.md`
- prefer `-spec.md` for design contracts
- prefer `-plan.md` for execution/migration documents

## Testing Guidelines

Use the automated tests for implementation changes and editorial validation for plan changes.

For code changes:

- run `PYTHONPATH=src python3 -m unittest discover -s tests`
- run `uv run pytest` when the project environment is available

For plan changes:

- verify links and paths point to real locations
- check dates, ownership boundaries, and schema names for consistency
- reread plans for contradictions with adjacent docs in [`plans/`](/Users/ncdial/devwork/research_processing/research_analyst/plans)

When proposing implementation details, include acceptance criteria and concrete example commands or queries where useful.

## Commit & Pull Request Guidelines

Git history is not available in this workspace, so no commit convention can be inferred from local history. Use concise, imperative commit titles such as `Add theme linker contributor guide` or `Clarify dispatcher migration assumptions`.

Pull requests should include:

- a short summary of the planning change
- impacted documents and neighboring systems
- open questions or unresolved assumptions
- screenshots only if the change affects rendered documentation elsewhere

## Architecture Notes

The active codebase implements the analysis layer between `research_parser` and `research_dispatcher`. Keep new code and plans aligned with those ownership boundaries: parser owns normalized extraction, this repo owns chunk/assertion/graph/forecast analysis, and dispatcher consumes downstream outputs.
