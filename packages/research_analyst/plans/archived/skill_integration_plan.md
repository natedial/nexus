# Skill Integration Plan: Two-Stage Synthesis Pipeline

## Overview

This plan details how to refactor `src/synthesizer.py` to replace the monolithic `prompts/synthesis.md` with a two-stage pipeline using existing skills:
1. `skills/throughline-synthesizer/` - Stage 1: Extract through-lines
2. `skills/callout-extractor/` - Stage 2: Extract callouts

---

## Architecture Design

### Current vs. Proposed Flow

**Current (Monolithic):**
```
themes + trades --> [Single LLM Call with synthesis.md] --> through_lines + callouts
```

**Proposed (Two-Stage):**
```
themes + trades --> [Stage 1: throughline-synthesizer] --> through_lines
                            |
                            v
               [Stage 2: callout-extractor] --> callouts
```

### Key Design Decisions

1. **Feature Flag:** `USE_SKILL_PIPELINE` environment variable (default: `false`) controls whether to use the new pipeline or fall back to monolithic prompt.

2. **Skill-Specific Model Configs:** Each stage can use a different model/settings via `config/models.yaml`.

3. **Error Handling:** If Stage 1 fails, abort synthesis. If Stage 2 fails, return through-lines with empty callouts.

4. **Prompt Loading:** Create prompt files that incorporate skill references into LLM-consumable prompts.

---

## Implementation Steps

### Step 1: Create Skill Prompts

Create new prompt files that the LLM can consume:

**File: `prompts/skills/throughline_synthesizer.md`**
```markdown
# Role & Objective
{include: prompts/components/role_objective_rates.md}

# Through-Line Selection
{include: skills/throughline-synthesizer/references/throughline_rubric.md}

# Synthesis Guidance
{include: skills/throughline-synthesizer/references/synthesis_guidance.md}

# Attribution Rules
{include: skills/throughline-synthesizer/references/attribution_rules.md}

# Task
Extract 3-8 through-lines from the provided themes and trades.

For each through-line provide:
- lead: One-line summary (max 25 words)
- supporting_sources: Array of source names
- consensus_level: "strong_consensus" | "moderate_consensus" | "mixed_views" | "contrarian"
- supporting_themes: Array of theme labels
- supporting_trades: Array of trade descriptions
- key_insight: Synthesis paragraph (max 120 words)

# Output Format
Return exactly one JSON object:
{
  "title": "Synthesis title",
  "through_lines": [...]
}
```

**File: `prompts/skills/callout_extractor.md`**
```markdown
# Role
You extract high-signal callouts from synthesized market insights.

# Callout Rubric
{include: skills/callout-extractor/references/callout_rubric.md}

# Task
Given the through-lines below, extract 2-4 quotable callouts.

Each callout must:
- Be 20-50 words, standalone
- Include specific instruments, timeframes, or levels
- Reference the source through-line

# Output Format
Return exactly one JSON object:
{
  "callouts": [
    {
      "text": "...",
      "source_through_line": "lead of the through-line",
      "source": "Attributed sources"
    }
  ]
}
```

---

### Step 2: Update `config/models.yaml`

Add skill-specific model configurations:

```yaml
synthesis:
  # Legacy monolithic synthesis (kept for fallback)
  provider: openai
  model: gpt-5.2
  max_tokens: 16000
  temperature: 0
  extended_thinking:
    enabled: true
    budget_tokens: 10000

# NEW: Skill-specific configurations
skills:
  throughline_synthesizer:
    provider: anthropic
    model: claude-opus-4-5-20251101
    max_tokens: 8000
    temperature: 0
    extended_thinking:
      enabled: true
      budget_tokens: 8000

  callout_extractor:
    # Lighter model for extraction task
    provider: anthropic
    model: claude-sonnet-4-20250514
    max_tokens: 4000
    temperature: 0
```

---

### Step 3: Update `config.py`

Add new configuration flag:

```python
# Synthesis pipeline toggle
USE_SKILL_PIPELINE = os.getenv('USE_SKILL_PIPELINE', 'false').lower() in ('true', '1', 'yes')
```

---

### Step 4: Update `src/llm.py`

Add function to load skill-specific configs:

```python
def load_skill_config(skill_name: str, config_path: Path | None = None) -> ModelConfig:
    """Load model configuration for a specific skill."""
    path = config_path or CONFIG_PATH

    with open(path) as f:
        data = yaml.safe_load(f)

    skills = data.get("skills", {})
    skill_data = skills.get(skill_name)

    if not skill_data:
        # Fallback to synthesis config if skill not defined
        logger.warning("Skill config not found for %s, using synthesis config", skill_name)
        return load_model_config(config_path)

    return ModelConfig.from_dict(skill_data)
```

---

### Step 5: Refactor `src/synthesizer.py`

Main changes to the Synthesizer class:

```python
class Synthesizer:
    """Performs cross-document synthesis using LLM."""

    def __init__(
        self,
        anthropic_api_key: str | None = None,
        openai_api_key: str | None = None,
        use_skill_pipeline: bool = False,
    ):
        self.client = LLMClient(...)
        self.use_skill_pipeline = use_skill_pipeline

        # Load configs
        self.synthesis_config = load_model_config()
        self.monolithic_prompt = _load_prompt()

        # Skill configs (lazy-loaded)
        self._throughline_config = None
        self._callout_config = None

    def synthesize(self, documents: list[dict]) -> SynthesisResult | None:
        """Route to skill pipeline or monolithic based on flag."""
        input_data = self._prepare_input(documents)

        if self.use_skill_pipeline:
            return self._synthesize_with_skills(input_data, len(documents))
        else:
            return self._synthesize_monolithic(input_data, len(documents))

    def _synthesize_with_skills(self, input_data: dict, doc_count: int) -> SynthesisResult | None:
        """Two-stage synthesis using skills."""

        # Stage 1: Extract through-lines
        print("  Stage 1: Extracting through-lines...")
        stage1_result = self._stage1_throughlines(input_data)

        if stage1_result is None:
            return None

        through_lines = stage1_result.get("through_lines", [])

        # Stage 2: Extract callouts
        print("  Stage 2: Extracting callouts...")
        callouts = self._stage2_callouts(through_lines)

        if callouts is None:
            callouts = []  # Graceful degradation

        # Post-process
        self._normalize_through_lines(through_lines)
        self._normalize_callouts(callouts, through_lines)

        return SynthesisResult(
            title=stage1_result.get("title", "Cross-Document Synthesis"),
            document_count=doc_count,
            through_lines=through_lines,
            callouts=callouts,
        )

    def _stage1_throughlines(self, input_data: dict) -> dict | None:
        """Stage 1: Extract through-lines from themes and trades."""
        try:
            raw = self.client.generate(
                config=self.throughline_config,
                system=self.throughline_prompt,
                user=json.dumps(input_data),
            )
            return json.loads(_clean_json_response(raw))
        except Exception as e:
            print(f"  Stage 1 error: {e}")
            return None

    def _stage2_callouts(self, through_lines: list[dict]) -> list[dict] | None:
        """Stage 2: Extract callouts from through-lines."""
        try:
            raw = self.client.generate(
                config=self.callout_config,
                system=self.callout_prompt,
                user=json.dumps({"through_lines": through_lines}),
            )
            return json.loads(_clean_json_response(raw)).get("callouts", [])
        except Exception as e:
            print(f"  Stage 2 error: {e}")
            return None
```

---

### Step 6: Update Callers

**`main.py` and `generate_pdf_only.py`:**

```python
synthesizer = Synthesizer(
    anthropic_api_key=Config.ANTHROPIC_API_KEY,
    openai_api_key=Config.OPENAI_API_KEY,
    use_skill_pipeline=Config.USE_SKILL_PIPELINE,  # NEW
)
```

---

### Step 7: Update `.env.example`

```bash
# Synthesis pipeline configuration
ENABLE_SYNTHESIS=true

# Use skill-based two-stage pipeline instead of monolithic prompt
# false = single LLM call with prompts/synthesis.md
# true = two-stage: throughline-synthesizer -> callout-extractor
USE_SKILL_PIPELINE=false
```

---

## Error Handling Strategy

| Stage | Failure Mode | Behavior |
|-------|--------------|----------|
| Stage 1 | API error, JSON parse error, empty through-lines | Return `None`, synthesis fails, falls back to per-document aggregation |
| Stage 2 | API error, JSON parse error | Return through-lines with empty callouts, report still generated |
| Both | Skill prompts missing | Use monolithic fallback |

---

## Migration Path

1. **Phase 1: Add Infrastructure** (No behavior change)
   - Add skill prompt files
   - Add config entries
   - Add `USE_SKILL_PIPELINE` flag (default: false)

2. **Phase 2: Implement Pipeline** (Flag-gated)
   - Refactor synthesizer.py
   - Test with `USE_SKILL_PIPELINE=true` in debug mode

3. **Phase 3: Validation**
   - Run both pipelines, compare output quality
   - Adjust skill prompts based on results

4. **Phase 4: Gradual Rollout**
   - Enable for specific filter combinations first
   - Monitor error rates and output quality

5. **Phase 5: Default Enable**
   - Change default to `USE_SKILL_PIPELINE=true`
   - Keep monolithic as fallback

---

## Files to Create/Modify

### New Files
- `prompts/skills/throughline_synthesizer.md` - Stage 1 prompt
- `prompts/skills/callout_extractor.md` - Stage 2 prompt

### Modified Files
- `src/synthesizer.py` - Main refactor (add skill pipeline methods)
- `src/llm.py` - Add `load_skill_config()` function
- `config.py` - Add `USE_SKILL_PIPELINE` flag
- `config/models.yaml` - Add skill-specific model configs
- `.env.example` - Document new flag
- `src/main.py` - Pass new flag to Synthesizer
- `generate_pdf_only.py` - Pass new flag to Synthesizer

---

## Testing Strategy

### Unit Tests
1. Test `_stage1_throughlines()` with mock LLM responses
2. Test `_stage2_callouts()` with mock LLM responses
3. Test error handling for both stages
4. Test fallback behavior

### Integration Tests
1. Run full pipeline with real API calls
2. Compare output quality: monolithic vs skill pipeline
3. Measure latency difference (two calls vs one)

### A/B Testing
1. Run both pipelines in parallel (debug mode)
2. Compare through-line quality scores
3. Compare callout specificity
