# Skill Decomposition Plan

## Current Architecture Summary

The current pipeline operates as:

1. **Database Query** (`database.py`): Fetches documents with themes, trades, and through-lines
2. **Input Preparation** (`synthesizer.py` lines 212-291): Extracts and tags themes/trades from documents
3. **Monolithic LLM Synthesis** (`synthesizer.py` lines 77-134): Single call that produces through-lines + callouts
4. **Post-processing** (`synthesizer.py` lines 136-177): Normalizes source attribution
5. **Formatting** (`formatter.py`): Aggregates and structures for PDF
6. **PDF Generation** (`pdf_generator.py`): Renders final report

---

## Proposed New Skills

### Priority 1: Theme Normalization Skill (High Impact, Medium Complexity)

**Problem:** Themes from different sources express the same concept with different labels (e.g., "Fed Hawkish Pivot" vs "FOMC Rate Path Shift"). This creates noise and missed consensus signals.

**Value of Separation:**
- Testability: Validate clustering quality independently
- Refinement: Prompt tuning focuses solely on semantic similarity
- Context Engineering: Smaller, focused context window
- Reusability: Normalized themes feed multiple downstream processes

**Input Contract:**
```json
{
  "themes": [
    {
      "source": "Goldman Sachs",
      "document": "GS Rates Weekly",
      "label": "Fed Hawkish Pivot",
      "context": "Fed signaling higher-for-longer...",
      "strength": "Primary",
      "confidence": "High"
    }
  ]
}
```

**Output Contract:**
```json
{
  "normalized_themes": [
    {
      "canonical_label": "Fed Policy Trajectory",
      "variants": [
        {"original_label": "Fed Hawkish Pivot", "source": "Goldman Sachs"},
        {"original_label": "FOMC Rate Path Uncertainty", "source": "JPMorgan"}
      ],
      "combined_context": "Multiple sources highlight...",
      "source_count": 2,
      "aggregate_strength": "Primary",
      "aggregate_confidence": "High"
    }
  ],
  "singleton_themes": []
}
```

**Dependencies:** None (first in chain)

---

### Priority 2: Consensus Detection Skill (High Impact, Medium Complexity)

**Problem:** Current synthesis prompt asks LLM to both detect consensus/divergence AND synthesize insights simultaneously, overloading the reasoning step.

**Value of Separation:**
- Testability: Validate agreement detection with known test cases
- Refinement: Dedicated prompt with precise consensus level rules
- Context Engineering: Pre-computed signals reduce synthesis prompt complexity
- Transparency: Explicit consensus mapping makes attribution clearer

**Input Contract:**
```json
{
  "normalized_themes": [...],
  "trades": [...],
  "sources": ["Goldman Sachs", "JPMorgan", "Barclays"]
}
```

**Output Contract:**
```json
{
  "consensus_signals": [
    {
      "topic": "Fed Policy Trajectory",
      "consensus_level": "strong_consensus",
      "agreeing_sources": ["Goldman Sachs", "JPMorgan", "Barclays"],
      "disagreeing_sources": [],
      "evidence": {
        "agreements": ["All three expect 50bp+ cuts by year-end"],
        "disagreements": []
      }
    }
  ]
}
```

**Dependencies:** Theme Normalization (optional but beneficial)

---

### Priority 3: Trade Filtering Skill (Medium Impact, Low Complexity)

**Problem:** All trades pass to synthesis regardless of conviction, redundancy, or staleness.

**Value of Separation:**
- Could be 80% Python (deduplication, date-based freshness) with optional LLM for semantic similarity
- Rules-based filtering is easier to tune

**Input Contract:**
```json
{
  "trades": [...],
  "filter_config": {
    "min_conviction": "Medium",
    "deduplicate": true,
    "max_trades_per_source": 3
  }
}
```

**Output Contract:**
```json
{
  "filtered_trades": [...],
  "removed_trades": [
    {"trade": {...}, "removal_reason": "duplicate|low_conviction|exceeded_source_limit"}
  ],
  "trade_clusters": [
    {"cluster_label": "Curve Steepeners", "trades": [...]}
  ]
}
```

**Dependencies:** None (can run in parallel with Theme Normalization)

---

### Priority 4: Source Intelligence (Medium Impact, Low Complexity)

**Problem:** Source abbreviation is hardcoded in `_abbreviate_source()`.

**Recommendation: NOT an LLM skill.** Instead:
- Create `config/sources.yaml` lookup table
- Add Python utility `src/source_intelligence.py`
- Falls back to acronym generation for unknown sources

**Dependencies:** None

---

### Priority 5: Quality Assurance Skill (High Impact, High Complexity)

**Problem:** No validation of synthesis output quality.

**Value of Separation:**
- Catches attribution errors before PDF generation
- Validates consensus level assignments
- Detects fabrication or misattribution

**Input Contract:**
```json
{
  "synthesis_output": {
    "title": "...",
    "through_lines": [...],
    "callouts": [...]
  },
  "original_inputs": {
    "themes": [...],
    "trades": [...]
  }
}
```

**Output Contract:**
```json
{
  "validation_passed": true,
  "issues": [
    {
      "severity": "error|warning",
      "type": "attribution_missing|fabrication_detected|consensus_mismatch",
      "location": "through_lines[2].key_insight",
      "message": "Claim 'X' not found in source inputs"
    }
  ],
  "quality_score": 0.85
}
```

**Dependencies:** Runs after Through-Line Synthesizer and Callout Extractor

---

## Implementation Priority Matrix

| Skill | Impact | Complexity | Python vs LLM | Priority |
|-------|--------|------------|---------------|----------|
| Theme Normalization | High | Medium | LLM (clustering) | 1 |
| Consensus Detection | High | Medium | LLM (reasoning) | 2 |
| Trade Filtering | Medium | Low | Hybrid | 3 |
| Source Intelligence | Medium | Low | Python-only | 4 |
| Quality Assurance | High | High | LLM (validation) | 5 |

---

## Proposed Pipeline Architecture

### Current (Monolithic)
```
DB Query → Input Prep → [LLM: Full Synthesis] → Post-process → Format → PDF
```

### Proposed (Skill-Based)
```
DB Query → Input Prep
              │
              ├─→ [Theme Normalization Skill] ──┐
              │                                  │
              ├─→ [Trade Filtering Skill] ──────┤
              │                                  │
              └─→ [Source Intelligence] ─────────┤
                                                 ▼
                                    [Consensus Detection Skill]
                                                 │
                                                 ▼
                                    [Through-Line Synthesizer Skill]
                                                 │
                                                 ▼
                                    [Callout Extractor Skill]
                                                 │
                                                 ▼
                                    [Quality Assurance Skill]
                                                 │
                                                 ▼
                                         Format → PDF
```

---

## File Structure for New Skills

```
skills/
├── theme-normalizer/
│   ├── SKILL.md
│   └── references/
│       ├── clustering_criteria.md
│       └── output_schema.md
├── consensus-detector/
│   ├── SKILL.md
│   └── references/
│       ├── consensus_rubric.md
│       └── evidence_rules.md
├── trade-filter/
│   ├── SKILL.md
│   └── references/
│       ├── deduplication_rules.md
│       └── conviction_criteria.md
├── quality-assurance/
│   ├── SKILL.md
│   └── references/
│       ├── validation_checklist.md
│       ├── attribution_rules.md
│       └── fabrication_detection.md
├── throughline-synthesizer/  (existing)
└── callout-extractor/        (existing)

config/
└── sources.yaml  (new - for Source Intelligence)

src/
└── source_intelligence.py  (new - Python utility)
```

---

## Key Trade-offs

1. **Latency vs Quality**: More skills = more LLM calls. Mitigate by parallelizing independent skills (Theme Norm + Trade Filter + Source Intel).

2. **Token Cost**: Each skill call has overhead, but smaller focused calls often produce better results.

3. **Error Propagation**: Skill chain creates dependency risk. QA Skill mitigates but adds another call.

4. **Complexity**: More moving parts. Mitigate with strong contracts, integration tests, clear ownership.
