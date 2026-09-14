# Docling Paragraph Grouping Checklist

Use this checklist to keep paragraph boundaries stable in the current parser pipeline:
`Docling -> blocks -> confidence -> boilerplate -> storage`.

## 1. Reproduce and lock a baseline

- [ ] Lock parser dependencies for the test run (`docling`, `docling-core`).
- [ ] Run one known-problem PDF through the full pipeline with logs:

```bash
python3 scripts/test_full_pipeline.py --pdf "<exact pdf name>" --force --log-file data/logs/docling_paragraph_check.log
```

- [ ] Capture these artifacts for comparison:
  - `data/logs/docling_paragraph_check.log`
  - `data/artifacts/<file_id>/document.md`
  - `data/artifacts/<file_id>/figures.jsonl`

## 2. Confirm where paragraph structure is lost

- [ ] Check parse logs for confidence status/reasons (`Parse confidence` in `src/pipeline.py`).
- [ ] Inspect `document.md` and verify headings/lists/paragraphs are separated by blank lines.
- [ ] If parse confidence is `REPAIR` or `FALLBACK`, record the reasons (`no_paragraphs`, `no_headings`, etc.).

## 3. Normalize markdown at parser boundary

Current behavior keeps raw parser markdown (`text_result.raw_output`) and only tokenizes it via `markdown_to_blocks`.
Add a shared normalization step before tokenization:

- [ ] Add `normalize_markdown(markdown: str) -> str` in `src/parser/artifacts.py`.
- [ ] Call it from `src/parser/docling_backend.py` (`parse_text`)
- [ ] Include at least:
  - newline normalization (`\r\n` -> `\n`)
  - collapse 3+ blank lines to 2
  - blank line before headings
  - blank line before list starts (`-`, `*`, `+`, `1.`)

## 4. Add explicit paragraph QA metrics

Add a lightweight metric helper and fail/repair rules based on current parser heuristics.

- [ ] Add helper in `src/parser/artifacts.py`:

```python
import re

def paragraph_stats(markdown: str) -> tuple[int, int, int]:
    text = markdown.strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    total_chars = len(text)
    max_paragraph_chars = max((len(p) for p in paragraphs), default=0)
    return len(paragraphs), max_paragraph_chars, total_chars
```

- [ ] Use stats in `src/parser/backend.py::ParserBackend.confidence` (or a parser-specific override).
- [ ] Starting thresholds for this repo:
  - `total_chars >= 3000 and paragraph_count < 3` -> add reason `low_paragraph_count`
  - `max_paragraph_chars > 2500` -> add reason `very_long_paragraph`
  - downgrade status to `REPAIR`/`FALLBACK` when these are present

## 5. Extend tests before rollout

- [ ] `tests/test_artifacts.py`
  - add normalization tests (headings/lists separated by blank lines)
  - add paragraph stats tests
- [ ] `tests/test_docling_blocks.py`
  - add a case where poorly separated markdown still yields multiple paragraph blocks after normalization
- [ ] add confidence tests for `low_paragraph_count` and `very_long_paragraph`

## 6. Rollout and verify

- [ ] Run tests:

```bash
pytest tests/test_artifacts.py tests/test_docling_blocks.py
```

- [ ] Verify no regression in extraction quality and fewer parse-confidence repairs caused by paragraph grouping.
