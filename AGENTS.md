# Nexus

Pipeline pieces, formerly three repos:

- packages/research_parser
- packages/research_analyst
- packages/research_dispatcher
- packages/research-relay

Rules:
- Work in the smallest package that owns the change.
- Do not refactor sibling packages unless the task spans the pipeline.
- Each package keeps its own install/run/test commands. Repo root is not an app.
- Coding agents: never run the full `packages/research_analyst` test suite unattended.
  Prefer targeted pytest paths. See `packages/research_analyst/AGENTS.md` (timeout,
  RSS / RLIMIT guardrails, opt-in `heavy` marker).
