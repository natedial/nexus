# LLM Workflow Migration

This document records the current synthesis stack, why we moved to it, and what changed from the earlier single-model workflow.

## Current Canonical Workflow

When `USE_SKILL_PIPELINE=true`, the cross-document synthesis path is:

1. Stage 1A extractor:
   `deepinfra:moonshotai/Kimi-K2-Instruct-0905`
2. Stage 1A fallback:
   `openai:gpt-5-mini`
3. Stage 1A secondary fallback:
   `deepinfra:MiniMaxAI/MiniMax-M2.5`
4. Stage 1B editor:
   `openai:gpt-5-mini`
5. Stage 2 callouts:
   `openai:gpt-5-mini`

The intended happy path is:

1. Kimi extracts the first-pass through-lines.
2. GPT-5 mini edits those through-lines for readability, consensus framing, and schema discipline.
3. GPT-5 mini extracts report callouts from the edited through-lines.

Fallbacks only apply when an earlier stage fails.

## Why We Migrated

The original stage-one approach depended too heavily on a single model handling the full corpus payload and producing polished final through-lines in one pass.

That created three problems:

1. Through-lines were often too loose.
   They grouped adjacent observations instead of surfacing a real narrative spine tied to collected themes.

2. Trade ideas ran on too long.
   Stage-one outputs frequently mixed thesis, rationale, and execution into one blob instead of a short executable trade expression.

3. DeepInfra model behavior was model-specific.
   The OpenAI-compatible API worked, but non-instruct and instruct models behaved differently enough that one generic request shape was not reliable.

## Prompt and Synthesis Changes

We tightened the through-line contract so the system now prefers:

- consensus as the framing layer
- fractures inside consensus as the main source of edge
- contrarian views only when they attack a load-bearing assumption
- concise supporting trades
- explicit `consensus_anchor` for every through-line

We also added a shared market-analysis meta-lens so synthesis asks:

- where consensus exists and breaks
- which signposts would flip a view
- which risks are underweighted
- where time horizons conflict
- where policy, geopolitics, and market structure intersect

## DeepInfra Lessons Incorporated

### Instruct models

`moonshotai/Kimi-K2-Instruct-0905` works best with:

- `response_format: {type: json_object}`
- no extra agentic flags by default
- a compact stage-one request shape on larger corpora

### Non-instruct / agentic-style models

`moonshotai/Kimi-K2.5` and `MiniMaxAI/MiniMax-M2.5` work better with:

- compact payloads
- lean prompts
- smaller requested output surface
- `response_format: {type: json_object}` first
- retry path without `response_format`
- DeepInfra compatibility defaults such as `tool_choice="none"` and `reasoning_effort="none"` when relevant

These models are viable only in compact stage-one mode. They are not the preferred primary path.

## Why Kimi Extractor + GPT Editor Won

On small and medium subsets, the models split naturally by role:

- `Kimi-K2-Instruct-0905` was faster and sharper.
  It surfaced more direct PM-style views, better first-pass trade framing, and stronger “what matters now” language.

- `gpt-5-mini` was the better editor.
  It produced cleaner consensus framing, better readability, and more polished causal synthesis.

The hybrid path produced the best combined result:

- Kimi finds the sharp draft
- GPT turns it into a cleaner, more publication-ready synthesis

Latency is higher than Kimi alone, but this is acceptable for a batch job run every few days.

## Tuned Stage-One Request Shape

The live Kimi primary now uses compact request shaping from `config/models.yaml`:

- `prompt_profile: lean`
- `throughline_count: 4`
- `max_key_insight_words: 100`
- `max_supporting_themes: 4`
- `max_supporting_trades: 1`
- `payload_theme_limit: 24`
- `payload_trade_limit: 8`

This compact shape matters.

Without it, Kimi and other DeepInfra models were more likely to:

- time out
- return incomplete JSON
- emit degenerate objects
- overrun the output budget

## Stage-One Normalization Layer

We added a normalization pass before downstream use so model drift does not break the pipeline.

The normalizer now:

- coerces non-canonical `consensus_level` labels back to the expected enum
- converts string or object `supporting_trades` into short trade-expression arrays
- normalizes stringified source/theme fields into lists
- prevents single-source items from being treated as strong consensus
- preserves the same schema for downstream editor and callout stages

This is especially important for DeepInfra non-instruct outputs.

## Fallback Order Rationale

### Primary: `Kimi-K2-Instruct-0905`

Chosen because it offers the best speed-to-insight ratio and works well as the first-pass extractor.

### First fallback: `gpt-5-mini`

Chosen because it remains the most reliable and comprehensive full-payload model.

### Secondary fallback: `MiniMax-M2.5`

Kept as a compact-mode fallback because it became viable after tuning, but it is not preferred over GPT-5 mini.

## Comparison Summary

High-level ranking from the migration tests:

### Final-output quality

1. `gpt-5-mini`
2. `Kimi-K2-Instruct-0905`
3. `MiniMax-M2.5`
4. `Kimi-K2.5`

### PM-style edge / sharpness

1. `Kimi-K2-Instruct-0905`
2. `gpt-5-mini`
3. `Kimi-K2.5`
4. `MiniMax-M2.5`

### Current recommendation

- Use Kimi instruct for extraction
- Use GPT-5 mini for editing and callouts
- Use GPT-5 mini as first fallback
- Keep MiniMax as secondary fallback

## Operational Notes

If future behavior degrades, check these first:

1. `config/models.yaml`
   Ensure the compact Kimi settings are still present.

2. `src/synthesizer.py`
   Confirm stage 1A uses config-driven payload caps and prompt shaping, and stage 1B editor remains enabled.

3. `src/llm.py`
   Confirm DeepInfra request construction still applies the compatibility ladder.

4. `compare_stage1_profiles.py`
   Use this to rerun the tuned profile comparison on live subsets.

5. `smoke_test_deepinfra.py`
   Use this for fast isolated provider checks.

## Files Most Relevant To This Migration

- `config/models.yaml`
- `src/synthesizer.py`
- `src/llm.py`
- `src/stage1_profiles.py`
- `compare_stage1_profiles.py`
- `compare_subset_models.py`
- `smoke_test_deepinfra.py`
- `prompts/skills/throughline_synthesizer.md`
- `prompts/skills/throughline_editor.md`
- `prompts/skills/callout_extractor.md`
