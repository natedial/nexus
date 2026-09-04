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

## Eval Infrastructure

This repo includes an eval framework for measuring and monitoring analysis agent quality. See [`plans/2026-04-14-analysis-agent-eval-infrastructure-spec.md`](plans/2026-04-14-analysis-agent-eval-infrastructure-spec.md) for the full spec.

### Golden Dataset

Golden documents are in `evals/golden/`:
- `documents/` — Source markdown documents
- `annotations.jsonl` — Expected outputs for each document

Run validation:
```bash
pytest tests/evals/test_golden_dataset.py -v
```

### CLI Commands

Run eval on golden set:
```bash
python -m research_analysis_layer.evals run \
  --golden evals/golden/ \
  --output evals/results/ \
  --agents thesis,positioning,contrarian,synthesizer
```

Run with LLM judge:
```bash
python -m research_analysis_layer.evals run \
  --golden evals/golden/ \
  --output evals/results/ \
  --judge \
  --judge-model gpt-5-mini
```

Compare to baseline:
```bash
python -m research_analysis_layer.evals compare \
  --baseline evals/baselines/main.json
```

Export training captures:
```bash
python -m research_analysis_layer.evals export \
  --start 2026-04-01 \
  --min-confidence 0.75 \
  --output data/training_sets/april.jsonl
```

### Programmatic Usage

```python
from research_analysis_layer.evals import (
    AgentEvalRunner,
    LLMJudge,
    EvalDatabase,
    TrainingCaptureManager,
)

runner = AgentEvalRunner(
    llm_client=llm_client,
    golden_path=Path("evals/golden/"),
    output_dir=Path("evals/results/"),
    eval_db=EvalDatabase("evals/eval.db"),
    training_capture=TrainingCaptureManager(Path("evals/captures/")),
)

summary = runner.run_golden(use_judge=True)
runner.save_results(summary)
```

### Setting a Baseline

After a successful eval run, save the results as a baseline:
```python
from research_analysis_layer.evals import EvalDatabase, compute_golden_set_hash
from pathlib import Path

db = EvalDatabase("evals/eval.db")
db.save_baseline(
    baseline_name="main",
    metrics={
        "schema_validity_rate": 0.95,
        "confidence_avg": 0.82,
    },
    golden_set_hash=compute_golden_set_hash(Path("evals/golden/")),
)
```
