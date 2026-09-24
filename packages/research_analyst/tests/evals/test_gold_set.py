"""Gold argument maps written through the co-reading command."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from research_analysis_layer.evals.gold_set import (
    DEFAULT_GOLDEN_PATH,
    GoldSetError,
    load_records,
    main,
    put_record,
    register_document,
    summarize_record,
    validate_record,
)

SPEECH = (
    "Inflation has come down a long way, but it is still above our 2 percent goal.\n\n"
    "Payroll gains have slowed to about 120 thousand a month, and wage growth is easing.\n\n"
    "Some argue we should cut now to protect the labor market. I think that would be premature.\n\n"
    "If services inflation keeps cooling, a cut later this year would be appropriate.\n"
)


def _record(**overrides):
    record = {
        "document_id": "powell-2026-09-17",
        "document_path": "documents/powell-2026-09-17.md",
        "document": {
            "title": "Economic outlook",
            "speaker": "Jerome Powell",
            "publisher": "Federal Reserve Board",
            "source_date": "2026-09-17",
            "doc_kind": "speech",
        },
        "status": "draft",
        "annotator": "nate",
        "claims": [
            {
                "id": "c1",
                "claim": "A rate cut now would be premature",
                "role": "conclusion",
                "claim_type": "policy",
                "stance": "hawkish",
                "rationale": "Inflation is still above goal, so easing before it is back is early.",
                "support_strength": "evidenced",
                "evidence": [
                    {
                        "text": "it is still above our 2 percent goal",
                        "kind": "quote",
                        "page": 1,
                    }
                ],
            },
            {
                "id": "c2",
                "claim": "Cut now to protect the labor market",
                "role": "counterpoint",
                "claim_type": "policy",
                "rationale": "Payroll growth has slowed.",
                "support_strength": "reasoned",
            },
            {
                "id": "c3",
                "claim": "A cut later this year would be appropriate if services inflation cools",
                "role": "condition",
                "claim_type": "forecast",
                "horizon": "later this year",
                "rationale": "Cooling services inflation would bring inflation back toward goal.",
                "support_strength": "reasoned",
                "proposed_by": "agent",
            },
        ],
        "links": [
            {"from": "c1", "to": "c2", "type": "answers"},
            {"from": "c3", "to": "c1", "type": "qualifies"},
            {"from": "c2", "to": "c1", "type": "contrasts_with"},
        ],
    }
    record.update(overrides)
    return record


class GoldSetTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.golden = Path(self._tmp.name)
        self.text_file = self.golden / "source.txt"
        self.text_file.write_text(SPEECH, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _register(self):
        return register_document(
            document_id="powell-2026-09-17",
            text_file=self.text_file,
            document={
                "title": "Economic outlook",
                "speaker": "Jerome Powell",
                "publisher": "Federal Reserve Board",
                "source_date": "2026-09-17",
                "doc_kind": "speech",
            },
            annotator="nate",
            golden_path=self.golden,
        )

    def test_register_copies_text_and_starts_draft(self) -> None:
        record = self._register()
        self.assertEqual(record["status"], "draft")
        self.assertEqual(record["claims"], [])
        stored = (self.golden / "documents" / "powell-2026-09-17.md").read_text(encoding="utf-8")
        self.assertEqual(stored, SPEECH)
        self.assertEqual(self._register()["document_id"], "powell-2026-09-17")

    def test_put_stores_roles_links_and_normalizes_contrast_direction(self) -> None:
        self._register()
        warnings = put_record(_record(), golden_path=self.golden)
        self.assertEqual(warnings, [])
        record = load_records(self.golden)["powell-2026-09-17"]
        roles = {claim["id"]: claim["role"] for claim in record["claims"]}
        self.assertEqual(roles, {"c1": "conclusion", "c2": "counterpoint", "c3": "condition"})
        contrast = [link for link in record["links"] if link["type"] == "contrasts_with"][0]
        self.assertEqual((contrast["from"], contrast["to"]), ("c1", "c2"))
        answers = [link for link in record["links"] if link["type"] == "answers"][0]
        self.assertEqual((answers["from"], answers["to"]), ("c1", "c2"))
        self.assertEqual(record["claims"][2]["proposed_by"], "agent")
        self.assertIn("annotated_at", record)

    def test_evidence_must_be_a_verbatim_quote_across_line_breaks(self) -> None:
        self._register()
        record = _record()
        record["claims"][0]["evidence"][0]["text"] = "Payroll gains have slowed to about\n120 thousand a month"
        put_record(record, golden_path=self.golden)

        record["claims"][0]["evidence"][0]["text"] = "inflation is falling rapidly everywhere"
        with self.assertRaises(GoldSetError) as caught:
            put_record(record, golden_path=self.golden)
        self.assertTrue(any("verbatim" in message for message in caught.exception.errors))

    def test_chart_evidence_can_cite_a_figure_key_instead_of_a_quote(self) -> None:
        self._register()
        record = _record()
        record["claims"][0]["evidence"] = [
            {"text": "Core PCE, 3m annualized", "kind": "chart", "figure_key": "figure:abcdef1234567890"}
        ]
        put_record(record, golden_path=self.golden)

    def test_links_must_join_existing_distinct_claims_once(self) -> None:
        self._register()
        record = _record(
            links=[
                {"from": "c1", "to": "c9", "type": "supports"},
                {"from": "c1", "to": "c1", "type": "supports"},
                {"from": "c1", "to": "c2", "type": "contrasts_with"},
                {"from": "c2", "to": "c1", "type": "contrasts_with"},
                {"from": "c1", "to": "c2", "type": "because"},
            ]
        )
        with self.assertRaises(GoldSetError) as caught:
            put_record(record, golden_path=self.golden)
        joined = " | ".join(caught.exception.errors)
        self.assertIn("'c9' is not a claim id", joined)
        self.assertIn("links a claim to itself", joined)
        self.assertIn("repeats an existing link", joined)
        self.assertIn("'because' is not one of", joined)

    def test_draft_allows_gaps_but_final_does_not(self) -> None:
        self._register()
        record = _record()
        record["claims"][1]["rationale"] = ""
        warnings = put_record(record, golden_path=self.golden)
        self.assertEqual(warnings, ["c2.rationale is empty"])

        record["status"] = "final"
        with self.assertRaises(GoldSetError):
            put_record(record, golden_path=self.golden)

        record["claims"][1]["rationale"] = "Payroll growth has slowed."
        put_record(record, golden_path=self.golden)
        self.assertEqual(load_records(self.golden)["powell-2026-09-17"]["status"], "final")

    def test_final_needs_a_conclusion(self) -> None:
        self._register()
        record = _record(status="final")
        record["claims"][0]["role"] = "premise"
        with self.assertRaises(GoldSetError) as caught:
            put_record(record, golden_path=self.golden)
        self.assertIn("a final record needs at least one conclusion", caught.exception.errors)

    def test_summary_reads_back_roles_links_and_agent_suggestions(self) -> None:
        self._register()
        put_record(_record(), golden_path=self.golden)
        summary = summarize_record(load_records(self.golden)["powell-2026-09-17"])
        self.assertIn("c1 conclusion, evidenced: A rate cut now would be premature", summary)
        self.assertIn("[suggested by agent]", summary)
        self.assertIn("c1 <-> c2: contrasts_with", summary)
        self.assertIn("c3 -> c1: qualifies", summary)

    def test_cli_put_and_validate(self) -> None:
        self._register()
        draft = self.golden / "draft.json"
        draft.write_text(json.dumps(_record()), encoding="utf-8")
        self.assertEqual(main(["--golden", str(self.golden), "put", "--file", str(draft)]), 0)
        self.assertEqual(main(["--golden", str(self.golden), "validate"]), 0)
        self.assertEqual(
            main(["--golden", str(self.golden), "show", "--document-id", "missing-doc"]), 1
        )

    def test_repository_gold_records_validate(self) -> None:
        for document_id, record in load_records(DEFAULT_GOLDEN_PATH).items():
            text_path = DEFAULT_GOLDEN_PATH / record["document_path"]
            text = text_path.read_text(encoding="utf-8") if text_path.is_file() else None
            errors, incomplete = validate_record(record, document_text=text)
            if record.get("status") == "final":
                errors += incomplete
            self.assertEqual(errors, [], document_id)


if __name__ == "__main__":
    unittest.main()
