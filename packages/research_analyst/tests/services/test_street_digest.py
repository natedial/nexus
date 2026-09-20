from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from research_analysis_layer.db.analysis_store import AnalysisStore
from research_analysis_layer.models.dispatch_scope import DispatchScope
from research_analysis_layer.services.dispatch_batch_exporter import (
    DispatchBatchExporter,
)
from research_analysis_layer.services.street_digest import (
    render_street_digest,
    short_publisher_label,
)


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
                "support_strength": "evidenced",
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


class StreetDigestTest(unittest.TestCase):
    def test_divergence_line_has_attribution_and_verdict(self) -> None:
        maps = [
            _map(
                source="Goldman Sachs",
                research_id=1,
                claim="A September Fed hike is very unlikely.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="labor cooled",
                ref_key="span:gs-1",
                evidence_text="payrolls slowed to 5k",
            ),
            _map(
                source="Citi",
                research_id=19,
                claim="Not setting up a September rate hike.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="not guidance",
                ref_key="span:citi-19",
                evidence_text="Warsh said the speech was not guidance",
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
        digest = render_street_digest(maps)
        self.assertTrue(digest.reached_street_scale)
        self.assertEqual(digest.agreements, [])
        self.assertEqual(len(digest.disagreements), 1)
        line = digest.disagreements[0]
        self.assertIn("GS", line)
        self.assertIn("Citi", line)
        self.assertIn("Barclays", line)
        self.assertIn("contested", line)
        self.assertIn("because", line)
        self.assertEqual(digest.lines, digest.disagreements)

    def test_consensus_line_names_houses_and_count(self) -> None:
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
                source="Morgan Stanley",
                research_id=12,
                claim="The Fed is done hiking.",
                claim_key="claim:fed_policy:hike:down",
                horizon="September",
                rationale="labor cooled",
                ref_key="span:ms-12",
                evidence_text="payrolls slowed",
            ),
        ]
        digest = render_street_digest(maps)
        self.assertEqual(len(digest.agreements), 1)
        line = digest.agreements[0]
        self.assertIn("GS and MS agree", line)
        self.assertIn("(2 houses)", line)
        self.assertEqual(digest.disagreements, [])

    def test_single_publisher_falls_back_below_street_scale(self) -> None:
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
            )
        ]
        digest = render_street_digest(maps)
        self.assertFalse(digest.reached_street_scale)
        self.assertEqual(digest.agreements, [])
        self.assertEqual(digest.disagreements, [])
        self.assertEqual(len(digest.fallback), 1)
        self.assertIn("below street scale", digest.fallback[0])
        self.assertIn("GS", digest.fallback[0])
        self.assertEqual(digest.lines, digest.fallback)

    def test_short_publisher_labels(self) -> None:
        self.assertEqual(short_publisher_label("Goldman Sachs"), "GS")
        self.assertEqual(short_publisher_label("J.P. Morgan"), "JPM")
        self.assertEqual(short_publisher_label("Nomura"), "Nomura")

    def test_ungrounded_multi_house_is_not_invented_as_consensus(self) -> None:
        maps = [
            {
                "source": "Goldman Sachs",
                "research_id": 1,
                "argument_map": [
                    {
                        "claim": "The Fed is done hiking.",
                        "claim_key": "claim:fed_policy:hike:down",
                        "horizon": "September",
                        "rationale": "",
                        "support_strength": "asserted",
                        "evidence": [],
                    }
                ],
            },
            {
                "source": "Morgan Stanley",
                "research_id": 12,
                "argument_map": [
                    {
                        "claim": "Hiking cycle is over.",
                        "claim_key": "claim:fed_policy:hike:down",
                        "horizon": "September",
                        "rationale": "",
                        "support_strength": "asserted",
                        "evidence": [],
                    }
                ],
            },
        ]
        digest = render_street_digest(maps)
        self.assertFalse(digest.reached_street_scale)
        self.assertEqual(digest.agreements, [])
        self.assertEqual(digest.disagreements, [])
        self.assertEqual(digest.fallback, [])
        self.assertEqual(digest.lines, [])


class StreetDigestExportTest(unittest.TestCase):
    def test_dispatch_batch_includes_street_section(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = AnalysisStore(Path(tmp.name) / "analysis.db")
        payload = {
            "argument_map": [
                {
                    "claim": "A September Fed hike is very unlikely.",
                    "claim_key": "claim:fed_policy:hike:down",
                    "horizon": "September",
                    "rationale": "labor cooled",
                    "support_strength": "evidenced",
                    "evidence": [
                        {
                            "text": "payrolls slowed",
                            "kind": "data",
                            "ref_key": "span:gs-1",
                        }
                    ],
                }
            ],
            "payload_json": {
                "document": {
                    "source": "Goldman Sachs",
                    "publisher": "Goldman Sachs",
                    "document_name": "note.pdf",
                    "source_date": "2026-08-22",
                }
            },
        }
        payload_ms = json.loads(json.dumps(payload))
        payload_ms["argument_map"][0]["claim"] = "The Fed is done hiking."
        payload_ms["argument_map"][0]["evidence"][0]["ref_key"] = "span:ms-12"
        payload_ms["payload_json"]["document"]["source"] = "Morgan Stanley"
        payload_ms["payload_json"]["document"]["publisher"] = "Morgan Stanley"

        for research_id, source, body in (
            (1, "Goldman Sachs", payload),
            (12, "Morgan Stanley", payload_ms),
        ):
            with store._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO analysis_documents (
                        research_id, file_id, document_hash, source, source_date,
                        document_name, title, publisher, area, region, asset_focus,
                        document_link, ingested_at, last_analyzed_at,
                        latest_analysis_version, latest_successful_run_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        research_id,
                        f"file-{research_id}",
                        f"hash-{research_id}",
                        source,
                        "2026-08-22",
                        "note.pdf",
                        "Note",
                        source,
                        None,
                        None,
                        None,
                        None,
                        "2026-08-22T00:00:00+00:00",
                        "2026-08-22T00:00:00+00:00",
                        "argmap-v1",
                        11,
                    ),
                )
            store.write_document_analysis(
                document_key=f"doc:{research_id}",
                research_id=research_id,
                document_hash=f"hash-{research_id}",
                analysis_version="argmap-v1",
                run_id="11",
                payload_json=json.dumps(body),
                thesis="thesis",
                confidence=0.8,
                total_input_tokens=1,
                total_output_tokens=1,
                total_tool_calls=0,
                total_duration_ms=10,
            )

        batch = DispatchBatchExporter(store).load_batch(
            DispatchScope(document_keys=["doc:1", "doc:12"], batch_key="test")
        )
        street = batch["cross_document_signals"]["street_agrees_splits"]
        self.assertTrue(street["reached_street_scale"])
        self.assertEqual(street["agreement_count"], 1)
        self.assertIn("(2 houses)", street["agreements"][0])
        self.assertIn("argument_map", batch["documents"][0])


if __name__ == "__main__":
    unittest.main()
