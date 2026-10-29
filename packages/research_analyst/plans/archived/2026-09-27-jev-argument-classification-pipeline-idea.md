# Jev-assisted argument classification pipeline idea

Status: deferred idea; requires design and evaluation before implementation  
Captured: 2026-09-27 America/New_York

## Idea

Use Jev as a fast, typed classification and validation layer inside `research_analyst`, while retaining LLMs for open-ended argument discovery, source-span selection, and nuanced evaluation.

The central boundary is:

- LLMs discover and assemble semantic content.
- Jev chooses among predefined categories and returns probabilities.
- deterministic code validates identifiers, source coordinates, and schema constraints.

Jev classifications are hypotheses with uncertainty, not authoritative facts.

## Proposed flow

1. An argument-discovery LLM reads parsed research text and emits candidate arguments. Each candidate includes a concise conclusion, exact source span, surrounding context, and stable source identifiers.
2. Jev classifies each candidate across several independent axes in one request where practical. The full probability distribution is retained rather than only the winning label.
3. Separate, fresh-context LLM calls inspect relevant source sections for linked logical components. These tasks may run concurrently:
   - supporting premises and evidence;
   - qualifiers, conditions, and invalidation criteria;
   - contrasts, challenges, contradictions, and counterevidence;
   - causal-chain completeness, where applicable.
4. Jev classifies each proposed relationship using a closed relation taxonomy.
5. Deterministic validation confirms that cited spans and stable keys exist and rejects malformed or ungrounded links.
6. Only after the argument structure has been assembled does an evaluator assess argument quality.
7. The validated argument bundle, provenance, classifications, probabilities, and quality results are persisted to the argument graph or supporting storage.

## Classification axes

Avoid forcing an argument into one overloaded category. Candidate axes include:

- semantic type: `observation`, `interpretation`, `forecast`, `market_impact`, `policy_claim`, `trade_claim`, `risk_condition`, and related existing types;
- logical form: causal, comparative, conditional, recommendation, question, or descriptive;
- temporality: historical, current, or forward-looking;
- support state: `evidenced`, `reasoned`, or `asserted`;
- conditionality: whether explicit conditions, qualifiers, or invalidation criteria are present;
- relationship: `supports`, `challenges`, `rebuts`, `concedes`, `duplicates`, `synthesizes`, contradicts, qualifies, or irrelevant.

Borderline probability distributions should be allowed to trigger claim splitting or review. A high-confidence category does not imply a high-quality argument.

## Argument bundle

The durable representation should distinguish the conclusion from its surrounding logical structure:

```text
Argument
├── conclusion
├── premises[]
├── evidence[]
├── qualifiers[]
├── conditions[]
├── counterevidence[]
├── invalidation_criteria[]
└── relations[]
```

Every component and relationship should retain:

- exact source provenance;
- stable local or persisted identifiers;
- classification probabilities;
- extraction or linking confidence;
- validation status; and
- model and prompt/version metadata.

## Keep three quality concepts separate

### Classification quality

Whether Jev assigned the correct predefined labels. Evaluate this against gold annotations using per-class precision, recall, confusion matrices, calibration, and abstention thresholds.

### Structural extraction quality

Whether the linking passes found the correct premises, evidence, qualifiers, counterevidence, and relationships without omissions or inventions. Evaluate exact provenance, source fidelity, relation correctness, and important-component recall.

### Argument quality

How strong the fully assembled argument is. Candidate dimensions include:

- evidence relevance and sufficiency;
- premise-to-conclusion support;
- causal completeness;
- specificity and falsifiability;
- treatment of qualifiers and counterevidence;
- unsupported assumptions;
- evidence-source independence; and
- overall argument strength.

These scores must be stored separately. Jev confidence is not an argument-quality score.

## Independence and anchoring safeguards

- Do not ask the discovery LLM to defend its own candidate in the same conversational context.
- Use a separate evidence-linking agent or a fresh context, even if it uses the same underlying model.
- Give linkers Jev's probabilities as revisable signals, not settled labels.
- Require linkers to select exact source passages rather than generate improved supporting prose.
- Permit `none`, `uncertain`, or review outcomes instead of forcing every candidate into the graph.

## Likely fit with the current package

This idea extends existing `research_analyst` concepts rather than replacing them:

- `plans/2026-03-27-assertion-taxonomy-spec.md` defines the assertion categories.
- `src/research_analysis_layer/models/agent_outputs.py` defines claim types, evidence references, and support strength.
- `src/research_analysis_layer/models/debate_models.py` defines debate relation types.
- `src/research_analysis_layer/services/argument_graph.py` queries resolved claims and evidence.
- `src/research_analysis_layer/evals/judge.py` already separates argument-map rubric evaluation from final-output judging.
- private gold argument maps can provide the calibration and regression dataset.

## Recommended first experiment

Run Jev in shadow mode on gold and representative production-like captures without changing persisted production output.

Start with narrow, closed decisions:

1. assertion or claim type;
2. support strength;
3. proposed pairwise relation type; and
4. binary grounding checks for proposed evidence links.

Measure accuracy and calibration per decision type, not only aggregate accuracy. Compare latency and cost with the current LLM judge. Establish class-specific confidence thresholds for automatic acceptance, escalation, and rejection.

Do not begin with open-ended claim extraction, arbitrary source-span discovery, rationale generation, or taxonomy discovery; those remain LLM tasks.

## Questions for future planning

- Should the first integration classify deterministic assertions, LLM-generated `ClaimNode`s, debate arguments, or all three at different stages?
- Which classification axes are authoritative enough to persist, and which remain run-local diagnostics?
- Should evidence linking use one structured LLM call or independent specialist calls?
- What is the maximum source context sent to Jev, particularly for licensed or sensitive research?
- How should abstention thresholds vary by category and downstream consequence?
- When Jev and the evidence linker disagree, which outcomes trigger splitting, another judge, or human review?
- Does `contradicts` belong in the durable relation taxonomy, or should it remain inferred from opposing claims and shared referents?
- Which argument-quality dimensions can be decomposed into reliable binary questions, and which require a nuanced LLM or human judge?
- How should model, taxonomy, prompt, and calibration versions be recorded for reproducibility?

## Planning exit criteria

Before implementation, produce a reviewed engineering design covering:

- component boundaries and data contracts;
- taxonomy changes and migrations;
- provider interface and failure behavior;
- privacy and data-handling constraints;
- concurrency, batching, latency, and cost budgets;
- confidence thresholds and escalation policy;
- shadow-mode evaluation protocol;
- gold-set additions; and
- rollout, observability, and rollback.
