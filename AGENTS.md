# Nexus

Pipeline pieces, formerly three repos:

- packages/research_parser
- packages/research_analyst
- packages/research_dispatcher
- packages/research-store
- packages/research-relay
- packages/morning_research

Rules:
- Work in the smallest package that owns the change.
- Do not refactor sibling packages unless the task spans the pipeline.
- Each package keeps its own install/run/test commands. Repo root is not an app.
