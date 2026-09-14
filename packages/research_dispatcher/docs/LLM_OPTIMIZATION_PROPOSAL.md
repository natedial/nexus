# LLM Load-Reduction and Model-Routing Proposal

## Scope
This proposal focuses on reducing LLM cost/latency in the synthesis pipeline and improving quality stability by moving non-generative steps to deterministic logic.

Primary integration points:
- `src/synthesizer.py`
- `src/llm.py`
- `config/models.yaml`
- `prompts/synthesis.md`
- `prompts/skills/throughline_synthesizer.md`
- `prompts/skills/callout_extractor.md`

## Current State (Observed)
- Synthesis runs either:
1. Monolithic prompt path (`_synthesize_monolithic`) or
2. Two-stage skill path (`_synthesize_with_skills`) in `src/synthesizer.py`.
- Through-line synthesis and callout extraction are both LLM-driven today.
- Current configured model usage is effectively centered on `openai:gpt-5-mini` (including skill entries in `config/models.yaml`).
- JSON cleanup/parsing exists (`_clean_json_response`), but retry/reroute behavior after malformed or weak outputs is limited.

## Highest-Impact Opportunities

### 1) Deterministic Through-line Scoring Before/Instead of LLM Selection
Current prompts ask the model to:
- pick top narratives,
- classify consensus,
- and prioritize by actionability.

Most required signals already exist in normalized inputs (`source`, `label`, `directionality`, `strength`, `conviction`, trade linkage) prepared in `_prepare_input`.

Recommended deterministic replacement:
- Cluster candidate themes by normalized label + linked trade context.
- Compute support metrics:
  - distinct supporting sources,
  - agreement vs contradiction by directionality,
  - average conviction/strength,
  - trade-actionability score.
- Assign `consensus_level` via thresholds:
  - `strong_consensus`: >=3 aligned sources with low contradiction.
  - `moderate_consensus`: 2 aligned sources with limited contradiction.
  - `mixed_views`: meaningful support on both sides.
  - `contrarian`: low-support minority view with high actionability.
- Select top 3-8 by deterministic score.

Expected impact:
- Removes one major reasoning burden from the model.
- Reduces variability and improves explainability of ranking.

### 2) Deterministic Callout Candidate Selection
Callout extraction currently uses an LLM to pick 2-4 high-signal statements.

Recommended deterministic replacement:
- Extract candidate sentences from through-line `key_insight`.
- Score each sentence using rule-based features:
  - specificity (numbers, levels, dates, named instruments),
  - attribution confidence (supporting source count),
  - divergence markers (e.g., "however", "but", "split"),
  - trade relevance keywords.
- Deduplicate by semantic key (label + instrument + direction).
- Return top 2-4, preserving source attribution.

Expected impact:
- Eliminates second-stage LLM call for most runs.
- Preserves consistency with explicit selection criteria.

### 3) Deterministic Validation Gate Before Escalation
Before accepting any LLM output, run strict validation:
- JSON schema validation for required fields and enums.
- Constraint checks:
  - through-lines count in range,
  - valid `consensus_level`,
  - no duplicate leads,
  - minimum attribution quality.

If validation fails:
- retry on same model once (cheap path),
- then escalate model tier (expensive path).

Expected impact:
- Avoids expensive re-runs on cases that can be fixed deterministically.
- Prevents malformed outputs from propagating.

## Model-Tier Routing Strategy

### Recommended Tiering
- Tier 0 (deterministic): filtering, clustering, scoring, schema checks, dedupe.
- Tier 1 (light model): short extraction/rewrite tasks only when deterministic confidence is low.
- Tier 2 (heavy model): final synthesis or difficult ambiguous cases.

### "Lighter Before Heavier" Flow (Default)
1. Run deterministic pipeline first.
2. If deterministic confidence >= threshold:
   - publish deterministic result directly, or
   - use light model for language polishing only.
3. If confidence < threshold:
   - call light model (`o1-mini`/`claude-3-5-haiku`) for intermediate synthesis.
4. If still low-confidence or invalid:
   - escalate to heavy model (`gpt-5-mini`/`gpt-5.2`/`claude-opus`).

Best fit in this codebase:
- Keep heavy model for final through-line narrative generation only.
- Move callout extraction to deterministic by default.
- Reserve light model for fallback enrichment when deterministic cues are sparse.

### "Heavier Before Lighter" Flow (Selective)
Use this only where high reasoning quality is critical upfront:
1. Heavy model generates high-quality canonical synthesis.
2. Light model performs constrained post-processing:
   - tone normalization,
   - brevity rewrite,
   - channel-specific formatting.

Best fit in this codebase:
- If production report quality is highly sensitive, keep heavy for canonical through-line text.
- Use light model for final style/format transforms instead of repeated heavy edits.

## Concrete Code Changes

### 1) Add Deterministic Scoring Module
Create `src/deterministic_synthesis.py`:
- `rank_throughlines(payload) -> list[Throughline]`
- `extract_callouts(throughlines) -> list[Callout]`
- `score_confidence(result) -> float`
- `validate_output(result) -> ValidationResult`

### 2) Integrate into Synthesizer Orchestration
Update `src/synthesizer.py`:
- Run deterministic stage immediately after `_prepare_input`.
- Add confidence gate and route decisions:
  - deterministic publish,
  - light-model augment,
  - heavy-model escalate.
- Add explicit retry policy for malformed/low-confidence responses.

### 3) Expand Model Config for Tier Chains
Update `config/models.yaml`:
- Define per-step chains, for example:
  - `throughline_synthesizer.primary: openai:o1-mini`
  - `throughline_synthesizer.fallback: openai:gpt-5-mini`
  - `throughline_synthesizer.escalate: openai:gpt-5.2`
  - `callout_extractor.mode: deterministic`
- Keep current defaults as compatibility fallback.

### 4) Extend LLM Client Routing Support
Update `src/llm.py`:
- Accept ordered model candidates per stage.
- Add reusable retry helper:
  - on parse/schema failure,
  - on confidence below threshold.

## Rollout Plan
1. Phase 1: Instrumentation and baselines
- Track per-run token cost, latency, retries, and validation failures.
- Save deterministic confidence metrics alongside outputs.

2. Phase 2: Deterministic callouts
- Replace LLM callout stage first (lowest risk).
- Compare output quality against current pipeline for 1-2 weeks.

3. Phase 3: Deterministic through-line ranking + light-first routing
- Keep heavy fallback enabled.
- Escalate only when confidence/validation triggers.

4. Phase 4: Full tier optimization
- Tune thresholds using observed precision/recall vs analyst acceptance.
- Optionally shift monolithic mode to deterministic + selective synthesis.

## Success Metrics
- 30-60% reduction in synthesis token spend.
- 20-40% reduction in end-to-end synthesis latency.
- <= current regression rate on analyst acceptance.
- Reduced output variance for identical inputs.
- Fewer malformed JSON/contract failures.

## Risks and Mitigations
- Risk: Deterministic scoring misses nuanced narrative context.
  - Mitigation: keep heavy fallback behind confidence gate.
- Risk: Rule drift as source data shape changes.
  - Mitigation: centralize thresholds in config and monitor calibration weekly.
- Risk: Over-routing to heavy model negates savings.
  - Mitigation: log escalation reasons and tune thresholds by reason code.

## Recommended Initial Defaults
- Deterministic callout extraction: enabled.
- Through-line deterministic ranking: enabled with fallback.
- Light-first model chain: enabled for through-line synthesis.
- Heavy escalation triggers:
  - schema failure,
  - confidence < 0.65,
  - contradiction density above threshold.

## Appendix: Minimal Decision Pseudocode
```python
prepared = prepare_input(records)
det_result = deterministic_rank(prepared)
det_conf = score_confidence(det_result)

if det_conf >= cfg.det_publish_threshold:
    return det_result

light_result = run_llm(stage="throughlines", tier="light", input=prepared)
if validate(light_result) and confidence(light_result) >= cfg.light_accept_threshold:
    return merge(det_result, light_result)

heavy_result = run_llm(stage="throughlines", tier="heavy", input=prepared)
return validate_or_fallback(heavy_result, det_result)
```
