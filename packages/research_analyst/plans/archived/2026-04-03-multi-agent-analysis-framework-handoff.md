# Multi-agent analysis framework handoff

## Purpose

Capture the implementation state of the Phase 1 multi-agent analysis framework added on 2026-04-03, including what shipped, how it is wired into the current bootstrap pipeline, what was verified, and what remains before live agent execution should be used against real provider credentials.

## Current status

The Phase 1 bootstrap implementation is now in place and code-verified for the local architecture:

- agent execution is integrated into the existing deterministic `research_analyst` pipeline
- agent outputs persist locally in SQLite, not directly to Supabase
- the existing `run`, `reprocess`, and `backfill` workflows can now control agent execution
- the CLI now supports targeted agent control and agent listing
- the framework has focused test coverage for config, payload building, persistence, and CLI behavior

This is an implementation of the revised local-first spec, not a remote publish workflow.

## Completed work

### 1. Agent execution primitives

Added the core service-layer pieces required for document-level agent analysis:

- [agent_executor.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/agent_executor.py)
- [agent_input_builder.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/agent_input_builder.py)
- [agent_llm_client.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/agent_llm_client.py)

What these do:

- `AgentInputBuilder` builds a bounded JSON payload from:
  - parsed document metadata
  - parser `parsed_data`
  - normalized themes and excerpts
  - deterministic chunks
  - deterministic evidence units
  - deterministic assertions
- `AgentExecutor` resolves configured agents, executes them in parallel, validates structured outputs, and persists per-agent rows
- `AgentLlmClient` establishes an explicit provider boundary instead of embedding provider logic directly into the pipeline

### 2. Shared agent metadata model

Expanded [agent_outputs.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/models/agent_outputs.py) with `AgentExecutionMetadata`.

Persisted agent outputs now carry:

- `research_id`
- `document_hash`
- `analysis_version`
- `agent_type`
- `model_requested`
- `model_used`
- `prompt_path`
- `prompt_version`
- `run_id`
- `attempt_count`
- `analyzed_at`

This fixes the freshness/provenance gap from the earlier draft.

### 3. Local SQLite persistence for agent outputs

Extended [analysis_store.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/db/analysis_store.py) with three local agent tables:

- `trading_analysis`
- `short_time_horizon_analysis`
- `talking_points_analysis`

Each table uses the idempotency key:

- `UNIQUE(research_id, document_hash, analysis_version, agent_type)`

Common persisted fields include:

- freshness and provenance metadata
- execution status
- error fields
- attempt count
- requested and actual model names

Agent-specific payload fields include:

- `opportunities_json`
- `insights_json`
- `talking_points_json`
- summary/headline or no-opportunity fields

`analysis_run_items` was also extended with:

- `agent_success_count`
- `agent_no_output_count`
- `agent_error_count`

### 4. Pipeline integration

Integrated agents into the existing deterministic analysis path in:

- [analyze_document.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/pipelines/analyze_document.py)
- [run_batch.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/pipelines/run_batch.py)
- [main.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/main.py)

Current execution order for the normal path:

1. quality gate
2. deterministic chunking/evidence/assertions/graph work
3. local deterministic persistence
4. agent execution from deterministic artifacts
5. local per-agent persistence

Important behavior:

- deterministic analysis is still the primary success criterion
- agent failures do not fail the entire document
- `agent-only` mode can rerun agents for a hydrated document without replaying deterministic persistence

### 5. CLI controls

Added the following controls to the existing CLI:

- `--skip-agents`
- `--agents`
- `--agent-only`
- `list-agents`

Current intended usage:

```bash
python -m research_analysis_layer.main run --limit 10 --skip-agents
python -m research_analysis_layer.main reprocess --research-id 123 --agents trading_opportunities
python -m research_analysis_layer.main reprocess --research-id 123 --agent-only --agents talking_points
python -m research_analysis_layer.main list-agents
```

### 6. Config and dependency updates

Expanded [config.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/config.py) with agent settings:

- `AGENT_EXECUTION_ENABLED`
- `AGENT_LLM_PROVIDER`
- `AGENT_LLM_API_KEY`
- `AGENT_LLM_BASE_URL`
- `AGENT_LLM_TIMEOUT_SECONDS`

`doctor` now reports agent execution configuration and prompt resolution state.

Installed and recorded missing runtime dependencies in:

- [pyproject.toml](/Users/ncdial/devwork/research_processing/research_analyst/pyproject.toml)
- [uv.lock](/Users/ncdial/devwork/research_processing/research_analyst/uv.lock)

Added:

- `pydantic`
- `pyyaml`

### 7. Focused test coverage

Added [test_agents.py](/Users/ncdial/devwork/research_processing/research_analyst/tests/test_agents.py) and updated [test_backfill.py](/Users/ncdial/devwork/research_processing/research_analyst/tests/test_backfill.py) for the new method signatures.

Covered behaviors:

- agent input payload truncation and metadata inclusion
- successful agent persistence
- failed agent persistence
- `list-agents` output
- backfill flow compatibility after agent-related signature changes

## Verification completed

Focused test run completed successfully:

```bash
uv run pytest tests/test_agents.py tests/test_backfill.py tests/test_config.py tests/test_forecast_cli.py
```

Result:

- `14 passed`

## Operational notes

### What is ready now

- local agent execution framework
- local persistence and idempotent reruns
- CLI control over agent participation
- config validation and prompt-resolution reporting

### What is not ready yet

- production use with real provider credentials has not been exercised in this session
- no remote publish workflow exists for agent outputs
- review/document inspection does not yet surface agent rows
- no live Anthropic API validation was run

## Recommended next steps

1. Set real agent env vars and run `doctor`.
2. Run one narrow live test:
   - `python -m research_analysis_layer.main reprocess --research-id <id> --agent-only --agents talking_points`
3. Inspect the local SQLite agent tables after the live run.
4. Add review-harness exposure for agent outputs so results are easy to inspect locally.
5. Decide whether a later phase should publish selected agent outputs to a remote store.

## Risks and caveats

### 1. No live provider validation yet

The Anthropic-oriented client path is implemented, but this session only verified mocked execution. Expect the first real run to be the point where provider payload or response-format assumptions get tightened.

### 2. Prompt quality now matters materially

The executor assumes:

- valid JSON output
- schema-compliant payloads
- no hallucinated quotes

If prompts are weak, the framework will persist error rows rather than silently degrading. That is correct behavior, but it means prompt iteration will likely be needed before broad rollout.

### 3. The project is not currently in a git repo

At the time of this handoff, `/Users/ncdial/devwork/research_processing/research_analyst` is not under a detected `.git` root. That blocks normal `git add`, `git commit`, and `git push` from this directory unless version control is initialized or the project is moved under an existing repository.

## File summary

Primary implementation files:

- [config.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/config.py)
- [main.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/main.py)
- [analysis_store.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/db/analysis_store.py)
- [analyze_document.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/pipelines/analyze_document.py)
- [run_batch.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/pipelines/run_batch.py)
- [agent_outputs.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/models/agent_outputs.py)
- [agent_executor.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/agent_executor.py)
- [agent_input_builder.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/agent_input_builder.py)
- [agent_llm_client.py](/Users/ncdial/devwork/research_processing/research_analyst/src/research_analysis_layer/services/agent_llm_client.py)

Primary test/doc files:

- [test_agents.py](/Users/ncdial/devwork/research_processing/research_analyst/tests/test_agents.py)
- [2026-04-03-multi-agent-analysis-framework-spec.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-04-03-multi-agent-analysis-framework-spec.md)
- [2026-04-03-multi-agent-analysis-framework-handoff.md](/Users/ncdial/devwork/research_processing/research_analyst/plans/2026-04-03-multi-agent-analysis-framework-handoff.md)
