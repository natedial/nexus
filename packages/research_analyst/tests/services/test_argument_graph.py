from __future__ import annotations

from unittest.mock import MagicMock
import unittest

from research_analysis_layer.services.argument_graph import ArgumentGraph


def _map(
    *,
    source: str,
    research_id: int,
    claim: str,
    claim_key: str,
    rationale: str,
    ref_key: str,
    evidence_text: str,
    referent_key: str | None,
    support_strength: str = "evidenced",
    extra_evidence: list[dict] | None = None,
) -> dict:
    evidence = []
    if referent_key is not None or evidence_text:
        row = {
            "text": evidence_text,
            "kind": "data",
            "ref_key": ref_key,
        }
        if referent_key is not None:
            row["referent_key"] = referent_key
        evidence.append(row)
    if extra_evidence:
        evidence.extend(extra_evidence)
    return {
        "source": source,
        "research_id": research_id,
        "argument_map": [
            {
                "claim": claim,
                "claim_key": claim_key,
                "rationale": rationale,
                "support_strength": support_strength,
                "evidence": evidence,
            }
        ],
    }


class ArgumentGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        self.graph = ArgumentGraph(min_publishers=2)

    def test_same_evidence_opposing_conclusions_is_an_interpretation_gap(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor has cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed to 5k",
                referent_key="series:nfp",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                rationale="speech was not guidance",
                ref_key="span:citi-19",
                evidence_text="payrolls cooled",
                referent_key="series:nfp",
            ),
            _map(
                source="Barclays",
                research_id=16,
                claim="25bp September hike most likely.",
                claim_key="claim:fed_policy:hike:up",
                rationale="hawkish tone",
                ref_key="span:barc-16",
                evidence_text="payrolls leave the door open",
                referent_key="series:nfp",
            ),
        ]
        snapshot = self.graph.query_maps(maps)
        self.assertEqual(len(snapshot.interpretation_gaps), 1)
        gap = snapshot.interpretation_gaps[0]
        self.assertEqual(gap.referent_key, "series:nfp")
        self.assertEqual(gap.family, "claim:fed_policy:hike")
        self.assertEqual(gap.source_diversity, 3)
        self.assertEqual(
            {side.publisher for side in gap.sides},
            {"Barclays", "Citi", "Goldman Sachs"},
        )
        polarities = {side.publisher: side.polarity for side in gap.sides}
        self.assertEqual(polarities["Barclays"], "up")
        self.assertEqual(polarities["Citi"], "down")
        self.assertEqual(polarities["Goldman Sachs"], "down")
        self.assertTrue(gap.rationale)

    def test_disjoint_referents_are_robust_consensus(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor has cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                rationale="speech was not guidance",
                ref_key="span:citi-19",
                evidence_text="Warsh said the speech was not guidance",
                referent_key="event:jackson_hole_2026:not_guidance",
            ),
        ]
        rows = self.graph.query_maps(maps).independence
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, "robust")
        self.assertEqual(rows[0].claim_key, "claim:fed_policy:hike:down")
        self.assertEqual(rows[0].shared_referents, [])
        self.assertEqual(rows[0].source_diversity, 2)

    def test_shared_referent_is_herding_consensus(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor has cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:citi-19",
                evidence_text="payrolls cooled",
                referent_key="series:nfp",
            ),
            _map(
                source="GS",
                research_id=2,
                claim="September hike remains unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="same payrolls print",
                ref_key="span:gs-2",
                evidence_text="NFP surprise",
                referent_key="series:nfp",
            ),
        ]
        rows = self.graph.query_maps(maps).independence
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, "herding")
        self.assertEqual(rows[0].shared_referents, ["series:nfp"])
        self.assertEqual(rows[0].source_diversity, 2)
        self.assertEqual(rows[0].positions, ["Citi", "Goldman Sachs"])

    def test_shared_plus_unique_referents_are_mixed(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor plus speech",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
                extra_evidence=[
                    {
                        "text": "speech was not guidance",
                        "kind": "quote",
                        "ref_key": "span:gs-1b",
                        "referent_key": "event:jackson_hole_2026:not_guidance",
                    }
                ],
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:citi-19",
                evidence_text="payrolls cooled",
                referent_key="series:nfp",
            ),
        ]
        rows = self.graph.query_maps(maps).independence
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].kind, "mixed")
        self.assertEqual(rows[0].shared_referents, ["series:nfp"])

    def test_same_referent_different_subjects_is_not_an_interpretation_gap(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
            _map(
                source="Deutsche Bank",
                research_id=8,
                claim="10y looks cheap.",
                claim_key="claim:us_10y:cheap:up",
                rationale="yields overshot",
                ref_key="span:db-8",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
        ]
        snapshot = self.graph.query_maps(maps)
        self.assertEqual(snapshot.interpretation_gaps, [])

    def test_single_publisher_emits_no_graph_hits(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=rid,
                claim="Maintain 2s/10s steepeners.",
                claim_key="claim:ust_2s10s:steepen:up",
                rationale="trend intact",
                ref_key=f"span:gs-{rid}",
                evidence_text="2s10s above 10bp",
                referent_key="entity:ust_2s10s",
            )
            for rid in (32, 34, 50)
        ]
        snapshot = self.graph.query_maps(maps)
        self.assertEqual(snapshot.interpretation_gaps, [])
        self.assertEqual(snapshot.independence, [])
        self.assertEqual(snapshot.contradictions, [])
        self.assertEqual(snapshot.backed_vs_asserted, [])
        self.assertEqual(snapshot.clustered_claim_count, 3)

    def test_evidence_contradicts_claim_from_shared_opposing_citation(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
            _map(
                source="Barclays",
                research_id=16,
                claim="25bp September hike most likely.",
                claim_key="claim:fed_policy:hike:up",
                rationale="hawkish tone",
                ref_key="span:barc-16",
                evidence_text="payrolls leave the door open",
                referent_key="series:nfp",
            ),
        ]
        hits = self.graph.query_maps(maps).contradictions
        self.assertEqual(len(hits), 2)
        by_pub = {hit.publisher: hit for hit in hits}
        self.assertEqual(by_pub["Goldman Sachs"].referent_key, "series:nfp")
        self.assertEqual(by_pub["Barclays"].referent_key, "series:nfp")
        self.assertEqual(
            {side.publisher for side in by_pub["Goldman Sachs"].opposing_sides},
            {"Barclays"},
        )
        self.assertTrue(by_pub["Goldman Sachs"].rationale)

    def test_mixed_polarity_house_does_not_hide_other_houses_contradiction(self) -> None:
        maps = [
            _map(
                source="Morgan Stanley",
                research_id=40,
                claim="On hold this year.",
                claim_key="claim:fed_policy:hike:down",
                rationale="data dependent",
                ref_key="span:ms-40",
                evidence_text="Jackson Hole was not a hike signal",
                referent_key="event:jackson_hole_2026",
            ),
            _map(
                source="Morgan Stanley",
                research_id=41,
                claim="A December hike is possible.",
                claim_key="claim:fed_policy:hike:up",
                rationale="dots still show a hike",
                ref_key="span:ms-41",
                evidence_text="December dots",
                referent_key="event:fomc",
            ),
            _map(
                source="Barclays",
                research_id=16,
                claim="25bp September hike most likely.",
                claim_key="claim:fed_policy:hike:up",
                rationale="hawkish tone",
                ref_key="span:barc-16",
                evidence_text="Jackson Hole was hawkish",
                referent_key="event:jackson_hole_2026",
            ),
        ]
        snapshot = self.graph.query_maps(maps)
        self.assertEqual(len(snapshot.interpretation_gaps), 1)
        self.assertEqual(snapshot.interpretation_gaps[0].referent_key, "event:jackson_hole_2026")
        pubs = {hit.publisher for hit in snapshot.contradictions}
        self.assertEqual(pubs, {"Barclays", "Morgan Stanley"})

    def test_explicit_contradicts_relation_hits_without_shared_citation(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
            _map(
                source="Barclays",
                research_id=16,
                claim="25bp September hike most likely.",
                claim_key="claim:fed_policy:hike:up",
                rationale="hawkish tone",
                ref_key="span:barc-16",
                evidence_text="Warsh was hawkish",
                referent_key="event:jackson_hole_2026:hawkish",
            ),
        ]
        snapshot = self.graph.query_maps(
            maps,
            relations=[
                {
                    "relation": "contradicts",
                    "referent_key": "series:nfp",
                    "claim_key": "claim:fed_policy:hike:up",
                }
            ],
        )
        self.assertEqual(snapshot.interpretation_gaps, [])
        self.assertEqual(len(snapshot.contradictions), 1)
        hit = snapshot.contradictions[0]
        self.assertEqual(hit.publisher, "Barclays")
        self.assertEqual(hit.referent_key, "series:nfp")
        self.assertIn("explicit contradicts", hit.rationale)

    def test_backed_vs_asserted_splits_publishers(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
                support_strength="evidenced",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                rationale="author view",
                ref_key="span:citi-19",
                evidence_text="",
                referent_key=None,
                support_strength="asserted",
            ),
        ]
        rows = self.graph.query_maps(maps).backed_vs_asserted
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].evidenced, ["Goldman Sachs"])
        self.assertEqual(rows[0].asserted, ["Citi"])
        self.assertEqual(rows[0].source_diversity, 2)
        self.assertEqual(self.graph.query_maps(maps).independence, [])

    def test_unresolved_referents_do_not_join(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key=None,
            ),
            _map(
                source="Barclays",
                research_id=16,
                claim="25bp September hike most likely.",
                claim_key="claim:fed_policy:hike:up",
                rationale="hawkish tone",
                ref_key="span:barc-16",
                evidence_text="payrolls leave the door open",
                referent_key=None,
            ),
        ]
        snapshot = self.graph.query_maps(maps)
        self.assertEqual(snapshot.interpretation_gaps, [])
        self.assertEqual(snapshot.contradictions, [])
        self.assertEqual(snapshot.clustered_claim_count, 2)

    def test_constructor_rejects_min_publishers_below_two(self) -> None:
        with self.assertRaisesRegex(ValueError, "min_publishers must be >= 2"):
            ArgumentGraph(min_publishers=1)

    def test_doctor_report_counts_hits(self) -> None:
        import sys
        import types

        if "research_pipeline_ops" not in sys.modules:
            stub = types.ModuleType("research_pipeline_ops")
            stub.PipelineOpsClient = MagicMock
            sys.modules["research_pipeline_ops"] = stub
        from research_analysis_layer.main import _argument_graph_report

        store = MagicMock()
        store.list_argument_maps_for_consensus.return_value = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed",
                referent_key="series:nfp",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                rationale="speech was not guidance",
                ref_key="span:citi-19",
                evidence_text="Warsh said the speech was not guidance",
                referent_key="event:jackson_hole_2026:not_guidance",
            ),
        ]
        settings = MagicMock()
        settings.consensus_min_publishers = 2
        report = _argument_graph_report(store, settings)
        self.assertEqual(report["interpretation_gap_count"], 0)
        self.assertEqual(report["robust_count"], 1)
        self.assertEqual(report["herding_count"], 0)
        self.assertEqual(report["contradiction_count"], 0)
        self.assertEqual(report["backed_vs_asserted_count"], 0)


if __name__ == "__main__":
    unittest.main()
