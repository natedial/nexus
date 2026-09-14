from __future__ import annotations

import unittest

from research_analysis_layer.models.agent_outputs import ClaimNode, EvidenceRef
from research_analysis_layer.services.evidence_referent_resolver import (
    EvidenceReferentResolver,
)


class EvidenceReferentResolverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.coarse = EvidenceReferentResolver(granularity="coarse")
        self.fine = EvidenceReferentResolver(granularity="fine")

    def test_same_fact_different_wording_shares_key(self) -> None:
        first = self.coarse.resolve_text(
            "Chair Warsh was trying to strengthen FOMC credibility with his speech at Jackson Hole today."
        )
        second = self.coarse.resolve_text(
            "To our ear, Chairman Warsh's speech at Jackson Hole was quite hawkish."
        )
        self.assertEqual(first, "event:jackson_hole_2026")
        self.assertEqual(second, first)

    def test_fine_key_keeps_speech_facet(self) -> None:
        key = self.fine.resolve_text(
            "Chair Warsh's Jackson Hole remarks assuaged inflation-credibility concerns."
        )
        self.assertEqual(key, "event:jackson_hole_2026:warsh_speech")

    def test_prose_only_evidence_stays_unresolved(self) -> None:
        self.assertIsNone(
            self.coarse.resolve_text(
                "CTAs are extremely skewed to buy silver. Systematic trend followers may add size."
            )
        )
        self.assertIsNone(
            self.coarse.resolve_text(
                "large-scale outflows in spot gold peaking at their 86th percentile"
            )
        )

    def test_warsh_speech_does_not_merge_with_september_fomc(self) -> None:
        speech = self.fine.resolve_text(
            "Chairman Warsh's speech at Jackson Hole was hawkish, making a 25bp September hike most likely."
        )
        meeting = self.fine.resolve_text(
            "Payer skew has been strongly bid on the back of Fed credibility concerns post July FOMC."
        )
        self.assertEqual(speech, "event:jackson_hole_2026:warsh_speech")
        self.assertEqual(meeting, "event:fomc_2026_07")
        self.assertNotEqual(speech, meeting)

    def test_tenor_and_breakeven_facts_stay_distinct(self) -> None:
        cash = self.fine.resolve_text(
            "10y USTs remain cheap on our valuation model and residuals have been stable."
        )
        breakevens = self.fine.resolve_text(
            "For 10y US breakevens, market pricing still appears about 60bp too low."
        )
        thirty = self.fine.resolve_text(
            "We see risks specifically at the 30y point of the Treasury curve."
        )
        self.assertEqual(cash, "series:us_10y")
        self.assertEqual(breakevens, "series:us_10y_breakevens")
        self.assertEqual(thirty, "series:us_30y")
        self.assertEqual(len({cash, breakevens, thirty}), 3)

    def test_core_pce_windows_do_not_false_merge_at_fine(self) -> None:
        three = self.fine.resolve_text("3-month annualized core PCE falls to 2.27%.")
        six = self.fine.resolve_text("6-month annualized core PCE inflation falls to 2%.")
        both = self.fine.resolve_text(
            "3-month annualized core PCE falls to 2.27% and 6-month annualized core PCE falls to 3.00%."
        )
        self.assertEqual(three, "series:us_core_pce_3m_saar")
        self.assertEqual(six, "series:us_core_pce_6m_saar")
        self.assertIsNone(both)
        self.assertEqual(
            self.coarse.resolve_text(
                "3-month annualized core PCE falls to 2.27% and 6-month annualized core PCE falls to 3.00%."
            ),
            "series:us_core_pce",
        )

    def test_peer_series_in_one_sentence_stay_unresolved(self) -> None:
        self.assertIsNone(
            self.coarse.resolve_text(
                "He revealed that core PCE and the unemployment rate are the two inputs to his reaction function."
            )
        )

    def test_brokertec_wins_over_tenor_mentions(self) -> None:
        key = self.coarse.resolve_text(
            "BrokerTec halved the minimum price increment for 5y and 10y USTs on 29 June 2026."
        )
        self.assertEqual(key, "event:brokertec_tick_size")

    def test_resolve_argument_map_writes_referent_key(self) -> None:
        claim = ClaimNode(
            claim="Warsh's Jackson Hole speech was hawkish.",
            evidence=[
                EvidenceRef(
                    text="Chair Warsh's Jackson Hole speech was more hawkish than expected.",
                    kind="quote",
                )
            ],
        )
        self.coarse.resolve_argument_map([claim])
        self.assertEqual(claim.evidence[0].referent_key, "event:jackson_hole_2026")

    def test_invalid_granularity_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            EvidenceReferentResolver(granularity="medium")


if __name__ == "__main__":
    unittest.main()
