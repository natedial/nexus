# Claim notes (`claim-note-v1`)

Deterministic product contract for one argument per record. Shared by five products (see Agent Store `docs/claim-note-products-plan.md`).

## Locked rules

- **Cause edge** (`cause_edges[]`): speaker says X causes Y — own edge, separate from `thread_role`. Stored as said; not fact-checked; no causal world model.
- **`speaker_weight`**: role enum only — `chair` | `voter` | `non-voter` | `interview` | `research_author`. Not a 0–1 score.
- **Speaker vs publisher**: who said it vs which document/house it came from — keep both fields distinct.
- **Dexter**: pointer, not an in-Nexus call. Product marks `dexter_pass.status=awaiting` and stops; Dexter attaches `completed` findings + sources externally. Products never fill numbers.
- **Thematic side**: stance on *that thread*, not a global hawk/dove label.
- **Morning attention** (later PR): own 3–5 point surface; *reads* G10 calendar + LIBRARY digest as inputs; does not change 5:55/6:10 tablet pushes.

## Commands

From `packages/research_dispatcher`:

```bash
python -m unittest discover -s tests/claim_notes -v
```

Fixtures: `fixtures/claim_notes/claim_notes.jsonl`
