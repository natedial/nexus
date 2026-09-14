"""Emit source_consensus_shift events when a cluster changes.

Slice 2 Task 6. Compare the latest ConsensusSnapshot to the previously
persisted cluster state. A first observation is not a shift. A no-change
recompute emits nothing. Sign flips and diversity-threshold crossings are
real shifts; the same transition is idempotent via event_key.

Positions are always publishers. Thresholds are config, default 3.
"""

from __future__ import annotations

from typing import Mapping

from research_analysis_layer.models.consensus_models import (
    ConsensusPoint,
    ConsensusSnapshot,
    DivergencePoint,
)
from research_analysis_layer.models.consensus_shift_models import (
    SHIFT_EVENT_TYPE,
    ClusterSign,
    ClusterState,
    ConsensusShiftEvent,
    ShiftReason,
)

DEFAULT_DIVERSITY_THRESHOLD = 3
SIGN_NONE: ClusterSign = "none"


class ConsensusShiftDetector:
    """Diff consecutive cluster snapshots into source_consensus_shift events."""

    def __init__(self, *, diversity_threshold: int = DEFAULT_DIVERSITY_THRESHOLD) -> None:
        if diversity_threshold < 2:
            raise ValueError(
                "consensus shift diversity_threshold must be >= 2, "
                f"received {diversity_threshold}"
            )
        self.diversity_threshold = diversity_threshold

    def states_from_snapshot(self, snapshot: ConsensusSnapshot) -> dict[str, ClusterState]:
        states: dict[str, ClusterState] = {}
        for point in snapshot.disagreements:
            state = _state_from_divergence(point)
            states[state.cluster_key] = state
        for point in snapshot.agreements:
            state = _state_from_consensus(point)
            states.setdefault(state.cluster_key, state)
        return states

    def detect(
        self,
        previous: Mapping[str, ClusterState],
        snapshot: ConsensusSnapshot,
    ) -> list[ConsensusShiftEvent]:
        current = self.states_from_snapshot(snapshot)
        events: list[ConsensusShiftEvent] = []
        for key, new in current.items():
            old = previous.get(key)
            if old is None:
                continue
            event = self._diff(old, new)
            if event is not None:
                events.append(event)
        for key, old in previous.items():
            if key in current:
                continue
            gone = ClusterState(
                cluster_key=old.cluster_key,
                subject=old.subject,
                predicate=old.predicate,
                horizon_bucket=old.horizon_bucket,
                sign=SIGN_NONE,
                source_diversity=0,
                positions=[],
            )
            event = self._diff(old, gone)
            if event is not None:
                events.append(event)
        events.sort(key=lambda item: item.event_key)
        return events

    def _diff(
        self,
        old: ClusterState,
        new: ClusterState,
    ) -> ConsensusShiftEvent | None:
        reasons: list[ShiftReason] = []
        if old.sign != new.sign:
            reasons.append("sign_flip")
        if _crossed_threshold(
            old.source_diversity, new.source_diversity, self.diversity_threshold
        ):
            reasons.append("diversity_threshold")
        if not reasons:
            return None
        event_key = (
            f"{SHIFT_EVENT_TYPE}|{old.cluster_key}|{old.sign}|{new.sign}|"
            f"{old.source_diversity}|{new.source_diversity}"
        )
        payload = {
            "cluster_key": old.cluster_key,
            "subject": old.subject,
            "predicate": old.predicate,
            "horizon_bucket": old.horizon_bucket,
            "from_sign": old.sign,
            "to_sign": new.sign,
            "from_source_diversity": old.source_diversity,
            "to_source_diversity": new.source_diversity,
            "from_positions": list(old.positions),
            "to_positions": list(new.positions),
            "reasons": reasons,
            "diversity_threshold": self.diversity_threshold,
        }
        return ConsensusShiftEvent(
            event_key=event_key,
            cluster_key=old.cluster_key,
            claim_key=old.claim_key,
            from_sign=old.sign,
            to_sign=new.sign,
            from_source_diversity=old.source_diversity,
            to_source_diversity=new.source_diversity,
            from_positions=list(old.positions),
            to_positions=list(new.positions),
            reasons=reasons,
            diversity_threshold=self.diversity_threshold,
            payload=payload,
        )


def cluster_key(subject: str, predicate: str, horizon_bucket: str) -> str:
    return f"cluster:{subject}:{predicate}:{horizon_bucket}"


def _state_from_consensus(point: ConsensusPoint) -> ClusterState:
    sign: ClusterSign = point.polarity if point.polarity in {"up", "down"} else SIGN_NONE
    return ClusterState(
        cluster_key=cluster_key(point.subject, point.predicate, point.horizon_bucket),
        subject=point.subject,
        predicate=point.predicate,
        horizon_bucket=point.horizon_bucket,
        sign=sign,
        source_diversity=point.source_diversity,
        positions=list(point.positions),
    )


def _state_from_divergence(point: DivergencePoint) -> ClusterState:
    positions = [side.position for side in point.sides]
    return ClusterState(
        cluster_key=cluster_key(point.subject, point.predicate, point.horizon_bucket),
        subject=point.subject,
        predicate=point.predicate,
        horizon_bucket=point.horizon_bucket,
        sign="contested",
        source_diversity=point.source_diversity,
        positions=positions,
    )


def _crossed_threshold(old: int, new: int, threshold: int) -> bool:
    return (old < threshold) != (new < threshold)
