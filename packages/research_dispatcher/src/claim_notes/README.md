# Claim notes (`claim-note-v1`)

Deterministic product contract for one argument per record. Shared by five products (see Agent Store `docs/claim-note-products-plan.md`).

## Locked rules

- **Cause edge** (`cause_edges[]`): speaker says X causes Y — own edge, separate from `thread_role`. Stored as said; not fact-checked; no causal world model.
- **`speaker_weight`**: role enum only — `chair` | `voter` | `non-voter` | `interview` | `research_author`. Not a 0–1 score.
- **Speaker vs publisher**: who said it vs which document/house it came from — keep both fields distinct.
- **Dexter**: pointer, not an in-Nexus call. Product marks `dexter_pass.status=awaiting` and stops; Dexter attaches `completed` findings + sources externally. Products never fill numbers.
- **Thematic side**: stance on *that thread*, not a global hawk/dove label.
- **Morning attention**: own 3–5 point surface → reMarkable notebook (`Morning Attention YYYY-MM-DD`, next to G10 / Research From) + one-line **Grok Bot** ping to Nate’s 1:1 with Proey (not SMTP). **Live path:** analyst `export-dispatch-batch` → `--argument-map-json` / `--analyst-batch-dir` → `project.py` (Gerhard validators). Min analyst env: `RESEARCH_ANALYST_ANALYSIS_DB_URL` (or `NEXUS_DATABASE_URL`) with existing argmap-v1 `document_analysis` + `RESEARCH_ANALYST_BATCH_OUT_DIR`. Empty Proton `research_claims` is unrelated. Empty since-watermark export → silent MA (do not invent ClaimNodes). **Not** `--library-json` body extract (demoted; #51 superseded). Optional G10 calendar fill. **Proey-owned** weekdays **~06:25 ET** after 06:10. Does not fold into G10 / Research From; does not change 5:55/6:10.

## Modules

| Path | Role |
| --- | --- |
| `models.py` | `ClaimNote` / Dexter / cause-edge contract |
| `project.py` | analyst `argument_map` document → `ClaimNote` list (**canonical MA feed**) |
| `project_library.py` | **Demoted** LIBRARY → ClaimNote (offline/legacy only; not live 6:25) |
| `library.py` | LIBRARY Notion Research Note read-path protocol (demoted for MA claims) |
| `notion_library.py` | Live Notion query (demoted for MA claims) |
| `ops.py` / `run_morning_attention.py` | Ops runner + CLI (handoff for Proey) |
| `delivery/` | Own reMarkable markdown + Grok Bot one-liner (handoff) |
| `products/` | recent ingest, thematic digest, morning attention, author evolution, impromptu study |

## Commands

From `packages/research_dispatcher`:

```bash
PYTHONPATH=. python -m unittest discover -s tests/claim_notes -v
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --argument-map-json fixtures/claim_notes/argument_map_documents.json \
  --handoff-dir /tmp/ma-handoff --dry-run --fake-delivery
```

Proey live: export then MA — see `docs/morning-attention-ops.md`.  
Fixtures: `fixtures/claim_notes/` (synthetic only; no real note bodies in git).
