# Decision real-document pilot plan

Status: approved 2026-11-09. Code is implemented; no model has been called on
the selected units yet.

Parent plan: [`2026-10-20-agent-reviewed-reference-expansion-plan.md`](2026-10-20-agent-reviewed-reference-expansion-plan.md), Slice 4 pilot.

## Goal

Find out where Jev is wrong on real research text it was never tuned on, and
leave behind a provisional reference set that later Jev versions can be scored
against without new labeling.

The output is:

- a per-question list of the units where Jev disagrees with two outside models
  from different families that agree with each other; and
- a provisional, agent-reviewed reference set.

It is not qualification. With 2 human-reviewed examples covering 5 of 12
questions, every question stays provisional whatever the results. Agreement
between two models is evidence, not truth: shared blind spots remain. Nothing
becomes gold, and nothing changes production routing.

## Why real text

All wording tuning so far (question sets v3–v5) used the 18 hand-written
fixture sentences, and Codex passes 1–3 saw them too. The earlier "live" runs
called live Jev on that fixture: `live_artifact_root` was null. Jev has never
been scored on real research.

## Frozen inputs

| Input | Value |
| --- | --- |
| Source documents | `analysis_documents` research_id 3, 4, 5 (Goldman Sachs 2026-09-21 duration; Morgan Stanley 2026-09-21 basis trade; Morgan Stanley 2026-09-20 euro bonds) |
| Units | `analysis_assertions` rows for those documents: 145 rows, 52 after exclusion rules v2 (14 / 13 / 25 by document) |
| Fixture overlap | 0 (checked by text match against fixture and `evals/` files) |
| Question set | `decision-question-set-v5`, hash `f2a2b8c1952652ca` |
| Selection | `select_stratified_pilot`, `max_units=50`, seed recorded in the pilot spec |
| Jev | `jev-1.13.0`, rerun on the selected units with v5 (cost: pennies) |

Unit preparation, all recorded as `transformations` on each source:

1. Strip the leading `<64-hex document hash>: ` prefix that every assertion
   text carries. Store the stripped text and its sha256.
2. Exclude legal and disclosure boilerplate with an explicit, versioned
   pattern list. Write the excluded rows to `excluded_units.jsonl` with the
   matching pattern, so the exclusions can be reviewed rather than trusted.
   - The rules also catch table rows, contact details, URLs, rating
     definitions, fragments under 40 characters, blobs over 1,200
     characters, and exact repeats within a document.
   - Everything from a report's trailing disclosures section onward is
     excluded. The section starts at the earliest boilerplate chunk, accepted
     only when at least half the units from there to the end are themselves
     excluded. That guard stops one stray phrase mid-report from cutting real
     content.
   - These rules were tuned by reading all 145 rows before any model saw
     them.
3. Keep text-extraction typos (for example "invest ent") as they are. Role
   instructions tell the models to judge meaning, not spelling.

Data exposure: the selected sentences go to Anthropic and OpenAI. The pipeline
already sends this research to both: the analyst sends it to OpenAI and the
dispatcher sends research content to Anthropic. No new provider is added.

## Models

| Role | Model | Price per 1M tokens (input / output) | Source |
| --- | --- | --- | --- |
| Annotator | `claude-sonnet-5-5`, official `anthropic` SDK | $2 / $10 | Claude API reference, cached 2026-10-06 |
| Reviewer | `gpt-5.6-terra`, existing OpenAI-compatible client | $2 / $12 | developers.openai.com pricing, checked 2026-11-09 |
| Adjudicator | off for this pilot | n/a | n/a |

- The two tiers are matched, so neither model is obviously the weaker labeler.
- Adjudication stays off because a third judgment cannot admit a label under
  the Slice 2 gate. Every disagreement is quarantined regardless, so the
  adjudicator would only add cost.
- Both pinned models must resolve to exactly the pinned ID, or the call is
  rejected.

Recorded correlation: Claude (through the coding agent) and GPT (through
Codex) both shaped the v3–v5 wording, and Jev's criteria came from that same
work. This is noted in the release manifest. It is not treated as
independence.

Alternative pair: `claude-opus-5-5` with `gpt-5.6-sol` ($4 / $20 each). That
costs about twice as much per call, so only about 25–30 units fit under the
cap.

### Swapping models and providers

Models are configured, not coded.

- **Catalog:** `evals/decision_pilot/models.json` lists every usable
  `provider:model` entry with its family, price card and sampling settings,
  plus the default model for each role.
- **Swap a model:** change the role's key in that file, or pass
  `--role reviewer=openai:gpt-5.6-sol` to `decision-agent-pilot prepare`.
- **Add a model:** add a catalog entry with its price card.
- **Add a provider:** register a client builder in `CLIENT_BUILDERS` in
  `decision_agent_models.py`.
- **OpenAI-compatible hosts** (for example open-weight families) use the
  `openai_compatible` provider with `base_url` and `api_key_env`.
- **Freezing:** `prepare` writes the resolved entries to `role_models.json`.
  A later catalog edit cannot change a prepared pilot, and `run` refuses a
  frozen model that differs from the pilot spec.

## Budget

- Hard cap: $5.00 in total. The harness `max_estimated_usd` is $4.50 for the
  main run. The remaining $0.50 covers the smoke run and Jev.
- Estimate: about $0.03–0.04 per call, assuming roughly 3k input tokens and
  1–3k output tokens including thinking. 50 units × 2 calls ≈ $3.0–4.0.
- Output and thinking tokens are the uncertain part, so a smoke run of 2 units
  (4 calls, about $0.15) measures real per-call cost first. The full run's
  unit count is then set from that measurement, never above 50.
- On hitting the cap, the harness stops with status `incomplete`. The results
  are reported as partial.

## Code changes

One PR in `packages/research_analyst`, tested with targeted pytest paths
only.

1. **Real-document unit export.** This adds the CLI `decision-real-units-export`.
   - It reads the database read-only.
   - It applies the prefix strip and the boilerplate exclusions.
   - It writes `AgentReferenceSource` records and a units file that Jev can
     classify.
   - It runs Jev v5 and writes a shadow artifact, so the existing pilot loader
     and comparison code can be reused.
2. **Completeness gate.** The provider rejects any response that does not
   address all 12 axes. Each axis must be either `labeled`, or `unresolved` or
   `abstained` with a reason. A rejected response gets one schema repair.
   This fixes the Codex pass 3 failure mode, where 132 of 216 questions were
   skipped.
3. **Computed span offsets.**
   - Models return only the quoted words. The provider computes `start` and
     `end` by locating the quote in `target_text`.
   - A quote that is missing or ambiguous triggers a schema repair. This fixes
     the bad-offset rejections from Codex pass 3.
   - The span schema sent to the model drops `start` and `end`.
4. **Anthropic client.** This adds a `reference_calls_are_single_attempt`
   client on the official `anthropic` SDK.
   - It reports effective sampling (`effort`) and returns the resolved model
     ID.
   - It adds `anthropic` as a dependency.
5. **Pilot run CLI.** This adds `decision-agent-pilot` with `--dry-run`,
   `--smoke N` and `--live`.
   - It writes the frozen pilot spec first.
   - It refuses to run if the spec, sources or question set have changed
     since then.
6. **Reference-vs-Jev report.** For each question, it reports:
   - how many labels were admitted and how many quarantined;
   - Jev's agreement with the admitted labels;
   - the list of disagreeing units.

## Success criteria (frozen before results)

- Every selected unit has both first passes on all 12 questions, or is listed
  as failed with the reason.
- The report gives, for each question: admitted count, quarantined count, and
  quarantine reasons, plus Jev disagreements with unit IDs and text.
- A separate reviewer can recompute every admission decision from the release
  files. A seeded 10% sample is re-checked by hand from the quoted spans.
- At most 3 policy escalations, each a compact root question.
- Total spend at or below $5.00, with actual cost per call reported.

## Per-question outcome rules (frozen before results)

Each question gets one of three outcomes.

| Outcome | Rule |
| --- | --- |
| Looks sound so far | At least 10 admitted labels, including at least 2 yes and 2 no (or 2 of each statement type seen), and Jev agrees on at least 90% of them |
| Wording needs work | Jev disagrees on more than 20% of admitted labels, or more than 40% of the units addressing the question are quarantined for model disagreement |
| Needs human labels | Anything else, including any question with fewer than 10 admitted labels |

The rules are applied in this order (`decision-agent-outcome-rules-v1`):

1. At least 10 units address the question and more than 40% are quarantined
   for model disagreement: wording needs work.
2. Fewer than 10 admitted labels: needs human labels.
3. Jev disagrees on more than 20% of comparable admitted labels: wording
   needs work.
4. Both answers appear at least twice, and Jev agrees on at least 90%: looks
   sound so far.
5. Anything else: needs human labels.

These rules are deliberately simple. They choose the next step for each
question and do not certify anything.

## Out of scope

- Qualification against human labels, gold promotion and production routing.
- Extracting assertions from more documents. That is the next scale-up, and it
  spends on the analysis pipeline outside this cap.
- Changes to the question wording during the pilot. Any change starts a new
  pilot.

## Order of work

1. Implement code changes 1–6 with scripted-provider tests. No spend.
2. Run the export and the dry run, and review the selected units and
   exclusions. Cost: Jev only.
3. Smoke run of 2 units, then report the real per-call cost. About $0.15.
4. Full run sized from the smoke cost. About $3–4.
5. Report, plus up to 3 policy escalations.
