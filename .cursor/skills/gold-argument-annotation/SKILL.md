---
name: gold-argument-annotation
description: Co-read a research note, policy speech, or paper with the user and store their gold judgments of its arguments (claims, roles, evidence, and the links between claims). Use when the user wants to build or extend the gold set, label a document's arguments, or "co-read" a paper and record what it argues.
---

# Gold argument annotation

The gold set is the user's judgment, not yours. You read alongside them, ask short questions, point out things they may have missed, and store what they decide. Never write a claim, role, or link into the gold set that the user has not agreed to.

Gold records train and grade the analyst's argument extraction. A record that reflects your reading instead of the user's makes the grade meaningless.

## Where things live

The `nexus` repository is public. Source texts and gold records contain verbatim research excerpts, so they live in a separate private gold repository, never in `nexus`. The command refuses to write anywhere inside the `nexus` checkout.

`RESEARCH_ANALYST_GOLD_DIR` points at the private gold checkout, normally set in `packages/research_analyst/.env`:

```bash
RESEARCH_ANALYST_GOLD_DIR=~/devwork/nexus-gold
```

If the command reports that no gold directory is configured, stop and ask the user where their private gold checkout is. Do not create a gold directory inside `nexus` or anywhere the user has not named.

All commands run from `packages/research_analyst`:

```bash
cd packages/research_analyst
uv run python -m research_analysis_layer.evals.gold_set <command>
# without uv: PYTHONPATH=src python3 -m research_analysis_layer.evals.gold_set <command>
```

| Path in the gold checkout | Contents |
|---|---|
| `arguments.jsonl` | One gold record per document. Written only by the command. |
| `documents/<document_id>.md` | The source text that evidence quotes are checked against. Its hash is stored on the record, so an edit after labeling is caught. |

Do not edit `arguments.jsonl` by hand, do not touch `evals/golden/annotations.jsonl` in `nexus` (a different, older eval), and do not write to Postgres.

## 1. Get the text

Use the first source that works:

1. Already parsed from Drive: `packages/research_parser/data/artifacts/<drive_file_id>/clean_text.md`. Chart citations for that document are in `figures.jsonl` in the same folder (`figure_key`, page, caption).
2. A local PDF: `pdftotext -layout paper.pdf /tmp/gold/<document_id>.txt`.
3. Text the user pastes: save it to `/tmp/gold/<document_id>.txt`.

Do not clean up or rewrite the text. Evidence quotes are matched against it.

Keep scratch files in `/tmp/gold/` or in the gold checkout, never inside `nexus`.

## 2. Register the document

Pick a `document_id` like `<publisher-or-speaker>-<yyyy-mm-dd>-<topic>`, lowercase, for example `powell-2026-09-17-outlook` or `gs-2026-09-12-term-premium`.

```bash
uv run python -m research_analysis_layer.evals.gold_set register \
  --document-id powell-2026-09-17-outlook \
  --text-file /tmp/gold/powell-2026-09-17-outlook.txt \
  --kind speech \
  --speaker "Jerome Powell" --publisher "Federal Reserve Board" \
  --date 2026-09-17 --title "Economic outlook" --annotator nate
```

`--kind` is one of `note`, `chart_pack`, `speech`, `paper`, `statement`, `minutes`, `testimony`, `other`. A bank note sets `--publisher` (the house). A speech sets `--speaker` and usually the institution as `--publisher`. Registering the same document again returns the existing draft.

## 3. Read together

Do not run the analyst on this document until its gold record is final. Seeing the tool's answer first anchors both of you.

1. **Ask for the headline first.** Before you share your read, ask the user what the author's main conclusion is, in a sentence or two.
2. **Go section by section.** For each section, ask what the author is claiming and why. Draft each claim in the user's words.
3. **Suggest, don't decide.** If you think the user missed a load-bearing claim, say so and quote the passage. Store it only if they accept, and mark it `"proposed_by": "agent"`. If they reject it, drop it.
4. **Keep it to the argument.** Most documents have 3–10 load-bearing claims. Do not pad with every sentence.
5. **Let doubt stand.** If the user is unsure about a claim or a link, keep it and set `"uncertain": true` rather than pushing them to decide.
6. **Keep notes on disagreements.** When you and the user read something differently, add a line to the record's `notes`. That disagreement is useful evidence later.

### Fields on each claim

| Field | What to record |
|---|---|
| `id` | `c1`, `c2`, ... in reading order. Never renumber a stored claim. Links point at these ids. |
| `claim` | One contention, atomic enough to compare with another author's claim. |
| `role` | `conclusion` (what the author wants you to believe), `premise` (a claim offered in support of another), `condition` (holds only if something else happens), `counterpoint` (a view the author raises in order to answer or reject it). |
| `claim_type` | `observation`, `forecast`, `causal`, `market_impact`, `policy`, `risk`, `recommendation`, or null. |
| `stance` | Direction in the author's terms (`hawkish`, `bearish`, `steepener`), or null. |
| `horizon` | The author's own words for the timeframe (`Q2 2026`, `later this year`), or null. Do not convert to dates. |
| `rationale` | The author's reasoning for the claim. Paraphrase is fine. Never add reasoning the author did not give. |
| `evidence` | What the author cites. `text` must be a verbatim quote, long enough to be unique (a phrase, not a lone number). Add `page` when known. For a chart, set `kind: "chart"`, put the caption in `text`, and set `figure_key` if the parser produced one. |
| `conditions` | Caveats the author attaches, as a list of strings. |
| `support_strength` | `evidenced` (the author cites data, a quote, or a chart), `reasoned` (argued without hard support), `asserted` (stated without support). Label honestly. |

### Links between claims

Record only connections the author makes. Leave out connections you or the user infer. Each link names two claim ids and a type. A claim can have any number of links, in either position.

| Type | Reads as | Example |
|---|---|---|
| `supports` | from gives a reason for to | "payrolls slowed" supports "cut in Q3" |
| `depends_on` | from holds only if to holds | "cut in Q3" depends_on "services inflation cools" |
| `qualifies` | from limits or narrows to | "unless core re-accelerates" qualifies "the Fed is done" |
| `leads_to` | the author says from brings about to | "heavy supply" leads_to "higher term premium" |
| `answers` | from is the author's reply to to | "cutting now is premature" answers the counterpoint "cut now" |
| `contrasts_with` | the two pull against each other, no direction | two readings the author sets side by side |

Direction matters for every type except `contrasts_with`: "c2 supports c1" is not "c1 supports c2". When the author describes a connection running both ways, such as a feedback loop, store two directed links (`c1 leads_to c2` and `c2 leads_to c1`). The command stores each `contrasts_with` pair once, whichever way you enter it.

## 4. Save often

Keep the working record in a scratch file, for example `/tmp/gold/<document_id>.json`, and store it after each section:

```bash
uv run python -m research_analysis_layer.evals.gold_set put --file /tmp/gold/powell-2026-09-17-outlook.json
```

`put` replaces the whole record for that document, then prints a plain-language readback plus any `still to do` items. Read the readback to the user in your own words and fix anything they correct.

If `put` rejects a quote as not verbatim, find the exact wording in the document text and show it to the user. Do not loosen the quote to make it pass.

Record shape:

```json
{
  "document_id": "powell-2026-09-17-outlook",
  "document_path": "documents/powell-2026-09-17-outlook.md",
  "document": {
    "title": "Economic outlook",
    "speaker": "Jerome Powell",
    "publisher": "Federal Reserve Board",
    "source_date": "2026-09-17",
    "doc_kind": "speech",
    "source_link": ""
  },
  "status": "draft",
  "annotator": "nate",
  "notes": "",
  "claims": [
    {
      "id": "c1",
      "claim": "A rate cut now would be premature",
      "role": "conclusion",
      "claim_type": "policy",
      "stance": "hawkish",
      "horizon": null,
      "rationale": "Inflation is still above goal, so easing now is early.",
      "evidence": [
        {"text": "it is still above our 2 percent goal", "kind": "quote", "page": 2, "figure_key": null}
      ],
      "conditions": [],
      "support_strength": "evidenced",
      "proposed_by": "annotator",
      "uncertain": false
    }
  ],
  "links": [
    {"from": "c1", "to": "c2", "type": "answers", "rationale": "", "uncertain": false}
  ]
}
```

Start from `show --document-id <id> --json` so the header from `register` carries over.

## 5. Finish

1. Run `show --document-id <id>` and walk the user through the whole readback: each claim with its role, reasoning, and evidence, then each link.
2. When they confirm, set `"status": "final"` and `put` again. A final record must have at least one conclusion, a rationale on every claim, and evidence on every `evidenced` claim.
3. Run `validate`. It must exit cleanly.
4. If the user wants the record saved, commit it in the private gold checkout, never in `nexus`:

```bash
cd "$RESEARCH_ANALYST_GOLD_DIR"
git add arguments.jsonl documents/<document_id>.md
git commit -m "Add gold argument map for <document_id>"
git push
```

Before pushing, confirm with `git remote -v` that the remote is the user's private gold repository.

## Keep in mind

- One question at a time. The user has limited time. Keep turns short and move section by section.
- A speech or policy paper has one voice. Leave agreement across houses and positioning out of it entirely.
- Never invent a quote, a page number, or a figure key.
- Do not change another document's record unless the user asks.
