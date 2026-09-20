"""Argument-graph queries over resolved argument maps.

Slice 2 Task 5. The graph is:

    Author (publisher) --makes--> Claim (claim_key)
                                     |
                                     +--cites--> Evidence (referent_key)

Queries are joins, not string matches. Positions are always publishers.
The substrate `contradicts` relation is schema-only today; this module infers
the same pattern from opposing-polarity citations of one referent, and also
accepts explicit `contradicts` rows when a caller has them.

Not wired into the live contrarian `research_search` tool — that is optional
and would change agent behavior. Callers use `ArgumentGraph` or the
`argument-graph` CLI.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Mapping, Sequence

from research_analysis_layer.models.argument_graph_models import (
    ArgumentGraphSnapshot,
    BackedVsAsserted,
    EvidenceContradiction,
    EvidenceIndependence,
    GraphSide,
    InterpretationGap,
)
from research_analysis_layer.services.claim_key_resolver import (
    claim_family,
    is_contradiction_candidate,
    parse_claim_key,
)
from research_analysis_layer.services.publisher_diversity import (
    Publisher,
    publisher_for_document,
    source_diversity,
)

DEFAULT_MIN_PUBLISHERS = 2
_STRENGTH_RANK = {"evidenced": 2, "reasoned": 1, "asserted": 0}


@dataclass(frozen=True, slots=True)
class CitedEvidence:
    """One resolved evidence citation on a claim."""

    referent_key: str
    text: str
    ref_key: str | None


@dataclass(frozen=True, slots=True)
class GraphClaim:
    """One resolved claim attributed through its document publisher."""

    publisher: Publisher
    research_id: int | None
    claim: str
    claim_key: str
    subject: str
    predicate: str
    polarity: str
    rationale: str
    support_strength: str
    evidence: tuple[CitedEvidence, ...]

    @property
    def family(self) -> str:
        return f"claim:{self.subject}:{self.predicate}"

    @property
    def referent_keys(self) -> frozenset[str]:
        return frozenset(item.referent_key for item in self.evidence)


@dataclass(frozen=True, slots=True)
class ExplicitContradiction:
    """Optional substrate-style contradicts edge (referent → claim_key)."""

    referent_key: str
    claim_key: str


class ArgumentGraph:
    """Query Author → Claim → Evidence joins across resolved maps."""

    def __init__(self, *, min_publishers: int = DEFAULT_MIN_PUBLISHERS) -> None:
        if min_publishers < 2:
            raise ValueError(
                "argument graph min_publishers must be >= 2, "
                f"received {min_publishers}"
            )
        self.min_publishers = min_publishers

    def query_maps(
        self,
        maps: Iterable[Mapping[str, Any]],
        *,
        claim_key: str | None = None,
        relations: Sequence[Mapping[str, Any]] | None = None,
    ) -> ArgumentGraphSnapshot:
        claims: list[GraphClaim] = []
        skipped = 0
        for document in maps:
            extracted, skipped_here = self._claims_from_map(document)
            claims.extend(extracted)
            skipped += skipped_here
        return self.query_claims(
            claims,
            claim_key=claim_key,
            relations=relations,
            skipped_unresolved=skipped,
        )

    def query_claims(
        self,
        claims: Sequence[GraphClaim],
        *,
        claim_key: str | None = None,
        relations: Sequence[Mapping[str, Any]] | None = None,
        skipped_unresolved: int = 0,
    ) -> ArgumentGraphSnapshot:
        family_claims = _filter_claims(claims, _family_scope(claim_key))
        key_claims = _filter_claims(claims, claim_key)
        explicit = tuple(_explicit_contradictions(relations))
        return ArgumentGraphSnapshot(
            interpretation_gaps=self.same_evidence_opposing_conclusions(family_claims),
            independence=self.consensus_evidence_independence(
                key_claims, claim_key=claim_key
            ),
            contradictions=self.evidence_contradicts_claim(
                family_claims, relations=explicit
            ),
            backed_vs_asserted=self.backed_vs_asserted(
                key_claims, claim_key=claim_key
            ),
            min_publishers=self.min_publishers,
            clustered_claim_count=len(claims),
            skipped_unresolved_count=skipped_unresolved,
        )

    def same_evidence_opposing_conclusions(
        self,
        claims: Sequence[GraphClaim],
    ) -> list[InterpretationGap]:
        """One referent cited by opposing-polarity claims from distinct houses."""
        grouped: dict[tuple[str, str], list[GraphClaim]] = defaultdict(list)
        for claim in claims:
            for evidence in claim.evidence:
                grouped[(evidence.referent_key, claim.family)].append(claim)

        gaps: list[InterpretationGap] = []
        for (referent, family), members in grouped.items():
            by_house = _one_polarity_per_publisher(members)
            if _publisher_diversity(by_house) < self.min_publishers:
                continue
            polarities = {item.polarity for item in by_house}
            if not {"up", "down"} <= polarities:
                continue
            sides = [_side(item, referent_key=referent) for item in _sorted_claims(by_house)]
            gaps.append(
                InterpretationGap(
                    referent_key=referent,
                    family=family,
                    source_diversity=_publisher_diversity(by_house),
                    sides=sides,
                    rationale=(
                        f"{referent} is cited for opposing {family} conclusions "
                        f"by {_join_labels(by_house)}"
                    ),
                )
            )
        gaps.sort(key=lambda item: (-item.source_diversity, item.referent_key, item.family))
        return gaps

    def consensus_evidence_independence(
        self,
        claims: Sequence[GraphClaim],
        *,
        claim_key: str | None = None,
    ) -> list[EvidenceIndependence]:
        """Disjoint referents → robust; a shared referent → herding."""
        rows: list[EvidenceIndependence] = []
        for key, members in _claims_by_key(claims, claim_key).items():
            by_house = _one_claim_per_publisher(members)
            if _publisher_diversity(by_house) < self.min_publishers:
                continue
            evidenced_houses = [item for item in by_house if item.referent_keys]
            if len({item.publisher.key for item in evidenced_houses}) < 2:
                continue
            refs_by_label = {
                item.publisher.label: sorted(item.referent_keys)
                for item in _sorted_claims(evidenced_houses)
            }
            cited_by: dict[str, set[str]] = defaultdict(set)
            for item in evidenced_houses:
                for referent in item.referent_keys:
                    cited_by[referent].add(item.publisher.key)
            shared = sorted(
                referent
                for referent, houses in cited_by.items()
                if len(houses) >= 2
            )
            unique_only = not shared
            sets = [item.referent_keys for item in evidenced_houses]
            identical = bool(sets) and all(item == sets[0] for item in sets)
            if unique_only:
                kind: Literal["robust", "herding", "mixed"] = "robust"
                why = "disjoint referent sets across publishers"
            elif identical or all(
                item.referent_keys <= set(shared) for item in evidenced_houses
            ):
                kind = "herding"
                why = "publishers cite the same referent_key set"
            else:
                kind = "mixed"
                why = "some shared referents and some publisher-unique referents"
            rows.append(
                EvidenceIndependence(
                    claim_key=key,
                    kind=kind,
                    source_diversity=_publisher_diversity(evidenced_houses),
                    positions=[item.publisher.label for item in _sorted_claims(evidenced_houses)],
                    shared_referents=shared,
                    referents_by_publisher=refs_by_label,
                    rationale=f"{key}: {why}",
                )
            )
        rows.sort(key=lambda item: (item.kind, item.claim_key))
        return rows

    def evidence_contradicts_claim(
        self,
        claims: Sequence[GraphClaim],
        *,
        relations: Sequence[ExplicitContradiction] = (),
    ) -> list[EvidenceContradiction]:
        """Referent linked to an opposing-polarity claim (inferred or explicit)."""
        hits: list[EvidenceContradiction] = []
        seen: set[tuple[str, str, str, str]] = set()
        indexed = _one_per_publisher_claim_key(claims)

        for claim in _sorted_claims(indexed):
            for evidence in claim.evidence:
                opposing = [
                    other
                    for other in indexed
                    if other.publisher.key != claim.publisher.key
                    and is_contradiction_candidate(claim.claim_key, other.claim_key)
                    and evidence.referent_key in other.referent_keys
                ]
                if not opposing:
                    continue
                stamp = (
                    claim.claim_key,
                    claim.publisher.key,
                    evidence.referent_key,
                    "inferred",
                )
                if stamp in seen:
                    continue
                seen.add(stamp)
                hits.append(
                    EvidenceContradiction(
                        claim_key=claim.claim_key,
                        publisher=claim.publisher.label,
                        research_id=claim.research_id,
                        claim=claim.claim,
                        polarity=claim.polarity,
                        referent_key=evidence.referent_key,
                        opposing_sides=[
                            _side(item, referent_key=evidence.referent_key)
                            for item in _sorted_claims(opposing)
                        ],
                        rationale=(
                            f"{claim.publisher.label} cites {evidence.referent_key} "
                            f"for {claim.claim_key}; "
                            f"{_join_labels(opposing)} cite it for the opposing polarity"
                        ),
                    )
                )

        claims_by_key: dict[str, list[GraphClaim]] = defaultdict(list)
        for claim in indexed:
            claims_by_key[claim.claim_key].append(claim)
        for relation in relations:
            targets = claims_by_key.get(relation.claim_key) or []
            for claim in _sorted_claims(_one_claim_per_publisher(targets)):
                opposing = [
                    other
                    for other in indexed
                    if other.publisher.key != claim.publisher.key
                    and is_contradiction_candidate(claim.claim_key, other.claim_key)
                    and relation.referent_key in other.referent_keys
                ]
                stamp = (
                    claim.claim_key,
                    claim.publisher.key,
                    relation.referent_key,
                    "explicit",
                )
                if stamp in seen:
                    continue
                seen.add(stamp)
                hits.append(
                    EvidenceContradiction(
                        claim_key=claim.claim_key,
                        publisher=claim.publisher.label,
                        research_id=claim.research_id,
                        claim=claim.claim,
                        polarity=claim.polarity,
                        referent_key=relation.referent_key,
                        opposing_sides=[
                            _side(item, referent_key=relation.referent_key)
                            for item in _sorted_claims(opposing)
                        ],
                        rationale=(
                            f"explicit contradicts relation: {relation.referent_key} "
                            f"against {claim.claim_key} ({claim.publisher.label})"
                        ),
                    )
                )

        hits.sort(
            key=lambda item: (item.referent_key, item.claim_key, item.publisher)
        )
        return hits

    def backed_vs_asserted(
        self,
        claims: Sequence[GraphClaim],
        *,
        claim_key: str | None = None,
    ) -> list[BackedVsAsserted]:
        """Evidenced at one house, asserted at another, on the same claim_key."""
        rows: list[BackedVsAsserted] = []
        for key, members in _claims_by_key(claims, claim_key).items():
            by_house = _one_claim_per_publisher(members)
            if _publisher_diversity(by_house) < self.min_publishers:
                continue
            evidenced = [
                item.publisher.label
                for item in _sorted_claims(by_house)
                if item.support_strength == "evidenced"
            ]
            asserted = [
                item.publisher.label
                for item in _sorted_claims(by_house)
                if item.support_strength == "asserted"
            ]
            reasoned = [
                item.publisher.label
                for item in _sorted_claims(by_house)
                if item.support_strength == "reasoned"
            ]
            if not evidenced or not asserted:
                continue
            rows.append(
                BackedVsAsserted(
                    claim_key=key,
                    source_diversity=_publisher_diversity(by_house),
                    evidenced=evidenced,
                    asserted=asserted,
                    reasoned=reasoned,
                    rationale=(
                        f"{key}: evidenced by {', '.join(evidenced)}; "
                        f"asserted by {', '.join(asserted)}"
                    ),
                )
            )
        rows.sort(key=lambda item: item.claim_key)
        return rows

    def _claims_from_map(
        self,
        document: Mapping[str, Any],
    ) -> tuple[list[GraphClaim], int]:
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

        extracted: list[GraphClaim] = []
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
            extracted.append(
                GraphClaim(
                    publisher=house,
                    research_id=int(research_id) if isinstance(research_id, int) else None,
                    claim=str(raw.get("claim") or ""),
                    claim_key=str(raw["claim_key"]),
                    subject=subject,
                    predicate=predicate,
                    polarity=polarity,
                    rationale=str(raw.get("rationale") or ""),
                    support_strength=str(raw.get("support_strength") or "asserted"),
                    evidence=tuple(_evidence_from_claim(raw)),
                )
            )
        return extracted, skipped


def _evidence_from_claim(raw: Mapping[str, Any]) -> list[CitedEvidence]:
    citations: list[CitedEvidence] = []
    for evidence in raw.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        referent = evidence.get("referent_key")
        if not isinstance(referent, str) or not referent.strip():
            continue
        text = evidence.get("text")
        ref_key = evidence.get("ref_key")
        citations.append(
            CitedEvidence(
                referent_key=referent.strip(),
                text=text.strip() if isinstance(text, str) else "",
                ref_key=ref_key.strip() if isinstance(ref_key, str) else None,
            )
        )
    return citations


def _family_scope(claim_key: str | None) -> str | None:
    """Keep both polarities so gaps/contradictions can still see the other side."""
    if not claim_key:
        return None
    parsed = parse_claim_key(claim_key)
    if parsed is None:
        return claim_key
    subject, predicate, _ = parsed
    return f"claim:{subject}:{predicate}"


def _filter_claims(
    claims: Sequence[GraphClaim],
    claim_key: str | None,
) -> list[GraphClaim]:
    if not claim_key:
        return list(claims)
    if parse_claim_key(claim_key):
        return [item for item in claims if item.claim_key == claim_key]
    family = claim_key if claim_key.startswith("claim:") else f"claim:{claim_key}"
    return [item for item in claims if item.family == family or claim_family(item.claim_key) == family]


def _claims_by_key(
    claims: Sequence[GraphClaim],
    claim_key: str | None,
) -> dict[str, list[GraphClaim]]:
    grouped: dict[str, list[GraphClaim]] = defaultdict(list)
    for claim in _filter_claims(claims, claim_key):
        grouped[claim.claim_key].append(claim)
    return grouped


def _one_per_publisher_claim_key(members: Sequence[GraphClaim]) -> list[GraphClaim]:
    grouped: dict[tuple[str, str], list[GraphClaim]] = defaultdict(list)
    for member in members:
        grouped[(member.publisher.key, member.claim_key)].append(member)
    kept: list[GraphClaim] = []
    for house_members in grouped.values():
        kept.extend(_one_claim_per_publisher(house_members))
    return kept


def _one_claim_per_publisher(members: Sequence[GraphClaim]) -> list[GraphClaim]:
    grouped: dict[str, list[GraphClaim]] = defaultdict(list)
    for member in members:
        grouped[member.publisher.key].append(member)
    kept: list[GraphClaim] = []
    for house_members in grouped.values():
        ranked = sorted(
            house_members,
            key=lambda item: (
                _STRENGTH_RANK.get(item.support_strength, 0),
                len(item.referent_keys),
                item.research_id or 0,
            ),
            reverse=True,
        )
        winner = ranked[0]
        merged_refs = {
            (item.referent_key, item.text, item.ref_key)
            for member in house_members
            for item in member.evidence
        }
        kept.append(
            GraphClaim(
                publisher=winner.publisher,
                research_id=winner.research_id,
                claim=winner.claim,
                claim_key=winner.claim_key,
                subject=winner.subject,
                predicate=winner.predicate,
                polarity=winner.polarity,
                rationale=winner.rationale,
                support_strength=winner.support_strength,
                evidence=tuple(
                    CitedEvidence(referent_key=ref, text=text, ref_key=ref_key)
                    for ref, text, ref_key in sorted(merged_refs)
                ),
            )
        )
    return kept


def _one_polarity_per_publisher(members: Sequence[GraphClaim]) -> list[GraphClaim]:
    grouped: dict[str, list[GraphClaim]] = defaultdict(list)
    for member in members:
        grouped[member.publisher.key].append(member)
    kept: list[GraphClaim] = []
    for house_members in grouped.values():
        polarities = {item.polarity for item in house_members}
        if len(polarities) != 1:
            continue
        merged = _one_claim_per_publisher(house_members)
        kept.extend(merged)
    return kept


def _explicit_contradictions(
    relations: Sequence[Mapping[str, Any]] | None,
) -> list[ExplicitContradiction]:
    if not relations:
        return []
    rows: list[ExplicitContradiction] = []
    for raw in relations:
        relation = str(raw.get("relation") or raw.get("edge_type") or "").strip().lower()
        if relation and relation != "contradicts":
            continue
        referent = raw.get("referent_key")
        claim_key = raw.get("claim_key")
        if not isinstance(referent, str) or not referent.strip():
            continue
        if not isinstance(claim_key, str) or parse_claim_key(claim_key) is None:
            continue
        rows.append(
            ExplicitContradiction(
                referent_key=referent.strip(),
                claim_key=claim_key,
            )
        )
    return rows


def _side(claim: GraphClaim, *, referent_key: str) -> GraphSide:
    texts = [
        item.text
        for item in claim.evidence
        if item.referent_key == referent_key and item.text
    ]
    return GraphSide(
        publisher=claim.publisher.label,
        research_id=claim.research_id,
        claim=claim.claim,
        claim_key=claim.claim_key,
        polarity=claim.polarity,
        rationale=claim.rationale,
        support_strength=claim.support_strength,
        evidence_text=texts[0] if texts else "",
        referent_keys=sorted(claim.referent_keys),
    )


def _sorted_claims(members: Sequence[GraphClaim]) -> list[GraphClaim]:
    return sorted(members, key=lambda item: (item.publisher.key, item.claim_key))


def _publisher_diversity(members: Sequence[GraphClaim]) -> int:
    return source_diversity(item.publisher for item in members)


def _join_labels(members: Sequence[GraphClaim]) -> str:
    labels = [item.publisher.label for item in _sorted_claims(members)]
    return ", ".join(labels)
