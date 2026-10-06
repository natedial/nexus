"""Deterministic projection: analyst argument_map document → ClaimNote list.

Canonical Morning Attention claim source (locked 2026-10-06): research_analyst
ClaimNodes / argument_map — not LIBRARY body extraction.

Does not call Dexter, does not invent live numbers, and does not infer a
causal world model. Cause edges are copied only when already present on the
claim (speaker-asserted storage). Single-document maps project as ``assert``
unless the claim already carries thread_role / thread_target_note_id.

Gerhard field rules (validators; under-extract OK — skip bad claims):
- one idea per claim
- correct speaker (never LIBRARY desk)
- no desk merges
- cause edges only when stated on the claim
- no invented numbers
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from src.claim_notes.models import (
    CauseEdge,
    ClaimNote,
    SpeakerWeight,
    TimeWindow,
)
from src.claim_notes.validate import validate_claim_note

_SPEAKER_WEIGHTS = frozenset(
    {"chair", "voter", "non-voter", "interview", "research_author"}
)
_THREAD_ROLES = frozenset({"assert", "extend", "break"})
_LIBRARY_DESK = re.compile(r"^library\s+desk$", re.IGNORECASE)
# "JPM / Barclays", "Citi & MS", "A and B" desk merges — never project as one speaker.
_DESK_MERGE = re.compile(
    r"\s+(?:/|&|\band\b)\s+",
    re.IGNORECASE,
)
# Second sentence / numbered list → more than one idea.
_MULTI_SENTENCE = re.compile(r"[.!?]\s+[A-Z0-9]")
_NUMBERED_ITEMS = re.compile(r"\b\d+[.)]\s+\S+.*\b\d+[.)]\s+")


def project_argument_map_document(
    document: Mapping[str, Any],
    *,
    default_speaker_weight: SpeakerWeight = "research_author",
) -> list[ClaimNote]:
    """Project one dispatch/analyst document's ``argument_map`` to claim notes.

    Invalid claims are skipped (under-extract). Documents with no usable
    speaker identity raise ``ValueError``.
    """
    argument_map = document.get("argument_map") or []
    if not isinstance(argument_map, list):
        raise ValueError("document.argument_map must be a list")

    speaker = _speaker(document)
    if _is_library_desk(speaker):
        # Never project LIBRARY desk as speaker — drop the whole document map.
        return []
    if _is_merged_desk(speaker):
        return []

    publisher = _optional_str(document.get("publisher"))
    research_id = _optional_int(document.get("research_id"))
    document_key = _optional_str(document.get("document_key")) or _optional_str(
        document.get("document_name")
    )
    source_date = _parse_date(document.get("source_date"))
    speaker_weight = _speaker_weight(
        document.get("speaker_weight"), default=default_speaker_weight
    )

    notes: list[ClaimNote] = []
    for index, raw in enumerate(argument_map):
        if not isinstance(raw, Mapping):
            continue
        claim_text = _optional_str(raw.get("claim"))
        if not claim_text:
            continue
        if not _is_one_idea(claim_text):
            continue
        # Per-claim speaker override must still obey Gerhard rules.
        claim_speaker = _optional_str(raw.get("speaker")) or speaker
        if _is_library_desk(claim_speaker) or _is_merged_desk(claim_speaker):
            continue
        note = ClaimNote(
            note_id=_note_id(document_key, research_id, index, claim_text),
            claim=claim_text,
            speaker=claim_speaker,
            publisher=publisher,
            thread_role=_thread_role(raw),
            thread_target_note_id=_optional_str(raw.get("thread_target_note_id")),
            time_window=_time_window(raw, source_date),
            support_kind="ingested_document_text",
            speaker_weight=speaker_weight,
            cause_edges=_cause_edges(raw),
            claim_key=_optional_str(raw.get("claim_key")),
            research_id=research_id,
            document_key=document_key,
            source_date=source_date,
            rationale=_optional_str(raw.get("rationale")) or "",
            conditions=_string_list(raw.get("conditions")),
            stance=_optional_str(raw.get("stance")),
        )
        notes.append(validate_claim_note(note))
    return notes


def project_argument_map_batch(
    documents: Sequence[Mapping[str, Any]],
    *,
    default_speaker_weight: SpeakerWeight = "research_author",
) -> list[ClaimNote]:
    """Project many documents; preserves document order then claim order."""
    notes: list[ClaimNote] = []
    for document in documents:
        notes.extend(
            project_argument_map_document(
                document, default_speaker_weight=default_speaker_weight
            )
        )
    return notes


def filter_argument_map_documents(
    documents: Sequence[Mapping[str, Any]],
    *,
    since: date | datetime | None = None,
    until: date | datetime | None = None,
) -> list[Mapping[str, Any]]:
    """Keep documents whose ``source_date`` falls in ``[since, until]`` (inclusive).

    Documents with no parseable ``source_date`` are kept when a bound is set
    only if they cannot be dated — actually drop undated when filtering by
    since/until so Proey since-watermark windows stay tight (under-include OK).
    """
    since_d = _as_date(since)
    until_d = _as_date(until)
    if since_d is None and until_d is None:
        return list(documents)

    out: list[Mapping[str, Any]] = []
    for document in documents:
        src = _parse_date(document.get("source_date"))
        if src is None:
            continue
        if since_d is not None and src < since_d:
            continue
        if until_d is not None and src > until_d:
            continue
        out.append(document)
    return out


def load_argument_map_documents(path: str | Any) -> list[Mapping[str, Any]]:
    """Load export-dispatch-batch JSON (``{documents:[...]}``) or a bare list."""
    import json
    from pathlib import Path

    raw = Path(path).read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, dict) and "documents" in data:
        docs = data["documents"]
    else:
        docs = data
    if not isinstance(docs, list):
        raise ValueError("argument_map JSON must be a list or {documents: [...]}")
    return docs


def resolve_analyst_batch_path(
    batch_dir: str | Any,
    *,
    batch_file: str | None = None,
) -> Any:
    """Resolve Proey analyst batch out dir → JSON path (latest.json or named file)."""
    from pathlib import Path

    root = Path(batch_dir)
    if batch_file:
        candidate = root / batch_file
        if not candidate.is_file():
            raise FileNotFoundError(f"analyst batch file not found: {candidate}")
        return candidate
    latest = root / "latest.json"
    if latest.is_file() or latest.is_symlink():
        return latest
    raise FileNotFoundError(
        f"no latest.json in analyst batch dir: {root} "
        "(run export-dispatch-batch first)"
    )


def _speaker(document: Mapping[str, Any]) -> str:
    for key in ("speaker", "author", "source"):
        value = _optional_str(document.get(key))
        if value:
            return value
    publisher = _optional_str(document.get("publisher"))
    if publisher:
        return publisher
    raise ValueError(
        "document needs speaker, author, source, or publisher to project claim notes"
    )


def _is_library_desk(speaker: str) -> bool:
    return bool(_LIBRARY_DESK.match(speaker.strip()))


def _is_merged_desk(speaker: str) -> bool:
    text = speaker.strip()
    if ";" in text:
        return True
    return bool(_DESK_MERGE.search(text))


def _is_one_idea(claim: str) -> bool:
    text = claim.strip()
    if not text:
        return False
    if ";" in text:
        return False
    if _MULTI_SENTENCE.search(text):
        return False
    if _NUMBERED_ITEMS.search(text):
        return False
    return True


def _speaker_weight(value: Any, *, default: SpeakerWeight) -> SpeakerWeight:
    if isinstance(value, str) and value.strip() in _SPEAKER_WEIGHTS:
        return value.strip()  # type: ignore[return-value]
    return default


def _thread_role(raw: Mapping[str, Any]) -> str:
    role = _optional_str(raw.get("thread_role"))
    if role in _THREAD_ROLES:
        return role
    return "assert"


def _time_window(raw: Mapping[str, Any], source_date: date | None) -> TimeWindow:
    horizon = _optional_str(raw.get("horizon"))
    if horizon:
        return TimeWindow(label=horizon)
    if source_date is not None:
        return TimeWindow(start=source_date, end=source_date, label=source_date.isoformat())
    return TimeWindow(label="unspecified")


def _cause_edges(raw: Mapping[str, Any]) -> list[CauseEdge]:
    """Copy speaker-asserted edges only — never invent a world-model link."""
    edges: list[CauseEdge] = []
    for item in raw.get("cause_edges") or []:
        if not isinstance(item, Mapping):
            continue
        cause = _optional_str(item.get("cause"))
        effect = _optional_str(item.get("effect"))
        if not cause or not effect:
            continue
        polarity = _optional_str(item.get("polarity")) or "unspecified"
        if polarity not in {"supports", "undermines", "unspecified"}:
            polarity = "unspecified"
        edges.append(
            CauseEdge(
                cause=cause,
                effect=effect,
                polarity=polarity,  # type: ignore[arg-type]
                as_stated=_optional_str(item.get("as_stated")),
            )
        )
    return edges


def _note_id(
    document_key: str | None,
    research_id: int | None,
    index: int,
    claim_text: str,
) -> str:
    digest = hashlib.sha1(claim_text.encode("utf-8")).hexdigest()[:10]
    doc = re.sub(r"[^a-zA-Z0-9._-]+", "-", document_key or "doc").strip("-") or "doc"
    rid = research_id if research_id is not None else "x"
    return f"cn-{doc}-{rid}-{index}-{digest}"


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = _optional_str(item)
        if text:
            out.append(text)
    return out


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return date.fromisoformat(text[:10])


def _as_date(value: date | datetime | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    return value
