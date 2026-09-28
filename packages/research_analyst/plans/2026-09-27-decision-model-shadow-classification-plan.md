# Decision-model shadow classification plan

Status: ready for implementation
Captured: 2026-09-27 America/New_York

## Objective

Add a provider-neutral, shadow-mode decision-classification experiment to
`research_analyst`. Jev is the first provider, but the rest of the pipeline must
depend only on normalized decision-model contracts so additional typed decision
models can be added later.

The initial implementation must not change canonical `DocumentAnalysis`,
`ClaimNode`, argument-map output, or downstream dispatcher behavior.

## Existing context

The package already has the main inputs and evaluation surfaces needed for the
experiment:

- `services/assertion_extractor.py` produces deterministic assertion units.
- `services/evidence_builder.py` provides source-grounded evidence.
- `models/agent_outputs.py` defines the current `ClaimNode` and
  `EvidenceRef` contracts.
- `services/round_executor.py` owns LLM orchestration and argument-map
  coercion.
- `pipelines/analyze_document.py` already supports shadow-style execution.
- `evals/` contains golden documents, result storage, comparison utilities,
  and judge infrastructure.

The first experiment should classify existing deterministic assertion units,
not introduce a new argument-discovery pipeline.

## Scope boundary

### In scope

- A small provider-neutral decision-model interface.
- A Jev adapter behind that interface.
- Batched classification of existing assertion units.
- Versioned, source-grounded sidecar artifacts.
- Retry, timeout, malformed-response, and incomplete-coverage handling.
- A shadow-mode/evaluation runner with no canonical output changes.
- Initial classification axes:
  - mutually exclusive statement type;
  - semantic subtype signals;
  - support/grounding signal;
  - explicit `uncertain`/`none` outcomes where applicable.
- Unit, contract, and evaluation tests.
- Gold labels and metrics sufficient to assess accuracy and calibration.

### Not in scope

- Replacing the existing synthesizer or deterministic assertion extractor.
- Writing Jev labels into `ClaimNode` or production database tables.
- Filtering production claims based on Jev thresholds.
- Full rhetorical-function taxonomy.
- Pairwise relation classification or contradiction inference.
- Automatic claim splitting or open-ended claim generation.
- Scaffold-to-synthesizer integration.
- A provider registry, plugin loader, or dynamic model discovery system.
- Privacy/legal approval for confidential production documents.

## Architecture

```text
existing parsed document
        |
        v
existing AssertionDraft units
        |
        v
provider-neutral ShadowClassifier
        |
        +--> DecisionModel adapter
        |       |
        |       +--> JevDecisionModel
        |
        +--> normalized DecisionBatchResult
        |
        v
versioned sidecar evaluation artifact
        |
        v
classification/calibration report
```

The provider boundary must be injected. The classifier, artifact writer, and
evaluator must not import Jev types or depend on Jev response JSON.

## Provider-neutral contracts

Add focused models, likely in
`src/research_analysis_layer/models/decision_models.py`:

- `DecisionQuestion`
  - stable question ID;
  - target unit ID;
  - question kind;
  - options for Choice-like decisions;
  - wording/version metadata.
- `DecisionBatch`
  - batch ID;
  - shared context;
  - target units;
  - questions;
  - source/document metadata.
- `DecisionResult`
  - question ID and target unit ID;
  - normalized answer/distribution;
  - raw provider payload, if retained;
  - status (`complete`, `uncertain`, `failed`);
  - provider/model metadata.
- `DecisionBatchResult`
  - batch status;
  - results;
  - missing or unknown IDs;
  - retry count;
  - latency and usage metadata;
  - provider error information.
- `DecisionModelMetadata`
  - provider name;
  - pinned model version;
  - question-set version;
  - adapter version.

Define a small protocol/ABC, likely in
`src/research_analysis_layer/services/decision_model.py`, with one batch
operation and capability metadata. Keep it synchronous/asynchronous according
to the package's existing client conventions; do not introduce a new
concurrency framework.

The normalized contract must not assume that every future provider has Jev's
specific confidence semantics. Raw provider-specific fields may be retained
under an adapter-owned payload, but normalized probabilities and statuses must
have documented meanings.

## Jev adapter

Add a Jev implementation, likely in
`src/research_analysis_layer/services/jev_decision_model.py`.

Responsibilities:

- translate normalized batches into Jev requests;
- preserve stable question and unit IDs;
- parse provider responses into normalized results;
- retain full distributions rather than only winning labels;
- capture resolved model version and request metadata;
- classify provider failures as retryable or permanent;
- never convert missing/failed responses into negative classifications.

Keep transport concerns isolated so adapter tests can use a fake transport.
Do not make the rest of the package aware of Jev request or response objects.

Configuration should select the provider and pinned model version through the
existing `Settings`/environment pattern. The experiment must be disabled by
default and must fail closed when required credentials or configuration are
missing.

## Shadow classifier

Add a runner, likely in
`src/research_analysis_layer/evals/decision_classifier.py`, that:

1. receives existing assertion units and source metadata;
2. builds stable unit IDs and source-grounded question inputs;
3. batches units by bounded size and coherent document/section context;
4. sends independent questions through the injected `DecisionModel`;
5. preserves source order during scatter/gather;
6. records incomplete coverage explicitly;
7. writes sidecar artifacts without modifying `DocumentAnalysis`.

The initial runner should use existing assertion provenance such as assertion
keys, chunk/order information, source text, section context, and document hash.
Do not invent new source identifiers when existing identifiers are available.

## Sidecar artifact

Use a versioned JSON or JSONL artifact under the existing evaluation output
conventions. Each unit result should retain:

- document key/hash and batch ID;
- stable unit and source identifiers;
- verbatim source text or a safely bounded representation;
- question-set version;
- provider, adapter, and pinned model versions;
- normalized distributions and selected outcomes;
- raw versus calibrated values as separate fields;
- classification status;
- retry count, latency, usage, and error metadata;
- coverage status for missing or failed questions.

Raw values must never be overwritten by later calibration. Artifact schema
changes require a version bump.

## Initial question set

Start with a narrow, versioned question set:

1. `statement_type` — one Choice-like outcome:
   `assertion`, `evidence_report`, `question`, `recommendation`,
   `background_methodology`, `other_or_unclear`.
2. Semantic subtype Nouls/signals:
   `is_observation`, `is_forecast`, `is_causal`, `is_market_impact`,
   `is_policy_claim`, `is_risk_or_scenario`, `is_comparative`,
   `is_trade_or_action`.
3. Support/grounding signals:
   `contains_verifiable_evidence`, `contains_reasoning_bridge`, and
   `is_substantive_author_claim`.

Do not treat any individual Jev score as argument quality or truth. The
classifier output is an observation used for evaluation and later candidate
generation.

## Failure handling

The implementation must explicitly handle:

- missing credentials/configuration;
- request timeout;
- rate limiting and transient provider errors;
- permanent provider errors;
- malformed provider JSON;
- invalid probability ranges or distributions;
- duplicate or unknown question IDs;
- partial batch responses;
- empty assertion input;
- provider/model version drift.

Permanent or partial failures must be visible in the artifact and report. A
failed batch must not silently become an all-negative result.

## Evaluation plan

Use a held-out split of private gold argument maps plus representative
production-like captures. Include deliberately difficult examples:

- compound claims;
- evidence mixed with interpretation;
- qualifiers and conditions;
- recommendations and questions;
- non-substantive/background prose;
- malformed or ungrounded evidence;
- competing or contradictory interpretations.

Measure separately:

- Choice confusion matrix and macro-F1;
- Noul precision/recall;
- AUROC/AUPRC where labels support it;
- Brier score and expected calibration error;
- abstention/uncertain rate;
- source/provenance coverage;
- incomplete-batch and permanent-error rates;
- p50/p95 latency and provider cost;
- comparison with the current deterministic classifier.

Calibrate on a separate split. Store calibration version and method alongside
the raw output; never interpret raw provider confidence as correctness without
Nexus-specific validation.

## Tests

Add tests for:

- generic runner behavior with a fake `DecisionModel`;
- stable source/unit IDs and provenance preservation;
- batching and deterministic source-order reconstruction;
- overlapping independent signals;
- explicit `none`/`uncertain` outcomes;
- normalized distribution validation;
- retryable versus permanent errors;
- timeout and partial-response coverage;
- malformed responses and unknown IDs;
- raw/calibrated field separation;
- provider/model/question-set metadata;
- disabled-by-default configuration;
- Jev adapter request/response translation;
- no mutation of canonical argument-map output;
- evaluation metrics on a small fixed fixture.

Test the generic runner independently from Jev so future decision-model
adapters do not require duplicating the full test suite.

## Acceptance criteria

- A fake provider can run the full shadow-classification flow without Jev.
- Jev is selected only through configuration and implements the generic
  decision-model contract.
- Existing analysis output and dispatcher payloads are byte-for-byte unchanged
  when the experiment is disabled.
- Shadow artifacts are source-grounded, versioned, and auditable.
- Partial coverage and provider failures are explicit and test-covered.
- Raw distributions are retained separately from calibrated values.
- Initial gold evaluation reports classification, calibration, coverage,
  latency, and cost metrics.
- No production filtering or argument-map persistence occurs before promotion
  gates are reviewed.

## Promotion gates

Do not proceed to scaffold generation until all of the following are reviewed:

- held-out classification quality meets the agreed per-axis targets;
- calibration is measured and usable for routing;
- load-bearing assertion recall is not worse than baseline;
- grounding/provenance coverage does not regress;
- incomplete-batch and provider failure behavior is operationally acceptable;
- latency and cost fit the document-processing budget;
- privacy/legal review permits the selected document classes to leave Nexus.

## Follow-up after promotion

Only after the shadow experiment passes should a separate plan cover:

1. deterministic candidate scaffold generation;
2. candidate provenance and unresolved-candidate handling;
3. bounded relation pairing;
4. LLM consolidation with Jev outputs treated as revisable signals;
5. shadow comparison against the current synthesizer;
6. eventual production schema and rollout changes.

