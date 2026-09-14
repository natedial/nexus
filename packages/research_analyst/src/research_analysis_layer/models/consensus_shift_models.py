"""source_consensus_shift memory events (Slice 2 Task 6).

Append-only local events. The parser `research_memory_events` table is the
substrate schema; nothing writes it yet, and argument maps are local SQLite,
so these rows live next to the maps until Task 7 exports them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SHIFT_EVENT_TYPE = "source_consensus_shift"
SHIFT_EVENT_VERSION = "consensus-shift-v1"
ClusterSign = Literal["up", "down", "contested", "none"]
ShiftReason = Literal["sign_flip", "diversity_threshold"]


class ClusterState(BaseModel):
    """Latest observed sign and publisher diversity for one cluster."""

    cluster_key: str
    subject: str
    predicate: str
    horizon_bucket: str
    sign: ClusterSign
    source_diversity: int
    positions: list[str] = Field(default_factory=list)

    @property
    def claim_key(self) -> str:
        return f"claim:{self.subject}:{self.predicate}"


class ConsensusShiftEvent(BaseModel):
    """One real change in a cluster's sign or diversity."""

    event_key: str
    event_type: str = SHIFT_EVENT_TYPE
    cluster_key: str
    claim_key: str
    event_version: str = SHIFT_EVENT_VERSION
    from_sign: ClusterSign
    to_sign: ClusterSign
    from_source_diversity: int
    to_source_diversity: int
    from_positions: list[str] = Field(default_factory=list)
    to_positions: list[str] = Field(default_factory=list)
    reasons: list[ShiftReason]
    diversity_threshold: int
    payload: dict = Field(default_factory=dict)
