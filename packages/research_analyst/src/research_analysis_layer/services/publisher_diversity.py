"""Publisher-deduped source diversity for Slice 2.

A position/side is always a **publisher** (the house), never a thesis or
contrarian lens, and never a per-claim field. Multiple notes from the same
bank are one source. That is the substrate's "false source diversity" edge
case: three Goldman notes must count as diversity 1.

`research_relations.source_diversity` exists in the parser memory schema but
is not written at runtime. This helper is the join Task 4+ must use for every
consensus/divergence count.

Publisher is resolved through the document: prefer `source` (filled on live
maps) then `publisher` (often null). Never read a claim-level publisher.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from research_analysis_layer.models.assertion_models import normalize_text

# Canonical house identities. Aliases cover short names the digest will use
# (GS, JPM) and punctuation variants (J.P. Morgan / JP Morgan).
_PUBLISHER_ALIASES: dict[str, tuple[str, str]] = {
    "jpmorgan": ("jpmorgan", "J.P. Morgan"),
    "jp morgan": ("jpmorgan", "J.P. Morgan"),
    "j p morgan": ("jpmorgan", "J.P. Morgan"),
    "jpm": ("jpmorgan", "J.P. Morgan"),
    "goldman sachs": ("goldman_sachs", "Goldman Sachs"),
    "goldman": ("goldman_sachs", "Goldman Sachs"),
    "gs": ("goldman_sachs", "Goldman Sachs"),
    "morgan stanley": ("morgan_stanley", "Morgan Stanley"),
    "ms": ("morgan_stanley", "Morgan Stanley"),
    "deutsche bank": ("deutsche_bank", "Deutsche Bank"),
    "deutsche": ("deutsche_bank", "Deutsche Bank"),
    "db": ("deutsche_bank", "Deutsche Bank"),
    "citi": ("citi", "Citi"),
    "citigroup": ("citi", "Citi"),
    "citibank": ("citi", "Citi"),
    "barclays": ("barclays", "Barclays"),
    "barclays capital": ("barclays", "Barclays"),
}


@dataclass(frozen=True, slots=True)
class Publisher:
    """A deduped publishing house."""

    key: str
    label: str


def canonical_publisher(
    *,
    source: str | None = None,
    publisher: str | None = None,
    name: str | None = None,
) -> Publisher | None:
    """Map a document's house fields to one canonical publisher.

    Prefers `source` (the filled house field on live maps), then `publisher`,
    then a bare `name`. Returns None when nothing usable is present.
    """
    raw = _first_nonempty(source, publisher, name)
    if raw is None:
        return None
    folded = normalize_text(raw)
    if not folded:
        return None
    mapped = _PUBLISHER_ALIASES.get(folded)
    if mapped is not None:
        key, label = mapped
        return Publisher(key=key, label=label)
    slug = folded.replace(" ", "_")
    return Publisher(key=slug, label=raw.strip())


def publisher_for_document(document: Any) -> Publisher | None:
    """Resolve publisher through the document, never a per-claim value."""
    source, publisher = _document_house_fields(document)
    return canonical_publisher(source=source, publisher=publisher)


def distinct_publishers(cluster: Iterable[Any]) -> tuple[Publisher, ...]:
    """Unique publishers in a cluster, sorted by key.

    Accepts document-like objects/dicts (`source` / `publisher`), or Publisher
    instances, or house-name strings. Duplicate notes from one bank collapse.
    """
    by_key: dict[str, Publisher] = {}
    for item in cluster:
        resolved = _resolve_member(item)
        if resolved is None:
            continue
        by_key.setdefault(resolved.key, resolved)
    return tuple(by_key[key] for key in sorted(by_key))


def source_diversity(cluster: Iterable[Any]) -> int:
    """Count of distinct publishers. Three GS notes → 1; GS + MS → 2."""
    return len(distinct_publishers(cluster))


def _resolve_member(item: Any) -> Publisher | None:
    if item is None:
        return None
    if isinstance(item, Publisher):
        return item
    if isinstance(item, str):
        return canonical_publisher(name=item)
    source, publisher = _document_house_fields(item)
    return canonical_publisher(source=source, publisher=publisher)


def _document_house_fields(item: Any) -> tuple[str | None, str | None]:
    if isinstance(item, Mapping):
        return _as_optional_str(item.get("source")), _as_optional_str(
            item.get("publisher")
        )
    nested = getattr(item, "document", None)
    if nested is not None and nested is not item:
        source, publisher = _document_house_fields(nested)
        if source or publisher:
            return source, publisher
    return (
        _as_optional_str(getattr(item, "source", None)),
        _as_optional_str(getattr(item, "publisher", None)),
    )


def _first_nonempty(*values: str | None) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def _as_optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None
