# Nexus

Research pipeline packages, formerly three repos. Each package under `packages/`
keeps its own install, run, and test commands; the repo root is not an app.

- `packages/research_parser`
- `packages/research_analyst`
- `packages/research_dispatcher`
- `packages/research-store`
- `packages/research-relay`
- `packages/morning_research`

## Configuration

Shared credentials live in the repo-root `.env`; each package keeps its own
settings in `packages/<pkg>/.env` under a `RESEARCH_<PACKAGE>_` prefix.

```bash
cp .env.example .env
cp packages/<pkg>/.env.example packages/<pkg>/.env
```

See [docs/environment.md](docs/environment.md) for the naming convention, the
load order, and what belongs at the root versus in each package.
