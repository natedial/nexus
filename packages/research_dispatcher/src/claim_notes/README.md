# Claim notes (`claim-note-v1`)

Deterministic product contract for one argument per record. Shared by five products (see Agent Store `docs/claim-note-products-plan.md`).

## Locked rules

- **Cause edge** (`cause_edges[]`): speaker says X causes Y — own edge, separate from `thread_role`. Stored as said; not fact-checked; no causal world model.
- **`speaker_weight`**: role enum only — `chair` | `voter` | `non-voter` | `interview` | `research_author`. Not a 0–1 score.
- **Speaker vs publisher**: who said it vs which document/house it came from — keep both fields distinct.
- **Dexter**: pointer, not an in-Nexus call. Product marks `dexter_pass.status=awaiting` and stops; Dexter attaches `completed` findings + sources externally. Products never fill numbers.
- **Thematic side**: stance on *that thread*, not a global hawk/dove label.
- **Morning attention**: own 3–5 point surface → reMarkable (`Morning Attention YYYY-MM-DD`) + Grok Bot 1:1 ping. **Live path:** `--library-json` with **full page `body`** → Gerhard multi-claim extraction (speaker = attributed desk, never `LIBRARY desk`) → handoff. Empty library = silent. Does not fold into G10 / Research From; no 5:55/6:10 changes.

## Modules

| Path | Role |
| --- | --- |
| `models.py` | `ClaimNote` / Dexter / cause-edge contract |
| `project.py` | analyst `argument_map` document → `ClaimNote` list |
| `project_library.py` | Gerhard: LIBRARY Research Note **body** → N claim notes (never `LIBRARY desk`) |
| `library.py` | LIBRARY Notion Research Note read-path protocol |
| `notion_library.py` | Live Notion query (Research Note + since-last-run) |
| `ops.py` / `run_morning_attention.py` | Ops runner + CLI (handoff for Proey) |
| `delivery/` | Own reMarkable markdown + Grok Bot one-liner (handoff) |
| `products/` | recent ingest, thematic digest, morning attention, author evolution, impromptu study |

## Commands

From `packages/research_dispatcher`:

```bash
PYTHONPATH=. python -m unittest discover -s tests/claim_notes -v
PYTHONPATH=. python src/claim_notes/run_morning_attention.py \
  --library-json /path/to/library_research_notes.json \
  --handoff-dir /tmp/ma-handoff --dry-run --fake-delivery
```

Host credentials: `docs/morning-attention-ops.md`  
Fixtures: `fixtures/claim_notes/`
