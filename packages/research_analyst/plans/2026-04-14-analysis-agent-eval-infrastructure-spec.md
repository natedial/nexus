# Analysis Agent Eval Infrastructure Spec

**Status**: Draft  
**Owner**: Research Analyst Team  
**Target**: Implementation  
**Dependencies**: research_parser, research_dispatcher

---

## 1. Problem Statement

The analysis agents (thesis, contrarian, positioning, synthesizer) produce high-stakes outputs that directly feed downstream systems (dispatch batch, review harness, forecast workflow). Currently:

1. **No quality metrics** — We validate prompt structure but not output quality
2. **No regression detection** — Prompt/model changes go untested against realistic outputs
3. **No training data capture** — Successful agent outputs are not captured for fine-tuning
4. **No ground truth** — No curated dataset of expected outputs for benchmarking

This spec addresses all four gaps.

---

## 2. Architecture Overview

```
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  Analysis Pipeline  │────▶│   Eval Runner        │────▶│  Quality Tracker    │
│  (existing)         │     │  (async, post-hoc)   │     │  (SQLite)           │
└─────────────────────┘     └──────────────────────┘     └─────────────────────┘
                                    │
                                    ▼
                          ┌──────────────────────┐
                          │   Golden Dataset     │
                          │   + LLM Judge        │
                          └──────────────────────┘
                                    │
                                    ▼
                          ┌──────────────────────┐
                          │  Training Capture    │
                          │  (JSONL export)      │
                          └──────────────────────┘
```

---

## 3. Core Components

### 3.1 Golden Dataset

**Location**: `research_analyst/evals/golden/`

**Structure**:
```
evals/
├── golden/
│   ├── documents/           # Source documents
│   │   ├── doc_001_jpm_rates.md
│   │   ├── doc_002_gs_fx.md
│   │   └── ...
│   └── annotations.jsonl     # Expected outputs
```

**Annotation Schema** (`annotations.jsonl`):
```json
{
  "document_id": "doc_001",
  "document_path": "documents/doc_001_jpm_rates.md",
  "source_type": "rates|fx|equities|multi_asset|credit",
  "expected": {
    "thesis": "One paragraph summary of primary thesis",
    "key_claims": [
      {
        "claim": "Fed cuts delayed to September",
        "supporting_evidence": "verbatim quote from document",
        "confidence": 0.85
      }
    ],
    "trading_opportunities": [
      {
        "thesis": "Short 10Y at 4.25%",
        "direction": "short",
        "instrument": "10Y Treasury",
        "timeframe": "weeks",
        "conviction": "high",
        "rationale": "Term premium elevated due to supply"
      }
    ],
    "talking_points": [
      {
        "text": "Cuts more likely in Q4 than Q3",
        "context": "Based on Fed forward guidance",
        "presentation_use": "headline"
      }
    ]
  },
  "quality_notes": "Human annotator notes on edge cases"
}
```

**Source**: Documents must be sourced from existing pipeline outputs in the parsed DB — not raw PDFs. Agents operate on pre-parsed content (themes, assertions, chunks), so golden inputs must match that structure. Using raw PDFs would introduce parsing variance and measure the wrong thing.

**Selection Criteria**:
- 10 documents minimum, covering major asset classes
- Mix of: clear thesis, ambiguous thesis, data-heavy, opinion-heavy
- Include 2-3 "hard cases" where agents historically struggle

### 3.2 Eval Runner

**Location**: `research_analyst/src/research_analysis_layer/evals/runner.py`

**Interface**:
```python
class AgentEvalRunner:
    def __init__(
        self,
        llm_client: LLMClient,
        golden_path: Path,
        output_dir: Path,
    ): ...

    def run_single(
        self,
        document_id: str,
        agent_types: list[str] = ["thesis", "contrarian", "positioning", "synthesizer"],
    ) -> EvalResult: ...

    def run_golden(
        self,
        limit: int | None = None,
    ) -> EvalSummary: ...

    def compare_to_baseline(
        self,
        baseline: str | Path,  # DB baseline name (str) or path to exported JSON
    ) -> RegressionReport: ...
```

**EvalResult Schema**:
```python
@dataclass
class EvalResult:
    document_id: str
    agent_type: str
    output: dict  # Actual agent output
    expected: dict  # Golden annotation
    schema_valid: bool
    field_scores: dict[str, float]  # Per-field similarity
    confidence: float  # Weighted average of field_scores using default field weights (§3.3)
    judge_scores: dict[str, float] | None  # LLM judge scores
    judge_reasoning: str | None
    latency_ms: int
    error: str | None

@dataclass
class EvalSummary:
    total_docs: int
    schema_validity_rate: float
    field_scores: dict[str, float]  # Aggregated across docs
    confidence_avg: float
    judge_scores: dict[str, float] | None
    latency_p95_ms: int
    latency_avg_ms: int
    results: list[EvalResult]

@dataclass
class RegressionReport:
    baseline_name: str   # DB baseline name or file path (str)
    changes: dict[str, float]  # metric -> delta
    regressions: list[str]  # Metrics that dropped
    new_failures: list[str]
```

### 3.3 Field-Level Comparison

For structured comparison between actual and expected outputs:

```python
def compute_field_similarity(
    actual: Any,
    expected: Any,
    field_type: str,  # "text", "list", "structured"
) -> float:
    if field_type == "text":
        # ROUGE-L (longest common subsequence F1) — no new dependencies
        return rouge_l(actual, expected)
    elif field_type == "list":
        # Per-item fuzzy match via difflib.SequenceMatcher (threshold 0.7),
        # score = matched_items / max(len(actual), len(expected))
        return list_match_rate(actual, expected)
    elif field_type == "structured":
        # Per-field weighted score
        return structured_match_score(actual, expected)
    return 0.0
```

**Note**: No embedding/sentence-transformers dependency. Semantic evaluation is the LLM judge's job (§3.4); field-level comparison handles fast structural regression detection only.

**Confidence score** (used by training capture trigger):
```python
confidence = sum(
    field_scores[field] * weight
    for field, weight in DEFAULT_FIELD_WEIGHTS.items()
    if field in field_scores
)
```
This is the weighted average of `field_scores` using the table below.

**Default Field Weights**:
| Field | Weight | Comparison Method |
|-------|--------|-------------------|
| thesis | 0.25 | Semantic similarity |
| key_claims.claim | 0.15 | Fuzzy match |
| trading_opportunities.thesis | 0.20 | Exact match |
| trading_opportunities.direction | 0.10 | Exact match |
| talking_points.text | 0.15 | Semantic similarity |
| confidence | 0.15 | Delta threshold |

### 3.4 LLM Judge

**Location**: `research_analyst/prompts/evals/judge.md`

**Templating**: Variables use `{{variable}}` syntax, substituted via plain `str.replace()` — consistent with the existing `AgentRegistry` prompt loader and avoids a new dependency.

**Prompt Structure**:
```markdown
You are evaluating the output of an AI research analyst agent.

## Task
Compare the agent's output to the golden reference and score quality.

## Agent Output
{{agent_output}}

## Golden Reference
{{golden_output}}

## Scoring Rubric (score 0-1 each)

1. **Thesis Clarity** (0-1): Does the thesis capture the document's core argument?
2. **Claim Grounding** (0-1): Are claims supported by evidence from the source?
3. **Trading Actionability** (0-1): Are opportunities specific and executable?
4. **Talking Point Quality** (0-1): Are insights quotable and presentation-ready?
5. **Coherence** (0-1): Do thesis, positioning, and contrarian views align?

## Output Format
Return JSON:
{
  "scores": {
    "thesis_clarity": 0.0,
    "claim_grounding": 0.0,
    "trading_actionability": 0.0,
    "talking_point_quality": 0.0,
    "coherence": 0.0
  },
  "reasoning": "Brief explanation of scores",
  "errors": ["List of issues found"]
}
```

**Runner Integration**:
```python
class LLMJudge:
    def __init__(self, llm_client: LLMClient, judge_model: str): ...

    def evaluate(
        self,
        eval_result: EvalResult,
        golden_doc: dict,
    ) -> JudgeScore: ...
```

### 3.5 Training Capture Workflow

**Goal**: Capture successful agent outputs for future fine-tuning

**Location**: `research_analyst/src/research_analysis_layer/evals/training_capture.py`

**Trigger**: When `confidence >= 0.75` AND `schema_valid == true`

**Capture Schema** (JSONL):
```json
{
  "capture_id": "cap_001_2026-04-14",
  "document_id": "doc_001",
  "capture_timestamp": "2026-04-14T10:30:00Z",
  "input": {
    "document_text": "...",
    "themes": [...],
    "assertions": [...],
    "chunks": [...]
  },
  "output": {
    "thesis": "...",
    "trading_opportunities": [...],
    "talking_points": [...]
  },
  "metadata": {
    "agent_type": "synthesizer",
    "model": "claude-sonnet-4-20250514",
    "prompt_version": "v2.3",
    "latency_ms": 45000,
    "confidence": 0.82
  },
  "quality": {
    "golden_score": 0.88,  # If evaluated against golden
    "judge_score": 0.85    # LLM judge score
  }
}
```

**Storage**:
```
evals/
├── captures/
│   ├── 2026-04/
│   │   ├── captures_2026-04-14.jsonl
│   │   └── ...
│   └── index.jsonl  # Index for fast lookup
```

**`index.jsonl` schema** (one entry per capture, appended on write):
```json
{
  "capture_id": "cap_001_2026-04-14",
  "document_id": "doc_001",
  "agent_type": "synthesizer",
  "captured_at": "2026-04-14T10:30:00Z",
  "confidence": 0.82,
  "file": "captures/2026-04/captures_2026-04-14.jsonl"
}
```

**Export Command**:
```bash
# Export captures for fine-tuning
python -m research_analysis_layer.evals.training_export \
    --start 2026-04-01 \
    --end 2026-04-30 \
    --min-confidence 0.75 \
    --output fine_tuning_data.jsonl
```

---

## 4. Quality Tracking

### 4.1 Database Schema

Extend existing SQLite schema (`analysis_db_url`):

```sql
-- Table: agent_eval_runs
CREATE TABLE agent_eval_runs (
    id INTEGER PRIMARY KEY,
    run_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    evaluated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- Schema validation
    schema_valid BOOLEAN NOT NULL,
    
    -- Field-level scores
    thesis_similarity REAL,
    claims_similarity REAL,
    trades_similarity REAL,
    talking_points_similarity REAL,
    confidence_similarity REAL,
    confidence REAL,  -- Weighted aggregate of field scores (§3.3)
    
    -- LLM judge scores
    judge_thesis_clarity REAL,
    judge_claim_grounding REAL,
    judge_trading_actionability REAL,
    judge_talking_point_quality REAL,
    judge_coherence REAL,
    judge_reasoning TEXT,
    
    -- Metadata
    latency_ms INTEGER,
    model_used TEXT,
    prompt_version TEXT,
    
    UNIQUE(run_id, document_id, agent_type)
);

-- Table: training_captures
CREATE TABLE training_captures (
    id INTEGER PRIMARY KEY,
    capture_id TEXT UNIQUE NOT NULL,
    document_id TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    confidence REAL NOT NULL,
    quality_score REAL,
    
    -- Reference to full output (stored separately)
    output_path TEXT
    -- No UNIQUE(document_id, agent_type) — multiple captures over time per document are valid
);

-- Table: eval_baselines
CREATE TABLE eval_baselines (
    id INTEGER PRIMARY KEY,
    baseline_name TEXT UNIQUE NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metrics_json TEXT NOT NULL,  -- JSON of baseline metrics
    golden_set_hash TEXT NOT NULL  -- Hash of golden set used
);
```

### 4.2 Metrics Tracked

| Metric | Source | Alert Threshold |
|--------|--------|-----------------|
| schema_validity_rate | Direct | < 95% |
| thesis_similarity (avg) | Field comparison | < 0.70 |
| judge_coherence (avg) | LLM Judge | < 0.75 |
| training_captures_count | Capture | N/A (info) |
| latency_p95 | Timing | > 180s |

---

## 5. CLI Interface

### 5.1 Run Eval on Golden Set

```bash
# Run full eval suite
python -m research_analysis_layer.evals run \
    --golden evals/golden/ \
    --output evals/results/2026-04-14/

# Run specific agent only
python -m research_analysis_layer.evals run \
    --golden evals/golden/ \
    --agents thesis,synthesizer

# Include LLM judge
python -m research_analysis_layer.evals run \
    --golden evals/golden/ \
    --judge \
    --judge-model claude-haiku-4-5-20251001
```

### 5.2 Compare to Baseline

```bash
# Compare current to baseline
python -m research_analysis_layer.evals compare \
    --baseline evals/baselines/v1.0/ \
    --current evals/results/2026-04-14/

# Output regression report
# Changes in metrics, list of regressions, pass/fail status
```

### 5.3 Training Export

```bash
# Export for fine-tuning
python -m research_analysis_layer.evals export \
    --start 2026-04-01 \
    --min-confidence 0.75 \
    --output data/training_sets/analyst_april.jsonl
```

---

## 6. Integration Points

### 6.1 Async Eval Trigger

After analysis pipeline completes (post-hoc, not blocking):

```python
# In analyze_document.py or separate cron job
def schedule_async_eval(analysis: DocumentAnalysis):
    eval_runner.submit(
        document_id=analysis.document_key,
        agent_types=["synthesizer"],  # Primary output
        callback=save_eval_result,
    )
```

### 6.2 CI/CD Integration

```yaml
# .github/workflows/eval.yaml (example)
name: Agent Eval
on:
  pull_request:
    paths:
      - 'prompts/agents/**'
      - 'src/research_analysis_layer/agents/**'
jobs:
  eval:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e .
      - run: python -m research_analysis_layer.evals run --golden evals/golden/
      - run: python -m research_analysis_layer.evals compare --baseline evals/baselines/main
```

### 6.3 Alerting

```python
# Pseudocode for monitoring
def check_regression(current: EvalSummary, baseline: EvalSummary):
    regressions = []
    for metric, current_val in current.metrics.items():
        baseline_val = baseline.metrics.get(metric, 1.0)
        delta = current_val - baseline_val
        if delta < -0.10:  # 10% threshold
            regressions.append(f"{metric}: {baseline_val:.2f} -> {current_val:.2f} ({delta:.1%})")
    
    if regressions:
        alert_slack(f"Regression detected: {regressions}")
        return False
    return True
```

---

## 7. File Structure

```
research_analyst/
├── evals/
│   ├── golden/
│   │   ├── documents/
│   │   │   ├── doc_001_jpm_rates.md
│   │   │   └── ...
│   │   └── annotations.jsonl
│   ├── captures/
│   │   └── ...
│   ├── baselines/
│   │   └── ...
│   └── results/
├── src/research_analysis_layer/
│   └── evals/
│       ├── __init__.py
│       ├── runner.py          # AgentEvalRunner
│       ├── judge.py           # LLMJudge
│       ├── comparison.py      # Field similarity, regression detection
│       ├── training_capture.py
│       └── cli.py             # CLI entry point
├── prompts/
│   └── evals/
│       └── judge.md
└── tests/
    └── evals/
        ├── test_runner.py
        ├── test_judge.py
        └── test_training_capture.py
```

---

## 8. Implementation Phases

> **Note on ordering**: Phase 1 (runner) precedes Phase 2 (golden dataset) deliberately. Building the runner first validates the annotation schema in code before manual annotation work begins — avoiding reformatting 10 documents after the fact.

### Phase 1: Eval Runner (Week 1-2)
- [ ] Implement `AgentEvalRunner` class
- [ ] Implement field-level similarity functions (ROUGE-L, SequenceMatcher)
- [ ] Add CLI interface
- [ ] Write unit tests against synthetic fixtures

### Phase 2: Golden Dataset (Week 2-3)
- [ ] Create directory structure
- [ ] Select 10 representative documents from parsed DB
- [ ] Annotate expected outputs (allow 1 week for inter-annotator review cycle)
- [ ] Write validation test (output matches schema)

### Phase 3: LLM Judge (Week 2)
- [ ] Create judge prompt
- [ ] Implement `LLMJudge` class
- [ ] Integrate into runner
- [ ] Test judge consistency

### Phase 4: Regression Detection (Week 2-3)
- [ ] Add database schema
- [ ] Implement baseline storage
- [ ] Implement comparison reporting
- [ ] Add alerting hook

### Phase 5: Training Capture (Week 3)
- [ ] Implement capture trigger
- [ ] Implement JSONL export
- [ ] Add CLI export command

### Phase 6: Integration (Week 3-4)
- [ ] Add to CI/CD pipeline
- [ ] Document CLI in AGENTS.md
- [ ] Set up baseline for first release

---

## 9. Acceptance Criteria

1. **Golden set quality**: 10 annotated documents, 2+ human reviewers, inter-annotator agreement > 0.80
2. **Eval runner**: Runs full suite in < 5 minutes for 10 docs
3. **Schema validation**: Detects malformed outputs with < 1% false positive
4. **Regression detection**: Catches 10%+ drops within 1 run
5. **Training capture**: Captures > 50% of high-confidence outputs
6. **CLI usability**: All commands have `--help` and complete in < 30s

---

## 10. Open Questions

1. ~~**Judge model**~~ **Resolved**: Use `claude-haiku-4-5-20251001`. Different model family from the Sonnet agents under test; fast and cheap for high-volume eval runs.
2. **Golden set refresh**: How often to update golden set? (Recommend: quarterly)
3. **Capture retention**: How long to keep training captures? (Recommend: 90 days)
4. **False positive tolerance**: What's acceptable false positive rate for schema validation?
