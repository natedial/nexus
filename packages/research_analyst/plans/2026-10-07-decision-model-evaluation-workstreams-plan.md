# Decision-model evaluation workstreams plan

Status: implementation in progress
Captured: 2026-10-07 America/New_York

## Implementation progress

- Phase 0 foundation started on 2026-10-07 in
  `research_analysis_layer.evals.decision_reviews`.
- Structured review records, lifecycle validation, immutable artifact and
  approval-trace checks, separate candidate/gold coverage, readable change
  reports, and proposed release manifests are implemented with tests.
- Import of the three agreed decisions is pending restoration of the original
  five-document run directory. Its `REVIEW_NOTES.md` and shadow artifacts are
  not present in this checkout, so their text, IDs, and approval hashes cannot
  be transcribed safely yet.

## Objective

Turn the Jev shadow experiment into a durable evaluation program while treating
human review time as the scarce resource. Separate work into:

1. a **human-in-the-loop lane** for decisions that require domain judgment; and
2. an **agent-friendly lane** for preparation, execution, measurement, and
   reporting that agents can complete independently.

The agent-friendly lane must leave clean, versioned outputs that another agent
can inspect without rerunning the experiment or reconstructing hidden context.
Neither lane promotes Jev into production routing. All work remains shadow-only
until the existing promotion gates are met.

## Current starting point

The repository already provides:

- a provider-neutral `DecisionModel` interface and live Jev adapter;
- versioned question-set snapshots and shadow artifacts;
- an 18-unit machine-readable decision fixture with gold labels;
- deterministic assertion types and baseline mappings;
- classification, coverage, provenance, latency, and error metrics;
- a completed five-document Jev run containing 65 fully covered units;
- three agreed review decisions currently recorded as prose in
  `REVIEW_NOTES.md` alongside that run.

The three agreed decisions expose useful edge cases:

- unrelated recommendation language contaminating a forecast classification;
- a negative or status-quo recommendation being missed;
- a sentence combining dominant forecast content with a secondary action.

## Operating principle

Humans should decide semantics, not prepare files, run models, calculate
metrics, or format reports.

Agents should do all work that can be reproduced from explicit rules and
versioned inputs. When an agent cannot resolve a case without making a semantic
judgment, it must add the case to a bounded review queue rather than invent a
gold label.

```text
agent prepares candidates and evidence
                |
                v
human adjudicates only selected cases
                |
                v
agent validates, scores, tests, and reports
```

## Lane A: human-in-the-loop work

This lane is deliberately small and asynchronous. Human availability controls
the growth rate of the gold set, but it must not block agent work elsewhere.

### A1. Adjudicate selected gold candidates

For each candidate, the reviewer decides:

- the primary `statement_type`;
- the applicable overlapping signals;
- whether the unit is substantive;
- whether evidence or an explicit reasoning bridge is present;
- the exact text scope being judged;
- whether the case is genuinely ambiguous or should have a definite label.

The review interface should present the sentence, minimal surrounding context,
the stored model input, Jev's result, deterministic baselines, and the reason
the case was selected. The reviewer should not have to search artifacts.

### A2. Resolve taxonomy questions

Human judgment is required when a case reveals a definition problem rather than
an ordinary model error. Current examples include:

- whether `is_market_impact` means any statement about a market variable or
  specifically a causal market effect;
- how a single primary type should represent mixed forecast/action sentences;
- whether dominant and secondary signals need separate annotation fields;
- how negative and status-quo actions fit `recommendation` and
  `is_trade_or_action`.

Taxonomy decisions must be recorded once in the question-set specification and
then applied mechanically by agents. Humans should not repeatedly answer the
same policy question case by case.

### A3. Audit a small random sample

Disagreement-driven sampling can miss cases where every automated system makes
the same mistake. A reviewer should inspect a small random sample from each
evaluation cycle. Start with the smaller of:

- 20 units; or
- 1% of newly classified units.

The audit rate may be reduced after several stable cycles, but should not reach
zero.

### A4. Approve gold-set releases

An agent may prepare and validate a proposed gold-set change, but a human must
approve:

- new gold labels;
- changed gold labels;
- taxonomy or question-set changes; and
- retirement of an existing gold case.

### Human review budget

Target a review packet of 10-20 cases per session. Each packet should prioritize
cases that add new semantic coverage, resolve high-impact disagreement, or test
a suspected failure mode. Do not ask the reviewer to label large random batches
merely to increase the count.

## Lane B: agent-friendly work

Agents may complete this lane end to end using the checked-in contracts and the
latest approved gold-set release.

### B1. Convert agreed prose reviews into structured candidates

Parse existing agreed review notes into proposed machine-readable records. Each
record must preserve:

- `review_id`;
- document and unit IDs;
- exact sentence scope;
- stored model input when it differs from the reviewed scope;
- question-set and model versions;
- primary statement type;
- all reviewed binary signals;
- optional dominant and secondary signal annotations;
- reviewer, review date, and approval status;
- rationale and issue tags;
- source artifact reference.

Already-agreed notes may be proposed for import without requesting the same
human judgment again. An agent must still validate that the text and IDs match
the immutable source artifacts before inclusion.

### B2. Build the gold-set maintenance tooling

Add tools that:

- validate schema and allowed labels;
- reject duplicate unit/version pairs;
- preserve review history instead of silently overwriting labels;
- detect source-text or question-set drift;
- produce a readable diff for proposed gold changes;
- split data by document so related units cannot leak across calibration and
  evaluation partitions;
- report label and document-type coverage.

Agents may prepare releases, but only approved records count as gold.

### B3. Generate silver labels

Create high-precision, rule-attributed labels from existing deterministic
signals and text structure. Initial rules may include:

- deterministic `open_question` to statement type `question`;
- deterministic `trade_claim` to `recommendation` and
  `is_trade_or_action=yes`;
- explicit recommendation language, including negative/status-quo forms;
- concrete statistics, named releases, quotations, citations, and figure
  references to `contains_verifiable_evidence=yes`;
- methodology headings and boilerplate patterns to
  `background_methodology` when unambiguous.

Every silver record must include the generating rule, rule version, confidence
tier, and any conflicting rule matches. Conflicted or low-confidence records
must be excluded from silver metrics and may become review candidates.

Silver labels must never be merged into the gold set automatically.

### B4. Add consistency and metamorphic tests

Generate semantically controlled variants and compare Jev outputs. The first
test families are:

1. **Context isolation:** clean sentence versus contaminated prefixes,
   headings, or neighboring sentences.
2. **Negative recommendation equivalence:** hold, maintain, refrain, and
   do-not-reposition phrasings.
3. **Compound decomposition:** combined forecast/action sentence versus its
   clauses classified separately.
4. **Batch invariance:** batch sizes 1, 2, 4, and 8, plus changed neighbors and
   order.
5. **Formatting invariance:** whitespace, bullets, headings, and harmless
   punctuation changes.
6. **Repeatability:** identical live requests repeated across a bounded number
   of runs.

Each family must define expected stable fields and probability tolerances.
Choice-label flips, high-confidence binary flips, and excessive probability
movement must be reported separately. A transformation that changes meaning
must not be treated as an invariance test.

### B5. Run gold, silver, and consistency evaluations separately

Do not collapse the three evidence types into one score:

- **gold metrics** estimate performance against approved human judgment;
- **silver agreement** finds broad regressions against automated rules;
- **consistency metrics** measure sensitivity without assuming a gold answer.

Agents should also calculate coverage, abstention, failure rate, latency,
provider usage, and estimated dollar cost for every run.

### B6. Build the review queue automatically

Select a bounded set of candidates using explicit priority rules:

1. high-confidence disagreement with gold;
2. disagreement on a load-bearing or actionable statement;
3. consistency-test failure;
4. Jev versus deterministic/silver disagreement;
5. new or underrepresented taxonomy case;
6. uncertainty near a proposed routing threshold;
7. random audit sample.

Near-duplicates should be clustered so a reviewer sees one representative case
unless the variation itself is the subject of the test.

### B7. Produce agent-reviewable outputs

Every evaluation run must write one immutable run directory containing:

```text
run_manifest.json
question_set.json
gold_metrics.json
silver_agreement.json
consistency_report.json
cost_and_latency.json
review_queue.jsonl
review_packet.md
SUMMARY.md
artifacts/
```

`run_manifest.json` is the source of provenance and must include code revision,
provider/model version, question-set hash, dataset versions, command arguments,
timestamps, and content hashes for every top-level output.

`SUMMARY.md` is the entry point for another agent. It must state:

- what changed from the comparison run;
- passes, regressions, and unresolved concerns;
- metric denominators, not only percentages;
- the highest-priority review cases;
- whether any promotion gate changed state;
- exact links or paths to supporting JSON and artifacts.

The report must distinguish observed facts from hypotheses. For example,
"classification changed when a prefix was present" is an observation;
"the prefix caused the error" remains a hypothesis until tested.

## Shared data contracts

### Gold record lifecycle

Use explicit states:

- `candidate`: agent-prepared, not trusted as gold;
- `agreed`: human-approved and eligible for the next release;
- `superseded`: retained for history but replaced by a later adjudication;
- `retired`: excluded with a recorded reason.

### Dominant versus secondary content

Keep the mutually exclusive primary `statement_type`. Add optional review-only
metadata for `dominant_signals` and `secondary_signals` rather than weakening
the existing binary result contract immediately. Promote those fields into the
runtime contract only if the expanded gold set proves they are needed.

### Version isolation

Gold labels attach to exact source text and a taxonomy/question-set version.
When wording changes the intended meaning of a label, create a new label
version or require migration review. Do not silently score old judgments under
new definitions.

## Execution phases

### Phase 0: preserve existing decisions

Agent-friendly:

- convert the three agreed review notes into proposed structured records;
- validate them against the five-document artifacts;
- generate a gold-change diff and coverage report.

Human-in-the-loop:

- approve the import only if any transcription ambiguity remains; otherwise
  retain the recorded `agreed by Nate` status and avoid duplicate review.

### Phase 1: automated evaluation foundation

Agent-friendly:

- implement gold validation and release manifests;
- implement the first high-precision silver rules;
- implement the six consistency-test families;
- add cost estimation and standardized run outputs;
- add unit and integration tests.

Human-in-the-loop:

- resolve the `is_market_impact`, negative recommendation, and mixed-content
  taxonomy questions once.

### Phase 2: targeted gold expansion

Agent-friendly:

- score the existing 65-unit live run;
- cluster disagreements and underrepresented cases;
- prepare review packets of 10-20 cases;
- incorporate approved decisions and regenerate reports.

Human-in-the-loop:

- review only the prepared packets;
- prioritize semantic coverage over raw case count.

Continue until the gold set has enough support per important axis to make its
metrics interpretable. The earlier 100-200 unit target is a direction, not a
reason to spend human time on redundant cases.

### Phase 3: calibration and promotion evidence

Agent-friendly:

- create document-isolated calibration and held-out splits;
- calculate Brier score, expected calibration error, AUROC/AUPRC where valid,
  and category-specific thresholds;
- compare model and question-set versions;
- run drift, latency, reliability, and cost reports;
- propose promotion-gate results with supporting evidence.

Human-in-the-loop:

- audit the held-out results and threshold tradeoffs;
- approve or reject any production promotion separately.

## Review packet design

To minimize human time, each review case should fit on one screen and show:

1. exact sentence to label;
2. optional surrounding context in a collapsed section;
3. stored model input with differences highlighted;
4. Jev result and probabilities;
5. deterministic and silver results with rule names;
6. the precise questions requiring judgment;
7. suggested labels clearly marked as agent proposals;
8. a short rationale field and approve/edit/defer outcome.

Do not expose raw provider payloads unless they are needed to investigate a
specific failure.

## Acceptance criteria

### Human lane

- No review packet exceeds 20 cases by default.
- Reviewers are never asked to recover context manually from raw artifacts.
- Agreed decisions are not presented again unless the taxonomy or source text
  changed.
- Every gold change has explicit human approval or an existing recorded
  approval trace.

### Agent lane

- One command produces the complete versioned run directory.
- Gold, silver, and consistency results remain separate.
- All generated labels and transformations carry rule/version provenance.
- Another agent can reproduce conclusions from `SUMMARY.md` and the referenced
  machine-readable outputs.
- Failures and missing coverage never become negative labels.
- No agent can promote a candidate label to gold or enable production routing.

## Immediate next actions

1. Define the structured review-record schema and import the three agreed notes
   as candidates.
2. Add a gold-set validator, release manifest, and readable change report.
3. Implement context-isolation tests using the contaminated-prefix case.
4. Implement negative/status-quo recommendation silver rules and metamorphic
   variants.
5. Implement compound-sentence decomposition tests without changing the
   runtime output schema.
6. Produce the first standardized run directory over the 18-unit fixture and
   65-unit live corpus.
7. Generate the first bounded human review packet from the resulting gaps and
   disagreements.
