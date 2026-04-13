# Multi-Agent Analysis Framework Specification

**Date**: 2026-04-03  
**Status**: Revised for Implementation  
**Owner**: research_analyst

## Goal

Enable multiple specialized analysis agents that generate additional document-level outputs for different end goals, while staying consistent with the current `research_analyst` bootstrap architecture:

- deterministic analysis remains the primary pipeline
- agent outputs are additive and fault-tolerant
- bootstrap persistence remains local SQLite first
- any later publish-to-Supabase step is a separate concern

## Priority Agents

1. **Trading Opportunities**: actionable trade ideas with conviction and risk/reward
2. **Short Time Horizons**: days/weeks positioning insights
3. **Talking Points**: quotable, presentation-ready excerpts

## Current-System Constraints

This spec is intentionally aligned to the codebase as it exists on 2026-04-03:

- the main pipeline persists to the local SQLite `AnalysisStore`
- the parsed DB client is read-oriented, except for the explicit forecast upload path
- `run`, `reprocess`, and `backfill` are the existing operational entrypoints
- `HydratedParsedDocument` does not expose a dedicated `full_text` field; agent input must be assembled from parsed document payload, themes, excerpts, and deterministic analysis artifacts

## Core Design Decisions

| Decision | Value |
|----------|-------|
| Input | `HydratedParsedDocument` plus deterministic analysis artifacts already computed in `AnalyzeDocumentPipeline` |
| Storage | Local SQLite tables in `AnalysisStore` during bootstrap |
| Execution | Parallel per document with retry and per-agent timeout |
| Failure handling | Agent failures do not fail deterministic document analysis |
| Freshness key | `research_id + document_hash + analysis_version + agent_type` |
| Prompt location | Workspace-root `prompts/` directory |
| Remote publish | Out of scope for Phase 1 |

## Architecture

### Agent Registry

Canonical location: `research_analyst/src/research_analysis_layer/services/agent_registry.py`

Canonical config: `research_analyst/agent_config.yaml`

```yaml
agents:
  trading_opportunities:
    prompt: prompts/trading_opportunities.md
    model: "claude-sonnet-4-20250514"
    fallback_model: "claude-sonnet-4-20250514"
    timeout_seconds: 120
    retry_count: 3
    priority: 1
    table_name: "trading_analysis"

  short_time_horizon:
    prompt: prompts/short_time_horizon.md
    model: "claude-haiku-4-20250514"
    fallback_model: "claude-haiku-4-20250514"
    timeout_seconds: 60
    retry_count: 3
    priority: 2
    table_name: "short_time_horizon_analysis"

  talking_points:
    prompt: prompts/talking_points.md
    model: "claude-haiku-4-20250514"
    fallback_model: "claude-haiku-4-20250514"
    timeout_seconds: 60
    retry_count: 3
    priority: 3
    table_name: "talking_points_analysis"

default_model: "claude-haiku-4-20250514"
default_timeout_seconds: 60
default_retry_count: 3
```

Registry responsibilities:

- load enabled agent definitions from YAML
- resolve prompt paths relative to workspace root
- expose per-agent execution config
- expose table names for persistence
- fail fast in `doctor` when config exists but prompt files are missing

### Agent Input Contract

Agents do not receive a raw `document.full_text` field because the current document model does not provide one directly.

Instead, each agent receives a normalized input payload assembled from:

- document metadata from `HydratedParsedDocument.document`
- parser `parsed_data`
- normalized themes and excerpts
- deterministic chunks
- deterministic evidence units
- deterministic assertions

Add a small serializer, for example `AgentInputBuilder`, that produces a bounded JSON payload for the LLM.

The serializer must:

- include document metadata useful for attribution
- include theme labels, contexts, and excerpts
- include deterministic assertions and summaries when available
- cap oversized text blocks to stay within model context
- produce stable field ordering so snapshots are testable

### Output Models

Canonical location: `research_analyst/src/research_analysis_layer/models/agent_outputs.py`

Keep the existing agent-specific payload models and add a shared metadata envelope for persistence and validation.

```python
class AgentExecutionMetadata(BaseModel):
    research_id: int
    document_hash: str
    analysis_version: str
    agent_type: str
    model_requested: str
    model_used: str
    prompt_path: str
    prompt_version: str
    run_id: int
    attempt_count: int
    analyzed_at: datetime


class TradingOpportunity(BaseModel):
    thesis: str
    direction: str
    instrument: str
    timeframe: str
    conviction: str
    risk_reward_ratio: str | None
    key_levels: str | None
    rationale: str
    supporting_excerpts: list[str]
    risks: list[str]


class TradingAnalysis(BaseModel):
    metadata: AgentExecutionMetadata
    opportunities: list[TradingOpportunity]
    no_opportunity_reason: str | None
```

Apply the same `metadata` envelope to:

- `ShortTimeHorizonAnalysis`
- `TalkingPointsAnalysis`

Notes:

- keep current field constraints in `agent_outputs.py`
- `supporting_excerpts` are parser-derived quotes or faithful excerpts, not arbitrary hallucinated text
- `prompt_version` should be derived from prompt file contents, for example a SHA-256 hash

### LLM Client Contract

This repo does not currently have an agent LLM execution layer. Phase 1 must introduce an explicit boundary instead of embedding provider logic directly into the pipeline.

Add an interface such as:

```python
class AgentLlmClient(Protocol):
    def generate_structured(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, object],
        model: str,
        timeout_seconds: int,
    ) -> dict[str, object]: ...
```

Phase 1 requirements:

- initial implementation may be Anthropic-oriented because configured models are Claude models
- provider details must stay behind the client boundary
- responses must be JSON-only and parsed into Pydantic models
- retry policy applies to timeout, transport, and validation failures
- fallback model is only used after the primary model exhausts its configured attempts

Required new settings:

- `AGENT_LLM_PROVIDER`
- `AGENT_LLM_API_KEY`
- optional `AGENT_LLM_BASE_URL`
- optional `AGENT_LLM_TIMEOUT_SECONDS`

`doctor` must validate these only when agent execution is enabled.

### Storage Schema

Phase 1 storage is local SQLite in `AnalysisStore._ensure_db()`.

Do not make direct Supabase writes part of the core agent pipeline yet.

Create one table per agent to preserve agent-specific payload shape while keeping query surfaces simple.

Common columns for each table:

- `id INTEGER PRIMARY KEY AUTOINCREMENT`
- `research_id INTEGER NOT NULL`
- `document_hash TEXT NOT NULL`
- `analysis_version TEXT NOT NULL`
- `agent_type TEXT NOT NULL`
- `prompt_version TEXT NOT NULL`
- `model_requested TEXT NOT NULL`
- `model_used TEXT NOT NULL`
- `run_id INTEGER NOT NULL`
- `attempt_count INTEGER NOT NULL DEFAULT 1`
- `status TEXT NOT NULL`
- `error_type TEXT NULL`
- `error_text TEXT NULL`
- `analyzed_at TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`

Agent-specific payload columns:

- `trading_analysis.opportunities_json`
- `trading_analysis.no_opportunity_reason`
- `short_time_horizon_analysis.insights_json`
- `short_time_horizon_analysis.summary`
- `talking_points_analysis.talking_points_json`
- `talking_points_analysis.primary_headline`

Uniqueness constraint for each table:

```sql
UNIQUE(research_id, document_hash, analysis_version, agent_type)
```

This is required so that:

- rerunning the same document hash and analysis version is idempotent
- prompt/model changes can be expressed by bumping `analysis_version`
- document replacements under the same `research_id` do not overwrite older outputs silently

Optional follow-up:

- if later phases require historical reruns within one `analysis_version`, replace the unique constraint with a current-row pointer model

### Persistence Rules

Persist one row per agent execution result, including failures.

Rules:

- successful deterministic analysis may coexist with failed agent rows
- agent reruns for the same uniqueness key should upsert the row
- failures must preserve `error_type`, `error_text`, `attempt_count`, and `model_used`
- downstream review tools should be able to distinguish `success`, `no_output`, and `error`

Recommended statuses:

- `success`
- `no_output`
- `error`

### Pipeline Integration

Integrate agent execution into the existing deterministic pipeline, not as a separate orchestration system.

Execution order inside `AnalyzeDocumentPipeline.run()`:

1. quality gate
2. deterministic chunking, evidence, assertions, graph updates
3. persist deterministic analysis to local SQLite
4. execute enabled agents using the already computed deterministic artifacts
5. persist per-agent results to local SQLite
6. return a result summary that includes agent success/failure counts

Important behavior:

- deterministic analysis failure still fails the document
- agent failure does not roll back deterministic analysis
- backfill safety gates still apply before any agent execution starts

### Execution Flow

```text
RunBatchPipeline.run/reprocess/backfill
  -> AnalyzeDocumentPipeline.run(...)
     -> deterministic analysis
     -> AnalysisStore.replace_document_analysis(...)
     -> AgentExecutor.execute(
          document=document,
          chunks=chunks,
          evidence_units=evidence_units,
          assertions=assertions,
          run_id=run_id,
          analysis_version=analysis_version,
        )
        -> registry.list_agents()
        -> parallel per agent
           -> load prompt
           -> build agent input payload
           -> call AgentLlmClient
           -> validate into agent output model
           -> upsert local agent row
        -> return execution summary
```

### CLI Integration

Use existing command surfaces first.

Required behavior:

- `run` executes enabled agents by default
- `reprocess` executes enabled agents by default
- `backfill --apply` executes enabled agents by default
- `doctor` validates agent config and prompt resolution

Recommended additive flags:

```bash
python -m research_analysis_layer.main run --limit 10 --skip-agents
python -m research_analysis_layer.main reprocess --research-id 123 --agents trading_opportunities
python -m research_analysis_layer.main reprocess --research-id 123 --agent-only --agents talking_points
python -m research_analysis_layer.main backfill --date-from 2026-01-01 --apply --agents all
python -m research_analysis_layer.main list-agents
```

CLI notes:

- `list-agents` is acceptable as a utility command
- do not introduce a separate `run-agents` primary workflow for Phase 1
- `agent-only` mode must still hydrate the document and apply the same agent input builder

### Observability

Stay consistent with the existing `PipelineOpsClient` stage-event model.

Emit stage events such as:

- `analyst.agent.prepare`
- `analyst.agent.execute`
- `analyst.agent.persist`

Each event payload should include:

- `agent_type`
- `research_id`
- `document_hash`
- `model_requested`
- `model_used`
- `attempt_count`
- `status`

Do not introduce a second observability vocabulary for agents.

## Prompt Location

Shared prompts remain at workspace root:

- `prompts/trading_opportunities.md`
- `prompts/short_time_horizon.md`
- `prompts/talking_points.md`

Prompt requirements:

- explicit output schema instructions
- explicit no-hallucination instruction
- quote only from supplied context
- return valid JSON only

## Implementation Checklist

- [ ] Keep `research_analyst/agent_config.yaml` as the canonical registry config
- [ ] Keep prompt files in workspace-root `prompts/`
- [ ] Add shared `AgentExecutionMetadata` models
- [ ] Add `AgentInputBuilder`
- [ ] Add `AgentLlmClient` interface and initial provider-backed implementation
- [ ] Add agent tables to `AnalysisStore._ensure_db()`
- [ ] Add `AnalysisStore` upsert/read helpers for agent outputs
- [ ] Implement `AgentExecutor`
- [ ] Integrate `AgentExecutor` into `AnalyzeDocumentPipeline`
- [ ] Extend `RunItemResult` with agent execution summary fields
- [ ] Extend `doctor` for agent config and prompt validation
- [ ] Add CLI flags for `--skip-agents`, `--agents`, and `--agent-only`
- [ ] Add `list-agents` utility command
- [ ] Add unit tests for config loading, prompt hashing, and payload validation
- [ ] Add integration tests with mocked LLM and local SQLite persistence
- [ ] Add CLI tests for new flags and `list-agents`

## Future Phases

### Phase 2: Review and Retrieval Layer

- expose local agent outputs via review/document inspection commands
- add agent-aware review snapshots
- support filtering by agent type and status

### Phase 3: Remote Publish Layer

- introduce an explicit publish command for selected agent outputs
- add remote-table contract only after local review workflow is stable
- keep publish separate from core analysis execution

### Phase 4: Cross-Document Aggregation

- aggregate trading themes across documents
- aggregate recurring talking points
- aggregate short-horizon shifts over time

## Testing Strategy

1. **Unit tests**
   - YAML config loading
   - prompt path resolution
   - prompt-version hashing
   - Pydantic validation
   - agent input builder truncation and stability

2. **Integration tests**
   - mocked LLM responses for each agent
   - retry and fallback behavior
   - local SQLite upsert behavior
   - idempotent rerun behavior for identical `research_id + document_hash + analysis_version + agent_type`

3. **CLI tests**
   - `list-agents`
   - `--skip-agents`
   - `--agents`
   - `--agent-only`

4. **Failure-mode tests**
   - one agent fails while others succeed
   - invalid JSON from model
   - timeout on primary model followed by fallback success
   - deterministic analysis succeeds while agent persistence records an error row
