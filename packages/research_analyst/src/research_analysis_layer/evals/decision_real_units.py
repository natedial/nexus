"""Export real-document assertion units for decision evaluation.

Units come from ``analysis_assertions`` rows of approved documents, read with a
read-only database session. Preparation is explicit and reviewable:

- the ``<64-hex document hash>: `` prefix stored on every assertion is removed;
- legal/disclosure boilerplate, very short fragments, and over-long blobs are
  excluded by a versioned rule list, and every excluded row is written out
  with the rule that matched, so exclusions can be reviewed rather than trusted.

Jev then classifies the kept units into one shadow artifact per document. The
pilot loader reads those artifacts, so pilot sources carry exactly the text Jev
saw.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from research_analysis_layer.evals.decision_agent_references import (
    SourceTransformation,
)
from research_analysis_layer.evals.decision_artifacts import write_shadow_artifact
from research_analysis_layer.evals.decision_reviews import sha256_text
from research_analysis_layer.models.assertion_models import AssertionDraft, normalize_text

EXPORT_SCHEMA = "decision-real-units-export-v1"
EXCLUSION_RULES_VERSION = "decision-real-units-exclusions-v3"
HASH_PREFIX = re.compile(r"^[0-9a-f]{64}: ")
MIN_UNIT_CHARS = 40
MAX_UNIT_CHARS = 1_200
TRAILING_EXCLUDED_SHARE = 0.5

# (rule_id, pattern). Matched case-insensitively against the stripped text.
BOILERPLATE_RULES: tuple[tuple[str, str], ...] = (
    ("disclosure", r"\bdisclos"),
    ("investment_risk_notice", r"investment risks|solely responsible"),
    ("value_may_fluctuate", r"price and value of investments|value of (?:the )?investments? .{0,40}(?:fall|fluctuat)"),
    ("past_performance", r"past performance"),
    ("client_relationships", r"client relationships?"),
    ("conflicts_of_interest", r"conflicts? of interest"),
    ("not_an_offer", r"not an offer|offer to (?:buy|sell)|solicitation"),
    ("regulatory_entity", r"\b(?:registered|regulated|authori[sz]ed) (?:by|with|in)\b"),
    ("legal_entity", r"\baffiliates?\b|legal entit"),
    ("copyright", r"copyright|all rights reserved|©"),
    ("distribution_notice", r"\bdistribut(?:e|ed|ion) (?:to|in|by)\b|redistribut"),
    ("analyst_certification", r"research analysts?|analyst certification"),
    ("report_self_reference", r"\bthis (?:report|material|publication|document) (?:is|has|was|does|should|may)\b"),
    ("sales_and_trading", r"sales and trading"),
    ("table_fragment", r"\|.*\|"),
    ("contact_details", r"[\w.+-]+@[\w-]+\.[\w.]+|\+\d{1,3}[\d ()-]{6,}"),
    ("url", r"https?://|\bwww\.|\.co(?:m)? ?/"),
    ("rating_definitions", r"definition of terms|the analyst expects|stock ratings?\b|ratings? of buy, hold"),
    ("terms_of_use", r"terms of use|investment advice|for your reference only|intended (?:only )?for '"),
)
_COMPILED_RULES = tuple(
    (rule_id, re.compile(pattern, re.IGNORECASE)) for rule_id, pattern in BOILERPLATE_RULES
)

# Page-layout text that is not an author statement: figure title blocks,
# exhibit captions, and source or note lines. Kept apart from the boilerplate
# rules so they never start or extend a trailing-disclosures cut. A heading
# glued to a real sentence ("Key Takeaways\n\nBasis notional has fallen...")
# is deliberately not matched.
LAYOUT_RULES: tuple[tuple[str, str], ...] = (
    ("figure_title_block", r"^figure\b"),
    ("exhibit_caption", r"(?:^|\n)\s*exhibit \d+:"),
    ("source_note", r"\bsource: |^note: "),
)
_COMPILED_LAYOUT_RULES = tuple(
    (rule_id, re.compile(pattern, re.IGNORECASE)) for rule_id, pattern in LAYOUT_RULES
)

PREFIX_TRANSFORMATION = SourceTransformation(
    transformation_id="strip-document-hash-prefix",
    kind="other",
    description=(
        "Removed the '<64-hex document hash>: ' label that analysis_assertions "
        "stores before every assertion text."
    ),
    meaning_preserved=True,
)


@dataclass(frozen=True)
class RealAssertionRow:
    assertion_id: int
    research_id: int
    document_hash: str | None
    chunk_order: int
    assertion_order: int
    assertion_type: str
    text: str


@dataclass(frozen=True)
class RealDocument:
    research_id: int
    document_hash: str | None
    source: str | None
    source_date: str | None
    title: str | None

    @property
    def document_key(self) -> str:
        return f"research-{self.research_id}"


@dataclass(frozen=True)
class PreparedUnit:
    row: RealAssertionRow
    text: str
    prefix_stripped: bool

    @property
    def unit_id(self) -> str:
        return f"chunk-{self.row.chunk_order}:assertion-{self.row.assertion_order}"


def fetch_documents(connection: Any, research_ids: Sequence[int]) -> list[RealDocument]:
    rows = connection.execute(
        "select research_id, document_hash, source, source_date::text, title "
        "from analysis_documents where research_id = any(%s) order by research_id",
        (list(research_ids),),
    ).fetchall()
    found = {int(row[0]) for row in rows}
    missing = sorted(set(research_ids) - found)
    if missing:
        raise ValueError(f"analysis_documents has no rows for research_id {missing}")
    return [RealDocument(int(r[0]), r[1], r[2], r[3], r[4]) for r in rows]


def fetch_assertion_rows(
    connection: Any, research_ids: Sequence[int]
) -> list[RealAssertionRow]:
    rows = connection.execute(
        "select id, research_id, document_hash, chunk_order, assertion_order, "
        "assertion_type, text from analysis_assertions where research_id = any(%s) "
        "order by research_id, chunk_order, assertion_order",
        (list(research_ids),),
    ).fetchall()
    return [
        RealAssertionRow(
            assertion_id=int(r[0]),
            research_id=int(r[1]),
            document_hash=r[2],
            chunk_order=int(r[3]),
            assertion_order=int(r[4]),
            assertion_type=str(r[5] or "unknown"),
            text=str(r[6] or ""),
        )
        for r in rows
    ]


def exclusion_reason(text: str, *, include_layout: bool = True) -> str | None:
    if len(text) < MIN_UNIT_CHARS:
        return f"too_short(<{MIN_UNIT_CHARS} chars)"
    if len(text) > MAX_UNIT_CHARS:
        return f"too_long(>{MAX_UNIT_CHARS} chars)"
    for rule_id, pattern in _COMPILED_RULES:
        if pattern.search(text):
            return f"boilerplate:{rule_id}"
    if include_layout:
        for rule_id, pattern in _COMPILED_LAYOUT_RULES:
            if pattern.search(text):
                return f"layout:{rule_id}"
    return None


def trailing_section_starts(
    rows: Sequence[RealAssertionRow], texts: Sequence[str]
) -> dict[int, int]:
    """First chunk of each document's trailing disclosures section.

    Candidates are chunks with a boilerplate-rule match (size rules do not
    count). The earliest candidate is accepted only when at least
    ``TRAILING_EXCLUDED_SHARE`` of the units from that chunk to the end are
    excluded by the per-unit rules, so one stray mention mid-report cannot cut
    real content. Layout rules are ignored here, so captions inside a report
    never pull the cut earlier.
    """

    by_document: dict[int, list[tuple[int, str | None]]] = {}
    for row, text in zip(rows, texts):
        by_document.setdefault(row.research_id, []).append(
            (row.chunk_order, exclusion_reason(text, include_layout=False))
        )
    starts: dict[int, int] = {}
    for research_id, units in by_document.items():
        candidates = sorted(
            {chunk for chunk, reason in units if reason and reason.startswith("boilerplate:")}
        )
        for chunk in candidates:
            tail = [reason for unit_chunk, reason in units if unit_chunk >= chunk]
            if sum(reason is not None for reason in tail) >= TRAILING_EXCLUDED_SHARE * len(tail):
                starts[research_id] = chunk
                break
    return starts


def prepare_units(
    rows: Iterable[RealAssertionRow],
) -> tuple[list[PreparedUnit], list[dict[str, Any]]]:
    kept: list[PreparedUnit] = []
    excluded: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int]] = set()
    rows = list(rows)
    stripped: list[tuple[str, bool]] = []
    for row in rows:
        match = HASH_PREFIX.match(row.text)
        text = row.text[match.end() :] if match else row.text
        stripped.append((text.strip(), bool(match)))
    trailing = trailing_section_starts(rows, [text for text, _ in stripped])
    kept_texts: set[tuple[int, str]] = set()
    for row, (text, prefix_stripped) in zip(rows, stripped):
        identity = (row.research_id, row.chunk_order, row.assertion_order)
        if identity in seen:
            raise ValueError(f"duplicate assertion position {identity}")
        seen.add(identity)
        reason = exclusion_reason(text)
        start = trailing.get(row.research_id)
        if reason is None and start is not None and row.chunk_order >= start:
            reason = f"trailing_disclosures(from chunk {start})"
        if reason is None and (row.research_id, text) in kept_texts:
            reason = "duplicate_text_in_document"
        if reason is None:
            kept_texts.add((row.research_id, text))
        if reason is not None:
            excluded.append(
                {
                    "assertion_id": row.assertion_id,
                    "research_id": row.research_id,
                    "unit_id": f"chunk-{row.chunk_order}:assertion-{row.assertion_order}",
                    "assertion_type": row.assertion_type,
                    "reason": reason,
                    "text": text,
                }
            )
            continue
        kept.append(PreparedUnit(row=row, text=text, prefix_stripped=prefix_stripped))
    return kept, excluded


def to_assertion_drafts(units: Sequence[PreparedUnit]) -> list[AssertionDraft]:
    return [
        AssertionDraft(
            chunk_order=unit.row.chunk_order,
            assertion_order=unit.row.assertion_order,
            assertion_type=unit.row.assertion_type,
            text=unit.text,
            normalized_text=normalize_text(unit.text),
            summary_text=unit.text,
        )
        for unit in units
    ]


def export_real_units(
    *,
    connection: Any,
    research_ids: Sequence[int],
    output_dir: Path,
    classifier: Any,
) -> dict[str, Any]:
    """Write prepared units, exclusions, and one Jev artifact per document."""

    if not research_ids:
        raise ValueError("at least one research_id is required")
    output_dir.mkdir(parents=True, exist_ok=False)
    documents = fetch_documents(connection, research_ids)
    rows = fetch_assertion_rows(connection, research_ids)
    kept, excluded = prepare_units(rows)

    (output_dir / "excluded_units.jsonl").write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in excluded),
        encoding="utf-8",
    )
    artifacts_dir = output_dir / "artifacts"
    per_document: list[dict[str, Any]] = []
    for document in documents:
        units = [unit for unit in kept if unit.row.research_id == document.research_id]
        (output_dir / f"units_{document.document_key}.jsonl").write_text(
            "".join(
                json.dumps(
                    {
                        "assertion_id": unit.row.assertion_id,
                        "unit_id": unit.unit_id,
                        "assertion_type": unit.row.assertion_type,
                        "prefix_stripped": unit.prefix_stripped,
                        "text": unit.text,
                        "text_sha256": sha256_text(unit.text),
                    },
                    sort_keys=True,
                )
                + "\n"
                for unit in units
            ),
            encoding="utf-8",
        )
        artifact = classifier.classify_assertions(
            to_assertion_drafts(units),
            document_key=document.document_key,
            document_hash=document.document_hash,
            provenance_by_unit={
                unit.unit_id: {
                    "assertion_id": unit.row.assertion_id,
                    "research_id": unit.row.research_id,
                    "source": document.source,
                    "source_date": document.source_date,
                }
                for unit in units
            },
        )
        path = write_shadow_artifact(artifact, artifacts_dir, prefix="shadow")
        per_document.append(
            {
                "research_id": document.research_id,
                "document_key": document.document_key,
                "source": document.source,
                "source_date": document.source_date,
                "title": document.title,
                "assertion_rows": sum(
                    row.research_id == document.research_id for row in rows
                ),
                "kept_units": len(units),
                "excluded_units": sum(
                    item["research_id"] == document.research_id for item in excluded
                ),
                "artifact": path.relative_to(output_dir).as_posix(),
                "question_set_version": artifact.question_set_version,
                "model_version": artifact.model_version,
            }
        )

    reasons: dict[str, int] = {}
    for item in excluded:
        reasons[item["reason"]] = reasons.get(item["reason"], 0) + 1
    manifest = {
        "schema_version": EXPORT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "research_ids": list(research_ids),
        "exclusion_rules_version": EXCLUSION_RULES_VERSION,
        "exclusion_rules": [list(rule) for rule in BOILERPLATE_RULES],
        "layout_rules": [list(rule) for rule in LAYOUT_RULES],
        "min_unit_chars": MIN_UNIT_CHARS,
        "max_unit_chars": MAX_UNIT_CHARS,
        "transformations": [PREFIX_TRANSFORMATION.model_dump(mode="json")],
        "assertion_rows": len(rows),
        "kept_units": len(kept),
        "excluded_units": len(excluded),
        "excluded_by_reason": dict(sorted(reasons.items())),
        "documents": per_document,
        "database_access": "read_only",
    }
    (output_dir / "export_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


__all__ = [
    "BOILERPLATE_RULES",
    "EXCLUSION_RULES_VERSION",
    "PREFIX_TRANSFORMATION",
    "PreparedUnit",
    "RealAssertionRow",
    "RealDocument",
    "exclusion_reason",
    "export_real_units",
    "fetch_assertion_rows",
    "fetch_documents",
    "prepare_units",
    "to_assertion_drafts",
]
