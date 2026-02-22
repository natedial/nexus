from __future__ import annotations

import re
from dataclasses import dataclass


PAGE_MARKER_REGEX = r"^--- PAGE (\d+) ---\s*$"
PAGE_MARKER_RE = re.compile(PAGE_MARKER_REGEX, re.MULTILINE)
FALLBACK_TARGET_CHARS = 2000
FALLBACK_MIN_CHARS = 700


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


def split_fallback_chunks(
    text: str,
    target_chars: int = FALLBACK_TARGET_CHARS,
    min_chars: int = FALLBACK_MIN_CHARS,
) -> list[Page]:
    if target_chars <= 0:
        raise ValueError("target_chars must be > 0")
    if min_chars <= 0:
        raise ValueError("min_chars must be > 0")

    text = text.strip()
    if not text:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return [Page(number=1, text=text)]

    pages: list[Page] = []
    current: list[str] = []
    current_len = 0
    page_number = 1

    for para in paragraphs:
        para_len = len(para)
        if para_len >= target_chars:
            if current:
                pages.append(Page(number=page_number, text="\n\n".join(current)))
                page_number += 1
                current = []
                current_len = 0
            pages.append(Page(number=page_number, text=para))
            page_number += 1
            continue

        projected_len = current_len + para_len + (2 if current else 0)
        if current and projected_len > target_chars and current_len >= min_chars:
            pages.append(Page(number=page_number, text="\n\n".join(current)))
            page_number += 1
            current = [para]
            current_len = para_len
            continue

        current.append(para)
        current_len = projected_len

    if current:
        if pages and current_len < min_chars:
            merged_text = pages[-1].text + "\n\n" + "\n\n".join(current)
            pages[-1] = Page(number=pages[-1].number, text=merged_text)
        else:
            pages.append(Page(number=page_number, text="\n\n".join(current)))

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
