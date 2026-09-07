"""Resolve argument-map evidence to canonical `referent_key` values.

This is Slice 2 Task 1. It is a new resolver and must not be folded into
`Resolver`, which owns the assertion world-graph (`concept:` / `forecast:` nodes).

Namespace (no free prose):

- `event:<slug>[:facet]` — a named event (speech, meeting, print, microstructure change)
- `series:<slug>` — a named datapoint or market series
- `entity:<slug>` — a named institution or instrument when the citation is about
  the entity itself rather than a print or event

Leave `referent_key` as `None` when the match is not confident. Distinct facts
that share words must not merge (Warsh speech ≠ September FOMC; 10y cash ≠
10y breakevens ≠ 30y; 3m core PCE ≠ 6m core PCE). False merges are worse than
misses.

The existing assertion `Resolver` and the forecast `indicator_key` catalog are
intentionally not reused as the runtime matcher: they do not emit `event:` /
`series:` / `entity:` keys. Forecast indicator names seed a few `series:`
entries only.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Sequence

from research_analysis_layer.models.agent_outputs import ClaimNode, EvidenceRef
from research_analysis_layer.models.assertion_models import normalize_text

REFERENT_NAMESPACES = ("event", "series", "entity")
REFERENT_GRANULARITIES = ("coarse", "fine")
DEFAULT_REFERENT_GRANULARITY = "coarse"


def _fold(text: str) -> str:
    return normalize_text(text or "")


def _has_phrase(folded: str, phrase: str) -> bool:
    needle = _fold(phrase)
    if not needle:
        return False
    return f" {needle} " in f" {folded} "


@dataclass(frozen=True)
class ReferentCatalogEntry:
    """One conservative catalog match rule."""

    fine_key: str
    coarse_key: str
    all_of: tuple[tuple[str, ...], ...]
    none_of: tuple[str, ...] = ()
    weight: int = 1

    def __post_init__(self) -> None:
        namespace = self.fine_key.split(":", 1)[0]
        if namespace not in REFERENT_NAMESPACES:
            raise ValueError(f"unsupported referent namespace: {self.fine_key}")
        coarse_ns = self.coarse_key.split(":", 1)[0]
        if coarse_ns not in REFERENT_NAMESPACES:
            raise ValueError(f"unsupported referent namespace: {self.coarse_key}")


# Catalog is hand-curated from live Slice 1 maps. Prefer misses over guesses.
REFERENT_CATALOG: tuple[ReferentCatalogEntry, ...] = (
    ReferentCatalogEntry(
        fine_key="event:jackson_hole_2026:warsh_speech",
        coarse_key="event:jackson_hole_2026",
        all_of=(
            ("warsh",),
            ("jackson hole", "speech", "symposium", "remarks", "reaffirmation"),
        ),
        weight=3,
    ),
    ReferentCatalogEntry(
        fine_key="event:fomc_2026_09",
        coarse_key="event:fomc",
        all_of=(("september", "sep"), ("fomc",)),
        none_of=("warsh", "jackson hole"),
    ),
    ReferentCatalogEntry(
        fine_key="event:fomc_2026_07",
        coarse_key="event:fomc",
        all_of=(("july",), ("fomc",)),
        none_of=("warsh", "jackson hole"),
    ),
    ReferentCatalogEntry(
        fine_key="event:fomc_2026_06",
        coarse_key="event:fomc",
        all_of=(("june",), ("fomc", "june meeting")),
        none_of=("warsh", "jackson hole"),
    ),
    ReferentCatalogEntry(
        fine_key="event:beige_book",
        coarse_key="event:beige_book",
        all_of=(("beige book",),),
        weight=3,
    ),
    ReferentCatalogEntry(
        fine_key="event:cpi_print:august_2026",
        coarse_key="event:cpi_print",
        all_of=(("august",), ("cpi",), ("print", "release")),
        weight=2,
    ),
    ReferentCatalogEntry(
        fine_key="event:brokertec_tick_size_2026_06_29",
        coarse_key="event:brokertec_tick_size",
        all_of=(("brokertec",),),
        weight=4,
    ),
    ReferentCatalogEntry(
        fine_key="event:china_property_package_2026_08_28",
        coarse_key="event:china_property_package",
        all_of=(
            ("property",),
            ("august 28", "package", "pboc"),
        ),
        weight=2,
    ),
    ReferentCatalogEntry(
        fine_key="series:us_10y_breakevens",
        coarse_key="series:us_breakevens",
        all_of=(
            ("breakeven", "breakevens"),
            ("10y", "10 year", "10yr"),
        ),
        weight=2,
    ),
    ReferentCatalogEntry(
        fine_key="series:us_breakevens",
        coarse_key="series:us_breakevens",
        all_of=(("breakeven", "breakevens", "inflation breakevens"),),
        none_of=("10y", "10 year", "10yr", "30y", "30 year"),
    ),
    ReferentCatalogEntry(
        fine_key="series:us_10y",
        coarse_key="series:us_10y",
        all_of=(
            ("10y", "10 year", "10yr"),
            ("ust", "usts", "treasury", "treasuries", "treasury yield", "treasury yields", "10y yield", "10y yields"),
        ),
        none_of=(
            "breakeven",
            "breakevens",
            "5s30s",
            "jgb",
            "bund",
            "germany",
            "aud",
            "asw",
            "buyback",
            "buybacks",
        ),
    ),
    ReferentCatalogEntry(
        fine_key="series:us_30y",
        coarse_key="series:us_30y",
        all_of=(
            ("30y", "30 year", "30yr"),
            ("ust", "usts", "treasury", "treasuries", "point"),
        ),
        none_of=("5s30s", "ig", "issuance", "corporate", "eu", "bund", "10y", "10 year", "10yr"),
    ),
    ReferentCatalogEntry(
        fine_key="series:us_5s30s",
        coarse_key="series:us_5s30s",
        all_of=(("5s30s",),),
        weight=3,
    ),
    ReferentCatalogEntry(
        fine_key="series:us_core_pce_3m_saar",
        coarse_key="series:us_core_pce",
        all_of=(("3m", "3 month", "3 mo"), ("core pce",)),
        weight=2,
    ),
    ReferentCatalogEntry(
        fine_key="series:us_core_pce_6m_saar",
        coarse_key="series:us_core_pce",
        all_of=(("6m", "6 month", "6 mo"), ("core pce",)),
        weight=2,
    ),
    ReferentCatalogEntry(
        fine_key="series:us_core_pce",
        coarse_key="series:us_core_pce",
        all_of=(("core pce",),),
        none_of=("3m", "3 month", "6m", "6 month"),
    ),
    ReferentCatalogEntry(
        fine_key="series:us_cpi",
        coarse_key="series:us_cpi",
        all_of=(("cpi",),),
        none_of=("print", "release", "core pce", "jgb"),
    ),
    ReferentCatalogEntry(
        fine_key="series:us_nfp",
        coarse_key="series:us_nfp",
        all_of=(("nfp", "nonfarm payroll", "nonfarm payrolls"),),
    ),
    ReferentCatalogEntry(
        fine_key="series:us_unemployment_rate",
        coarse_key="series:us_unemployment_rate",
        all_of=(("unemployment rate",),),
        none_of=("kalshi",)
    ),
    ReferentCatalogEntry(
        fine_key="series:us_jobs_workers_gap",
        coarse_key="series:us_jobs_workers_gap",
        all_of=(("jobs workers gap", "jobs-workers gap"),),
        weight=2,
    ),
    ReferentCatalogEntry(
        fine_key="series:us_mortgage_rate",
        coarse_key="series:us_mortgage_rate",
        all_of=(("mortgage rate", "mortgage rates"),),
    ),
    ReferentCatalogEntry(
        fine_key="series:lira",
        coarse_key="series:lira",
        all_of=(
            ("lira", "leading indicator of remodeling"),
        ),
        weight=3,
    ),
)


@dataclass(frozen=True)
class ReferentMatch:
    entry: ReferentCatalogEntry
    score: int

    @property
    def fine_key(self) -> str:
        return self.entry.fine_key

    @property
    def coarse_key(self) -> str:
        return self.entry.coarse_key


class EvidenceReferentResolver:
    """Deterministic catalog matcher for `EvidenceRef.referent_key`."""

    def __init__(
        self,
        *,
        granularity: str = DEFAULT_REFERENT_GRANULARITY,
        catalog: Sequence[ReferentCatalogEntry] | None = None,
    ) -> None:
        normalized = (granularity or DEFAULT_REFERENT_GRANULARITY).strip().lower()
        if normalized not in REFERENT_GRANULARITIES:
            raise ValueError(
                "invalid referent granularity: expected coarse or fine, "
                f"received {granularity!r}"
            )
        self.granularity = normalized
        self.catalog = tuple(catalog) if catalog is not None else REFERENT_CATALOG

    def resolve_text(self, text: str, *, context_text: str | None = None) -> str | None:
        """Map evidence prose to one referent key, or None if unsure."""
        blob = _fold(text)
        if context_text and len(blob) < 40:
            extra = _fold(context_text)
            if extra:
                blob = f"{blob} {extra}".strip()
        if not blob:
            return None

        matches = self._collect_matches(blob)
        if not matches:
            return None

        events = [item for item in matches if item.fine_key.startswith("event:")]
        series = [item for item in matches if item.fine_key.startswith("series:")]
        entities = [item for item in matches if item.fine_key.startswith("entity:")]

        if events:
            picked = self._pick_group(events)
            if picked is not None:
                return picked
            # An event mention that is internally ambiguous still beats guessing
            # among the series it happens to name.
            return None

        if series:
            series_coarse = {item.coarse_key for item in series}
            if len(series_coarse) > 1:
                # Distinct series that share a sentence are not one fact.
                return None
            return self._pick_group(series)

        if entities:
            return self._pick_group(entities)
        return None

    def _pick_group(self, matches: Sequence[ReferentMatch]) -> str | None:
        emit_keys = {self._emit_key(item.entry) for item in matches}
        if len(emit_keys) == 1:
            return next(iter(emit_keys))
        coarse_keys = {item.coarse_key for item in matches}
        if self.granularity == "coarse" and len(coarse_keys) == 1:
            return next(iter(coarse_keys))
        return None

    def resolve_evidence(
        self,
        evidence: EvidenceRef,
        *,
        context_text: str | None = None,
    ) -> str | None:
        key = self.resolve_text(evidence.text, context_text=context_text)
        evidence.referent_key = key
        return key

    def resolve_argument_map(self, argument_map: Sequence[ClaimNode]) -> None:
        for claim in argument_map:
            for evidence in claim.evidence:
                self.resolve_evidence(evidence, context_text=claim.claim)

    def resolve_payload(self, payload: dict) -> tuple[int, int]:
        """Mutate `payload["argument_map"]` in place. Returns (resolved, total)."""
        resolved = 0
        total = 0
        for claim in payload.get("argument_map") or []:
            if not isinstance(claim, dict):
                continue
            claim_text = str(claim.get("claim") or "")
            for evidence in claim.get("evidence") or []:
                if not isinstance(evidence, dict):
                    continue
                total += 1
                key = self.resolve_text(
                    str(evidence.get("text") or ""),
                    context_text=claim_text,
                )
                evidence["referent_key"] = key
                if key:
                    resolved += 1
        return resolved, total

    def _collect_matches(self, folded: str) -> list[ReferentMatch]:
        hits: list[ReferentMatch] = []
        for entry in self.catalog:
            score = self._score(folded, entry)
            if score is not None:
                hits.append(ReferentMatch(entry=entry, score=score))
        return hits

    def _score(self, folded: str, entry: ReferentCatalogEntry) -> int | None:
        if any(_has_phrase(folded, token) for token in entry.none_of):
            return None
        score = 0
        for group in entry.all_of:
            matched_lens = [
                len(_fold(option))
                for option in group
                if _has_phrase(folded, option)
            ]
            if not matched_lens:
                return None
            score += max(matched_lens)
        return score * entry.weight

    def _emit_key(self, entry: ReferentCatalogEntry) -> str:
        if self.granularity == "fine":
            return entry.fine_key
        return entry.coarse_key


def load_referent_golden(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        rows.append(json.loads(stripped))
    return rows


def score_referent_golden(
    rows: Iterable[dict],
    resolver: EvidenceReferentResolver,
) -> dict:
    """Score labeled evidence→referent pairs.

    False merges (predicted a different non-null key, or a key when none was
    expected) are counted separately from misses (expected a key, got None).
    """
    total = 0
    correct = 0
    misses = 0
    false_merges = 0
    expected_positive = 0
    predicted_positive = 0
    true_positive = 0
    publishers: set[str] = set()

    for row in rows:
        total += 1
        publisher = row.get("publisher")
        if publisher:
            publishers.add(str(publisher))
        expected = row.get(
            "coarse_key" if resolver.granularity == "coarse" else "fine_key"
        )
        predicted = resolver.resolve_text(str(row.get("text") or ""))
        if expected:
            expected_positive += 1
        if predicted:
            predicted_positive += 1
        if predicted == expected:
            correct += 1
            if expected:
                true_positive += 1
            continue
        if expected and predicted is None:
            misses += 1
            continue
        false_merges += 1

    precision = (
        true_positive / predicted_positive if predicted_positive else 1.0
    )
    recall = true_positive / expected_positive if expected_positive else 1.0
    return {
        "total": total,
        "correct": correct,
        "misses": misses,
        "false_merges": false_merges,
        "precision": precision,
        "recall": recall,
        "false_merge_rate": false_merges / total if total else 0.0,
        "publisher_count": len(publishers),
        "granularity": resolver.granularity,
    }


def referent_resolution_stats(
    payloads: Iterable[dict],
    resolver: EvidenceReferentResolver | None = None,
) -> dict:
    """Count stored and preview unresolved rates across argument-map evidence."""
    total = 0
    stored_resolved = 0
    preview_resolved = 0
    for payload in payloads:
        argument_map = payload.get("argument_map") or []
        for claim in argument_map:
            if not isinstance(claim, dict):
                continue
            claim_text = str(claim.get("claim") or "")
            for evidence in claim.get("evidence") or []:
                if not isinstance(evidence, dict):
                    continue
                total += 1
                stored = evidence.get("referent_key")
                if stored:
                    stored_resolved += 1
                    preview_resolved += 1
                    continue
                if resolver is None:
                    continue
                preview = resolver.resolve_text(
                    str(evidence.get("text") or ""),
                    context_text=claim_text,
                )
                if preview:
                    preview_resolved += 1
    stored_unresolved = total - stored_resolved
    preview_unresolved = total - preview_resolved
    return {
        "evidence_count": total,
        "stored_resolved_count": stored_resolved,
        "stored_unresolved_rate": (stored_unresolved / total) if total else 0.0,
        "preview_resolved_count": preview_resolved,
        "preview_unresolved_rate": (preview_unresolved / total) if total else 0.0,
        "granularity": resolver.granularity if resolver is not None else None,
    }
