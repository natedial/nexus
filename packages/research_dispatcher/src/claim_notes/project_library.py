"""LIBRARY Research Note → claim-note-v1 (Gerhard extraction contract).

One Research Note → **N claims** from the **full page body** (not title /
Description alone). Proey's ``--library-json`` must include ``body``.

Locked rules (do not reopen):
1. Extract claims from full body text as stated — never invent numbers.
2. ``speaker`` = attributed desk/author in the note (JPM, Barclays, …) —
   **never** ``LIBRARY desk``.
3. ``publisher`` = Notion LIBRARY, or the note's source publisher when present.
4. ``thread_role`` = assert | extend | break from framing; default **assert**.
5. ``stance`` (side) only when the note states one; otherwise **null**.
6. ``support_kind`` = ``ingested_document_text``; ``dexter_pass`` null unless
   the note itself marks a live-number need.
7. ``cause_edges`` only when the note **explicitly** asserts A causes B.
8. Morning-attention risk-into-prints filtering is the product surface — not here.
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
# Banned — scaffolding used this; Gerhard lock forbids it as speaker.
_BANNED_SPEAKERS = frozenset({"library desk", "library", "notion library"})

_CLAIM_START = re.compile(
    r"(?im)^\s*(?:claim|contention)\s*[:\-–—]\s*(.+)$"
)
_META_LINE = re.compile(
    r"(?im)^\s*(speaker|author|desk|publisher|source|thread(?:_role)?|"
    r"thread_target(?:_note_id)?|target|stance|side|role|cause|causes|"
    r"support_kind|live_number|need_live)\s*[:\-–—]\s*(.+)$"
)
_HEADER_ATTR = re.compile(
    r"(?im)^\s*(?:speaker|author|desk|by)\s*[:\-–—]\s*(.+)$"
)
_HEADER_PUB = re.compile(
    r"(?im)^\s*(?:publisher|source|house)\s*[:\-–—]\s*(.+)$"
)
_BULLET_CLAIM = re.compile(r"(?m)^\s*[-*•]\s+(?:claim\s*[:\-–—]\s*)?(.+)$")
_CAUSE_ARROW = re.compile(
    r"(?i)^\s*(.+?)\s*(?:->|→|⇒|causes?|leads?\s+to)\s+(.+?)(?:\s*\((supports|undermines|unspecified)\))?\s*$"
)
_THREAD_WORD = re.compile(
    r"(?i)\b(assert|extend(?:s|ing)?|break(?:s|ing)?)\b"
)
_EXTEND_HINT = re.compile(r"(?i)\b(extend(?:s|ing)?|builds?\s+on|adds?\s+to)\b")
_BREAK_HINT = re.compile(r"(?i)\b(break(?:s|ing)?|rejects?|contradicts?|pushes?\s+back)\b")


def project_library_research_note(note: LibraryResearchNote) -> list[ClaimNote]:
    """Extract N claim notes from one LIBRARY Research Note body.

    Returns an empty list when there is no attributable speaker or no body claims.
    Never invents ``LIBRARY desk`` as speaker.
    """
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
    # Body is canonical; title/summary alone are scaffolding and insufficient.
    if not body:
        return []

    header_speaker, header_publisher = _header_attribution(body)
    speaker = _resolve_speaker(note, header_speaker)
    if speaker is None:
        return []

    publisher = _resolve_publisher(note, header_publisher)
    source_date = _source_date(note)
    raw_claims = _split_claim_units(body)
    if not raw_claims:
        return []

    notes_out: list[ClaimNote] = []
    for index, unit in enumerate(raw_claims):
        built = _build_claim_note(
            note,
            unit,
            index=index,
            default_speaker=speaker,
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
        text = (raw or "").strip()
        if not text:
            continue
        if text.lower() in _BANNED_SPEAKERS:
            continue
        return text
    return None


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
    # Only scan the preamble before the first Claim: / bullet block.
    preamble = body
    first_claim = _CLAIM_START.search(body)
    first_bullet = _BULLET_CLAIM.search(body)
    cut = len(body)
    if first_claim:
        cut = min(cut, first_claim.start())
    if first_bullet:
        cut = min(cut, first_bullet.start())
    preamble = body[:cut]
    for match in _HEADER_ATTR.finditer(preamble):
        speaker = match.group(1).strip() or speaker
    for match in _HEADER_PUB.finditer(preamble):
        publisher = match.group(1).strip() or publisher
    return speaker, publisher


def _split_claim_units(body: str) -> list[dict[str, Any]]:
    """Split body into claim units (structured Claim: blocks or bullets)."""
    structured = _parse_structured_claims(body)
    if structured:
        return structured
    return _parse_bullet_claims(body)


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
        # Claim line itself may be only the first line; meta may refine claim.
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
            "support_kind": meta.get("support_kind"),
            "raw_block": block,
        }
        # Causes may also appear as Cause: lines collected in meta.
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
        elif key == "support_kind":
            meta["support_kind"] = value
        elif key in {"live_number", "need_live"}:
            meta["need_live"] = value.lower() in {"1", "true", "yes", "y"}
        elif key == "claim":
            meta["claim"] = value
    return meta


def _parse_bullet_claims(body: str) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    for match in _BULLET_CLAIM.finditer(body):
        text = match.group(1).strip()
        if not text:
            continue
        # Skip meta-looking bullets.
        if _META_LINE.match(f"- {text}") or _HEADER_ATTR.match(text) or _HEADER_PUB.match(text):
            continue
        if text.lower().startswith(("speaker:", "author:", "publisher:", "source:")):
            continue
        units.append(
            {
                "claim": text,
                "speaker": None,
                "publisher": None,
                "thread_role": None,
                "thread_target_note_id": None,
                "stance": None,
                "causes": [],
                "need_live": False,
                "support_kind": None,
                "raw_block": text,
            }
        )
    return units


def _build_claim_note(
    note: LibraryResearchNote,
    unit: dict[str, Any],
    *,
    index: int,
    default_speaker: str,
    default_publisher: str,
    source_date: date | None,
) -> ClaimNote | None:
    claim_text = str(unit.get("claim") or "").strip()
    if not claim_text:
        return None

    speaker_raw = (unit.get("speaker") or default_speaker or "").strip()
    if not speaker_raw or speaker_raw.lower() in _BANNED_SPEAKERS:
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
    cause_edges = _cause_edges(unit.get("causes") or [], claim_text, str(unit.get("raw_block") or ""))

    need_live = bool(unit.get("need_live"))
    support_kind = "live_data" if need_live else "ingested_document_text"
    dexter_pass = None
    if need_live:
        # Pointer only — products never invent findings. External Dexter attaches later.
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
    """Default assert when no prior thread — do not invent extend/break targets."""
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
    if not text:
        return None
    # Do not invent hawk/dove from synonyms — only accept as stated.
    return text


def _cause_edges(
    causes: list[Any], claim_text: str, raw_block: str
) -> list[CauseEdge]:
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
    # Only add from free text when an explicit cause line exists in the block
    # (already collected). Do not scrape invented causal links from prose.
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
    digest = _stable_digest(claim)
    return f"{base}-{index}-{digest}"


def _stable_digest(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
