from src.parser import BlockType, TextBlock
from src.research_memory import ResearchArtifactContext
from src.source import SourceDocument
from tests.fake_source_store import FakeSourceStore, _FakePostgrestClient, _FakeTable


def _source(**kwargs) -> SourceDocument:
    values = {
        "document_id": "drive-gs",
        "document_name": "2026-08-31_GS_Rates.pdf",
        "full_text": "Rates Outlook\n\nDuration should rally if payrolls cool.",
        "source": "Goldman Sachs",
        "source_date": "2026-08-31",
        "document_uri": "gdrive://drive-gs",
        "document_link": "https://drive.google.com/file/d/drive-gs/view",
    }
    values.update(kwargs)
    return SourceDocument(**values)


def test_insert_research_writes_block_backed_spans_and_artifacts():
    fake = _FakePostgrestClient()
    client = FakeSourceStore(fake)
    context = ResearchArtifactContext(
        parse_backend="docling",
        parse_confidence_score=0.88,
        parse_confidence_status="PASS",
        raw_markdown_path="/tmp/document.md",
        clean_text_path="/tmp/clean_text.md",
        blocks_path="/tmp/blocks.jsonl",
        blocks=[
            TextBlock(block_type=BlockType.HEADING, text="Rates Outlook", page=1, level=1),
            TextBlock(
                block_type=BlockType.PARAGRAPH,
                text="Duration should rally if payrolls cool.",
                page=1,
                bbox=[1.0, 2.0, 3.0, 4.0],
            ),
            TextBlock(
                block_type=BlockType.TABLE,
                text="| Tenor | Yield |\n| 2y | 3.8 |",
                page=2,
            ),
        ],
    )

    stored = client.insert_research(
        _source(),
        "2026-08-31_GS_Rates.pdf",
        artifact_context=context,
    )

    assert stored["id"] == 1
    parsed_data = fake.tables["parsed_research"][0]["parsed_data"]
    assert parsed_data["parse"]["backend"] == "docling"
    assert parsed_data["parse"]["ocr_retried"] is False
    assert parsed_data["parse"]["ocr_retry_reasons"] == []
    assert "themes" not in parsed_data
    assert "trades" not in parsed_data
    assert not fake.tables.get("research_themes")

    artifacts = fake.tables["research_document_artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["parse_backend"] == "docling"
    assert artifacts[0]["artifact_manifest"]["source"] == "parser_blocks"

    spans = fake.tables["research_spans"]
    assert [span["span_type"] for span in spans] == ["section", "paragraph", "table"]
    assert spans[1]["page_start"] == 1
    assert spans[1]["coordinates"] == {"bbox": [1.0, 2.0, 3.0, 4.0]}
    assert spans[2]["page_start"] == 2

    chunks = fake.tables["research_retrieval_chunks"]
    assert len(chunks) == 1
    assert set(chunks[0]["span_keys"]) == {span["span_key"] for span in spans}


def test_insert_research_memory_failure_blocks_the_run():
    fake = _FakePostgrestClient()

    def _boom_table(name: str):
        if name in {
            "research_document_artifacts",
            "research_spans",
            "research_retrieval_chunks",
        }:
            raise RuntimeError("memory unavailable")
        return _FakeTable(fake, name)

    fake.table = _boom_table  # type: ignore[method-assign]
    client = FakeSourceStore(fake)

    try:
        client.insert_research(
            _source(document_id="drive-citi", source="Citi", full_text="A paragraph."),
            "note.pdf",
        )
    except RuntimeError as exc:
        assert "memory unavailable" in str(exc)
    else:
        raise AssertionError("span write failure should fail the storage step")
