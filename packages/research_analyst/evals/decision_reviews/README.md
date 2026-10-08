# Decision review records

This directory is the checked-in home for decision-model review history. Review
records remain separate from the older 18-unit fixture labels because they have
an explicit lifecycle and attach to immutable live-run artifacts.

Only records with `status=agreed`, a human approval trace, and successfully
verified source files are eligible for a proposed gold release. The tooling
never changes a record's status and never changes production routing.

Checked-in `reviews.jsonl` currently holds two already-agreed notes as
`decision-review-record-v2` records. Each is **partially labeled**: only the
Noul keys explicitly agreed in the note are stored. Omitted keys are
unreviewed — never stored as `false`, never inferred. Keep these records for
partial-label evaluation and regression tests. Workflows that require a full
11-Noul vector must exclude them (`require_complete=True` / the release
manifest's `eligible_complete_review_ids`) until a later review completes the
remaining axes.

## Record contract

Each JSON or JSONL record is validated by
`research_analysis_layer.evals.decision_reviews.DecisionReviewRecord` and
contains:

- exact reviewed text and its SHA-256 hash;
- stored model input and its hash when the reviewed scope is narrower;
- document/unit identity and document type;
- provider, model, adapter, question-set version, and question-set hash;
- one primary `statement_type` and any subset of the 11 recognized Noul
  labels (`noul_labels`). Null values are rejected; omitted keys are
  unreviewed;
- `label_completeness` (`complete` or `partial`) and `unreviewed_noul_ids`,
  derived from omitted recognized keys;
- optional dominant and secondary signal annotations;
- reviewer, review date, lifecycle status, rationale, and issue tags;
- a content-addressed relative path to the source shadow artifact; and
- for agreed records, a content-addressed approval-note reference.

Relative paths are resolved under the supplied artifact root. Absolute paths
and parent traversal are rejected so a release can be inspected from one
bounded run directory. For the checked-in records, that root is
`evals/decision_reviews/sources`.

## Prepare a proposed release

From `packages/research_analyst`:

```bash
uv run python -m research_analysis_layer.evals.decision_reviews \
  --records evals/decision_reviews/reviews.jsonl \
  --artifact-root evals/decision_reviews/sources \
  --output evals/results/decision-gold-candidate-v1 \
  --release-version decision-gold-candidate-v1
```

The command writes:

- `review_record.schema.json` — the machine-readable JSON Schema for one
  review record;
- `validation.json` — schema, lifecycle, source-text, question-set, model, and
  approval-trace checks;
- `coverage.json` — separate agreed-gold and candidate coverage, including
  yes/no/unreviewed/reviewed counts per Noul axis and complete/partial
  record counts;
- `CHANGE_REPORT.md` — readable additions, changes, and removals relative to
  `--previous`, when supplied; and
- `release_manifest.json` — content hashes, all eligible agreed records, and
  the split between `eligible_complete_review_ids` and
  `eligible_partial_review_ids`. Partial records stay available for
  per-axis scoring; they are excluded from full-vector metrics.

Omitting `--artifact-root` is useful for schema-only checks, but produces a
`proposed_unverified` manifest with no eligible records.

## Standardized evaluation run

Gold, silver, and consistency evidence stay in separate files. One command
writes the immutable run directory:

```bash
uv run python -m research_analysis_layer.evals decision-eval \
  --provider fake \
  --output evals/results/decision-eval-local \
  --live-artifact-root evals/decision_reviews/sources
```

`--live-artifact-root` is optional. When supplied, existing shadow artifacts
are hashed and copied into the run directory; they are not reclassified and
do not become gold. Agreed reviews are scored on the supplied labels only.
The command cannot promote a candidate label or change production routing.

## Updating a judgment

Do not overwrite the old event. Keep it with `status=superseded`, add a new
record with a new `review_id`, and set `supersedes_review_id` to the retained
record. At most one `candidate` or `agreed` record may be active for a given
document, unit, and question-set version.
