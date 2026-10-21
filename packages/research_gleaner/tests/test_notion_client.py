from research_gleaner.notion.client import DEFAULT_NOTION_VERSION, NotionClient


class FakeResponse:
    status_code = 200
    headers = {}
    text = "{}"

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class FakeHttpClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, *, json=None, params=None):
        self.calls.append((method, url, json, params))
        return FakeResponse(next(self.responses))

    def close(self):
        return None


def test_query_uses_current_data_source_endpoint():
    client = NotionClient("token", min_interval=0)
    fake = FakeHttpClient([{"results": [], "has_more": False}])
    client._client.close()
    client._client = fake

    result = client.query_data_source(
        "source-1",
        filter_body={"property": "Status", "select": {"equals": "Ready"}},
        sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
    )

    method, url, body, params = fake.calls[0]
    assert result["results"] == []
    assert method == "POST"
    assert url.endswith("/v1/data_sources/source-1/query")
    assert body["filter"]["property"] == "Status"
    assert body["page_size"] == 100
    assert params is None
    assert client._headers["Notion-Version"] == DEFAULT_NOTION_VERSION


def test_paginate_passes_each_returned_cursor():
    cursors = []

    def fetch_page(*, start_cursor=None):
        cursors.append(start_cursor)
        if start_cursor is None:
            return {"results": [{"id": "one"}], "has_more": True, "next_cursor": "next"}
        return {"results": [{"id": "two"}], "has_more": False, "next_cursor": None}

    client = NotionClient("token", min_interval=0)
    try:
        results = client.paginate(fetch_page)
    finally:
        client.close()

    assert cursors == [None, "next"]
    assert [item["id"] for item in results] == ["one", "two"]
