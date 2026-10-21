import json

from research_gleaner.notion.query import NotionQuery
from research_gleaner.pipeline import run_notion_capture
from research_gleaner.store import CaptureStore


class FakeNotionClient:
    def __init__(self):
        self.query_calls = []

    def paginate(self, fetch_page):
        return fetch_page(start_cursor=None)["results"]

    def query_data_source(self, data_source_id, **kwargs):
        self.query_calls.append((data_source_id, kwargs))
        return {
            "results": [
                {
                    "id": "page-1",
                    "url": "https://notion.so/page-1",
                    "last_edited_time": "2026-10-12T12:00:00Z",
                    "properties": {
                        "Name": {
                            "type": "title",
                            "title": [{"plain_text": "Rates"}],
                        }
                    },
                }
            ],
            "has_more": False,
        }

    def list_block_children(self, block_id, *, start_cursor=None, page_size=100):
        assert block_id == "page-1"
        return {
            "results": [
                {
                    "id": "block-1",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {
                        "rich_text": [
                            {"plain_text": "Durable idea", "annotations": {"color": "blue"}}
                        ]
                    },
                }
            ],
            "has_more": False,
        }


def test_pipeline_exports_all_observed_and_marks_new(tmp_path):
    client = FakeNotionClient()
    store = CaptureStore(tmp_path / "gleaner.db")
    output = tmp_path / "captures.json"
    query = NotionQuery(data_source_id="source-1", since="24h")

    first = run_notion_capture(client, store, query, output)
    second = run_notion_capture(client, store, query, output)

    payload = json.loads(output.read_text())
    assert len(first.captures) == 1
    assert len(first.new_capture_ids) == 1
    assert len(second.captures) == 1
    assert second.new_capture_ids == ()
    assert payload["capture_count"] == 1
    assert payload["new_capture_count"] == 0
    assert payload["captures"][0]["text"] == "Durable idea"
    assert client.query_calls[0][0] == "source-1"
