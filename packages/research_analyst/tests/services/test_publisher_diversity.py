from __future__ import annotations

from types import SimpleNamespace
import unittest

from research_analysis_layer.models.document_models import ParsedDocument
from research_analysis_layer.services.publisher_diversity import (
    Publisher,
    canonical_publisher,
    distinct_publishers,
    publisher_for_document,
    source_diversity,
)


class PublisherDiversityTest(unittest.TestCase):
    def test_three_notes_from_one_publisher_count_as_one(self) -> None:
        cluster = [
            {"source": "Goldman Sachs", "research_id": 8},
            {"source": "GS", "research_id": 10},
            {"source": "Goldman", "research_id": 23},
        ]
        publishers = distinct_publishers(cluster)
        self.assertEqual([p.label for p in publishers], ["Goldman Sachs"])
        self.assertEqual(source_diversity(cluster), 1)

    def test_two_publishers_count_as_two(self) -> None:
        cluster = [
            {"source": "Goldman Sachs"},
            {"source": "Goldman Sachs"},
            {"source": "Morgan Stanley"},
        ]
        self.assertEqual(source_diversity(cluster), 2)
        self.assertEqual(
            [p.label for p in distinct_publishers(cluster)],
            ["Goldman Sachs", "Morgan Stanley"],
        )

    def test_jp_morgan_aliases_collapse(self) -> None:
        cluster = ["J.P. Morgan", "JP Morgan", "JPM", "jpmorgan"]
        self.assertEqual(source_diversity(cluster), 1)
        self.assertEqual(distinct_publishers(cluster)[0].key, "jpmorgan")
        self.assertEqual(distinct_publishers(cluster)[0].label, "J.P. Morgan")

    def test_prefers_document_source_over_empty_publisher(self) -> None:
        doc = ParsedDocument(
            id=12,
            document_name="note.pdf",
            source="J.P. Morgan",
            source_date="2026-08-22",
            parsed_data={},
            publisher=None,
        )
        resolved = publisher_for_document(doc)
        self.assertEqual(resolved, Publisher(key="jpmorgan", label="J.P. Morgan"))

    def test_hydrated_document_resolves_through_nested_document(self) -> None:
        inner = ParsedDocument(
            id=19,
            document_name="note.pdf",
            source="Citi",
            source_date="2026-08-22",
            parsed_data={},
        )
        hydrated = SimpleNamespace(document=inner, research_id=19)
        self.assertEqual(publisher_for_document(hydrated).label, "Citi")

    def test_missing_house_is_skipped_not_counted(self) -> None:
        cluster = [
            {"source": None, "publisher": None},
            {"source": "Barclays"},
            "",
            None,
        ]
        self.assertEqual(source_diversity(cluster), 1)

    def test_unknown_house_still_dedupes_on_normalized_name(self) -> None:
        cluster = ["Nomura", "nomura", " NOMURA "]
        self.assertEqual(source_diversity(cluster), 1)
        self.assertEqual(distinct_publishers(cluster)[0].key, "nomura")

    def test_canonical_publisher_empty_is_none(self) -> None:
        self.assertIsNone(canonical_publisher())
        self.assertIsNone(canonical_publisher(source="  ", publisher=""))

    def test_doctor_report_uses_source_diversity(self) -> None:
        from unittest.mock import MagicMock

        from research_analysis_layer.main import _publisher_diversity_report

        store = MagicMock()
        store.list_analyzed_documents.return_value = [
            {"source": "Goldman Sachs"},
            {"source": "GS"},
            {"source": "Morgan Stanley"},
        ]
        report = _publisher_diversity_report(store)
        self.assertEqual(report["document_count"], 3)
        self.assertEqual(report["source_diversity"], 2)
        self.assertEqual(report["publishers"], ["Goldman Sachs", "Morgan Stanley"])


if __name__ == "__main__":
    unittest.main()
