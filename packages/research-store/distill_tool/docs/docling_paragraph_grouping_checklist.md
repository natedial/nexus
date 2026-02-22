# Docling Paragraph Grouping Checklist

Use this to make extracted markdown preserve paragraph boundaries before running `distill`.

## 1. Lock and inspect your Docling output

1. Pin a Docling version in your extractor environment.
2. Run extraction on one known-problem file (like your `sample_text` input).
3. Inspect the markdown and confirm whether headings, bullets, and body text are separated by blank lines.

## 2. Render markdown from block structure (not plain text concatenation)

1. Walk Docling blocks/elements in reading order.
2. Emit block text with explicit separators:
   - Heading: blank line before and after.
   - Paragraph: blank line after.
   - List item: one item per line, blank line after list.
   - Table/caption: blank line before and after.
3. Do not join all blocks with a single space.

## 3. Add a markdown normalization pass

After export, run a cleanup pass:

1. Normalize newlines to `\n`.
2. Replace 3+ consecutive newlines with exactly 2.
3. Ensure a blank line before Markdown headings (`#`, `##`, ...).
4. Ensure a blank line before list starts (`- `, `* `, `1. `).

## 4. Add a QA gate before distill

Reject extracted markdown if either check fails:

1. Paragraph count is too low for long docs.
2. Max paragraph length is too high.

Recommended starting thresholds for your current chunking defaults:

- `max_paragraph_chars <= 2 * fallback_target_chars`
- `paragraph_count >= max(3, total_chars // fallback_target_chars // 2)`

## 5. Minimal QA script (drop into your extractor pipeline)

```python
import re

def paragraph_stats(markdown: str) -> tuple[int, int, int]:
    text = markdown.strip()
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    total_chars = len(text)
    max_paragraph_chars = max((len(p) for p in paragraphs), default=0)
    return len(paragraphs), max_paragraph_chars, total_chars
```

## 6. Rollout plan

1. Fix exporter separators.
2. Enable QA gate in CI/extraction job.
3. Re-extract a small sample set and compare paragraph stats.
4. Re-run distill and verify chunk count distribution is no longer dominated by single huge chunks.
