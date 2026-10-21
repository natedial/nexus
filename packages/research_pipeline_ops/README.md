# Research Pipeline Ops

Shared operational journal and incident queue for Nexus batch jobs.

This package records run metadata in the root Nexus PostgreSQL database. It
does not replace package-owned ledgers or store research, email, highlight, or
report content.

## Install

Install it alongside a Nexus producer package:

```bash
python3 -m pip install -e packages/research_pipeline_ops
```

Set `PIPELINE_OPS_DATABASE_URL` or the shared `NEXUS_DATABASE_URL`. Producers
normally construct `PipelineOpsClient.from_env(...)` with a package-owned
SQLite spool path.

## Commands

```bash
nexus-ops doctor
nexus-ops check --json
nexus-ops incidents --status open --json
nexus-ops claim --actor codex-batch-monitor --limit 5 --json
nexus-ops retry --incident INCIDENT_KEY --dry-run
```

Apply the root migrations before enabling producers. All initial job catalog
rows are disabled until their package adoption and canary are complete.
