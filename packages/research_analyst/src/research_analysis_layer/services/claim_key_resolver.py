"""Resolve argument-map claims to canonical `claim_key` values.

This is Slice 2 Task 2. It does not write the memory-substrate `research_claims`
table (schema only today). It fills the present-but-null `ClaimNode.claim_key`
so later consensus work can join "same conclusion" across publishers.

Key scheme (no free prose, horizon is not in the key):

    claim:<subject>:<predicate>:<polarity>

- `subject` — what the conclusion is about (`fed_policy`, `us_10y`, `ust_2s10s`)
- `predicate` — the move (`hike`, `cheap`, `steepen`)
- `polarity` — `up` | `down` | `neutral` on that subject's conventional axis

Same conclusion = same `(subject, predicate, polarity)` **modulo horizon**.
September hike vs December hike share a key; horizon bucketing is a separate
function for Task 4 clustering.

Opposing polarity on the same `(subject, predicate)` is a contradiction
candidate (`is_contradiction_candidate`). Leave `claim_key` None when the
subject or polarity is not confident. False merges are worse than misses.

The substrate `research_claims` row already has `subject_text`, `predicate`,
`polarity`, and `time_horizon`, but nothing in this repo writes those rows.
This resolver is the runtime join key for argument maps.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Sequence

from research_analysis_layer.models.agent_outputs import ClaimNode
from research_analysis_layer.models.assertion_models import normalize_text

CLAIM_POLARITIES = ("up", "down", "neutral")
HORIZON_BUCKETS = (
    "meeting_2026_09",
    "meeting_2026_12",
    "year_2026",
    "near_term",
    "medium",
    "longer",
    "unspecified",
)

_STANCE_UP = (
    "hawkish",
    "bullish",
    "tightening",
    "inflationary",
    "steepening",
    "steepener",
    "supportive",
)
_STANCE_DOWN = (
    "dovish",
    "bearish",
    "easing",
    "flatten",
    "flatter",
)
_STANCE_NEUTRAL = ("neutral", "mixed", "uncertain", "cautious")


def _fold(text: str) -> str:
    return normalize_text(text or "")


def _has_phrase(folded: str, phrase: str) -> bool:
    needle = _fold(phrase)
    if not needle:
        return False
    return f" {needle} " in f" {folded} "


def _any_phrase(folded: str, phrases: Sequence[str]) -> bool:
    return any(_has_phrase(folded, phrase) for phrase in phrases)


@dataclass(frozen=True)
class ClaimCatalogEntry:
    subject: str
    predicate: str
    all_of: tuple[tuple[str, ...], ...]
    none_of: tuple[str, ...] = ()
    polarity_up: tuple[str, ...] = ()
    polarity_down: tuple[str, ...] = ()
    weight: int = 1

    @property
    def family(self) -> str:
        return f"claim:{self.subject}:{self.predicate}"


CLAIM_CATALOG: tuple[ClaimCatalogEntry, ...] = (
    ClaimCatalogEntry(
        subject="fed_policy",
        predicate="hike",
        all_of=(
            (
                "hike",
                "hikes",
                "rate hike",
                "rate hikes",
                "25bp",
                "on hold",
                "remain on hold",
                "hold this year",
                "tightening",
            ),
        ),
        none_of=(
            "ecb",
            "boe",
            "boj",
            "jgb",
            "bank rate",
            "5s30s",
            "2s10s",
            "7s30s",
            "steepener",
        ),
        polarity_up=("hike", "hikes", "25bp", "tightening", "raises the probability", "forecasts two"),
        polarity_down=(
            "on hold",
            "remain on hold",
            "hold this year",
            "unlikely",
            "do not",
            "does not",
            "not setting up",
            "not necessarily imply",
            "very unlikely",
        ),
        weight=3,
    ),
    ClaimCatalogEntry(
        subject="warsh_speech_tone",
        predicate="tone",
        all_of=(
            ("warsh", "jackson hole"),
            ("hawkish", "dovish"),
        ),
        none_of=("hike", "hikes", "on hold", "25bp", "remain on hold"),
        polarity_up=("hawkish",),
        polarity_down=("dovish",),
        weight=2,
    ),
    ClaimCatalogEntry(
        subject="fed_credibility",
        predicate="restore",
        all_of=(
            ("credibility", "price stability", "inflation commitment"),
        ),
        none_of=("hike", "on hold"),
        polarity_up=("strengthen", "restored", "assuaged", "reaffirmation"),
        weight=2,
    ),
    ClaimCatalogEntry(
        subject="us_10y",
        predicate="cheap",
        all_of=(
            ("10y", "10 year", "10yr"),
            ("ust", "treasury", "cheap", "rich"),
        ),
        none_of=("breakeven", "jgb", "bund", "germany", "aud"),
        polarity_up=("cheap",),
        polarity_down=("rich",),
    ),
    ClaimCatalogEntry(
        subject="us_breakevens",
        predicate="width",
        all_of=(("breakeven", "breakevens", "inflation pricing"),),
        polarity_up=("wider", "risen", "widening"),
        polarity_down=("narrower", "narrow", "narrower us inflation"),
    ),
    ClaimCatalogEntry(
        subject="ust_2s10s",
        predicate="steepen",
        all_of=(("2s10s", "2s 10s", "2s/10s"),),
        none_of=("german", "bund", "eur", "jgb"),
        polarity_up=("steepen", "steepener", "steepeners", "steepening"),
        polarity_down=("flatteners", "too steep", "unwind"),
        weight=2,
    ),
    ClaimCatalogEntry(
        subject="ust_5s30s",
        predicate="steepen",
        all_of=(("5s30s", "5s 30s"),),
        polarity_up=("steepen", "steepener", "steepeners", "steepening"),
        polarity_down=("flatteners", "too steep", "unwind"),
        weight=2,
    ),
    ClaimCatalogEntry(
        subject="ust_7s30s",
        predicate="steepen",
        all_of=(("7s30s", "7s 30s"),),
        polarity_up=("steepen", "steepener", "steepeners", "steepening"),
        polarity_down=("flatteners", "too steep", "unwind"),
        weight=2,
    ),
)


@dataclass(frozen=True)
class ClaimResolution:
    claim_key: str | None
    subject: str | None
    predicate: str | None
    polarity: str | None
    horizon_bucket: str

    @property
    def family(self) -> str | None:
        if not self.subject or not self.predicate:
            return None
        return f"claim:{self.subject}:{self.predicate}"


def parse_claim_key(claim_key: str | None) -> tuple[str, str, str] | None:
    if not claim_key:
        return None
    parts = claim_key.split(":")
    if len(parts) != 4 or parts[0] != "claim":
        return None
    _, subject, predicate, polarity = parts
    if polarity not in CLAIM_POLARITIES:
        return None
    return subject, predicate, polarity


def claim_family(claim_key: str | None) -> str | None:
    parsed = parse_claim_key(claim_key)
    if parsed is None:
        return None
    subject, predicate, _ = parsed
    return f"claim:{subject}:{predicate}"


def is_contradiction_candidate(left: str | None, right: str | None) -> bool:
    """True when two keys share subject+predicate and have opposite polarity."""
    a = parse_claim_key(left)
    b = parse_claim_key(right)
    if a is None or b is None:
        return False
    subject_a, predicate_a, polarity_a = a
    subject_b, predicate_b, polarity_b = b
    if subject_a != subject_b or predicate_a != predicate_b:
        return False
    return {polarity_a, polarity_b} == {"up", "down"}


def horizon_bucket(horizon: str | None, *, claim_text: str = "") -> str:
    """Bucket free-text horizons so Task 4 can cluster without string-matching."""
    blob = _fold(" ".join(part for part in (horizon or "", claim_text) if part))
    if not blob:
        return "unspecified"
    if _any_phrase(blob, ("september", "sep")) and not _any_phrase(
        blob, ("december",)
    ):
        return "meeting_2026_09"
    if _any_phrase(blob, ("december",)):
        return "meeting_2026_12"
    if _any_phrase(
        blob,
        ("remainder of year", "this year", "hold this year", "2026"),
    ) and not _any_phrase(blob, ("2027",)):
        return "year_2026"
    if _any_phrase(
        blob,
        ("days", "weeks", "near term", "near-term", "current", "tomorrow", "intraday"),
    ):
        return "near_term"
    if _any_phrase(
        blob,
        ("months", "quarter", "q2", "q3", "q4", "h2", "1 3 months", "medium"),
    ):
        return "medium"
    if _any_phrase(blob, ("2027", "12m", "year-end", "longer")):
        return "longer"
    return "unspecified"


def normalize_stance_polarity(stance: str | None) -> str | None:
    folded = _fold(stance or "")
    if not folded:
        return None
    if _any_phrase(folded, _STANCE_UP) and not _any_phrase(folded, _STANCE_DOWN):
        return "up"
    if _any_phrase(folded, _STANCE_DOWN) and not _any_phrase(folded, _STANCE_UP):
        return "down"
    if _any_phrase(folded, _STANCE_NEUTRAL) and not (
        _any_phrase(folded, _STANCE_UP) or _any_phrase(folded, _STANCE_DOWN)
    ):
        return "neutral"
    return None


class ClaimKeyResolver:
    """Deterministic catalog matcher for `ClaimNode.claim_key`."""

    def __init__(self, *, catalog: Sequence[ClaimCatalogEntry] | None = None) -> None:
        self.catalog = tuple(catalog) if catalog is not None else CLAIM_CATALOG

    def resolve(
        self,
        claim: str,
        *,
        stance: str | None = None,
        horizon: str | None = None,
    ) -> ClaimResolution:
        folded = _fold(claim)
        bucket = horizon_bucket(horizon, claim_text=claim)
        if not folded:
            return ClaimResolution(None, None, None, None, bucket)

        matches: list[tuple[ClaimCatalogEntry, int]] = []
        for entry in self.catalog:
            score = self._score(folded, entry)
            if score is not None:
                matches.append((entry, score))
        if not matches:
            return ClaimResolution(None, None, None, None, bucket)

        by_subject: dict[str, int] = {}
        for entry, score in matches:
            by_subject[entry.subject] = max(by_subject.get(entry.subject, 0), score)
        if len(by_subject) > 1:
            ranked = sorted(by_subject.values(), reverse=True)
            if ranked[0] < 2 * ranked[1]:
                return ClaimResolution(None, None, None, None, bucket)
            winner = max(by_subject, key=by_subject.get)
            matches = [
                (entry, score)
                for entry, score in matches
                if entry.subject == winner
            ]

        best = max(score for _, score in matches)
        contenders = [entry for entry, score in matches if score == best]
        predicates = {entry.predicate for entry in contenders}
        if len(predicates) != 1:
            return ClaimResolution(None, None, None, None, bucket)
        entry = contenders[0]
        polarity = self._polarity(folded, entry, stance)
        if polarity is None:
            return ClaimResolution(None, entry.subject, entry.predicate, None, bucket)
        return ClaimResolution(
            claim_key=f"claim:{entry.subject}:{entry.predicate}:{polarity}",
            subject=entry.subject,
            predicate=entry.predicate,
            polarity=polarity,
            horizon_bucket=bucket,
        )

    def resolve_claim(self, node: ClaimNode) -> str | None:
        resolution = self.resolve(node.claim, stance=node.stance, horizon=node.horizon)
        node.claim_key = resolution.claim_key
        return resolution.claim_key

    def resolve_argument_map(self, argument_map: Sequence[ClaimNode]) -> None:
        for node in argument_map:
            self.resolve_claim(node)

    def resolve_payload(self, payload: dict) -> tuple[int, int]:
        resolved = 0
        total = 0
        for claim in payload.get("argument_map") or []:
            if not isinstance(claim, dict):
                continue
            total += 1
            resolution = self.resolve(
                str(claim.get("claim") or ""),
                stance=claim.get("stance") if isinstance(claim.get("stance"), str) else None,
                horizon=claim.get("horizon") if isinstance(claim.get("horizon"), str) else None,
            )
            claim["claim_key"] = resolution.claim_key
            if resolution.claim_key:
                resolved += 1
        return resolved, total

    def _score(self, folded: str, entry: ClaimCatalogEntry) -> int | None:
        if any(_has_phrase(folded, token) for token in entry.none_of):
            return None
        score = 0
        for group in entry.all_of:
            matched = [
                len(_fold(option))
                for option in group
                if _has_phrase(folded, option)
            ]
            if not matched:
                return None
            score += max(matched)
        return score * entry.weight

    def _polarity(
        self,
        folded: str,
        entry: ClaimCatalogEntry,
        stance: str | None,
    ) -> str | None:
        down = _any_phrase(folded, entry.polarity_down)
        up = _any_phrase(folded, entry.polarity_up)
        if down and not up:
            return "down"
        if up and not down:
            return "up"
        if down and up:
            # Negation / "on hold" beats a bare "hike" mention in the same sentence.
            return "down"
        return normalize_stance_polarity(stance)


def load_claim_golden(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        rows.append(json.loads(stripped))
    return rows


def score_claim_golden(rows: Iterable[dict], resolver: ClaimKeyResolver) -> dict:
    total = 0
    correct = 0
    misses = 0
    false_merges = 0
    expected_positive = 0
    predicted_positive = 0
    true_positive = 0
    publishers: set[str] = set()
    contradiction_pairs = 0
    contradiction_hits = 0

    for row in rows:
        total += 1
        if row.get("publisher"):
            publishers.add(str(row["publisher"]))
        expected = row.get("claim_key")
        predicted = resolver.resolve(
            str(row.get("claim") or ""),
            stance=row.get("stance"),
            horizon=row.get("horizon"),
        ).claim_key
        if expected:
            expected_positive += 1
        if predicted:
            predicted_positive += 1
        if predicted == expected:
            correct += 1
            if expected:
                true_positive += 1
        elif expected and predicted is None:
            misses += 1
        else:
            false_merges += 1
        contra = row.get("contradicts")
        if contra:
            contradiction_pairs += 1
            if is_contradiction_candidate(predicted, contra) or is_contradiction_candidate(
                expected, contra
            ):
                contradiction_hits += 1

    precision = true_positive / predicted_positive if predicted_positive else 1.0
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
        "contradiction_pairs": contradiction_pairs,
        "contradiction_hits": contradiction_hits,
    }


def claim_resolution_stats(
    payloads: Iterable[dict],
    resolver: ClaimKeyResolver | None = None,
) -> dict:
    total = 0
    stored_resolved = 0
    preview_resolved = 0
    for payload in payloads:
        for claim in payload.get("argument_map") or []:
            if not isinstance(claim, dict):
                continue
            total += 1
            stored = claim.get("claim_key")
            if stored:
                stored_resolved += 1
                preview_resolved += 1
                continue
            if resolver is None:
                continue
            preview = resolver.resolve(
                str(claim.get("claim") or ""),
                stance=claim.get("stance") if isinstance(claim.get("stance"), str) else None,
                horizon=claim.get("horizon") if isinstance(claim.get("horizon"), str) else None,
            ).claim_key
            if preview:
                preview_resolved += 1
    stored_unresolved = total - stored_resolved
    preview_unresolved = total - preview_resolved
    return {
        "claim_count": total,
        "stored_resolved_count": stored_resolved,
        "stored_unresolved_rate": (stored_unresolved / total) if total else 0.0,
        "preview_resolved_count": preview_resolved,
        "preview_unresolved_rate": (preview_unresolved / total) if total else 0.0,
    }
