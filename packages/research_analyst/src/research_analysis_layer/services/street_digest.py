"""Deterministic 'street agrees / splits' digest lines (Slice 2 Task 7).

Renders ConsensusPoint / DivergencePoint in the rubric shape, with a
per-document fallback only where a cluster has not reached distinct-publisher
scale. Positions are always publishers. No LLM phrasing step.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping

from pydantic import BaseModel, Field

from research_analysis_layer.models.consensus_models import (
    ConsensusPoint,
    ConsensusSnapshot,
    DivergencePoint,
)
from research_analysis_layer.services.consensus_cluster import ConsensusClusterer
from research_analysis_layer.services.publisher_diversity import (
    canonical_publisher,
    source_diversity,
)

_SHORT_LABELS = {
    "goldman_sachs": "GS",
    "morgan_stanley": "MS",
    "jpmorgan": "JPM",
    "deutsche_bank": "DB",
    "citi": "Citi",
    "barclays": "Barclays",
}


class StreetDigestSection(BaseModel):
    """Rendered street-agrees / street-splits digest for one window."""

    agreements: list[str] = Field(default_factory=list)
    disagreements: list[str] = Field(default_factory=list)
    fallback: list[str] = Field(default_factory=list)
    lines: list[str] = Field(default_factory=list)
    reached_street_scale: bool = False
    agreement_count: int = 0
    disagreement_count: int = 0

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump()


def render_street_digest(
    maps: Iterable[Mapping[str, Any]],
    *,
    min_publishers: int = 2,
    snapshot: ConsensusSnapshot | None = None,
) -> StreetDigestSection:
    """Cluster maps if needed, then render attributed digest lines."""
    clusterer = ConsensusClusterer(min_publishers=min_publishers)
    map_list = list(maps)
    resolved = snapshot or clusterer.cluster_maps(map_list)
    agreements = [_agreement_line(point) for point in resolved.agreements]
    disagreements = [_disagreement_line(point) for point in resolved.disagreements]
    covered = {
        (point.subject, point.predicate, point.horizon_bucket)
        for point in (*resolved.agreements, *resolved.disagreements)
    }
    fallback = _fallback_lines(clusterer, map_list, covered, min_publishers)
    street_lines = agreements + disagreements
    lines = street_lines if street_lines else fallback
    return StreetDigestSection(
        agreements=agreements,
        disagreements=disagreements,
        fallback=fallback,
        lines=lines,
        reached_street_scale=bool(street_lines),
        agreement_count=len(agreements),
        disagreement_count=len(disagreements),
    )


def short_publisher_label(name: str) -> str:
    """Digest short names: Goldman Sachs → GS."""
    resolved = canonical_publisher(source=name, name=name)
    if resolved is None:
        return name.strip()
    return _SHORT_LABELS.get(resolved.key, resolved.label)


def _agreement_line(point: ConsensusPoint) -> str:
    houses = [short_publisher_label(name) for name in point.positions]
    return f"{_join_names(houses)} agree {point.point} ({point.source_diversity} houses)"


def _disagreement_line(point: DivergencePoint) -> str:
    parts: list[str] = []
    for side in point.sides:
        house = short_publisher_label(side.position)
        why = side.reasons[0].text if side.reasons else ""
        if why:
            parts.append(f"{house} {side.claim} because {why}")
        else:
            parts.append(f"{house} {side.claim}")
    return f"{'; '.join(parts)} ({point.verdict})"


def _fallback_lines(
    clusterer: ConsensusClusterer,
    maps: list[Mapping[str, Any]],
    covered: set[tuple[str, str, str]],
    min_publishers: int,
) -> list[str]:
    grouped: dict[tuple[str, str, str], list] = defaultdict(list)
    for document in maps:
        extracted, _skipped = clusterer._claims_from_map(document)
        for claim in extracted:
            key = (claim.subject, claim.predicate, claim.horizon_bucket)
            if key in covered:
                continue
            grouped[key].append(claim)
    lines: list[str] = []
    for (subject, predicate, bucket), members in sorted(grouped.items()):
        if source_diversity(item.publisher for item in members) >= min_publishers:
            continue
        noun = f"{subject} {predicate}".replace("_", " ")
        if bucket and bucket != "unspecified":
            noun = f"{noun} ({bucket})"
        for member in sorted(members, key=lambda item: item.publisher.key):
            house = short_publisher_label(member.publisher.label)
            lines.append(
                f"{house} on {noun}: {member.claim} (below street scale)"
            )
    return lines


def _join_names(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])}, and {names[-1]}"
