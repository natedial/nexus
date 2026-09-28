---
cursor:
  subagentId: "bc-932506da-5714-5a9b-9356-0bcbeb2cb946"
---

# Jev for Nexus argument classification

_Brainstorm and recommendation, 2026-09-27_

## Recommendation

Run Jev in **shadow mode as a parallel span classifier that builds a provenance-preserving candidate argument scaffold**, then have the existing document-level LLM consolidate that scaffold globally. Jev should assign one mutually exclusive statement type plus independent probabilities for semantic subtypes and rhetorical functions; deterministic code should turn those signals into candidate nodes, evidence links, and deliberately tentative local edges. The LLM still owns whole-document thesis discovery, deduplication, global relation adjudication, and the final 3–7-claim map.

This changes the generative task from zero-shot “find and map the argument” to “consolidate and correct a source-grounded candidate map.” Start without hard filtering or production-schema changes. Store raw probabilities, candidate provenance, question-set version, and resolved Jev version; promote only after held-out evaluation shows better final-map coverage/grounding without losing load-bearing claims. A post-map Jev verifier remains useful, but the scaffold is the primary architecture.

## What Nexus actually does today

The proposed “argument / supporting assertion / fact / opinion” four-way classifier is **not the active Nexus taxonomy**. There are several partially overlapping layers:

| Layer | Unit | Current labels / output | How produced |
|---|---|---|---|
| Parser memory | Source block, usually a paragraph | `paragraph`, `section`, `table`, `figure`; stable `span_key`, page/section/character coordinates | Deterministic in `research_parser/src/research_memory/spans.py` |
| Parser retrieval | Several ordered spans | Retrieval chunks target 6,000 characters, minimum 1,800, with one-span overlap | Deterministic in `research_memory/spans.py` |
| Legacy parser theme fallback | Theme | `Forecast`, `Opinion`, `Description` | Hydrated from stored parser themes; only used for analyst chunking when retrieval chunks and spans are absent |
| Analyst chunk | Retrieval chunk first, then span, then theme | `retrieval_chunk`, `span`, or theme-derived types | `research_analysis_layer/services/chunker.py` |
| Deterministic assertion | Sentence-like candidate within an analyst chunk | Implemented: `observation`, `interpretation`, `forecast`, `causal_claim`, `market_impact`, `risk_condition`, `policy_claim`, `trade_claim`, `open_question` | Regex/keyword heuristics in `services/assertion_extractor.py`; no model call |
| Document argument map | 3–7 document-level claims | Claim type: `observation`, `forecast`, `causal`, `market_impact`, `policy`, `risk`, `recommendation`; support: `evidenced`, `reasoned`, `asserted`; evidence kind: `data`, `quote`, `citation`, `chart`, `prior_view` | Final synthesizer LLM in `services/round_executor.py`, validated by `models/agent_outputs.py` |
| Private gold set | Human-selected claim and claim pair | Role: `conclusion`, `premise`, `condition`, `counterpoint`; links: `supports`, `depends_on`, `qualifies`, `leads_to`, `answers`, `contrasts_with` | Co-reading annotations in `evals/gold_set.py`; richer than the production map |
| Optional debate | Temporary document-local argument | Relations: `supports`, `challenges`, `rebuts`, `concedes`, `duplicates`, `synthesizes`; verdicts include accepted/rejected/contested | Multi-agent debate, default disabled |

### Pipeline and classification points

1. `research_parser` creates citeable paragraph/table/figure spans and packs them into retrieval chunks. It does not decide which paragraphs are arguments.
2. `research_analyst` prefers retrieval chunks, falls back to individual spans, then to legacy themes.
3. Evidence units preserve span provenance.
4. `AssertionExtractor` splits chunk and evidence text into at most five sentence candidates and assigns assertion types with string markers.
5. Nodes/edges are resolved deterministically from those assertions.
6. If agents are enabled, the final synthesizer sees bounded chunks, evidence units, assertions, and optionally debate state. It generates the document-level 3–7-claim `argument_map`.
7. Unknown evidence references are nulled. An `evidenced` claim with no surviving grounded `ref_key` is downgraded to `reasoned`. The referent and claim-key resolvers run afterward.

Thus a paragraph can already yield several assertions, while one document-level claim can draw on several spans. “One paragraph, one mutually exclusive label” would flatten both relationships.

### Current model-call and cost shape

- The parser memory, chunking, evidence-building, and assertion classification path is local and deterministic: **zero LLM calls**.
- With the default `DEBATE_MODE=off`, debate rounds are skipped and one `gpt-5` synthesizer call produces narrative fields and the argument map.
- With debate `on`, one document uses six calls: two parallel proposal calls, then challenge, rebuttal, adjudication, and synthesis. There are five wall-clock stages because the two proposals run concurrently.
- `shadow` runs that debate chain plus a separate baseline synthesis, so it can use seven calls.
- Nexus persists per-round input/output/cache tokens, tool-call count, and duration, but not dollar cost. Actual spend therefore depends on provider/model pricing and document payload size. Agent input is bounded (for example, chunks at 900 characters and evidence units at 400 characters), but the same base payload can be sent to several rounds.

### Known failure modes visible in code

- **Invalid nested enums drop the entire claim.** `EvidenceRef.kind` accepts only five values. If an LLM emits `kind: "reasoning"`, Pydantic rejects the `ClaimNode`, and `_coerce_argument_map` logs `argument_map: dropping invalid claim`. Reasoning belongs in `rationale`, but the failure handling loses the whole otherwise-useful claim.
- **Heuristic assertion typing is brittle.** Substring markers such as `should`, `market`, `if`, and `could` can over-trigger; the first five sentence candidates win; compound claims are not reliably split as the taxonomy spec intends.
- **The intended and implemented assertion taxonomies differ.** The spec includes `comparative_view`, but the extractor never emits it. Most retrieval chunks default to `observation`.
- **Paragraph boundaries are not semantic boundaries.** A claim, its evidence, and its qualification may be in adjacent spans; retrieval chunks preserve context but are much coarser than paragraphs.
- **Production maps lack explicit roles and claim-to-claim links.** Those exist in the gold format and debate state, not in `DocumentAnalysis.argument_map`.
- **Quality checks are mostly post hoc.** The linter catches missing rationale, ungrounded evidenced claims, duplicates, and non-substantive claims in evals, but it does not recover claims already dropped during schema coercion.
- **Model confidence is not field-level confidence.** The production map has one document-level confidence, while individual claims and links do not retain calibrated probabilities.

## What Jev is

Jev is TypeSafe AI's first “System One” model: a hosted decision model for bounded, typed judgments rather than generated prose. The HTTP interface is:

```text
POST https://api.typesafe.ai/v1/systemone
{ "state": <text-or-JSON>, "model": "jev-1.13.0", "questions": { ... } }
```

It has three primitives:

- **Noul:** a yes/no question returning `P(yes)` as `noul`.
- **Choice:** one winner from 2–255 supplied options, plus a probability for every option and a separate `confidence`.
- **Score:** an expected position over 2–10 ordered levels, level probabilities, and `confidence`.

Questions sharing a state are evaluated independently and in parallel. One answer does not become hidden context for another. That is a strong fit for Nate's layering idea: “contains a substantive claim,” “qualifies another claim,” and “addresses counter-evidence” can all be high at once if asked as separate Nouls.

As of Jev 1.13:

- Price is **$0.042 per million input tokens** ($42/billion); output tokens are free.
- Published limits are 250,000 tokens/second and 1,200 requests/minute, but TypeSafe says these are dynamically adjusting.
- Context is 64k tokens per request, with a 32k limit for the state plus the longest question.
- Input is text/JSON only, not images, audio, or video.
- TypeSafe says most requests complete in about 100 ms. Its 13-question/54k-character cookbook measured 0.27 s batched versus 2.71 s for 13 sequential calls, and $0.000497 versus $0.006090 because the shared state was billed once. That is a vendor example, not a Nexus benchmark.
- `jev-latest` currently resolves to `jev-1.13.0`, but aliases move. Production thresholds should pin and log the version.

### Calibration claim, with the important caveat

TypeSafe says Jev is trained with “Reinforcement Learning for Calibrated Decisions” so that, over groups of predictions, higher probabilities correspond to outcomes occurring more often. Its own docs explicitly say this does **not** guarantee an individual answer.

For Choice and Score, Jev's `confidence` is a statistic describing how concentrated the returned distribution is; it is **not** the probability that the selected answer is correct. Noul directly returns a yes probability and has no separate confidence. Separate Nouls also need not obey logical identities: `P(A)` and `1-P(not A)` may disagree.

An independent September 2026 sentiment experiment by Anthus is a useful warning, though not a finance-domain benchmark. On 8,801 examples, raw Noul confidence averaged about 7 points above accuracy and two-option Choice about 15 points above accuracy. Question wording materially changed results. Isotonic calibration on held-out labels reduced calibration error substantially, with a few hundred labels capturing much of the benefit. The responsible interpretation is: Jev probabilities may rank cases well, but Nexus must calibrate each fixed question/version on Nexus data before using thresholds.

### Documented limits relevant to Nexus

- Jev is literal; exact criteria and boundary cases matter.
- It degrades with indirection and large amounts of irrelevant state (“context rot”).
- It is weak at arithmetic, counting, precise date comparisons, and Score interpolation.
- State is not automatically treated as hostile; prompt-injection-like content can move answers.
- A Choice is relative and always allocates probability mass among supplied options, so it needs `none`/`not_applicable` where appropriate.
- It does not generate prose. It cannot write claims, rationales, or new evidence citations.
- English is its strongest language.
- TypeSafe says requests are not used for training; zero-data-retention is an enterprise feature. Retention/DPA terms still need review before sending confidential sell-side research.

## Proposed layered question set

Use a short section context: document metadata, heading path, target span, one preceding/following span, and stable span keys. Avoid asking every local classifier to rediscover the whole-document thesis.

### Layer A: one mutually exclusive statement type (Choice)

Every target gets exactly one primary structural type:

- `assertion` — a proposition the author presents as true or likely;
- `evidence_report` — a concrete datum, quote, chart/citation reference, or prior event;
- `question` — genuinely unresolved or interrogative;
- `recommendation` — an action, policy, position, or trade;
- `background_methodology` — framing, definitions, method, or scene-setting;
- `other_or_unclear` — required escape hatch.

This field is exclusive because downstream code needs one answer to “what kind of statement is this primarily?” It is not a complete description of the span.

### Layer B: multi-label semantic subtypes (Noul)

Ask each independently; several can be high:

- `is_observation`
- `is_forecast`
- `is_causal`
- `is_market_impact`
- `is_policy_claim`
- `is_risk_or_scenario`
- `is_comparative`
- `is_trade_or_action`

A sentence such as “sticky inflation will delay cuts and pressure the long end” can legitimately be forecast + causal + policy + market impact. These subtypes map to the current assertion/claim taxonomy but should not be forced to compete in one Choice.

Evidence-report units can likewise receive independent `is_numeric_data`, `is_direct_quote`, `is_external_citation`, `is_chart_reference`, and `is_prior_event_or_view` signals. The final LLM still selects the single current `EvidenceRef.kind`; the multi-label signals prevent an evidence span that is both data and a citation from being prematurely flattened.

### Layer C: multi-label rhetorical functions (Noul)

- `is_substantive_author_claim`
- `is_load_bearing_conclusion`
- `directly_supports_another_claim`
- `contains_verifiable_evidence`
- `contains_reasoning_bridge`
- `qualifies_or_conditions_claim`
- `introduces_counterpoint`
- `introduces_adverse_evidence`
- `answers_or_rebuts_counterpoint`
- `concedes_or_narrows`
- `is_background_or_methodology_only`

A span can simultaneously support a claim, contain evidence, and qualify its scope. That overlap is the reason these are independent Nouls rather than a role Choice. A separate `primary_role` Choice may be added later for compatibility with the gold schema, but it must not replace the multi-label functions.

Do not begin with Score. “Centrality” sounds ordinal, but Jev's own docs warn that Score levels are weak for numerical interpolation. `is_load_bearing_conclusion` plus a calibrated Noul threshold is easier to interpret.

### Layer D: local candidate relations

For bounded candidate pairs, ask independent relation questions:

- `supports`
- `qualifies`
- `depends_on`
- `causally_leads_to`
- `answers_or_rebuts`
- `is_in_tension`
- `is_logically_incompatible`
- `unrelated`

If code eventually needs one relation, use a Choice over the gold link types plus `unrelated` and `ambiguous`, but retain the Noul vector for audit. Preserve these distinctions:

- **counterpoint** — an opposing proposition is introduced;
- **counter-evidence** — adverse factual evidence is introduced;
- **qualification/narrowing** — the original remains with reduced scope;
- **concession** — part of the opposing point is accepted;
- **alternative explanation** — the same observation gets a different causal account;
- **rebuttal** — the opposing point is answered;
- **contradiction** — both propositions cannot hold in the same scope and time.

“Contradiction” is a candidate relationship, not an evidence kind.

## Mapping to current schemas

| Jev output | Existing home | Recommendation |
|---|---|---|
| Span probabilities | No production field | Sidecar annotation keyed by `span_key`, model version, question-set version |
| Exclusive `statement_type` | No exact production equivalent | Use only to construct the transient scaffold |
| Semantic subtype probabilities | `ClaimNode.claim_type` / `AssertionDraft.assertion_type` | Normalize naming (`causal` vs `causal_claim`, etc.); let the LLM choose the final single claim type |
| Rhetorical-function probabilities | Gold `role`, conditions, rationale, debate relations | Evaluate against gold first; do not add wholesale to `ClaimNode` |
| Evidence signals | `EvidenceRef.kind` and `ref_key` | Use to propose evidence items; provenance must still come from existing span keys |
| Derived support posture | `ClaimNode.support_strength` | Infer from accepted evidence/rationale links, not one local label; `evidenced` still requires a grounded reference |
| Qualification/condition | `ClaimNode.conditions`, assertion `condition_text`, debate `qualifier_text` | Populate only from source text selected by the existing extractor/generator |
| Pair relation | Gold links; debate relations | Keep sidecar until a production claim-link schema is chosen |
| Contradiction | Gold `contrasts_with`; debate `challenges`; cross-document argument graph | Preserve scope, time, and direction; do not collapse all three concepts |

## Concrete architecture: classify → scaffold → consolidate

### 1. Prepare source-grounded classification units

The parser remains authoritative for source text and coordinates. The analyst takes each usable paragraph/span and applies the existing deterministic sentence splitter so a paragraph containing several propositions can yield several target units. Each unit keeps:

- parent `span_key`, `retrieval_chunk_key`, section path, page, and order;
- deterministic `unit_id`, sentence index, text hash, and verbatim `surface_text`;
- previous/next span IDs for local context.

Jev does not generate node text. A candidate node starts as the verbatim sentence/span; only the global LLM may normalize it into an atomic claim.

### 2. Classify units in parallel

For each section-sized batch, send shared context and one named question bundle per target unit. Jev returns the exclusive statement-type distribution plus independent subtype/function probabilities. Treat all outputs as observations, not decisions.

Proposed per-unit sidecar contract:

```json
{
  "schema_version": "argument-signals-v1",
  "document_key": "doc:5246:<hash>",
  "batch_id": "doc:5246:<hash>:section:rates:1",
  "unit_id": "span:<span_key>:sentence:2",
  "span_key": "<stable parser span key>",
  "retrieval_chunk_key": "<chunk key>",
  "section_path": ["Rates", "Policy outlook"],
  "page": 4,
  "surface_text": "Sticky services inflation should delay the first cut.",
  "text_hash": "<sha256>",
  "context": {
    "heading": "Policy outlook",
    "previous_span_key": "<key>",
    "next_span_key": "<key>",
    "document_brief_version": "outline-v1"
  },
  "statement_type": {
    "choice": "assertion",
    "probabilities": {
      "assertion": 0.84,
      "evidence_report": 0.03,
      "question": 0.01,
      "recommendation": 0.02,
      "background_methodology": 0.04,
      "other_or_unclear": 0.06
    }
  },
  "semantic_subtypes": {
    "is_forecast": 0.88,
    "is_causal": 0.79,
    "is_policy_claim": 0.91,
    "is_market_impact": 0.12
  },
  "rhetorical_functions": {
    "is_substantive_author_claim": 0.96,
    "is_load_bearing_conclusion": 0.67,
    "directly_supports_another_claim": 0.58,
    "qualifies_or_conditions_claim": 0.08
  },
  "classification_status": "complete",
  "model": "jev-1.13.0",
  "question_set_version": "argument-signals-v1",
  "calibration_version": null
}
```

Raw response probabilities should be retained even when application thresholds say “candidate” or “ignore.” Calibrated probabilities, when available, are a separate versioned field; never overwrite the raw values. Request-level usage, latency, retries, resolved model, and errors belong on one batch record keyed by `batch_id`, not copied onto every unit.

### 3. Build candidate nodes and evidence links

Deterministic aggregation turns signals into a scaffold:

- A unit with sufficient assertion/recommendation/question probability becomes a **candidate claim node**.
- A unit with high `contains_verifiable_evidence` or `evidence_report` becomes a **candidate evidence item** carrying its real `span_key`.
- A reasoning bridge becomes candidate `rationale` material, not `EvidenceRef.kind`.
- A condition/qualification is attached as candidate condition text to nearby claims.
- Counterpoints, adverse evidence, concessions, and rebuttals remain explicit candidates rather than being flattened into “contradiction.”

Each candidate retains every contributing unit ID and raw score. Thresholds decide inclusion in the scaffold, not truth. Near-threshold units go into an `unresolved_candidates` list so the LLM can inspect them.

### 4. Infer relations conservatively

Do not compare every node with every other node. Generate a bounded pair set using deterministic structural cues:

1. same or adjacent span;
2. same section/retrieval chunk;
3. explicit discourse markers (`because`, `therefore`, `however`, `unless`);
4. shared normalized subject/entity plus compatible time horizon;
5. a function pairing that makes a relation plausible, such as evidence → claim or qualifier → claim.

Ask Jev relation questions only for that shortlist. Emit a candidate edge only with:

- source and target candidate IDs;
- direction;
- full relation-probability vector;
- the structural reason the pair was proposed;
- shared entity/time/scope fields when known;
- exact supporting span keys.

Guardrails against overclaiming:

- call every edge `candidate`, never canonical;
- use calibrated, relation-specific thresholds and keep `ambiguous`/`unrelated`;
- never infer global contradiction from polarity alone;
- require matching entity, scope, horizon, and modality before `is_logically_incompatible`;
- do not infer an evidence link merely because evidence and a claim are nearby;
- retain competing relation hypotheses rather than forcing one winner;
- let the global LLM delete, reverse, or retype every edge.

### 5. Aggregate and deduplicate without erasing disagreement

Aggregate after all parallel batches complete:

- Exact text hash or stable-unit identity: merge deterministically.
- Overlapping retrieval chunks citing the same `span_key`: merge provenance, not scores.
- Normalized-text duplicates with the same subtype/stance/horizon: group as a duplicate cluster.
- Similar text with different modality, horizon, stance, or qualifier: keep separate.
- Apparent contradictions: never deduplicate.

Do not average probabilities from different context windows as though they were independent measurements. Preserve each classification observation; an optional calibrated reducer may choose max, median, or reliability-weighted evidence later. Any combined “priority score” is a ranking heuristic, not a probability.

The resulting transient scaffold is:

```json
{
  "candidate_nodes": [],
  "candidate_edges": [],
  "candidate_evidence_links": [],
  "duplicate_clusters": [],
  "unresolved_candidates": [],
  "coverage": {
    "classified_unit_count": 0,
    "source_span_count": 0,
    "failed_batch_count": 0
  }
}
```

### 6. Give the LLM a consolidation task, not a blank page

Change the synthesizer prompt from “extract 3–7 main claims” to:

1. read the entire compact document outline and candidate scaffold;
2. choose the document's load-bearing thesis using whole-document evidence;
3. merge duplicate/local candidate nodes into 3–7 atomic global claims;
4. preserve or correct claim type, stance, horizon, conditions, and support strength;
5. adjudicate candidate support/qualification/counterpoint/rebuttal/contradiction edges;
6. separate reasoning (`rationale`) from concrete evidence;
7. cite only supplied stable source keys;
8. inspect unresolved candidates before omitting them.

The scaffold is advisory. The prompt must say that Jev scores can be wrong and that local centrality is not global importance. The LLM may create a missing claim or edge only when it cites source spans and records an ephemeral `scaffold_override` reason for evaluation. It may also reject candidates. Production output can remain the current `DocumentAnalysis`/`ClaimNode` schema; candidate IDs and overrides can live in traces until a durable link schema is justified.

### Document-context inputs

Use two context products:

- **Local classification context:** metadata, heading path, target unit, neighboring spans, and the rest of the short section/retrieval chunk.
- **Global consolidation context:** a deterministic outline (title, headings, first/last substantive spans, parser themes where available), the complete scaffold, and compact cited excerpts.

Do not feed a generated thesis back into local classification; that creates circular confirmation. `is_load_bearing_conclusion` is only a local prior until the LLM evaluates the full document.

### Concurrency and batching

- Batch by section or retrieval chunk so state is shared but topically coherent.
- Put roughly 8–16 target units in a batch, then tune from measured token use and accuracy; token limits are ceilings, not batching targets.
- Ask all type/subtype/function questions for those targets in one request, with IDs pointing to explicit state fields.
- Process independent batches with a small bounded worker pool. Preserve source order during scatter/gather.
- Retry `429`/`529` with SDK backoff; on permanent failure, mark batch coverage incomplete and fall back to the current deterministic/LLM path.
- Relation classification is a second parallel wave over only shortlisted pairs.
- Cap candidates sent to the LLM by calibrated recall-oriented gates and diversity, while always retaining unresolved high-centrality and counterpoint candidates.

## Where Jev fits: options

### 1. Pre-filter before LLM synthesis

**Pros:** cheap signal over every span; can prioritize argumentative content, reduce prompt volume, and make paragraph-level omission visible.

**Cons:** the highest-risk placement. A false negative can permanently remove the main claim, especially when a premise and conclusion are split across paragraphs. Centrality requires document context, which conflicts with Jev's context-rot warning.

**Use:** ranking and token-budget allocation only at first. Never hard-drop a span solely from Jev.

### 2. Replacement for deterministic assertion typing

**Pros:** likely better semantics than keyword markers; independent probabilities expose ambiguity; could cover `comparative_view` and nuanced counterpoints.

**Cons:** turns a free local stage into a network dependency; still cannot split and rewrite atomic claims or provide provenance; labels do not exactly match production; costs/latency become nonzero.

**Use:** shadow challenger to `AssertionExtractor`, measuring disagreements. Replacement is plausible later for type assignment, not for extraction itself.

### 3. Replacement for the argument-map synthesizer

**Pros:** superficially attractive cost and latency.

**Cons:** technically mismatched. Jev cannot generate claim text, rationale, conditions, or references and cannot select an open-ended 3–7 claim set. A bounded Choice would only choose among candidates generated elsewhere.

**Use:** do not pursue as the initial design.

### 4. Candidate scaffold followed by global LLM consolidation

**Pros:** best fit. Parallel local classification improves coverage and provenance; the global LLM handles thesis selection and cross-section synthesis. It directly reduces zero-shot omission pressure and the `"reasoning"` evidence-kind/drop failure. Uncertain local items can be retained for adjudication instead of silently dropped.

**Cons:** incremental cost and architecture; noisy local candidates or edges can anchor the LLM incorrectly; the scaffold can bloat the prompt if aggregation is weak.

**Use:** recommended. Keep a lightweight post-map verifier as an optional second stage.

## Efficiency and cost expectation

At the published Jev rate:

```text
Jev cost = billed input tokens × $0.042 / 1,000,000
```

For illustration, 20 section/chunk calls at 2,000–5,000 billed input tokens each would cost about **$0.0017–$0.0042 per document**. A better implementation may batch several target spans and all their questions into one section-level request, paying for shared context once. Measure the actual `usage.input_tokens`; question text and criteria are still billed.

Jev should return in sub-second time when batched, but a Nexus benchmark must include network retries and document fan-out. At 20 sequential chunk calls, even 100–300 ms each becomes 2–6 seconds; bounded concurrency or section batching matters.

Compared with Nexus:

- It is far cheaper per token than a frontier generative model and emits no billed prose.
- It does **not** eliminate the default GPT synthesis call; it makes that call a constrained consolidation pass. The first rollout adds a few mills per document and some latency.
- The expected efficiency gain is fewer raw passages in the generative prompt, fewer retries from invalid nested outputs, and less model effort spent discovering local structure. Savings are not guaranteed: an uncompressed scaffold can cost more tokens than the baseline.
- Because default debate is already `off`, “skip the debate” is not a current baseline saving. Compare against the actual one-call default, not the six-call optional architecture.

### Expected quality and efficiency gains

- **Higher recall:** every source unit is inspected, so arguments in low-salience sections are less likely to disappear.
- **Better grounding:** nodes/evidence begin with stable span keys rather than model-invented references.
- **More nuance:** exclusive structural type coexists with multiple semantic and rhetorical functions.
- **Fewer schema failures:** evidence/rationale distinctions are prepared before `ClaimNode` validation.
- **Easier debugging:** a missing final claim can be traced to classification, scaffold gating, aggregation, or LLM consolidation.
- **More focused generation:** the LLM spends its budget on global thesis, deduplication, and adjudication.
- **Parallel wall time:** local batches and pair checks run concurrently; one GPT consolidation remains the serial critical path.
- **Possible token savings:** send compact candidate excerpts instead of every bounded chunk, but only after recall is proven.

The countervailing costs are the Jev requests, a larger transient data structure, relation-pair work, and extra orchestration. Measure end-to-end, not just Jev latency.

## Evaluation plan

### Dataset

1. Reuse the private gold argument set: it already has conclusions/premises/conditions/counterpoints, claim types, support strength, evidence kinds, and claim links.
2. Add a small stratified span layer: initially 200–500 paragraphs/spans from 20–40 documents, deliberately including tables, headings, background, methodology, mixed claim/evidence paragraphs, qualifications, and adverse evidence.
3. Label source-span roles independently from current Nexus output. Current-output agreement alone is not ground truth.
4. Split calibration and final test sets by document, not by paragraph, to avoid leakage.

### Staged experiment

0. **Freeze labels and contract.** Human-label the span sample, define question wording and versioned thresholds, and test the data contract without changing synthesis.
1. **Shadow classification.** Run type/subtype/function questions; compare with human labels and current deterministic assertions. No scaffold enters the LLM.
2. **Shadow scaffold.** Build candidate nodes/evidence/edges and score scaffold coverage against gold maps. Review false edges and missing load-bearing claims.
3. **Prompt A/B.** On the same documents and same GPT model, compare:
   - **A:** current zero-shot argument-map synthesis;
   - **B:** scaffold consolidation with all original source context;
   - **C:** scaffold consolidation without candidate edges (edge ablation);
   - **D:** scaffold consolidation with compact candidate excerpts (efficiency arm).
4. **Calibrate and gate.** Fit per-question calibration on a separate split, rerun held-out documents, and set recall-oriented inclusion/review thresholds.
5. **Limited guided rollout.** Use scaffold mode with automatic fallback to baseline when coverage is incomplete, Jev fails, or the LLM reports insufficient support.
6. **Optimize only after quality holds.** Reduce raw GPT context or skip low-value candidates incrementally; retain periodic human audits and version-triggered recalibration.

Pin `jev-1.13.0`, freeze the exact question text/options as a versioned artifact, and rerun the same examples on any question or model change.

### Measures

- Per Noul: AUROC/AUPRC, Brier score, expected calibration error, and precision/recall at proposed thresholds.
- Per Choice: confusion matrix, macro-F1, top probability calibration, `none_or_other` frequency.
- Scaffold: gold-claim oracle recall (does any candidate cover each gold claim?), candidate-node precision, evidence-link precision/recall, relation precision by type, unresolved rate, duplicate-cluster purity, and source-span coverage.
- Argument-map outcomes: load-bearing claim recall, role/type accuracy, evidence grounding, qualifier retention, counterpoint/rebuttal recall, duplicate rate, and invalid-claim drop rate.
- Consolidation behavior: candidate acceptance/rejection rate, scaffold-override rate, incorrect anchoring rate, and recovery of gold claims absent from the scaffold.
- Pipeline outcomes: GPT input/output tokens, prompt bytes, end-to-end p50/p95 latency, Jev batch/pair usage and cost, retries/errors, fallback rate, and human-review rate.
- Disagreement review: sample `Jev ≠ current`, `both agree but gold differs`, and low-confidence cases. Agreement can merely reveal shared bias.

### Promotion gates

- No hard span filtering until held-out recall for load-bearing conclusions and supporting premises is at least the human-approved target and no worse than baseline.
- Calibrate probabilities on a separate split; do not interpret raw Choice `confidence` as correctness.
- Require no degradation in grounded-evidence and qualifier-retention metrics.
- Demonstrate a measurable downstream benefit—fewer dropped claims, fewer GPT tokens, or better gold scores. Fast/cheap labels alone are not enough.
- Run confidential-data/legal review before live documents leave Nexus.

## Integration sketch

The change belongs in `packages/research_analyst`, not `research_parser`: parser should continue to own stable source extraction and provenance.

1. Add a future service such as `services/argument_signal_classifier.py` behind configuration and a TypeSafe client adapter.
2. Invoke it after `Chunker`/`EvidenceBuilder`, when stable spans and evidence references are available.
3. Add an `ArgumentScaffoldBuilder`-like stage that creates deterministic unit IDs, batches classifications, shortlists relation pairs, aggregates duplicate candidates, and records coverage.
4. Keep immutable sidecar records keyed by document/unit, pinned Jev model, question-set version, raw/calibrated probabilities, token usage, latency, and error state.
5. Extend `AgentInputBuilder` with an optional bounded `argument_scaffold` payload; preserve the existing base payload for shadow and fallback modes.
6. Revise the synthesizer prompt to consolidate/correct the scaffold and emit the existing `DocumentAnalysis`. Capture temporary candidate IDs and override reasons for evals.
7. Add an optional verifier before final coercion so invalid evidence kinds are repaired deterministically or flagged before an entire claim is dropped. Jev advises classification; it never invents text or references.
8. Do not alter parser spans, canonical claim identities, or production claim-link storage in the pilot.

## Pros

- True multi-label characterization without forcing one paragraph into one bucket.
- Per-dimension probabilities support confidence routing, selective review, and diagnostics.
- Many questions share state and run in one round trip.
- Very low published token price and no output-token charge.
- Typed answers remove JSON/prose parsing failures at the classification layer.
- A fixed, versioned question set is easier to evaluate than a broad synthesis prompt.
- Complements the richer gold roles/links that production currently does not expose.
- Could catch evidence/rationale confusion before Pydantic drops a claim.
- Produces an inspectable initial graph instead of requiring zero-shot map discovery.

## Cons and risks

- Raw probabilities and Choice confidence are not automatically calibrated for Nexus.
- Question wording, type, criteria, and model version are part of the classifier and can shift behavior.
- Independent questions do not guarantee logically consistent answers.
- Paragraph-local context can miss cross-paragraph argumentative structure; document-wide context can cause distraction.
- The main thesis is inherently whole-document; local `is_load_bearing` scores are priors, not answers.
- Relation pairing can grow quadratically without deterministic shortlist rules.
- Noisy high-probability candidates can anchor the consolidating LLM and make it less willing to recover omitted claims.
- Aggressive deduplication can erase meaningful differences in horizon, modality, or stance.
- Incomplete batch coverage can look like negative classification unless coverage is explicit.
- Jev cannot generate or repair open-ended claims and provenance.
- Additional vendor, network, rate-limit, retention, and operational dependencies.
- Prompt injection/adversarial source prose is a documented weakness.
- A forced Choice without `none` will produce a plausible wrong label.
- Sidecar signals create schema/versioning complexity and another observability surface.
- If GPT context/calls are not reduced, Jev is additive cost and latency.
- Domain performance on sell-side research is unknown; vendor and sentiment benchmarks do not establish it.

## Sources

### Nexus code

- `packages/research_parser/src/research_memory/spans.py`
- `packages/research_parser/src/research_memory/records.py`
- `packages/research_analyst/src/research_analysis_layer/services/chunker.py`
- `packages/research_analyst/src/research_analysis_layer/services/evidence_builder.py`
- `packages/research_analyst/src/research_analysis_layer/services/assertion_extractor.py`
- `packages/research_analyst/src/research_analysis_layer/models/agent_outputs.py`
- `packages/research_analyst/src/research_analysis_layer/services/round_executor.py`
- `packages/research_analyst/src/research_analysis_layer/pipelines/analyze_document.py`
- `packages/research_analyst/src/research_analysis_layer/evals/gold_set.py`
- `packages/research_analyst/agent_config.yaml`

### Jev

- TypeSafe, [API reference](https://docs.typesafe.ai/api)
- TypeSafe, [Models and pricing](https://docs.typesafe.ai/models)
- TypeSafe, [System One](https://docs.typesafe.ai/concepts/system-one)
- TypeSafe, [Confidence](https://docs.typesafe.ai/confidence)
- TypeSafe, [Jev 1.13 jaggedness](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
- TypeSafe, [Parallel questions cookbook](https://docs.typesafe.ai/cookbooks/parallel_questions)
- TypeSafe, [Introducing System One Models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev)
- Ryan Porter / Anthus, [Can You Trust Jev's Confidence?](https://anth.us/blog/can-you-trust-jev-confidence/) — independent single-domain calibration experiment, not a Nexus benchmark
