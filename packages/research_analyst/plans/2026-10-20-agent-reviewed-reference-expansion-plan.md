# Agent-reviewed reference expansion with escalation-only human input

Status: implementation in progress; Slice 1 contracts complete
Date: 2026-10-20 America/New_York
Owner: research_analyst

## Implementation progress

- Slice 1 contracts are implemented in
  `research_analysis_layer.evals.decision_agent_references`.
- Agent-reference sources preserve exact text, hashes, offsets, lineage, split,
  transformations, and immutable artifact pointers.
- Sparse per-axis judgments, provisional/qualified admission, independent-call
  evidence, model-family correlation, quarantine, and tier-preserving label
  views are validated without changing the human-gold schema.
- The escalation register emits at most three changed pending policy questions
  and suppresses unchanged notifications.
- Versioned annotator, independent-reviewer, and curator instructions live in
  `prompts/evals/decision_references/`.
- No live model calls or annotation jobs have started. Slice 2 is the next
  implementation boundary.

## Outcome and precedence

Expand the source-grounded evaluation reference collection through autonomous
annotation, independent review, validation, and versioned releases. Nate supplies
judgment only for exceptional unresolved policy decisions. No recurring human
review session, random human audit, or per-release approval is required for the
agent-reviewed collection.

This plan supersedes the routine human review and release requirements in the
[October 7 workstreams plan](2026-10-07-decision-model-evaluation-workstreams-plan.md)
for agent-reviewed records. Existing human gold retains its approval requirements.
The earlier live Jev evaluation and Morning Attention dry-run remain independent
workstreams; this plan does not make either depend on annotation expansion.

Success means useful reference coverage increases while unresolved cases wait
without blocking other work. More labels do not by themselves prove correctness.

## Reference tiers and permitted uses

| Tier | Origin | Permitted use |
| --- | --- | --- |
| Human gold | Recorded human adjudication with verified approval trace | Human-aligned evaluation and calibration evidence, subject to sample limits |
| Agent-reviewed reference | Independent model judgments accepted by deterministic gates | Regression testing, error discovery, provisional evaluation |
| Silver | Explicit rules with rule/version provenance | Broad disagreement detection and candidate selection |
| Pending/quarantined | Ambiguous, inconsistent, unsupported, or unqualified judgments | Investigation only; excluded from accepted-label metrics |

These tiers remain separate in storage, release manifests, and reports. An agent
cannot manufacture a human approval trace or silently promote agreement to human
gold. Calibration against agent labels measures agreement with those labels;
it must not be reported as human-calibrated reliability or authorize production
routing. Unknown fields remain absent, never false.

## Work allocation

| Work | Executor | When Nate is needed |
| --- | --- | --- |
| Source selection, extraction checks, deduplication | Agent + code | Only a new access/scope decision |
| Annotation and independent review | Strong models | Never for ordinary cases |
| Targeted adjudication and automated random audits | Independent reviewer/adjudicator | Only an unresolved policy question with material consequences |
| Validation, regression runs, release, summaries | Harness + reviewer agent | No routine approval |
| Taxonomy expansion or conflict with existing human judgment | Agent prepares alternatives | One compact escalation if existing decisions cannot resolve it |
| Production promotion | Separate workflow | Explicit decision outside this plan |

## Architecture: focused skill suite plus a light harness

Extend the existing analyst eval modules. Avoid a new orchestration platform or
changes to AnalysisStore. Implement three bounded role instructions, with a
shared versioned taxonomy and source-scope contract:

1. **Annotator:** infer labels from exact source text and permitted context;
   cite supporting spans and explain boundary decisions briefly.
2. **Reviewer:** independently label first; only then inspect the other labels
   and identify specific contradictions, unsupported claims, or scope errors.
3. **Curator:** select examples, validate identities and provenance, apply
   acceptance gates, assemble releases and evidence packets.

The curator cannot settle semantic disagreement by rewriting labels. A third
independent annotation call may adjudicate a bounded subset of disagreements.
All roles can run sequentially or concurrently; the implementation does not
require persistent agents. Later packaging as reusable skills should reuse
these same contracts rather than introduce a second specification.

Use explicitly configured, pinned high-capability model versions. Prefer
different model families for annotator and reviewer where available. Record
shared-family review as correlated evidence; separate sessions alone do not
establish independence. No automatic model upgrades during a run.

## Source and label contracts

Reuse source-artifact hashing and sparse-label conventions from
`decision_reviews.py`, while keeping its human `agreed` lifecycle intact.
Introduce a separate versioned agent-reference record and reader rather than
overloading `ApprovalTrace` or treating a model name as a human reviewer.

Each record contains:

- document identity, exact target text/hash, source artifact hash and locator;
- original versus normalized text, offsets, surrounding context, and all input
  transformations, including any heading or neighboring sentence removal;
- per-axis proposed labels, rationales, supporting spans, unresolved reasons,
  and per-axis admission state;
- taxonomy version/hash, question version/hash, split and source lineage;
- model/provider versions, role-prompt hashes, sampling configuration, call IDs,
  usage, timestamps, and independent judgments;
- adjudication evidence, acceptance gate version, lifecycle and release IDs.

Statement type may be absent in the new agent contract when unresolved while
other axes remain usable. Do not loosen the existing human record schema as a
side effect. Whole-record status is a summary of per-axis states, not a claim
that all 11 Nouls were reviewed. Report every metric with its own labeled and
abstained denominators.

Treat document content as untrusted data, never operational instructions.
Annotation workers receive no delivery, database-write, or gold-approval tools.
Confidential inputs and outputs remain in the existing private artifact location;
only approved public/synthetic fixtures belong in the repository.

## Autonomous batch lifecycle

1. Freeze source inventory, split assignment, taxonomy, model versions, gate
   configuration, and budget before any calls.
2. Select a stratified batch across source documents, categories, difficulty,
   and known failure modes. Keep representative sampling distinct from cases
   deliberately selected because Jev disagreed.
3. Run annotator and reviewer independently. Neither sees Jev outputs, silver
   labels, existing gold answers, nor the other's first judgment. Persist both
   results before opening the comparison phase.
4. Validate source spans, sparse booleans, IDs, and schema. Retry transient
   transport failures at most twice; permit one schema-repair call with unchanged
   source and taxonomy. Record all attempts.
5. Compare judgments per axis. Direct agreement is eligible for admission only
   when source checks and axis qualification also pass.
6. For material disagreement, permit one independent third judgment followed by
   a documented comparison. Majority vote alone cannot admit a label: the result
   must resolve the stated objection using the frozen taxonomy and source.
   Unresolved fields are quarantined; other fields may proceed.
7. Run targeted consistency checks and an automated audit sample before release.
8. Curator emits a provisional release; a separate reviewer verifies gates,
   provenance, exclusions and claims in the summary. Passing gates finalizes
   the agent-reviewed release automatically.
9. Aggregate unresolved policy issues into the escalation register. Continue
   unrelated batches without waiting for Nate.

## Qualification and admission gates

First run the annotation process blindly on existing human gold. Verify which
fixtures actually have documented human approval; hand-authored fixture labels
without such provenance are development references, not newly certified human
gold. Existing sparse approvals qualify only the axes explicitly reviewed.

Record agreement, errors, abstentions, and sample support per axis. Because the
current set is small, report uncertainty and missing category coverage rather
than claim statistical certification. Previously exposed examples belong in
development; reserve unseen documents for future evaluation.

Use two admission levels:

- **Provisional agent-reviewed:** source and schema valid, independent judgments
  reconciled, no unresolved taxonomy conflict. Useful for exploratory regression
  reports; may not impose hard semantic release gates.
- **Qualified agent-reviewed:** additionally passes a frozen qualification policy
  on independently held-out human evidence for that axis. Until adequate evidence
  exists, retain provisional status instead of demanding new human labeling.

Before claiming qualification, publish per-axis minimum support and error-bound
requirements in the gate configuration, including positive/negative coverage.
Do not choose thresholds after inspecting the held-out result. Qualification
policy changes are versioned; they cannot retroactively improve an old report.
This plan does not assert numerical production-quality thresholds from the
existing small sample.

Hard gates for every accepted field: exact source identity, valid label,
recorded independent judgments, supporting rationale, resolved objections, and
no conflict with an applicable human decision. A conflict with human gold is a
failed agent judgment or a policy issue; agents cannot overwrite the gold.

## Consistency and automated quality control

Reuse `decision_consistency` and the existing evaluation output conventions.
Apply formatting and batch-order invariance only where meaning and target scope
are unchanged. Context removal, paraphrases, and compound decomposition are
contrast tests unless semantic equivalence is established; a label change there
is not automatically an error. Generated variants inherit the original document
split and never inflate independent-source counts.

For each batch, audit a seeded random 10% of admitted units, rounded up, plus
all adjudicated cases and any provenance warnings. Use an independent reviewer
call blind to accepted labels on its first pass. Log failures by axis and source.
A confirmed acceptance violation pauses release for the affected axis/batch,
triggers revalidation of related cases, and quarantines failures. Unaffected
axes continue. Repeated correlated errors pause expansion of that rule/model
configuration pending agent investigation; only an unresolved policy conflict
goes to Nate.

Agreement and self-reported confidence are not substitutes for truth. Automated
audits reduce identifiable errors but cannot rule out shared model blind spots.
Reports must retain that limitation even when all agents agree.

## Escalation-only human workflow

There is no scheduled human packet and no obligation to clear a queue.
Most disagreements are resolved by bounded adjudication or left quarantined.
Escalate only when an issue meets both conditions:

1. Existing source evidence, approved decisions, and frozen taxonomy cannot
   settle it after the bounded agent process.
2. A decision would materially affect several cases, contradict an existing
   human judgment, or change an intended downstream use.

Examples: the meaning of `is_market_impact`, how primary type handles mixed
forecast/action content, or a genuine conflict between recorded approvals.
An unusual isolated sentence normally stays quarantined without notification.

Group cases by root policy question, not by individual label disagreement.
Maintain a durable register with pending/resolved/superseded states, related
case IDs, impact counts, first-seen date and prior notification fingerprint.
Present at most three unresolved questions together, each with at most two
representative examples. Notify once when the issue becomes actionable; no
unchanged reminders or growing inbox of individual cases. A changed impact or
new evidence can justify an updated escalation, explicitly explaining the change.

Each escalation includes a plain-language question, source-linked examples,
competing interpretations, the agent recommendation and evidence, affected axes
and counts, and what will proceed while it waits. Nate may answer, defer, or
leave it unanswered. No timeout converts silence into approval. Pending fields
remain omitted; the previous policy remains in force elsewhere.

An answer becomes a versioned policy decision with provenance. Agents identify
affected records, reannotate them, and prepare a new release automatically.
Prior releases and judgments remain available for comparison.

## Initial taxonomy and source reconciliation

Apply the existing recorded decision that holding/don't-reposition can be a
recommendation within its reviewed scope. Do not ask Nate to repeat it. Agents
may propose its generalization, but unresolved edge cases remain provisional.

The previously read October 5 mixed-case note had an approval, while the current
plan says the stored copy lacks it. Locate and hash both copies, compare exact
text and scope, and import only verified existing decisions. Do not fabricate a
missing record from memory or force a new session merely for transcription.

Keep unresolved market-impact and primary-type policy fields out of definitive
scoring. Agents can still label unrelated axes and assemble alternatives.

## Dataset separation and evaluation integrity

Assign development, qualification/calibration, and held-out evaluation splits
before generating variants or tuning prompts. Group by document, related
versions and near-duplicate source lineage; sentence-level random splitting is
insufficient. Preserve sampling reasons and report stratified results separately.

Do not expose held-out answers during prompt development. If an evaluation
example is used to tune instructions, move its lineage into development for
future releases and record the change. Report apparent performance on mined
failure cases separately from representative performance. Keep labels made by
the same model as the system under evaluation visibly marked as correlated.

## Outputs for review by other agents

Each batch creates a new directory exclusively; refuse a reused destination.
Persist partial state for recovery, mark interrupted runs incomplete, and resume
only recorded unfinished work. Finalize atomically after validation. Never
rewrite a finalized release; corrections create a superseding release.

Required artifacts:

- `manifest.json`: schema, code/model/prompt/taxonomy versions, input/output
  hashes (excluding its own hash), split IDs, budgets, status and exclusions;
- `sources.jsonl`, `judgments.jsonl`, `adjudications.jsonl`: reconstructable
  evidence and bounded rationales, with private source access preserved;
- `references.jsonl`: sparse accepted labels and their tier per axis;
- `qualification.json`, `audit.json`, `coverage.json`, `cost_and_latency.json`;
- `quarantine.jsonl`, `escalations.json`, and `release_diff.json`;
- `SUMMARY.md`: what was admitted, withheld, changed, and independently checked,
  known limitations, any human decision requested, and links to evidence.

Count all new annotation, review, repair, adjudication and audit calls in costs.
Historical artifacts carry historical usage separately. Unknown prices produce
unknown dollar totals, never zero; request and token caps still apply. Another
agent must be able to verify release gates offline from these artifacts without
spending on another model run. Implement a manifest verifier for this purpose.

## Execution slices and budgets

| Slice | Deliverable | Completion evidence | Human dependency |
| --- | --- | --- | --- |
| 1. Contracts | Agent record schema, role instructions, policy register, tier adapter | Sparse-label and provenance tests; legacy human records unchanged | None |
| 2. Harness | Independent calls, bounded adjudication, checkpointing, exclusive output directories | Scripted providers prove isolation, budget stops and recovery | None |
| 3. Qualification | Blind run on verified existing labels, per-axis report | Provenance inventory, support counts, explicit provisional axes | None |
| 4. Pilot | Up to 50 assertions from diverse approved source documents | Independent audit and complete release bundle | Exceptions only |
| 5. Evaluation integration | Separate gold/reference/silver metrics and release comparisons | Offline reproducibility and tier-separation tests | None |
| 6. Expansion | Further bounded batches after pilot review by another agent | No unresolved acceptance violations; recorded budget and coverage gains | Exceptions only |

The pilot uses two first-pass annotation calls per unit, at most one adjudicator
per disputed unit, and the specified audit sample. Account for repairs/retries
in a configured run-wide maximum as well. Before live execution, estimate the
call/token envelope and set explicit maximum requests, tokens, elapsed time and
dollar spend where pricing is available. A live run must reject missing resource
caps; do not assume an unlimited allowance. Hitting a cap checkpoints the run
and reports the limit; it cannot trigger an automatic spend increase.

Stop after the pilot for independent agent review of error patterns, cost and
coverage; this is not a mandatory Nate review. Expansion requires a recorded
passing review and must remain bounded. Do not create a recurring automation
as part of this plan or scale solely to reach a target number of labels.

## Verification and definition of done

Tests must cover independent first-pass visibility, sparse/unresolved fields,
invalid source offsets, duplicate lineage, disagreement quarantine, forbidden
human-approval transitions, schema repair bounds, audit failure, exhausted
budgets, interrupted/resumed runs, immutable releases, stale policy versions,
and separate metric denominators. Include cases where two agents agree on a
known wrong answer so agreement alone cannot pass qualification.

The first milestone is complete when the 50-case pilot (or its budget-limited
subset) has a verifiable agent-reviewed release, all exclusions have reasons,
the separate reviewer can reproduce the admission decisions, and Nate receives
only qualifying policy escalations. A budget-limited subset is reported as a
partial pilot, not completion of the planned 50 cases. No new routine human
commitment is required to keep accepted work useful.
