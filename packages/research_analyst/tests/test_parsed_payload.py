from __future__ import annotations

import unittest
from urllib.error import HTTPError
from io import BytesIO

from research_analysis_layer.db.parsed_db_client import ParsedDbClient
from research_analysis_layer.models.document_models import (
    HydratedParsedDocument,
    HydratedTheme,
    ParsedDocument,
    ParsedTheme,
)
from research_analysis_layer.parsed_payload import (
    file_id_from_payload,
    identity_fields,
    legacy_metadata,
    payload_kind,
)
from research_analysis_layer.services.agent_input_builder import AgentInputBuilder
from research_analysis_layer.services.backfill import synthesize_state_record
from research_analysis_layer.services.chunker import Chunker


SUBSTRATE_PAYLOAD = {
    "full_text": "The Fed is done hiking. " * 40,
    "identity": {
        "document_id": "1AbCdefghijKlmnoPQ",
        "publisher_slug": "gs",
        "parser_version": "parse-storage-v1",
    },
    "parse": {
        "backend": "docling",
        "confidence": 0.92,
        "themes": [{"label": "SHOULD_NOT_BE_USED"}],
        "trades": [{"instrument": "SHOULD_NOT_BE_USED"}],
    },
}


class RecordingTablesClient(ParsedDbClient):
    def __init__(self, tables: dict[str, list[dict]]):
        super().__init__("https://example.supabase.co", "secret")
        self.tables = tables
        self.requested: list[str] = []

    def _get(self, table, params):
        self.requested.append(table)
        if table not in self.tables:
            raise HTTPError(
                f"https://example.supabase.co/rest/v1/{table}",
                404,
                "Not Found",
                hdrs=None,
                fp=BytesIO(b""),
            )
        return list(self.tables[table])


def _substrate_document(**overrides) -> ParsedDocument:
    payload = dict(SUBSTRATE_PAYLOAD)
    payload.update(overrides.pop("parsed_data_update", {}))
    kwargs = {
        "id": 42,
        "document_name": "2026-08-30_GS_fomc.pdf",
        "source": "Goldman Sachs",
        "source_date": "2026-08-30",
        "parsed_data": payload,
        "document_link": "https://drive.google.com/file/d/1AbCdefghijKlmnoPQ/view",
        "theme_count": 0,
        "trade_count": 0,
        "document_hash": "hash-substrate",
    }
    kwargs.update(overrides)
    return ParsedDocument(**kwargs)


class ParsedPayloadHelpersTest(unittest.TestCase):
    def test_classifies_legacy_and_substrate_shapes(self) -> None:
        self.assertEqual(
            payload_kind({"full_text": "x", "metadata": {"document_id": "a"}, "themes": []}),
            "legacy",
        )
        self.assertEqual(payload_kind(SUBSTRATE_PAYLOAD), "substrate")
        self.assertEqual(payload_kind({}), "empty")

    def test_identity_is_not_copied_into_metadata(self) -> None:
        self.assertEqual(
            identity_fields(SUBSTRATE_PAYLOAD)["document_id"], "1AbCdefghijKlmnoPQ"
        )
        self.assertEqual(legacy_metadata(SUBSTRATE_PAYLOAD), {})
        self.assertEqual(
            file_id_from_payload(SUBSTRATE_PAYLOAD), "1AbCdefghijKlmnoPQ"
        )

    def test_legacy_file_id_still_comes_from_metadata(self) -> None:
        parsed = {"full_text": "x", "metadata": {"document_id": "file-legacy"}}
        self.assertEqual(file_id_from_payload(parsed), "file-legacy")
        self.assertEqual(identity_fields(parsed), {})

    def test_falls_back_to_document_link(self) -> None:
        parsed = {"full_text": "x", "identity": {}, "parse": {}}
        file_id = file_id_from_payload(
            parsed,
            document_link="https://drive.google.com/file/d/1AbCdefghijKlmnoPQ/view?usp=share",
        )
        self.assertEqual(file_id, "1AbCdefghijKlmnoPQ")


class SubstrateHydrationTest(unittest.TestCase):
    def test_hydrates_from_chunks_and_spans_not_parse_themes(self) -> None:
        client = RecordingTablesClient(
            {
                "research_themes": [],
                "research_theme_excerpts": [],
                "research_retrieval_chunks": [
                    {
                        "chunk_key": "chunk:42:1",
                        "research_id": 42,
                        "chunk_order": 1,
                        "title": "Fed path",
                        "section_name": "Rates",
                        "text": "GS sees the Committee on hold through year-end.",
                        "span_keys": ["span:42:1"],
                    }
                ],
                "research_spans": [
                    {
                        "span_key": "span:42:1",
                        "research_id": 42,
                        "span_order": 1,
                        "span_type": "paragraph",
                        "text": "The Committee is on hold through year-end.",
                    }
                ],
            }
        )
        hydrated = client.hydrate_document(_substrate_document())

        self.assertEqual(hydrated.file_id, "1AbCdefghijKlmnoPQ")
        self.assertTrue(hydrated.ready_for_analysis)
        self.assertEqual(len(hydrated.themes), 1)
        self.assertEqual(hydrated.themes[0].theme.label, "Fed path")
        self.assertEqual(
            hydrated.themes[0].excerpts[0].excerpt_text,
            "The Committee is on hold through year-end.",
        )
        self.assertNotEqual(hydrated.themes[0].theme.label, "SHOULD_NOT_BE_USED")
        self.assertIn("research_retrieval_chunks", client.requested)
        self.assertNotIn("parsed_data.themes", str(hydrated.themes[0].theme.label))

    def test_missing_extraction_tables_still_hydrates_from_spans(self) -> None:
        client = RecordingTablesClient(
            {
                "research_spans": [
                    {
                        "span_key": "span:42:1",
                        "research_id": 42,
                        "span_order": 1,
                        "span_type": "paragraph",
                        "text": "Services inflation is still sticky.",
                    }
                ]
            }
        )
        hydrated = client.hydrate_document(_substrate_document())
        self.assertTrue(hydrated.ready_for_analysis)
        self.assertEqual(len(hydrated.themes), 1)
        self.assertIn("sticky", hydrated.themes[0].theme.context)
        self.assertEqual(hydrated.themes[0].theme.argument_structure["source"], "span")

    def test_prefers_research_themes_when_extraction_service_has_run(self) -> None:
        client = RecordingTablesClient(
            {
                "research_themes": [
                    {
                        "id": 7,
                        "research_id": 42,
                        "theme_order": 1,
                        "label": "On hold",
                        "scope": None,
                        "primary_category": "Rates",
                        "relevance": ["Rates"],
                        "classification": "Forecast",
                        "strength": "Primary",
                        "confidence": "High",
                        "evidence_count": 1,
                        "mention_count": 1,
                        "context": "On hold through year-end.",
                        "directionality": None,
                        "argument_structure": None,
                    }
                ],
                "research_theme_excerpts": [
                    {
                        "id": 9,
                        "theme_id": 7,
                        "excerpt_order": 1,
                        "excerpt_text": "On hold through year-end.",
                    }
                ],
                "research_retrieval_chunks": [
                    {"chunk_key": "unused", "text": "should not be used"}
                ],
                "research_spans": [],
            }
        )
        hydrated = client.hydrate_document(_substrate_document(theme_count=1))
        self.assertEqual([theme.theme.label for theme in hydrated.themes], ["On hold"])
        self.assertNotIn("research_retrieval_chunks", client.requested)

    def test_hydrate_search_does_not_read_parsed_data_metadata(self) -> None:
        client = RecordingTablesClient(
            {
                "parsed_research": [
                    {
                        "id": 42,
                        "document_name": "note.pdf",
                        "source": "Goldman Sachs",
                        "source_date": "2026-08-30",
                        "parsed_data": SUBSTRATE_PAYLOAD,
                        "document_link": "https://drive.google.com/file/d/1AbCdefghijKlmnoPQ/view",
                        "theme_count": 0,
                        "trade_count": 0,
                        "document_hash": "hash-substrate",
                    }
                ],
                "research_themes": [],
                "research_retrieval_chunks": [
                    {
                        "chunk_key": "chunk:42:1",
                        "chunk_order": 1,
                        "title": "Labor",
                        "text": "Payrolls stay firm.",
                    }
                ],
                "research_spans": [],
            }
        )
        rows = client.hydrate_search(limit=1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].file_id, "1AbCdefghijKlmnoPQ")
        self.assertTrue(rows[0].ready_for_analysis)

    def test_agent_input_keeps_identity_out_of_metadata(self) -> None:
        document = HydratedParsedDocument(
            document=_substrate_document(),
            themes=[
                HydratedTheme(
                    theme=ParsedTheme(
                        id=1,
                        research_id=42,
                        theme_order=1,
                        label="Fed path",
                        scope=None,
                        primary_category="Rates",
                        relevance=[],
                        classification="Description",
                        strength="Secondary",
                        confidence="Medium",
                        evidence_count=1,
                        mention_count=1,
                        context="On hold.",
                        directionality=None,
                        argument_structure={"source": "retrieval_chunk"},
                    )
                )
            ],
            file_id="1AbCdefghijKlmnoPQ",
        )
        payload = AgentInputBuilder().build(
            agent_type="thesis",
            document=document,
            chunks=Chunker().chunk_document(document),
            evidence_units=[],
            assertions=[],
        )
        self.assertEqual(payload["document"]["metadata"], {})
        self.assertEqual(payload["document"]["identity"]["publisher_slug"], "gs")
        self.assertEqual(payload["document"]["identity"]["document_id"], "1AbCdefghijKlmnoPQ")
        self.assertTrue(payload["document"]["full_text_excerpt"])

    def test_synthesize_state_record_uses_identity_file_id(self) -> None:
        document = HydratedParsedDocument(
            document=_substrate_document(),
            themes=[],
            file_id=None,
        )
        record = synthesize_state_record(document)
        self.assertEqual(record.file_id, "1AbCdefghijKlmnoPQ")

    def test_ready_for_analysis_when_theme_count_is_zero_but_chunks_exist(self) -> None:
        theme = ParsedTheme(
            id=1,
            research_id=42,
            theme_order=1,
            label="Fed path",
            scope=None,
            primary_category=None,
            relevance=[],
            classification="Description",
            strength="Secondary",
            confidence="Medium",
            evidence_count=1,
            mention_count=1,
            context="On hold.",
            directionality=None,
            argument_structure=None,
        )
        hydrated = HydratedParsedDocument(
            document=_substrate_document(theme_count=0),
            themes=[HydratedTheme(theme=theme)],
        )
        self.assertTrue(hydrated.ready_for_analysis)

    def test_legacy_ready_for_analysis_still_requires_theme_count_match(self) -> None:
        document = ParsedDocument(
            id=1,
            document_name="doc.pdf",
            source="JPM",
            source_date="2026-03-30",
            parsed_data={"full_text": "x", "metadata": {"document_id": "file-1"}},
            theme_count=2,
            document_hash="h",
        )
        theme = ParsedTheme(
            id=1,
            research_id=1,
            theme_order=1,
            label="Only one",
            scope=None,
            primary_category=None,
            relevance=[],
            classification="Description",
            strength="Secondary",
            confidence="Medium",
            evidence_count=0,
            mention_count=0,
            context="x",
            directionality=None,
            argument_structure=None,
        )
        hydrated = HydratedParsedDocument(
            document=document,
            themes=[HydratedTheme(theme=theme)],
        )
        self.assertFalse(hydrated.ready_for_analysis)


if __name__ == "__main__":
    unittest.main()
