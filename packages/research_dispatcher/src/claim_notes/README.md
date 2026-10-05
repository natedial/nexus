# Claim notes (`claim-note-v1`)

Deterministic product contract for one argument per record. Shared by five products (see Agent Store `docs/claim-note-products-plan.md`).

## Rules

- **Cause edge** (`cause_edges[]`): speaker says X causes Y — own edge, separate from `thread_role`. Stored as said; not fact-checked; no causal world model.
- **Live numbers**: only from a completed `DexterResearchPass`. Do not invent or fill numbers.
- **Speaker weight**: on the note only — never passed to graphic selection (#45 shape→pattern).
- **Morning attention** (later PR): own 3–5 point surface; *reads* G10 calendar + LIBRARY digest as inputs; does not change 5:55/6:10 tablet pushes.

## Commands

From `packages/research_dispatcher`:

```bash
python -m unittest discover -s tests/claim_notes -v
```

Fixtures: `fixtures/claim_notes/claim_notes.jsonl`
