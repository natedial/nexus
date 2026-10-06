"""LIBRARY Research Note → claim-note-v1 (Gerhard extraction contract).

One Research Note → **N claims** from the **full page body** (not title /
Description alone). Proey's ``--library-json`` must include ``body``.

Locked rules (do not reopen):
1. Extract claims from full body text as stated — never invent numbers.
2. ``speaker`` = attributed desk/author (JPM, Barclays, …) — **never**
   ``LIBRARY desk``. Prefer **inline / numbered-takeaway** attribution;
   structured ``Speaker:`` / ``Claim:`` markers remain an optional path.
3. ``publisher`` = Notion LIBRARY, or the note's source publisher when present.
4. ``thread_role`` = assert | extend | break from framing; default **assert**.
5. ``stance`` (side) only when the note states one; otherwise **null**.
6. ``support_kind`` = ``ingested_document_text``; ``dexter_pass`` null unless
   the note itself marks a live-number need.
7. ``cause_edges`` only when the note **explicitly** asserts A causes B.
8. Skip citation/metadata lines (``**Title:**``, bibliography rows, …).
9. Do **not** assign one note-level speaker to every line (that invents junk).
10. Morning-attention risk-into-prints filtering is the product surface — not here.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from src.claim_notes.library import LibraryResearchNote
from src.claim_notes.models import CauseEdge, ClaimNote, TimeWindow
from src.claim_notes.validate import validate_claim_note

LIBRARY_PUBLISHER = "Notion LIBRARY"
_BANNED_SPEAKERS = frozenset({"library desk", "library", "notion library"})

# Citation / chrome labels — never speakers, never claims.
_META_KEYS = frozenset(
    {
        "title",
        "author",
        "authors",
        "date",
        "published",
        "published_at",
        "retrieved",
        "retrieved_at",
        "url",
        "link",
        "doi",
        "isbn",
        "source",
        "abstract",
        "reference",
        "references",
        "bibliography",
        "citation",
        "tags",
        "type",
        "resource type",
        "summary",
        "description",
        "series",
        "page",
        "pdf",
        "scope note",
        "scope",
        "question",
        "data",
        "method",
        "how to read it",
        "context",
        "review window",
        "established conclusions",
        "tentative interpretations",
        "open questions",
        "bottom line",
        "evidence",
        "changed",
        "new",
        "priority",
        "communications",
        "balance sheet",
        "productivity & jobs",
        "inflation frameworks",
        "data stance",
        "task forces",
        "not analyzed",
        "manufacturing ppi only",
    }
)

# Finding labels kept from paper digests (Atlanta Fed style).
_PAPER_FINDING_LABELS = frozenset(
    {
        "aggregate",
        "result",
        "results",
        "finding",
        "findings",
        "conclusion",
        "pass-through",
        "passthrough",
        "normal times",
        "crisis",
        "authors' bottom line",
        "author's bottom line",
        "mechanism",
    }
)

_SPEAKER_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "their",
        "its",
        "but",
        "all",
        "he",
        "she",
        "we",
        "this",
        "that",
        "these",
        "those",
        "not",
        "and",
        "or",
        "for",
        "with",
        "from",
        "per",
        "leaders",
        "priority",
        "external",
    }
)

# Bank / sell-side desks for inline attribution. Institution names that appear
# only in Sources / bibliography rows (Federal Reserve, Atlanta Fed, …) are
# intentionally excluded — paper authors come from the Authors line instead.
_KNOWN_DESKS: tuple[str, ...] = (
    "JP Morgan",
    "JPMorgan",
    "JPM",
    "Goldman Sachs",
    "Goldman",
    "Morgan Stanley",
    "Barclays",
    "Citigroup",
    "Bank of America",
    "Deutsche Bank",
    "BofA",
    "Citi",
    "UBS",
    "HSBC",
    "BNP",
    "GS",
    "MS",
    "DB",
)

_CLAIM_START = re.compile(r"(?im)^\s*(?:claim|contention)\s*[:\-–—]\s*(.+)$")
_META_LINE = re.compile(
    r"(?im)^\s*(speaker|author|desk|publisher|source|thread(?:_role)?|"
    r"thread_target(?:_note_id)?|target|stance|side|role|cause|causes|"
    r"support_kind|live_number|need_live)\s*[:\-–—]\s*(.+)$"
)
_HEADER_ATTR = re.compile(r"(?im)^\s*(?:speaker|author|desk|by)\s*[:\-–—]\s*(.+)$")
_HEADER_PUB = re.compile(r"(?im)^\s*(?:publisher|source|house)\s*[:\-–—]\s*(.+)$")
_BULLET_CLAIM = re.compile(r"(?m)^\s*[-*•]\s+(?:claim\s*[:\-–—]\s*)?(.+)$")
_CAUSE_ARROW = re.compile(
    r"(?i)^\s*(.+?)\s*(?:->|→|⇒|causes?|leads?\s+to)\s+(.+?)"
    r"(?:\s*\((supports|undermines|unspecified)\))?\s*$"
)
_CAUSE_IN_CLAIM = re.compile(
    r"(?i)^(?P<cause>.+?)\s+(?:causes?|leads?\s+to)\s+(?P<effect>.+)$"
)
_THREAD_WORD = re.compile(r"(?i)\b(assert|extend(?:s|ing)?|break(?:s|ing)?)\b")

# **Title:** / - **Authors:** / bare Title:
_CITATION_LINE = re.compile(
    r"(?ix)^\s*(?:[-*•]\s+)?"
    r"(?:\*\*)?"
    r"(?:title|authors?|date|url|link|doi|isbn|published|retrieved|"
    r"reference|references|bibliography|abstract|tags|resource\s*type|"
    r"series|page|pdf|scope\s*note|scope|question|data|method|"
    r"how\s+to\s+read\s+it|context|review\s+window|"
    r"established\s+conclusions|tentative\s+interpretations|open\s+questions|"
    r"bottom\s+line|evidence|changed|new)"
    r"(?:\*\*)?\s*:"
)

# Inline: "JPM: …" / "Gilchrist (Atlanta Fed): …" / "Citigroup — US Rates Weekly: …"
_INLINE_SPEAKER_CLAIM = re.compile(
    r"(?x)^\s*(?:[-*•]\s+)?"
    r"(?P<speaker>"
    r"(?!https?|mailto)"
    r"[A-Z][A-Za-z0-9][A-Za-z0-9 .,&/'/\-]{0,50}?"
    r"(?:\s*[—–-]\s*[A-Z][A-Za-z0-9 .,&/'/\-]{0,40})?"
    r"(?:\s*\([^)]{1,50}\))?"
    r")"
    r"\s*:\s+"
    r"(?P<claim>\S.+)$"
)

_LEADING_DESK = re.compile(
    r"(?ix)^\s*(?:[-*•]\s+)?"
    r"(?P<speaker>"
    + "|".join(re.escape(d) for d in sorted(_KNOWN_DESKS, key=len, reverse=True))
    + r")\b(?:\s*\((?P<affil>[^)]{1,50})\))?[,\s]+(?P<claim>\S.+)$"
)

# Numbered executive takeaway: 1. **JPM has withdrawn…** / 1. **Thematic…**
_NUMBERED_TAKEAWAY = re.compile(
    r"(?m)^\s*(?P<num>\d+)\.\s+\*\*(?P<bold>.+?)(?:\*\*|(?=\n)|$)"
)

# Paper-digest finding bullet. Notion often bolds "Label:" including the colon:
#   - **Authors:** names…
#   - **Aggregate (model-implied):** finding…
#   - **Pass-through depends on the state…** more prose…
_FINDING_BULLET = re.compile(
    r"(?m)^\s*[-*•]\s+\*\*(?P<inner>.+?)\*\*(?P<rest>.*)$"
)
_AUTHORS_LINE = re.compile(
    r"(?im)^\s*[-*•]\s+\*\*Authors?:\*\*\s*(?P<authors>.+)$"
)

_MIN_CLAIM_CHARS = 20


def project_library_research_note(note: LibraryResearchNote) -> list[ClaimNote]:
    """Extract N claim notes from one LIBRARY Research Note body."""
    return list(extract_claims_from_library_note(note))


def project_library_research_notes(
    notes: Sequence[LibraryResearchNote],
) -> list[ClaimNote]:
    """Extract claims from many LIBRARY Research Notes (body required)."""
    out: list[ClaimNote] = []
    for note in notes:
        out.extend(project_library_research_note(note))
    return out


def extract_claims_from_library_note(note: LibraryResearchNote) -> list[ClaimNote]:
    """Gerhard body extraction — full page body → claim-note-v1 list."""
    body = (note.body or "").strip()
    if not body:
        return []

    header_speaker, header_publisher = _header_attribution(body)
    note_level_speaker = _resolve_speaker(note, header_speaker)
    publisher = _resolve_publisher(note, header_publisher)
    source_date = _source_date(note)

    structured = _parse_structured_claims(body)
    if structured:
        units = structured
        allow_note_speaker_fallback = True
    else:
        # Real Notion digests: prose / numbered takeaways / paper findings.
        # Never blanket-apply one note-level speaker to every line.
        units = _parse_prose_claims(body)
        allow_note_speaker_fallback = False

    if not units:
        return []

    notes_out: list[ClaimNote] = []
    for index, unit in enumerate(units):
        built = _build_claim_note(
            note,
            unit,
            index=index,
            default_speaker=note_level_speaker if allow_note_speaker_fallback else None,
            default_publisher=publisher,
            source_date=source_date,
        )
        if built is not None:
            notes_out.append(built)
    return notes_out


def _resolve_speaker(
    note: LibraryResearchNote, header_speaker: str | None
) -> str | None:
    for raw in (note.speaker, note.author, header_speaker):
        text = _clean_speaker(raw)
        if text:
            return text
    return None


def _clean_speaker(raw: str | None) -> str | None:
    text = (raw or "").strip().strip("*").strip()
    if not text:
        return None
    # Strip publication subtitle after em-dash: "Citigroup — US Rates Weekly"
    text = re.split(r"\s*[—–]\s*", text, maxsplit=1)[0].strip()
    if text.lower() in _BANNED_SPEAKERS:
        return None
    if text.lower().rstrip(":") in _META_KEYS:
        return None
    if not _plausible_speaker(text):
        return None
    return text


def _plausible_speaker(text: str) -> bool:
    """Accept desk/author labels only — reject sentence fragments."""
    words = [w for w in re.split(r"\s+", text.strip()) if w]
    if not words:
        return False
    if len(text) > 48 or len(words) > 6:
        return False
    # Dates / numeric chrome
    if re.match(r"^\d{1,2}\s+\w+\s*,?\s*\d{4}$", text):
        return False
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return False
    first = re.sub(r"[^A-Za-z]", "", words[0]).lower()
    if first in _SPEAKER_STOPWORDS:
        return False
    if _desk_at_start(text):
        return True
    # Person / person et al. / person (Affil) / First Last (Affil)
    if re.match(
        r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:\s+et\s+al\.?)?(?:\s*\([^)]{1,40}\))?$",
        text,
    ):
        return True
    # All-caps short desk codes already handled via known desks; reject other
    # Title-Case phrases that are not person names.
    return False


def _resolve_publisher(
    note: LibraryResearchNote, header_publisher: str | None
) -> str:
    for raw in (note.publisher, header_publisher):
        text = (raw or "").strip()
        if text:
            return text
    return LIBRARY_PUBLISHER


def _source_date(note: LibraryResearchNote) -> date | None:
    if note.source_date is not None:
        return note.source_date
    if note.saved_at is not None:
        stamp = note.saved_at
        return stamp.date() if isinstance(stamp, datetime) else None
    return None


def _header_attribution(body: str) -> tuple[str | None, str | None]:
    speaker = None
    publisher = None
    cut = len(body)
    first_claim = _CLAIM_START.search(body)
    if first_claim:
        cut = min(cut, first_claim.start())
    preamble = body[:cut]
    for match in _HEADER_ATTR.finditer(preamble):
        speaker = _clean_speaker(match.group(1)) or speaker
    for match in _HEADER_PUB.finditer(preamble):
        publisher = match.group(1).strip() or publisher
    return speaker, publisher


def _parse_structured_claims(body: str) -> list[dict[str, Any]]:
    starts = list(_CLAIM_START.finditer(body))
    if not starts:
        return []
    units: list[dict[str, Any]] = []
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(body)
        block = body[match.start() : end]
        claim_text = match.group(1).strip()
        meta = _parse_meta_lines(block)
        if meta.get("claim"):
            claim_text = str(meta["claim"]).strip()
        unit: dict[str, Any] = {
            "claim": claim_text,
            "speaker": meta.get("speaker") or meta.get("author") or meta.get("desk"),
            "publisher": meta.get("publisher") or meta.get("source"),
            "thread_role": meta.get("thread_role") or meta.get("thread") or meta.get("role"),
            "thread_target_note_id": meta.get("thread_target_note_id")
            or meta.get("thread_target")
            or meta.get("target"),
            "stance": meta.get("stance") or meta.get("side"),
            "causes": list(meta.get("causes") or []),
            "need_live": bool(meta.get("need_live") or meta.get("live_number")),
            "raw_block": block,
        }
        for cause_line in meta.get("cause_lines") or []:
            edge = _parse_cause_line(cause_line)
            if edge:
                unit["causes"].append(edge)
        units.append(unit)
    return units


def _parse_meta_lines(block: str) -> dict[str, Any]:
    meta: dict[str, Any] = {"cause_lines": [], "causes": []}
    for match in _META_LINE.finditer(block):
        key = match.group(1).strip().lower()
        value = match.group(2).strip()
        if key in {"speaker", "author", "desk", "publisher", "source", "stance", "side"}:
            if key == "side":
                meta["stance"] = value
            elif key in {"author", "desk"}:
                meta.setdefault("speaker", value)
            elif key == "source":
                meta.setdefault("publisher", value)
            else:
                meta[key] = value
        elif key in {"thread", "thread_role", "role"}:
            meta["thread_role"] = value
        elif key in {"thread_target", "thread_target_note_id", "target"}:
            meta["thread_target_note_id"] = value
        elif key in {"cause", "causes"}:
            meta["cause_lines"].append(value)
        elif key in {"live_number", "need_live"}:
            meta["need_live"] = value.lower() in {"1", "true", "yes", "y"}
        elif key == "claim":
            meta["claim"] = value
    return meta


def _parse_prose_claims(body: str) -> list[dict[str, Any]]:
    """Real digest path: numbered takeaways, inline desks, paper findings."""
    units: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(unit: dict[str, Any] | None) -> None:
        if unit is None:
            return
        key = f"{unit['speaker']}::{unit['claim']}".lower()
        if key in seen:
            return
        seen.add(key)
        units.append(unit)

    # Paper digests: Authors → speaker; skip Sources/chrome inline scrape.
    paper_units = _parse_paper_finding_bullets(body)
    if paper_units:
        for unit in paper_units:
            _add(unit)
        return units

    # 1) Numbered executive takeaways (common Codex / desk digest shape).
    for unit in _parse_numbered_takeaways(body):
        _add(unit)

    # 2) Inline "Desk: claim" / leading-desk lines.
    for line in _iter_candidate_lines(body):
        if _is_citation_or_metadata(line):
            continue
        _add(_parse_inline_attribution(line))

    return units


def _parse_numbered_takeaways(body: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    # Split body into numbered blocks so in-block bank attribution is visible.
    blocks = re.split(r"(?m)(?=^\s*\d+\.\s+)", body)
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        match = _NUMBERED_TAKEAWAY.match(block)
        if not match:
            continue
        bold = match.group("bold").strip().rstrip("*").strip()
        if not _usable_claim_text(bold):
            continue
        if _is_citation_or_metadata(bold):
            continue

        speaker = _desk_at_start(bold)
        if speaker is None:
            # Thematic takeaway — attribute only when one desk dominates the
            # opening of the block (not every bank name deeper in the doc).
            head = block[:500]
            speaker = _dominant_desk(head)
        if speaker is None:
            continue

        causes: list[Any] = []
        cause_match = _CAUSE_IN_CLAIM.match(bold)
        if cause_match:
            causes.append(
                {
                    "cause": cause_match.group("cause").strip(),
                    "effect": cause_match.group("effect").strip(),
                    "polarity": "supports",
                    "as_stated": bold,
                }
            )
        units.append(_prose_unit(speaker, bold, raw=block[:240], causes=causes))
    return units


def _parse_paper_finding_bullets(body: str) -> list[dict[str, Any]]:
    """Citation-heavy research notes: skip **Title:** etc.; keep findings."""
    authors = _authors_from_body(body)
    if authors is None:
        return []  # need Authors line for speaker; never invent one

    speaker = authors
    # Prefer Key findings / Implications sections; ignore Sources chrome.
    scoped = _paper_finding_scope(body)

    buckets: dict[str, dict[str, Any]] = {}
    for match in _FINDING_BULLET.finditer(scoped):
        inner = (match.group("inner") or "").strip()
        rest = (match.group("rest") or "").strip()
        label, value, bold_claim = _split_finding_bold(inner, rest)
        key = label.lower().split("(")[0].strip()
        if key in _META_KEYS:
            continue
        keep = any(key.startswith(k) or k in key for k in _PAPER_FINDING_LABELS)
        if not keep:
            continue
        # Bold lead is the claim when it is already a finding sentence;
        # otherwise use the value after the label.
        if bold_claim:
            claim = bold_claim
        elif value:
            claim = value
        else:
            claim = label
        claim = claim.strip().strip('"').strip()
        if not _usable_claim_text(claim):
            continue
        causes = _explicit_causes_from_claim(claim)
        bucket = _paper_bucket(key)
        if bucket and bucket not in buckets:
            buckets[bucket] = _prose_unit(
                speaker, claim, raw=match.group(0), causes=causes
            )

    return _select_paper_units(buckets)


def _paper_finding_scope(body: str) -> str:
    """Keep Key findings + Implications; drop Citation/Sources/Caveats."""
    parts: list[str] = []
    for match in re.finditer(
        r"(?ims)^##\s+(?P<title>[^\n]+)\n(?P<body>.*?)(?=^##\s+|\Z)", body
    ):
        title = match.group("title").strip().lower()
        if title.startswith(
            ("key finding", "implication", "summary")
        ) or "pass-through" in title:
            parts.append(match.group(0))
    return "\n".join(parts) if parts else body


def _split_finding_bold(inner: str, rest: str) -> tuple[str, str, str | None]:
    """Return (label, value, bold_claim_or_none) for Notion ``**Label:** val``."""
    text = inner.strip()
    if text.endswith(":"):
        label = text[:-1].strip()
        return label, rest, None
    if ":" in text:
        label, after = text.split(":", 1)
        label = label.strip()
        value = (after.strip() + (" " + rest if rest else "")).strip()
        # "Normal times: about zero." — bold is already the claim sentence.
        if after.strip() and (
            after.strip().endswith((".", "?", "!")) or len(label) >= 20
        ):
            return label, value, text
        return label, value, None
    # Bold sentence without trailing colon (pass-through lead, etc.).
    if rest:
        return text, rest, text if len(text) >= 20 else None
    return text, "", text if len(text) >= 20 else None


def _paper_bucket(key: str) -> str | None:
    lowered = key.lower()
    if lowered.startswith("normal"):
        return "normal"
    if lowered.startswith("crisis"):
        return "crisis"
    if "aggregate" in lowered:
        return "aggregate"
    if "pass-through" in lowered or "passthrough" in lowered:
        return "passthrough"
    if "bottom line" in lowered:
        return "bottom"
    if lowered.startswith(("mechanism", "finding", "result", "conclusion")):
        return "other"
    return "other"


def _select_paper_units(buckets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Aim for ~2 curated paper claims: regime finding + state-dependence."""
    units: list[dict[str, Any]] = []

    normal = buckets.get("normal")
    crisis = buckets.get("crisis")
    if normal and crisis:
        # Concatenate as-stated bold leads — do not invent a paraphrase.
        combined = f"{normal['claim'].rstrip('.')} ; {crisis['claim']}"
        units.append(
            _prose_unit(
                str(normal["speaker"]),
                combined,
                raw=str(normal.get("raw_block") or ""),
                causes=list(normal.get("causes") or [])
                + list(crisis.get("causes") or []),
            )
        )
    elif normal or crisis or buckets.get("aggregate"):
        units.append(normal or crisis or buckets["aggregate"])

    for key in ("passthrough", "bottom", "other"):
        if key in buckets and len(units) < 2:
            # Avoid duplicating an already-selected unit.
            cand = buckets[key]
            if units and cand["claim"] == units[0]["claim"]:
                continue
            units.append(cand)

    return units[:2]


def _explicit_causes_from_claim(claim: str) -> list[dict[str, Any]]:
    causes: list[dict[str, Any]] = []
    cause_match = _CAUSE_IN_CLAIM.match(claim)
    if cause_match:
        causes.append(
            {
                "cause": cause_match.group("cause").strip(),
                "effect": cause_match.group("effect").strip(),
                "polarity": "supports",
                "as_stated": claim,
            }
        )
        return causes
    if re.search(r"(?i)\bcauses?\b|\bleads?\s+to\b", claim):
        nested = _CAUSE_IN_CLAIM.search(claim)
        if nested:
            causes.append(
                {
                    "cause": nested.group("cause").strip(),
                    "effect": nested.group("effect").strip(),
                    "polarity": "supports",
                    "as_stated": claim,
                }
            )
    return causes


def _authors_from_body(body: str) -> str | None:
    match = _AUTHORS_LINE.search(body)
    if not match:
        return None
    authors = match.group("authors").strip()
    # "Simon Gilchrist (NYU, NBER), Bin Wei (Atlanta Fed), …"
    first = _first_author_chunk(authors)
    name_part = re.sub(r"\s*\([^)]*\)\s*$", "", first).strip()
    parts = [p for p in name_part.split() if re.match(r"^[A-Za-z]", p)]
    surname = parts[-1] if parts else None
    if surname and re.search(r"Atlanta\s+Fed", authors, re.I):
        if len(parts) > 1 or "," in authors:
            return f"{surname} et al. (Atlanta Fed)"
        return f"{surname} (Atlanta Fed)"
    return _clean_speaker(name_part or first)


def _first_author_chunk(authors: str) -> str:
    """Split author list on commas that are outside parentheses."""
    depth = 0
    for i, ch in enumerate(authors):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            return authors[:i].strip()
    return authors.strip()


def _desk_at_start(text: str) -> str | None:
    stripped = text.strip().lstrip("*").strip()
    for desk in sorted(_KNOWN_DESKS, key=len, reverse=True):
        if re.match(rf"(?i)^{re.escape(desk)}\b", stripped):
            # Normalize short forms
            return _normalize_desk(desk)
    return None


def _normalize_desk(desk: str) -> str:
    mapping = {
        "jpmorgan": "JPM",
        "jp morgan": "JPM",
        "jpm": "JPM",
        "citigroup": "Citi",
        "citi": "Citi",
        "goldman sachs": "Goldman",
        "goldman": "Goldman",
        "gs": "Goldman",
        "morgan stanley": "MS",
        "ms": "MS",
        "bank of america": "BofA",
        "bofa": "BofA",
        "deutsche bank": "DB",
        "db": "DB",
        "barclays": "Barclays",
    }
    return mapping.get(desk.lower(), desk)


def _dominant_desk(text: str) -> str | None:
    """Return a desk only when one known desk clearly dominates attribution."""
    counts: dict[str, int] = {}
    for desk in _KNOWN_DESKS:
        # Word-boundary counts; normalize into canonical speaker.
        hits = len(re.findall(rf"(?i)\b{re.escape(desk)}\b", text))
        if hits:
            canon = _normalize_desk(desk)
            counts[canon] = counts.get(canon, 0) + hits
    if not counts:
        return None
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    top, top_n = ranked[0]
    if top_n <= 0:
        return None
    if len(ranked) > 1 and ranked[1][1] >= top_n:
        return None  # tie / mixed — do not invent a single speaker
    # Require a clear lead (not a single incidental mention in a long block).
    if top_n == 1 and len(text) > 400:
        # Allow single clear "according to X" / "X notes" attribution.
        if not re.search(
            rf"(?i)\b(?:according\s+to|per|from)\s+{re.escape(top)}\b|"
            rf"\b{re.escape(top)}\s+(?:notes?|says?|argues?|expects?|sees?|writes?)\b",
            text,
        ):
            return None
    return top


def _iter_candidate_lines(body: str) -> list[str]:
    out: list[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        out.append(line)
        if line.count(":") >= 2 and len(line) > 120:
            for part in re.split(r"(?<=[.!?])\s+(?=[A-Z])", line):
                part = part.strip()
                if part and part != line:
                    out.append(part)
    return out


def _is_citation_or_metadata(line: str) -> bool:
    text = line.strip()
    if not text:
        return True
    if _CITATION_LINE.match(text):
        return True
    bold_meta = re.match(r"^\s*(?:[-*•]\s+)?\*\*(?P<key>[^*]+)\*\*\s*:", text)
    if bold_meta:
        key = bold_meta.group("key").strip().lower().split("(")[0].strip()
        if key in _META_KEYS:
            return True
    if re.match(r"^[A-Z][A-Za-z\-]+,\s+[A-Z].*\(\d{4}\)", text):
        return True
    if re.match(r"(?i)^\s*#{1,6}\s+", text):
        return True
    if re.match(r"(?i)^\s*https?://\S+$", text):
        return True
    return False


def _parse_inline_attribution(line: str) -> dict[str, Any] | None:
    text = line.strip()
    match = _INLINE_SPEAKER_CLAIM.match(text)
    if match:
        speaker = _clean_speaker(match.group("speaker"))
        claim = match.group("claim").strip()
        if speaker and _usable_claim_text(claim):
            # Prefer short desk token when speaker starts with known desk.
            desk = _desk_at_start(speaker) or speaker
            return _prose_unit(desk, claim, raw=text)
    match = _LEADING_DESK.match(text)
    if match:
        speaker = match.group("speaker").strip()
        affil = (match.group("affil") or "").strip()
        if affil:
            speaker_full = f"{_normalize_desk(speaker)} ({affil})"
        else:
            speaker_full = _normalize_desk(speaker)
        speaker_full = _clean_speaker(speaker_full)
        claim = match.group("claim").strip()
        claim = re.sub(
            r"^(?:says?|notes?|argues?|expects?|writes?|sees?)\s+",
            "",
            claim,
            flags=re.I,
        )
        if speaker_full and _usable_claim_text(claim):
            return _prose_unit(speaker_full, claim, raw=text)
    return None


def _usable_claim_text(claim: str) -> bool:
    text = claim.strip()
    if len(text) < _MIN_CLAIM_CHARS:
        return False
    if text.lower().startswith(("http://", "https://")):
        return False
    if _is_citation_or_metadata(text):
        return False
    return True


def _prose_unit(
    speaker: str,
    claim: str,
    *,
    raw: str,
    causes: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "claim": claim.strip(),
        "speaker": speaker,
        "publisher": None,
        "thread_role": None,
        "thread_target_note_id": None,
        "stance": None,
        "causes": list(causes or []),
        "need_live": False,
        "raw_block": raw,
    }


def _build_claim_note(
    note: LibraryResearchNote,
    unit: dict[str, Any],
    *,
    index: int,
    default_speaker: str | None,
    default_publisher: str,
    source_date: date | None,
) -> ClaimNote | None:
    claim_text = str(unit.get("claim") or "").strip()
    if not claim_text or not _usable_claim_text(claim_text):
        return None

    speaker_raw = _clean_speaker(unit.get("speaker") or default_speaker)
    if speaker_raw is None:
        return None

    publisher_raw = (unit.get("publisher") or default_publisher or "").strip()
    publisher = publisher_raw or LIBRARY_PUBLISHER

    thread_target = str(unit.get("thread_target_note_id") or "").strip() or None
    thread_role = _thread_role(
        explicit=unit.get("thread_role"),
        claim_text=claim_text,
        raw_block=str(unit.get("raw_block") or ""),
        has_prior_thread=bool(thread_target),
    )
    stance = _stance(unit.get("stance"))
    cause_edges = _cause_edges(unit.get("causes") or [])

    need_live = bool(unit.get("need_live"))
    support_kind = "live_data" if need_live else "ingested_document_text"
    dexter_pass = None
    if need_live:
        from datetime import timezone

        from src.claim_notes.models import DexterResearchPass

        dexter_pass = DexterResearchPass(
            pass_id=f"dex-lib-{_stable_digest(claim_text)}",
            requested_at=datetime.now(timezone.utc),
            query=claim_text,
            status="awaiting",
        )

    return validate_claim_note(
        ClaimNote(
            note_id=_claim_note_id(note, claim_text, index),
            claim=claim_text,
            speaker=speaker_raw,
            publisher=publisher,
            thread_role=thread_role,  # type: ignore[arg-type]
            thread_target_note_id=thread_target if thread_role in ("extend", "break") else None,
            time_window=_time_window(source_date),
            support_kind=support_kind,  # type: ignore[arg-type]
            speaker_weight="research_author",
            cause_edges=cause_edges,
            document_key=note.url or note.note_id,
            source_date=source_date,
            rationale=(note.title or "").strip(),
            stance=stance,
            dexter_pass=dexter_pass,
        )
    )


def _thread_role(
    *,
    explicit: Any,
    claim_text: str,
    raw_block: str,
    has_prior_thread: bool,
) -> str:
    if not has_prior_thread:
        return "assert"
    if isinstance(explicit, str) and explicit.strip():
        word = explicit.strip().lower()
        match = _THREAD_WORD.search(word)
        if match:
            base = match.group(1).lower()
            if base.startswith("extend"):
                return "extend"
            if base.startswith("break"):
                return "break"
            if base.startswith("assert"):
                return "assert"
    blob = f"{claim_text}\n{raw_block}"
    if re.search(r"(?i)\b(we\s+break|breaks?\s+the|breaking)\b", blob):
        return "break"
    if re.search(r"(?i)\b(we\s+extend|extends?\s+the|extending)\b", blob):
        return "extend"
    return "assert"


def _stance(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cause_edges(causes: list[Any]) -> list[CauseEdge]:
    edges: list[CauseEdge] = []
    for item in causes:
        if isinstance(item, CauseEdge):
            edges.append(item)
            continue
        if isinstance(item, dict):
            cause = str(item.get("cause") or "").strip()
            effect = str(item.get("effect") or "").strip()
            if cause and effect:
                polarity = str(item.get("polarity") or "unspecified").strip().lower()
                if polarity not in {"supports", "undermines", "unspecified"}:
                    polarity = "unspecified"
                edges.append(
                    CauseEdge(
                        cause=cause,
                        effect=effect,
                        polarity=polarity,  # type: ignore[arg-type]
                        as_stated=str(item.get("as_stated") or "").strip() or None,
                    )
                )
            continue
        if isinstance(item, str):
            parsed = _parse_cause_line(item)
            if parsed:
                edges.append(parsed)
    return edges


def _parse_cause_line(line: str) -> CauseEdge | None:
    match = _CAUSE_ARROW.match(line.strip())
    if not match:
        return None
    cause = match.group(1).strip()
    effect = match.group(2).strip()
    polarity = (match.group(3) or "unspecified").strip().lower()
    if polarity not in {"supports", "undermines", "unspecified"}:
        polarity = "unspecified"
    if not cause or not effect:
        return None
    return CauseEdge(
        cause=cause,
        effect=effect,
        polarity=polarity,  # type: ignore[arg-type]
        as_stated=line.strip(),
    )


def _time_window(source_date: date | None) -> TimeWindow:
    if source_date is not None:
        return TimeWindow(
            start=source_date, end=source_date, label=source_date.isoformat()
        )
    return TimeWindow(label="LIBRARY Research Note")


def _claim_note_id(note: LibraryResearchNote, claim: str, index: int) -> str:
    base = (note.note_id or "").strip() or "lib"
    return f"{base}-{index}-{_stable_digest(claim)}"


def _stable_digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
