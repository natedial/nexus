from __future__ import annotations

import unittest

from research_analysis_layer.models.agent_outputs import ClaimNode
from research_analysis_layer.services.claim_key_resolver import (
    ClaimKeyResolver,
    horizon_bucket,
    is_contradiction_candidate,
)


class ClaimKeyResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = ClaimKeyResolver()

    def test_same_direction_same_subject_shares_key(self) -> None:
        citi = self.resolver.resolve(
            "The authors do not view Warsh's speech as setting up a September rate hike.",
            stance="dovish",
            horizon="September",
        )
        gs = self.resolver.resolve(
            "A September Fed hike is very unlikely.",
            stance="dovish",
            horizon="September",
        )
        self.assertEqual(citi.claim_key, "claim:fed_policy:hike:down")
        self.assertEqual(gs.claim_key, citi.claim_key)

    def test_on_hold_joins_no_hike(self) -> None:
        hold = self.resolver.resolve(
            "Base-case: the Fed will remain on hold this year as disinflation progresses.",
            stance="dovish",
            horizon="remainder of year",
        )
        self.assertEqual(hold.claim_key, "claim:fed_policy:hike:down")

    def test_opposing_polarity_is_contradiction_candidate(self) -> None:
        down = self.resolver.resolve(
            "A September Fed hike is very unlikely.",
            stance="dovish",
            horizon="September",
        )
        up = self.resolver.resolve(
            "Chairman Warsh's Jackson Hole speech was hawkish and raises the probability of a 25bp September Fed hike.",
            stance="hawkish",
            horizon="September",
        )
        self.assertEqual(down.claim_key, "claim:fed_policy:hike:down")
        self.assertEqual(up.claim_key, "claim:fed_policy:hike:up")
        self.assertEqual(down.family, up.family)
        self.assertTrue(is_contradiction_candidate(down.claim_key, up.claim_key))

    def test_horizon_is_not_in_claim_key(self) -> None:
        september = self.resolver.resolve(
            "raises the probability of a 25bp September Fed hike",
            stance="hawkish",
            horizon="September",
        )
        december = self.resolver.resolve(
            "an additional 25bp hike in December after September",
            stance="hawkish",
            horizon="December",
        )
        self.assertEqual(september.claim_key, december.claim_key)
        self.assertEqual(september.horizon_bucket, "meeting_2026_09")
        self.assertEqual(december.horizon_bucket, "meeting_2026_12")

    def test_speech_tone_does_not_merge_with_hike_call(self) -> None:
        tone = self.resolver.resolve(
            "Chair Warsh's Jackson Hole speech was more hawkish than expected.",
            stance="hawkish",
        )
        hike = self.resolver.resolve(
            "A September Fed hike is very unlikely.",
            stance="dovish",
            horizon="September",
        )
        self.assertEqual(tone.claim_key, "claim:warsh_speech_tone:tone:up")
        self.assertEqual(hike.claim_key, "claim:fed_policy:hike:down")
        self.assertNotEqual(tone.family, hike.family)
        self.assertFalse(is_contradiction_candidate(tone.claim_key, hike.claim_key))

    def test_tenor_subjects_stay_distinct(self) -> None:
        cash = self.resolver.resolve(
            "10y USTs remain cheap on Deutsche Bank's valuation model.",
            stance="neutral",
        )
        twos = self.resolver.resolve("Maintain 2s/10s steepeners.", stance="bullish")
        fives = self.resolver.resolve(
            "We expect the 5s30s curve to continue to steepen.",
            stance="bullish steepener",
        )
        self.assertEqual(cash.claim_key, "claim:us_10y:cheap:up")
        self.assertEqual(twos.claim_key, "claim:ust_2s10s:steepen:up")
        self.assertEqual(fives.claim_key, "claim:ust_5s30s:steepen:up")
        self.assertEqual(len({cash.subject, twos.subject, fives.subject}), 3)

    def test_prose_and_foreign_policy_stay_unresolved(self) -> None:
        self.assertIsNone(
            self.resolver.resolve("CTAs are extremely skewed to buy silver.", stance="bullish").claim_key
        )
        self.assertIsNone(
            self.resolver.resolve(
                "The ECB will retain a cautious approach at the September meeting despite an expected hike.",
                stance="cautious",
                horizon="September",
            ).claim_key
        )
        self.assertIsNone(
            self.resolver.resolve(
                "10y JGB yields are expected at 3.0% by year-end.",
                stance="bearish",
            ).claim_key
        )

    def test_horizon_bucket_helpers(self) -> None:
        self.assertEqual(horizon_bucket("September"), "meeting_2026_09")
        self.assertEqual(horizon_bucket("December"), "meeting_2026_12")
        self.assertEqual(horizon_bucket("remainder of year"), "year_2026")
        self.assertEqual(horizon_bucket("weeks"), "near_term")
        self.assertEqual(horizon_bucket(None), "unspecified")

    def test_resolve_argument_map_writes_claim_key(self) -> None:
        node = ClaimNode(
            claim="A September Fed hike is very unlikely.",
            stance="dovish",
            horizon="September",
        )
        self.resolver.resolve_argument_map([node])
        self.assertEqual(node.claim_key, "claim:fed_policy:hike:down")


if __name__ == "__main__":
    unittest.main()
