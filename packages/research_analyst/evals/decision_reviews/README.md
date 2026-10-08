# Decision review records

This directory is the checked-in home for decision-model review history. Review
records remain separate from the older 18-unit fixture labels because they have
an explicit lifecycle and attach to immutable live-run artifacts.

Only records with `status=agreed`, a human approval trace, and successfully
verified source files are eligible for a proposed gold release. The tooling
never changes a record's status and never changes production routing.

## Record contract

Each JSON or JSONL record is validated by
`research_analysis_layer.evals.decision_reviews.DecisionReviewRecord` and
contains:

- exact reviewed text and its SHA-256 hash;
- stored model input and its hash when the reviewed scope is narrower;
- document/unit identity and document type;
- provider, model, adapter, question-set version, and question-set hash;
- one primary `statement_type` and all binary decision labels;
- optional dominant and secondary signal annotations;
- reviewer, review date, lifecycle status, rationale, and issue tags;
- a content-addressed relative path to the source shadow artifact; and
- for agreed records, a content-addressed approval-note reference.

Relative paths are resolved under the supplied artifact root. Absolute paths
and parent traversal are rejected so a release can be inspected from one
bounded run directory.

## Prepare a proposed release

From `packages/research_analyst`:

```bash
uv run python -m research_analysis_layer.evals.decision_reviews \
  --records evals/decision_reviews/reviews.jsonl \
  --artifact-root /path/to/immutable-five-doc-run \
  --output evals/results/decision-gold-candidate-v1 \
  --release-version decision-gold-candidate-v1
```

The command writes:

- `review_record.schema.json` — the machine-readable JSON Schema for one
  review record;
- `validation.json` — schema, lifecycle, source-text, question-set, model, and
  approval-trace checks;
- `coverage.json` — separate agreed-gold and candidate coverage;
- `CHANGE_REPORT.md` — readable additions, changes, and removals relative to
  `--previous`, when supplied; and
- `release_manifest.json` — content hashes and the exact agreed records
  eligible for the proposed release.

Omitting `--artifact-root` is useful for schema-only checks, but produces a
`proposed_unverified` manifest with no eligible records.

## Updating a judgment

Do not overwrite the old event. Keep it with `status=superseded`, add a new
record with a new `review_id`, and set `supersedes_review_id` to the retained
record. At most one `candidate` or `agreed` record may be active for a given
document, unit, and question-set version.
