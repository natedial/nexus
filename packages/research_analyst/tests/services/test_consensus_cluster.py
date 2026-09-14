from __future__ import annotations

import unittest

from research_analysis_layer.services.consensus_cluster import ConsensusClusterer


def _map(
    *,
    source: str,
    research_id: int,
    claim: str,
    claim_key: str,
    horizon: str | None,
    rationale: str,
    ref_key: str,
    evidence_text: str,
    support_strength: str = "evidenced",
) -> dict:
    return {
        "source": source,
        "research_id": research_id,
        "argument_map": [
            {
                "claim": claim,
                "claim_key": claim_key,
                "horizon": horizon,
                "rationale": rationale,
                "support_strength": support_strength,
                "evidence": [
                    {
                        "text": evidence_text,
                        "kind": "data",
                        "ref_key": ref_key,
                    }
                ],
            }
        ],
    }


class ConsensusClustererTest(unittest.TestCase):
    def setUp(self) -> None:
        self.clusterer = ConsensusClusterer(min_publishers=2)

    def test_three_maps_yield_expected_consensus_and_divergence(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="labor market has cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed to 5k",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="The authors do not view Warsh's speech as setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="speech was not forward guidance",
                ref_key="span:citi-19",
                evidence_text="Warsh said the speech was not guidance",
            ),
            _map(
                source="Barclays",
                research_id=16,
                claim="Chairman Warsh's Jackson Hole speech raises the probability of a 25bp September Fed hike.",
                claim_key="claim:fed_policy:hike:up",
                horizon="September",
                rationale="hawkish tone plus 25bp baseline",
                ref_key="span:barc-16",
                evidence_text="25bp September hike most likely",
            ),
        ]
        snapshot = self.clusterer.cluster_maps(maps)
        self.assertEqual(snapshot.agreements, [])
        self.assertEqual(len(snapshot.disagreements), 1)
        split = snapshot.disagreements[0]
        self.assertEqual(split.subject, "fed_policy")
        self.assertEqual(split.predicate, "hike")
        self.assertEqual(split.horizon_bucket, "meeting_2026_09")
        self.assertEqual(split.source_diversity, 3)
        self.assertEqual(split.verdict, "contested")
        self.assertIsNone(split.favored_position)
        self.assertEqual(
            {side.position for side in split.sides},
            {"Barclays", "Citi", "Goldman Sachs"},
        )

    def test_same_direction_two_houses_is_consensus(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="not guidance",
                ref_key="span:citi-19",
                evidence_text="speech was not guidance",
            ),
        ]
        snapshot = self.clusterer.cluster_maps(maps)
        self.assertEqual(len(snapshot.agreements), 1)
        self.assertEqual(snapshot.disagreements, [])
        point = snapshot.agreements[0]
        self.assertEqual(point.positions, ["Citi", "Goldman Sachs"])
        self.assertEqual(point.source_diversity, 2)
        self.assertEqual(point.polarity, "down")
        self.assertEqual(point.contradiction_count, 0)

    def test_three_notes_one_publisher_emit_neither(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=rid,
                claim="Maintain 2s/10s steepeners.",
                claim_key="claim:ust_2s10s:steepen:up",
                horizon="weeks",
                rationale="trend intact",
                ref_key=f"span:gs-{rid}",
                evidence_text="2s10s above 10bp",
            )
            for rid in (32, 34, 50)
        ]
        snapshot = self.clusterer.cluster_maps(maps)
        self.assertEqual(snapshot.agreements, [])
        self.assertEqual(snapshot.disagreements, [])
        self.assertEqual(snapshot.clustered_claim_count, 3)

    def test_same_bank_aliases_do_not_create_false_diversity(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="Maintain 2s/10s steepeners.",
                claim_key="claim:ust_2s10s:steepen:up",
                horizon="weeks",
                rationale="trend intact",
                ref_key="span:gs-1",
                evidence_text="2s10s above 10bp",
            ),
            _map(
                source="GS",
                research_id=2,
                claim="Hold 2s/10s steepeners.",
                claim_key="claim:ust_2s10s:steepen:up",
                horizon="weeks",
                rationale="policy flattening reverses",
                ref_key="span:gs-2",
                evidence_text="flattening should reverse",
            ),
            _map(
                source="J.P. Morgan",
                research_id=32,
                claim="Maintain 2s/10s steepeners.",
                claim_key="claim:ust_2s10s:steepen:up",
                horizon="weeks",
                rationale="trend intact",
                ref_key="span:jpm-32",
                evidence_text="2s10s steepener held",
            ),
        ]
        snapshot = self.clusterer.cluster_maps(maps)
        self.assertEqual(len(snapshot.agreements), 1)
        self.assertEqual(snapshot.agreements[0].source_diversity, 2)
        self.assertEqual(
            snapshot.agreements[0].positions,
            ["Goldman Sachs", "J.P. Morgan"],
        )

    def test_ungrounded_claims_do_not_emit_a_point(self) -> None:
        maps = [
            {
                "source": "Citi",
                "research_id": 1,
                "argument_map": [
                    {
                        "claim": "A September Fed hike is very unlikely.",
                        "claim_key": "claim:fed_policy:hike:down",
                        "horizon": "September",
                        "evidence": [{"text": "no ref", "kind": "data"}],
                    }
                ],
            },
            {
                "source": "Goldman Sachs",
                "research_id": 2,
                "argument_map": [
                    {
                        "claim": "September hike is unlikely.",
                        "claim_key": "claim:fed_policy:hike:down",
                        "horizon": "September",
                        "evidence": [],
                    }
                ],
            },
        ]
        snapshot = self.clusterer.cluster_maps(maps)
        self.assertEqual(snapshot.agreements, [])
        self.assertEqual(snapshot.disagreements, [])

    def test_min_publishers_three_holds_two_house_consensus(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="not guidance",
                ref_key="span:citi-19",
                evidence_text="speech was not guidance",
            ),
        ]
        snapshot = ConsensusClusterer(min_publishers=3).cluster_maps(maps)
        self.assertEqual(snapshot.agreements, [])

    def test_same_house_mixed_polarity_is_dropped(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
            ),
            _map(
                source="GS",
                research_id=2,
                claim="A September hike is now the base case.",
                claim_key="claim:fed_policy:hike:up",
                horizon="September",
                rationale="speech was hawkish",
                ref_key="span:gs-2",
                evidence_text="hawkish Jackson Hole",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="not guidance",
                ref_key="span:citi-19",
                evidence_text="speech was not guidance",
            ),
            _map(
                source="Barclays",
                research_id=16,
                claim="25bp September hike most likely.",
                claim_key="claim:fed_policy:hike:up",
                horizon="September",
                rationale="hawkish tone",
                ref_key="span:barc-16",
                evidence_text="25bp September hike most likely",
            ),
        ]
        snapshot = self.clusterer.cluster_maps(maps)
        self.assertEqual(snapshot.agreements, [])
        self.assertEqual(len(snapshot.disagreements), 1)
        split = snapshot.disagreements[0]
        self.assertEqual(split.source_diversity, 2)
        self.assertEqual(
            {side.position for side in split.sides},
            {"Barclays", "Citi"},
        )

    def test_september_and_december_do_not_share_a_cluster(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
            ),
            _map(
                source="Barclays",
                research_id=16,
                claim="A 25bp December hike is the base case.",
                claim_key="claim:fed_policy:hike:up",
                horizon="December",
                rationale="hawkish tone",
                ref_key="span:barc-16",
                evidence_text="December hike most likely",
            ),
        ]
        snapshot = self.clusterer.cluster_maps(maps)
        self.assertEqual(snapshot.agreements, [])
        self.assertEqual(snapshot.disagreements, [])
        self.assertEqual(snapshot.clustered_claim_count, 2)

    def test_payload_json_maps_cluster_like_top_level_maps(self) -> None:
        maps = [
            {
                "source": "Citi",
                "research_id": 19,
                "payload_json": _map(
                    source="ignored",
                    research_id=19,
                    claim="Not setting up a September rate hike.",
                    claim_key="claim:fed_policy:hike:down",
                    horizon="September",
                    rationale="not guidance",
                    ref_key="span:citi-19",
                    evidence_text="speech was not guidance",
                ),
            },
            {
                "source": "Goldman Sachs",
                "research_id": 1,
                "payload_json": _map(
                    source="ignored",
                    research_id=1,
                    claim="A September Fed hike is very unlikely.",
                    claim_key="claim:fed_policy:hike:down",
                    horizon="September",
                    rationale="labor cooled",
                    ref_key="span:gs-1",
                    evidence_text="payrolls slowed",
                ),
            },
        ]
        snapshot = self.clusterer.cluster_maps(maps)
        self.assertEqual(len(snapshot.agreements), 1)
        self.assertEqual(snapshot.agreements[0].positions, ["Citi", "Goldman Sachs"])

    def test_constructor_rejects_min_publishers_below_two(self) -> None:
        with self.assertRaisesRegex(ValueError, "min_publishers must be >= 2"):
            ConsensusClusterer(min_publishers=1)

    def test_doctor_report_counts_points(self) -> None:
        from unittest.mock import MagicMock

        from research_analysis_layer.main import _consensus_report

        store = MagicMock()
        store.list_argument_maps_for_consensus.return_value = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="not guidance",
                ref_key="span:citi-19",
                evidence_text="speech was not guidance",
            ),
        ]
        settings = MagicMock()
        settings.consensus_min_publishers = 2
        report = _consensus_report(store, settings)
        self.assertEqual(report["agreement_count"], 1)
        self.assertEqual(report["disagreement_count"], 0)
        self.assertEqual(report["clustered_claim_count"], 2)


if __name__ == "__main__":
    unittest.main()
