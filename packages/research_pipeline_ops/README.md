# Research Pipeline Ops

Shared operational journal and incident queue for Nexus batch jobs.

This package records run metadata in the root Nexus PostgreSQL database. It
does not replace package-owned ledgers or store research, email, highlight, or
report content.

## Install

Nexus uses `uv` with a package-local virtual environment. From the repository
root, install the package and its development dependencies with:

```bash
uv sync --project packages/research_pipeline_ops --extra dev
```

Do not install into or activate the repository-root `.venv`; it is not a Nexus
application environment and may not contain `pip`.

Set `PIPELINE_OPS_DATABASE_URL` or the shared `NEXUS_DATABASE_URL`. Producers
normally construct `PipelineOpsClient.from_env(...)` with a package-owned
SQLite spool path.

## Commands

```bash
uv run --project packages/research_pipeline_ops nexus-ops doctor
uv run --project packages/research_pipeline_ops nexus-ops check --json
uv run --project packages/research_pipeline_ops nexus-ops incidents --status open --json
uv run --project packages/research_pipeline_ops nexus-ops claim --actor codex-batch-monitor --limit 5 --json
uv run --project packages/research_pipeline_ops nexus-ops retry --incident INCIDENT_KEY --dry-run
```

Apply the root migrations before enabling producers. All initial job catalog
rows are disabled until their package adoption and canary are complete.
