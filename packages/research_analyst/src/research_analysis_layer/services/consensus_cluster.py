"""Cluster resolved argument maps into consensus and divergence points.

Slice 2 Task 4. Cluster key is `(subject, predicate, horizon_bucket)`.
Publisher diversity is always `source_diversity()` — notes from the same
house collapse. Single-publisher clusters emit nothing.

Consensus: ≥ N distinct publishers, one polarity, contradiction_count 0.
Divergence: distinct publishers with opposing up/down polarity.
Verdict defaults to `contested`; Task 4 does not pick a favored side.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from research_analysis_layer.models.consensus_models import (
    ConsensusPoint,
    ConsensusSnapshot,
    DivergencePoint,
    DivergenceSide,
    GroundedReason,
)
from research_analysis_layer.services.claim_key_resolver import (
    horizon_bucket,
    parse_claim_key,
)
from research_analysis_layer.services.publisher_diversity import (
    Publisher,
    publisher_for_document,
    source_diversity,
)

DEFAULT_MIN_PUBLISHERS = 2
_STRENGTH_SCORE = {"evidenced": 0.9, "reasoned": 0.7, "asserted": 0.55}

_POINT_NOUNS: dict[tuple[str, str], str] = {
    ("fed_policy", "hike"): "Fed hike path",
    ("warsh_speech_tone", "tone"): "Warsh speech tone",
    ("fed_credibility", "restore"): "Fed credibility",
    ("us_10y", "cheap"): "10y UST valuation",
    ("us_breakevens", "width"): "UST breakeven width",
    ("ust_2s10s", "steepen"): "UST 2s10s",
    ("ust_5s30s", "steepen"): "UST 5s30s",
    ("ust_7s30s", "steepen"): "UST 7s30s",
}

_HORIZON_LABELS = {
    "meeting_2026_09": "September 2026",
    "meeting_2026_12": "December 2026",
    "year_2026": "2026",
    "near_term": "near term",
    "medium": "medium term",
    "longer": "longer term",
}

_POLARITY_GLANCE = {
    ("fed_policy", "hike", "up"): "hike",
    ("fed_policy", "hike", "down"): "on hold / no hike",
    ("ust_2s10s", "steepen", "up"): "steepening",
    ("ust_2s10s", "steepen", "down"): "flattening",
    ("ust_5s30s", "steepen", "up"): "steepening",
    ("ust_7s30s", "steepen", "up"): "steepening",
    ("us_10y", "cheap", "up"): "cheap",
    ("us_breakevens", "width", "down"): "narrower",
    ("us_breakevens", "width", "up"): "wider",
}


@dataclass(frozen=True, slots=True)
class ClusteredClaim:
    """One resolved claim attributed through its document publisher."""

    publisher: Publisher
    research_id: int | None
    claim: str
    claim_key: str
    subject: str
    predicate: str
    polarity: str
    horizon_bucket: str
    rationale: str
    support_strength: str
    reasons: tuple[GroundedReason, ...]


class ConsensusClusterer:
    """Build ConsensusPoint / DivergencePoint sets from resolved maps."""

    def __init__(self, *, min_publishers: int = DEFAULT_MIN_PUBLISHERS) -> None:
        if min_publishers < 2:
            raise ValueError(
                "consensus min_publishers must be >= 2, "
                f"received {min_publishers}"
            )
        self.min_publishers = min_publishers

    def cluster_maps(self, maps: Iterable[Mapping[str, Any]]) -> ConsensusSnapshot:
        """Cluster document maps. Each map needs `source`/`publisher` + `argument_map`."""
        claims: list[ClusteredClaim] = []
        skipped = 0
        for document in maps:
            extracted, skipped_here = self._claims_from_map(document)
            claims.extend(extracted)
            skipped += skipped_here
        return self.cluster_claims(claims, skipped_unresolved=skipped)

    def cluster_claims(
        self,
        claims: Sequence[ClusteredClaim],
        *,
        skipped_unresolved: int = 0,
    ) -> ConsensusSnapshot:
        grouped: dict[tuple[str, str, str], list[ClusteredClaim]] = defaultdict(list)
        for claim in claims:
            grouped[(claim.subject, claim.predicate, claim.horizon_bucket)].append(
                claim
            )

        agreements: list[ConsensusPoint] = []
        disagreements: list[DivergencePoint] = []
        for (subject, predicate, bucket), members in grouped.items():
            point = self._cluster_point(subject, predicate, bucket, members)
            if isinstance(point, ConsensusPoint):
                agreements.append(point)
            elif isinstance(point, DivergencePoint):
                disagreements.append(point)

        disagreements.sort(
            key=lambda item: {"high": 0, "medium": 1, "low": 2}[item.materiality]
        )
        agreements.sort(key=lambda item: (-item.source_diversity, item.point))
        return ConsensusSnapshot(
            agreements=agreements,
            disagreements=disagreements,
            min_publishers=self.min_publishers,
            clustered_claim_count=len(claims),
            skipped_unresolved_count=skipped_unresolved,
        )

    def _cluster_point(
        self,
        subject: str,
        predicate: str,
        bucket: str,
        members: Sequence[ClusteredClaim],
    ) -> ConsensusPoint | DivergencePoint | None:
        by_house = self._one_position_per_publisher(members)
        if _publisher_diversity(by_house) < 2:
            return None

        polarities = {item.polarity for item in by_house}
        if "up" in polarities and "down" in polarities:
            return self._divergence(subject, predicate, bucket, by_house)
        if len(polarities) == 1 and _publisher_diversity(by_house) >= self.min_publishers:
            polarity = next(iter(polarities))
            if polarity == "neutral":
                return None
            return self._consensus(subject, predicate, polarity, bucket, by_house)
        return None

    def _one_position_per_publisher(
        self,
        members: Sequence[ClusteredClaim],
    ) -> list[ClusteredClaim]:
        grouped: dict[str, list[ClusteredClaim]] = defaultdict(list)
        for member in members:
            grouped[member.publisher.key].append(member)
        kept: list[ClusteredClaim] = []
        for house_members in grouped.values():
            polarities = {item.polarity for item in house_members}
            if len(polarities) != 1:
                # Same bank, mixed polarity: no single position to count.
                continue
            kept.append(_preferred_member(house_members))
        return kept

    def _consensus(
        self,
        subject: str,
        predicate: str,
        polarity: str,
        bucket: str,
        members: Sequence[ClusteredClaim],
    ) -> ConsensusPoint | None:
        reasons = _unique_reasons(members)
        if not reasons:
            return None
        diversity = _publisher_diversity(members)
        scores = [_STRENGTH_SCORE.get(item.support_strength, 0.55) for item in members]
        confidence = round(sum(scores) / len(scores), 2)
        return ConsensusPoint(
            point=_point_label(subject, predicate, bucket, polarity=polarity),
            positions=[item.publisher.label for item in _sorted_members(members)],
            reasons=reasons,
            confidence=confidence,
            subject=subject,
            predicate=predicate,
            polarity=polarity,
            horizon_bucket=bucket,
            source_diversity=diversity,
            contradiction_count=0,
        )

    def _divergence(
        self,
        subject: str,
        predicate: str,
        bucket: str,
        members: Sequence[ClusteredClaim],
    ) -> DivergencePoint | None:
        sides: list[DivergenceSide] = []
        for member in _sorted_members(members):
            reasons = list(member.reasons)
            if not reasons:
                continue
            sides.append(
                DivergenceSide(
                    position=member.publisher.label,
                    claim=member.claim,
                    polarity=member.polarity,
                    reasons=reasons,
                )
            )
        if len(sides) < 2:
            return None
        if len({side.polarity for side in sides}) < 2:
            return None
        evidenced = sum(
            1 for member in members if member.support_strength == "evidenced"
        )
        materiality: Literal["high", "medium", "low"]
        if evidenced >= 2:
            materiality = "high"
        elif evidenced == 1:
            materiality = "medium"
        else:
            materiality = "low"
        return DivergencePoint(
            point=_point_label(subject, predicate, bucket, polarity=None),
            sides=sides,
            verdict="contested",
            favored_position=None,
            verdict_reason="opposing publisher polarities; no favored side",
            materiality=materiality,
            subject=subject,
            predicate=predicate,
            horizon_bucket=bucket,
            source_diversity=_publisher_diversity(members),
            contradiction_count=1,
        )

    def _claims_from_map(
        self,
        document: Mapping[str, Any],
    ) -> tuple[list[ClusteredClaim], int]:
        house = publisher_for_document(document)
        if house is None:
            nested = document.get("document")
            if isinstance(nested, Mapping):
                house = publisher_for_document(nested)
        payload = document.get("payload_json")
        if isinstance(payload, dict):
            argument_map = payload.get("argument_map") or []
        else:
            argument_map = document.get("argument_map") or []
        if house is None or not isinstance(argument_map, list):
            return [], 0

        extracted: list[ClusteredClaim] = []
        skipped = 0
        research_id = document.get("research_id")
        for raw in argument_map:
            if not isinstance(raw, dict):
                continue
            parsed = parse_claim_key(
                raw.get("claim_key") if isinstance(raw.get("claim_key"), str) else None
            )
            if parsed is None:
                skipped += 1
                continue
            subject, predicate, polarity = parsed
            claim_text = str(raw.get("claim") or "")
            bucket = horizon_bucket(
                raw.get("horizon") if isinstance(raw.get("horizon"), str) else None,
                claim_text=claim_text,
            )
            reasons = tuple(_reasons_from_claim(raw))
            extracted.append(
                ClusteredClaim(
                    publisher=house,
                    research_id=int(research_id) if isinstance(research_id, int) else None,
                    claim=claim_text,
                    claim_key=str(raw["claim_key"]),
                    subject=subject,
                    predicate=predicate,
                    polarity=polarity,
                    horizon_bucket=bucket,
                    rationale=str(raw.get("rationale") or ""),
                    support_strength=str(raw.get("support_strength") or "asserted"),
                    reasons=reasons,
                )
            )
        return extracted, skipped


def _preferred_member(members: Sequence[ClusteredClaim]) -> ClusteredClaim:
    ranked = sorted(
        members,
        key=lambda item: (
            _STRENGTH_SCORE.get(item.support_strength, 0),
            len(item.reasons),
            item.research_id or 0,
        ),
        reverse=True,
    )
    return ranked[0]


def _publisher_diversity(members: Sequence[ClusteredClaim]) -> int:
    """Distinct houses. Pass resolved Publisher objects into source_diversity()."""
    return source_diversity(item.publisher for item in members)


def _sorted_members(members: Sequence[ClusteredClaim]) -> list[ClusteredClaim]:
    return sorted(members, key=lambda item: item.publisher.key)


def _unique_reasons(members: Sequence[ClusteredClaim]) -> list[GroundedReason]:
    seen: set[tuple[str, str]] = set()
    reasons: list[GroundedReason] = []
    for member in _sorted_members(members):
        for reason in member.reasons:
            stamp = (reason.ref_key, reason.text)
            if stamp in seen:
                continue
            seen.add(stamp)
            reasons.append(reason)
    return reasons


def _reasons_from_claim(raw: Mapping[str, Any]) -> list[GroundedReason]:
    reasons: list[GroundedReason] = []
    for evidence in raw.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        ref_key = evidence.get("ref_key")
        text = evidence.get("text")
        if not isinstance(ref_key, str) or not ref_key.strip():
            continue
        if not isinstance(text, str) or not text.strip():
            continue
        reasons.append(
            GroundedReason(
                text=text.strip()[:400],
                ref_type="evidence",
                ref_key=ref_key.strip(),
            )
        )
    return reasons


def _point_label(
    subject: str,
    predicate: str,
    bucket: str,
    *,
    polarity: str | None,
) -> str:
    base = _POINT_NOUNS.get((subject, predicate), f"{subject} {predicate}".replace("_", " "))
    if polarity:
        glance = _POLARITY_GLANCE.get((subject, predicate, polarity))
        if glance:
            base = f"{base}: {glance}"
    horizon = _HORIZON_LABELS.get(bucket)
    if horizon:
        return f"{base} ({horizon})"
    return base
