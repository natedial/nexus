from src.parser import BlockType, TextBlock
from src.research_memory import ResearchArtifactContext
from src.source import SourceDocument
from src.storage.supabase import SupabaseClient


class _FakeResponse:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, client, name: str):
        self._client = client
        self._name = name
        self._action = "select"
        self._filters = []
        self._payload = None
        self._on_conflict = []

    def select(self, _columns: str):
        self._action = "select"
        return self

    def eq(self, column: str, value):
        self._filters.append((column, value))
        return self

    def limit(self, _value: int):
        return self

    def delete(self):
        self._action = "delete"
        return self

    def upsert(self, payload, on_conflict: str):
        self._action = "upsert"
        self._payload = payload
        self._on_conflict = [item.strip() for item in on_conflict.split(",") if item]
        return self

    def execute(self):
        rows = self._client.tables.setdefault(self._name, [])

        if self._action == "select":
            matched = [row for row in rows if self._matches(row)]
            return _FakeResponse(matched)

        if self._action == "delete":
            self._client.tables[self._name] = [
                row for row in rows if not self._matches(row)
            ]
            return _FakeResponse([])

        if self._action == "upsert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            stored = []
            for payload in payloads:
                updated = False
                for row in rows:
                    if all(row.get(column) == payload.get(column) for column in self._on_conflict):
                        row.update(payload)
                        stored.append(dict(row))
                        updated = True
                        break
                if not updated:
                    row = dict(payload)
                    if "id" not in row:
                        row["id"] = self._client.next_ids.setdefault(self._name, 1)
                        self._client.next_ids[self._name] += 1
                    rows.append(row)
                    stored.append(dict(row))
            return _FakeResponse(stored)

        raise AssertionError(f"Unsupported action: {self._action}")

    def _matches(self, row: dict) -> bool:
        return all(row.get(column) == value for column, value in self._filters)


class _FakeSupabase:
    def __init__(self):
        self.tables = {"parsed_research": []}
        self.next_ids = {"parsed_research": 1}

    def table(self, name: str):
        return _FakeTable(self, name)


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
    fake = _FakeSupabase()
    client = SupabaseClient.__new__(SupabaseClient)
    client._client = fake
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
    assert "research_themes" not in fake.tables

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
    fake = _FakeSupabase()

    def _boom_table(name: str):
        if name in {
            "research_document_artifacts",
            "research_spans",
            "research_retrieval_chunks",
        }:
            raise RuntimeError("memory unavailable")
        return _FakeTable(fake, name)

    fake.table = _boom_table  # type: ignore[method-assign]
    client = SupabaseClient.__new__(SupabaseClient)
    client._client = fake

    try:
        client.insert_research(
            _source(document_id="drive-citi", source="Citi", full_text="A paragraph."),
            "note.pdf",
        )
    except RuntimeError as exc:
        assert "memory unavailable" in str(exc)
    else:
        raise AssertionError("span write failure should fail the storage step")
