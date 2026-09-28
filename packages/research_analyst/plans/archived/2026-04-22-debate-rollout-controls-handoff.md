# Debate Rollout Controls — Handoff

## Purpose

Capture the implementation state of the debate rollout controls (Option B of the
debate roadmap), completed 2026-04-22. All 10 plan tasks are implemented, tested,
committed, and green. This doc is the handover for the next session.

## Roadmap context

The debate pipeline was built in three sequential options:

| Option | Work | Status |
|--------|------|--------|
| A | Eval trigger/capture infrastructure | Complete |
| B | Debate rollout controls (`off`/`shadow`/`on`) | **Complete — this session** |
| C | Argument-level evals (Task 8 from debate plan) | Not started |

Option C is the natural next step. Spec reference: the "Non-Goals" section of
`docs/superpowers/specs/2026-04-19-debate-rollout-controls-design.md` explicitly
defers argument-level evals to a separate spec.

---

## What shipped in this session

### 1. Settings (`config.py`)

Three new fields on `Settings`, resolved from env vars in `from_env()`:

| Field | Env var | Default |
|-------|---------|---------|
| `analyst_debate_mode` | `ANALYST_DEBATE_MODE` | `"off"` |
| `analyst_debate_judge_model` | `ANALYST_DEBATE_JUDGE_MODEL` | `None` |
| `analyst_max_debate_arguments` | `ANALYST_MAX_DEBATE_ARGUMENTS` | `8` |

`validate()` rejects unknown modes and non-positive `max_debate_arguments`.

### 2. Shadow table (`analysis_store.py`)

New `shadow_document_analysis` table with idempotency key
`(research_id, document_hash, analysis_version, run_id, variant)`. Indexed on
`debate_session_id`. Two new accessors: `write_shadow_document_analysis` and
`load_shadow_document_analysis`.

### 3. RoundExecutor rollout primitives (`services/round_executor.py`)

- `RolloutStats` dataclass: per-process counters for shadow observability
  (shadow_runs_total, shadow_failures_total, shadow_debate_truncated_total,
  per-mode token/duration totals).
- Constructor extended: `debate_mode`, `debate_judge_model`, `max_debate_arguments`.
- `off` mode: rounds with `writes_forum_state: true` are skipped entirely.
- `_apply_argument_cap(forum_context)` trims arguments and drops orphaned relations.
- `_apply_judge_model_override(agent_specs)` replaces adjudicator model when set.
- `run_baseline_synthesis(...)` runs the synthesizer with no forum context and
  records baseline token/duration counters.

### 4. Shadow dual-write path (`pipelines/analyze_document.py`)

In `shadow` mode, after the debate chain:
1. If debate chain returned `None`: increment `shadow_failures_total`, skip shadow
   write, still run baseline (document never fails due to debate failure).
2. If debate chain succeeded: write debate output to `shadow_document_analysis`,
   run baseline synthesis, write baseline as authoritative `document_analysis`.

`_emit_shadow_log(...)` writes a structured JSON line to stderr with event
`shadow_run_complete` per completed shadow document.

### 5. CLI wiring + doctor output (`main.py`)

`build_app` passes debate settings to `RoundExecutor`. `_print_rollout_stats`
signature:

```python
def _print_rollout_stats(round_executor, *, settings: Settings | None = None) -> None
```

Always prints `debate_mode=<mode>`. In `shadow`/`on` modes also prints:

```
rollout_stats: shadow_runs=... shadow_failures=... debate_tokens_total=...
               baseline_tokens_total=... debate_avg_ms=... baseline_avg_ms=...
```

When `round_executor` is `None` (no LLM credentials configured), falls back to
printing the mode from `settings` so `doctor` is never silent about rollout state.

### 6. Operations runbook (`docs/operations/debate-rollout.md`)

Covers: mode table, companion env vars, kill switch, promotion workflow,
observability, failure semantics, recovery. Canonical operator reference for
running the rollout.

### 7. Test coverage

24 new tests across 5 files, all green (303 total suite passes):

| File | Tests |
|------|-------|
| `tests/test_settings_debate_mode.py` | 4 |
| `tests/db/test_shadow_document_analysis.py` | 3 |
| `tests/services/test_round_executor_rollout.py` | 10 |
| `tests/pipelines/test_analyze_document_shadow.py` | 3 |
| `tests/test_doctor_rollout.py` | 4 |

---

## Commit log (this session)

```
ea12f6f  chore: add .gitignore and remove tracked generated/secret files
6a99192  feat(doctor): always surface debate_mode even when round_executor is absent
92303a2  feat(main): wire debate settings into RoundExecutor and add doctor rollout stats
bd2887f  feat(pipeline): shadow dual-write path with debate-failure isolation
da6d176  feat(round_executor): add debate_mode/RolloutStats and off-mode skip
b68a606  feat(store): add shadow_document_analysis table and accessors
aada033  feat(config): add analyst_debate_mode/judge_model/max_arguments settings
```

---

## Current branch state

- Branch: `main`, in sync with `origin/main` (pushed as of 2026-04-22).
- All tests green. `ruff` clean. No mypy in this project.
- `.gitignore` now covers: `.env`, `__pycache__/`, `*.pyc`, `*.egg-info/`,
  `data/analysis.db`, `.pytest_cache/`.

---

## Open items

### 1. Orphaned file — resolved

`src/research_analysis_layer/db/_debate_review_patch.py` is absent from the repo.
This open item is closed.

### 2. Option C — argument-level evals

The next planned workstream. This was explicitly out of scope for the rollout
controls spec. No design doc or plan exists yet for Option C; a spec will need to
be written before implementation.

Relevant context:
- The `shadow_document_analysis` table (written in shadow mode) is the primary
  data source for offline quality comparison.
- The `RolloutStats` counters and `shadow_run_complete` stderr log lines are the
  live observability surface.
- Argument-level evals likely involve inspecting `debate_arguments`,
  `debate_scores`, and `debate_verdicts` tables — the
  `_load_debate_session_for_review` method in the orphan file may be a draft
  toward this.

---

## Key files

| File | Role |
|------|------|
| `src/research_analysis_layer/config.py` | Settings with debate mode fields |
| `src/research_analysis_layer/main.py` | CLI wiring, `_print_rollout_stats` |
| `src/research_analysis_layer/db/analysis_store.py` | `shadow_document_analysis` table and accessors |
| `src/research_analysis_layer/services/round_executor.py` | `RolloutStats`, argument cap, judge model override, baseline synthesis |
| `src/research_analysis_layer/pipelines/analyze_document.py` | Shadow dual-write path, failure isolation, `_emit_shadow_log` |
| `docs/operations/debate-rollout.md` | Operator runbook |
| `docs/superpowers/specs/2026-04-19-debate-rollout-controls-design.md` | Approved design spec |
| `docs/superpowers/plans/2026-04-20-debate-rollout-controls-plan.md` | 10-task TDD implementation plan |
