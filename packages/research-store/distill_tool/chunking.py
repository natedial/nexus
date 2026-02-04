from __future__ import annotations

import re
from dataclasses import dataclass


PAGE_MARKER_REGEX = r"^--- PAGE (\d+) ---\s*$"
PAGE_MARKER_RE = re.compile(PAGE_MARKER_REGEX, re.MULTILINE)


@dataclass(frozen=True)
class Page:
    number: int
    text: str


def split_pages(markdown: str, marker_re: re.Pattern[str] = PAGE_MARKER_RE) -> list[Page]:
    matches = list(marker_re.finditer(markdown))
    if not matches:
        stripped = markdown.strip()
        return [Page(number=1, text=stripped)] if stripped else []

    pages: list[Page] = []
    preamble = markdown[: matches[0].start()].strip()
    for idx, match in enumerate(matches):
        page_number = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        text = markdown[start:end].strip()
        if idx == 0 and preamble:
            text = f"{preamble}\n\n{text}" if text else preamble
        if text:
            pages.append(Page(number=page_number, text=text))
    return pages


def apply_page_overlap(pages: list[Page], overlap_paragraphs: int = 1) -> list[Page]:
    if overlap_paragraphs <= 0 or len(pages) <= 1:
        return pages

    overlapped: list[Page] = []
    prev_paragraphs: list[str] = []
    for page in pages:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page.text) if p.strip()]
        prefix = ""
        if prev_paragraphs:
            overlap = prev_paragraphs[-overlap_paragraphs:]
            prefix = "\n\n".join(overlap).strip()
        if prefix:
            new_text = f"{prefix}\n\n{page.text}"
        else:
            new_text = page.text
        overlapped.append(Page(number=page.number, text=new_text))
        prev_paragraphs = paragraphs
    return overlapped
