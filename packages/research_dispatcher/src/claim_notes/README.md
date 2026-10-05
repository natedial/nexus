# Claim notes (`claim-note-v1`)

Deterministic product contract for one argument per record. Shared by five products (see Agent Store `docs/claim-note-products-plan.md`).

## Locked rules

- **Cause edge** (`cause_edges[]`): speaker says X causes Y — own edge, separate from `thread_role`. Stored as said; not fact-checked; no causal world model.
- **`speaker_weight`**: role enum only — `chair` | `voter` | `non-voter` | `interview` | `research_author`. Not a 0–1 score.
- **Speaker vs publisher**: who said it vs which document/house it came from — keep both fields distinct.
- **Dexter**: pointer, not an in-Nexus call. Product marks `dexter_pass.status=awaiting` and stops; Dexter attaches `completed` findings + sources externally. Products never fill numbers.
- **Thematic side**: stance on *that thread*, not a global hawk/dove label.
- **Morning attention**: own 3–5 point surface → reMarkable notebook (`Morning Attention YYYY-MM-DD`, next to G10 / Research From) + one-line **Grok Bot** ping to Nate’s 1:1 with Proey (not SMTP); *reads* G10 calendar + Notion LIBRARY (Resource Type = Research Note only; **since last run**). **Proey-owned** weekdays **~06:25 ET** after 06:10. Empty day = silent. Does not fold into G10 / Research From; does not change 5:55/6:10. Canonical LIBRARY link: https://app.notion.com/p/2839852eebb4806c9127c229dcc2ddb9

## Modules

| Path | Role |
| --- | --- |
| `models.py` | `ClaimNote` / Dexter / cause-edge contract |
| `project.py` | analyst `argument_map` document → `ClaimNote` list |
| `library.py` | LIBRARY Notion Research Note read-path protocol |
| `notion_library.py` | Live Notion query (Research Note + since-last-run) |
| `ops.py` / `run_morning_attention.py` | Ops runner + CLI (handoff for Proey) |
| `delivery/` | Own reMarkable markdown + Grok Bot one-liner (handoff) |
| `products/` | recent ingest, thematic digest, morning attention, author evolution, impromptu study |

## Commands

From `packages/research_dispatcher`:

```bash
PYTHONPATH=. python -m unittest discover -s tests/claim_notes -v
PYTHONPATH=. python src/claim_notes/run_morning_attention.py --dry-run --fake-delivery \
  --argument-map-json fixtures/claim_notes/argument_map_documents.json
```

Host credentials: `docs/morning-attention-ops.md`  
Fixtures: `fixtures/claim_notes/`
