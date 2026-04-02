# Synthesis Depth Overhaul Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the synthesis pipeline from compressed summaries into analyst-grade through-lines with deep evidence, cited analysis, and high-conviction-only trade filtering.

**Architecture:** Seven coordinated changes across config, prompts, synthesizer logic, formatter, and config.py. Stage 1A moves to GPT-5-mini full profile for depth. Stage 1B/1C/1D get relaxed constraints. A new evidence enrichment step feeds full context to the analyst stage. Trades are filtered to High conviction by default via a new env var.

**Tech Stack:** Python, YAML config, Markdown prompts, ReportLab PDF

---

### Task 1: Switch Stage 1A to GPT-5-mini Full Profile + Increase key_insight Budget

**Files:**
- Modify: `config/models.yaml:17-36` (throughline_synthesizer section)
- Modify: `prompts/synthesis.md:87` (key_insight word cap)
- Modify: `prompts/skills/throughline_synthesizer.md:85,110` (key_insight word cap)

- [ ] **Step 1: Update `config/models.yaml` throughline_synthesizer to GPT-5-mini full profile**

Replace the `throughline_synthesizer` block:

```yaml
  throughline_synthesizer:
    # Stage 1 primary: GPT-5-mini with full prompt for analyst-grade depth
    provider: openai
    model: gpt-5-mini
    max_tokens: 16000
    temperature: 0
    request_timeout_seconds: 120
    max_retries: 0
    prompt_profile: full
    max_key_insight_words: 300
    max_supporting_themes: 6
    max_supporting_trades: 2
```

Key changes:
- Provider: `deepinfra` -> `openai`
- Model: `Kimi-K2-Instruct` -> `gpt-5-mini`
- max_tokens: `1400` -> `16000`
- prompt_profile: `lean` -> `full`
- max_key_insight_words: `100` -> `300`
- max_supporting_themes: `4` -> `6`
- max_supporting_trades: `1` -> `2`
- Removed: `response_format`, `drop_response_format_on_retry`, `payload_theme_limit`, `payload_trade_limit` (full profile doesn't need these caps)

- [ ] **Step 2: Demote Kimi to first fallback, keep existing fallback chain**

Replace `throughline_synthesizer_fallback`:

```yaml
  throughline_synthesizer_fallback:
    # Stage 1 fallback: Kimi instruct (was primary, now fallback)
    provider: deepinfra
    model: moonshotai/Kimi-K2-Instruct-0905
    max_tokens: 1400
    temperature: 0
    request_timeout_seconds: 90
    max_retries: 0
    retry_backoff_seconds: 2
    response_format:
      type: json_object
    drop_response_format_on_retry: false
    prompt_profile: lean
    throughline_count: 4
    max_key_insight_words: 100
    max_supporting_themes: 4
    max_supporting_trades: 1
    payload_theme_limit: 24
    payload_trade_limit: 8
```

Keep `throughline_synthesizer_secondary_fallback` unchanged (MiniMax stays as last resort).

- [ ] **Step 3: Increase key_insight cap in `prompts/synthesis.md`**

Change line 87 from:
```
7. **key_insight**: Structured synthesis (max 120 words) covering:
```
to:
```
7. **key_insight**: Structured synthesis (max 300 words) covering:
```

- [ ] **Step 4: Increase key_insight cap in `prompts/skills/throughline_synthesizer.md`**

Change line 110 from:
```
      "key_insight": "Synthesis paragraph (max 120 words) covering the narrative, agreement, disagreement, mechanism, and implications"
```
to:
```
      "key_insight": "Synthesis paragraph (max 300 words) covering the narrative, agreement, disagreement, mechanism, and implications with source-attributed citations"
```

Also update line 85 synthesis guidance to encourage depth:
```
Keep insights concise and specific to rates, macro, or cross-market flows.
```
becomes:
```
Develop each insight with enough depth to explore both sides of the argument. Cite specific sources by name when attributing claims. Explain the causal chain and the conditions under which the view would break. Be specific to rates, macro, or cross-market flows.
```

- [ ] **Step 5: Commit**

```bash
git add config/models.yaml prompts/synthesis.md prompts/skills/throughline_synthesizer.md
git commit -m "feat: promote GPT-5-mini as Stage 1A primary, increase key_insight to 300 words"
```

---

### Task 2: Remove 100-Word Cap from Stage 1B Editor

**Files:**
- Modify: `prompts/skills/throughline_editor.md:79`

- [ ] **Step 1: Update the editor word cap**

Change line 79 from:
```
5. Keep `key_insight` under 100 words
```
to:
```
5. Preserve the depth and source citations in `key_insight` — tighten prose without compressing substance
```

- [ ] **Step 2: Commit**

```bash
git add prompts/skills/throughline_editor.md
git commit -m "feat: remove 100-word key_insight cap from throughline editor"
```

---

### Task 3: Pass Full Context + Excerpts to Stage 1C Analyst

**Files:**
- Modify: `src/synthesizer.py:1014` (`_build_analysis_payload` method)

- [ ] **Step 1: Remove context truncation and include excerpts**

In `_build_analysis_payload`, change the evidence-building loop (around line 1010):

```python
                for theme in theme_index.get(label, [])[:3]:
                    evidence.append({
                        "source": self._clean_text(theme.get("source")),
                        "document": self._truncate_text(theme.get("document", ""), 72),
                        "context": self._truncate_text(theme.get("context", ""), 220),
                        "strength": self._clean_text(theme.get("strength")),
                        "confidence": self._clean_text(theme.get("confidence")),
                    })
```

to:

```python
                for theme in theme_index.get(label, [])[:3]:
                    entry = {
                        "source": self._clean_text(theme.get("source")),
                        "document": self._truncate_text(theme.get("document", ""), 72),
                        "context": theme.get("context", ""),
                        "strength": self._clean_text(theme.get("strength")),
                        "confidence": self._clean_text(theme.get("confidence")),
                    }
                    excerpts = theme.get("excerpts")
                    if excerpts and isinstance(excerpts, list):
                        entry["excerpts"] = excerpts[:5]
                    directionality = theme.get("directionality")
                    if directionality and isinstance(directionality, dict):
                        entry["directionality"] = directionality
                    evidence.append(entry)
```

Key changes:
- `context`: removed `_truncate_text(..., 220)` — full context flows through
- Added `excerpts` passthrough (up to 5 verbatim quotes)
- Added `directionality` passthrough (bullish/bearish signal)

- [ ] **Step 2: Commit**

```bash
git add src/synthesizer.py
git commit -m "feat: pass full context and excerpts to Stage 1C analyst"
```

---

### Task 4: Reduce Coverage Mandate from 10 to 6 Questions

**Files:**
- Modify: `src/synthesizer.py:662` (`_coerce_analysis_result` validation)
- Modify: `prompts/skills/throughline_analyst.md:73-76`

- [ ] **Step 1: Relax validation in `_coerce_analysis_result`**

Change line 662 from:
```python
        if covered_questions != set(range(1, 11)):
            raise ValueError("analysis writeup must cover all ten market-edge questions")
```
to:
```python
        if len(covered_questions) < 6:
            raise ValueError(
                f"analysis writeup must cover at least 6 of 10 market-edge questions, "
                f"got {len(covered_questions)}"
            )
```

- [ ] **Step 2: Update analyst prompt to match**

In `prompts/skills/throughline_analyst.md`, change line 74:
```
6. Across the full writeup, all ten question ids must be covered at least once
```
to:
```
6. Across the full writeup, cover at least 6 of the ten question ids — prioritize the questions the evidence actually supports rather than forcing coverage of questions with thin support
```

- [ ] **Step 3: Update existing test to match new threshold**

In `tests/test_synthesizer_analysis_validation.py`, the tests currently use question_ids [1-5] and [6-10] which sum to all 10. These tests still pass with the relaxed rule. Add one test that verifies the new minimum:

Add to the test class:

```python
    def test_coerce_analysis_result_rejects_fewer_than_six_questions(self):
        data = {
            "analysis_paragraphs": [
                {
                    "text": "Paragraph one.",
                    "through_line_ids": ["TL1"],
                    "theme_labels": ["oil shock"],
                    "question_ids": [1, 2, 3],
                },
                {
                    "text": "Paragraph two.",
                    "through_line_ids": ["TL2"],
                    "theme_labels": ["carry"],
                    "question_ids": [4, 5],
                },
            ]
        }
        with self.assertRaises(ValueError) as ctx:
            self.synthesizer._coerce_analysis_result(data, self.through_lines)
        self.assertIn("at least 6", str(ctx.exception))

    def test_coerce_analysis_result_accepts_six_questions(self):
        data = {
            "analysis_paragraphs": [
                {
                    "text": "Paragraph one.",
                    "through_line_ids": ["TL1"],
                    "theme_labels": ["oil shock"],
                    "question_ids": [1, 2, 3],
                },
                {
                    "text": "Paragraph two.",
                    "through_line_ids": ["TL2"],
                    "theme_labels": ["carry"],
                    "question_ids": [4, 5, 6],
                },
            ]
        }
        result = self.synthesizer._coerce_analysis_result(data, self.through_lines)
        self.assertEqual(len(result["analysis_paragraphs"]), 2)
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_synthesizer_analysis_validation.py -v
```

Expected: all tests pass (existing + 2 new)

- [ ] **Step 5: Commit**

```bash
git add src/synthesizer.py prompts/skills/throughline_analyst.md tests/test_synthesizer_analysis_validation.py
git commit -m "feat: relax coverage mandate from 10/10 to 6/10 market-edge questions"
```

---

### Task 5: Add Evidence Enrichment to Stage 1A Payload

**Files:**
- Modify: `src/synthesizer.py` (`_prepare_input` method, around line 1070)

This adds cross-document evidence grouping so the model sees which themes appear across multiple sources, with full context from each. This is the "analyst note-taking" enhancement — the model gets pre-organized evidence clusters instead of a flat list.

- [ ] **Step 1: Add `_enrich_with_cross_document_evidence` method**

Add after `_prepare_input` method:

```python
    def _enrich_with_cross_document_evidence(
        self,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Add cross-document evidence clusters to help the synthesizer see agreement/disagreement patterns.

        Groups themes by label across documents, preserving full context and excerpts.
        This gives the model pre-organized 'analyst notes' showing where sources converge or diverge.
        """
        themes = input_data.get("themes", [])
        if not themes:
            return input_data

        clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for theme in themes:
            label = self._clean_text(theme.get("label"))
            if label:
                clusters[label].append({
                    "source": theme.get("source", ""),
                    "document": theme.get("document", ""),
                    "context": theme.get("context", ""),
                    "strength": theme.get("strength", ""),
                    "confidence": theme.get("confidence", ""),
                    "excerpts": theme.get("excerpts", []),
                    "directionality": theme.get("directionality"),
                })

        # Only include clusters with 2+ sources (cross-document signal)
        cross_doc_clusters = []
        for label, entries in clusters.items():
            unique_sources = {e["source"] for e in entries if e["source"]}
            if len(unique_sources) >= 2:
                cross_doc_clusters.append({
                    "label": label,
                    "source_count": len(unique_sources),
                    "sources": sorted(unique_sources),
                    "entries": entries[:5],
                })

        # Sort by source_count descending (strongest cross-document signal first)
        cross_doc_clusters.sort(key=lambda c: c["source_count"], reverse=True)

        enriched = dict(input_data)
        if cross_doc_clusters:
            enriched["cross_document_clusters"] = cross_doc_clusters
        return enriched
```

- [ ] **Step 2: Wire enrichment into `_synthesize_with_skills`**

In `_synthesize_with_skills`, after the `_prepare_input` call on the `synthesize` method (line 242), the `input_data` is passed to `_stage1_throughlines`. Modify `_stage1_throughlines` to enrich before sending.

In `_stage1_throughlines` method, add enrichment before the loop (around line 406):

```python
    def _stage1_throughlines(self, input_data: dict) -> dict | None:
        """Stage 1: Extract through-lines from themes and trades."""
        enriched_data = self._enrich_with_cross_document_evidence(input_data)
        configs = [self.throughline_config]
```

Then change the payload construction inside the loop from `input_data` to `enriched_data`:

```python
                stage1_input = self._prepare_stage1_payload(
                    apply_payload_limits(enriched_data, stage1_profile),
                    config,
                )
```

- [ ] **Step 3: Commit**

```bash
git add src/synthesizer.py
git commit -m "feat: add cross-document evidence clustering to Stage 1A payload"
```

---

### Task 6: Set Temperature 0.3 for Stage 1C/1D Writing Stages

**Files:**
- Modify: `config/models.yaml:76-90` (throughline_analyst and throughline_analyst_editor)

- [ ] **Step 1: Update temperature in models.yaml**

Change `throughline_analyst` temperature from `0` to `0.3`:
```yaml
  throughline_analyst:
    # Stage 1C analyst: PM-facing writeup grounded in edited through-lines and scoped theme evidence
    provider: openai
    model: gpt-5-mini
    max_tokens: 5000
    temperature: 0.3
    request_timeout_seconds: 90
    max_retries: 0
```

Change `throughline_analyst_editor` temperature from `0` to `0.3`:
```yaml
  throughline_analyst_editor:
    # Stage 1D analyst editor: tighten the PM writeup while preserving grounding and coverage
    provider: openai
    model: gpt-5-mini
    max_tokens: 4000
    temperature: 0.3
    request_timeout_seconds: 90
    max_retries: 0
```

- [ ] **Step 2: Commit**

```bash
git add config/models.yaml
git commit -m "feat: set temperature 0.3 for Stage 1C/1D writing stages"
```

---

### Task 7: Filter Trades to High Conviction by Default

**Files:**
- Modify: `config.py:68` (add new env var)
- Modify: `.env.example:47` (document new env var)
- Modify: `src/formatter.py:242-281` (`_aggregate_trades` method)
- Modify: `generate_pdf_only.py:75` (pass filter config to formatter)
- Modify: `src/main.py` (pass filter config to formatter)

- [ ] **Step 1: Add `FILTER_TRADE_CONVICTION` to `config.py`**

After line 68 (`FILTER_ASSET_FOCUS`), add:
```python
    FILTER_TRADE_CONVICTION = os.getenv('FILTER_TRADE_CONVICTION', 'high')  # Filter trades: high, medium, low, all (default: high)
```

- [ ] **Step 2: Add to `.env.example`**

After the `FILTER_ASSET_FOCUS` line, add:
```
# Filter trades by minimum conviction level (default: high)
# Options: high (only high), medium (medium+high), low (all), all (all)
FILTER_TRADE_CONVICTION=high
```

- [ ] **Step 3: Add conviction filtering to `_aggregate_trades`**

Add a `conviction_filter` parameter to `_aggregate_trades`:

```python
    def _aggregate_trades(self, data: List[Dict[str, Any]], conviction_filter: str = "all") -> List[Dict[str, Any]]:
```

After the conviction normalization (around line 265), add a filter check:

```python
                conviction = raw_conviction.strip().lower() if isinstance(raw_conviction, str) else 'n/a'

                # Apply conviction filter
                if conviction_filter == "high" and conviction != "high":
                    continue
                elif conviction_filter == "medium" and conviction not in ("high", "medium", "moderate"):
                    continue
```

- [ ] **Step 4: Pass conviction filter through `format_report`**

Update `format_report` signature and usage:

```python
    def format_report(self, data: List[Dict[str, Any]], active_filters: Dict[str, Any] = None, conviction_filter: str = "all") -> Dict[str, Any]:
```

Change the trades line in the return dict:
```python
            'trades': self._aggregate_trades(data, conviction_filter=conviction_filter),
```

- [ ] **Step 5: Wire Config into `generate_pdf_only.py`**

Change line 75:
```python
    report_data = formatter.format_report(data, active_filters=active_filters)
```
to:
```python
    report_data = formatter.format_report(
        data,
        active_filters=active_filters,
        conviction_filter=Config.FILTER_TRADE_CONVICTION,
    )
```

- [ ] **Step 6: Wire Config into `src/main.py`**

Find the `formatter.format_report(data, active_filters=active_filters)` call and update similarly:

```python
    report_data = formatter.format_report(
        data,
        active_filters=active_filters,
        conviction_filter=Config.FILTER_TRADE_CONVICTION,
    )
```

- [ ] **Step 7: Add conviction filter to active_filters display**

In both `generate_pdf_only.py` and `src/main.py`, after the other filter checks, add:
```python
    if Config.FILTER_TRADE_CONVICTION != 'all':
        active_filters['trade_conviction'] = Config.FILTER_TRADE_CONVICTION
```

- [ ] **Step 8: Commit**

```bash
git add config.py .env.example src/formatter.py generate_pdf_only.py src/main.py
git commit -m "feat: filter trades to high conviction by default (FILTER_TRADE_CONVICTION)"
```
