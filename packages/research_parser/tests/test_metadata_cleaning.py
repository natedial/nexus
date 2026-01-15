import json

from src.extraction.metadata import _clean_json_response


def test_clean_json_response_strips_trailing_commentary():
    raw = (
        "Based on the document analysis, here's the metadata extraction:\n\n"
        "{\n"
        '  "source": "Goldman Sachs",\n'
        '  "source_date": "2026-01-10",\n'
        '  "area": "USD",\n'
        '  "region": "US",\n'
        '  "asset_focus": "rates",\n'
        '  "publisher": "Goldman Sachs"\n'
        "}\n\n"
        "Key reasoning:\n"
        "- Source is clearly Goldman Sachs from the document's header and style\n"
    )

    cleaned = _clean_json_response(raw)
    data = json.loads(cleaned)

    assert data["source"] == "Goldman Sachs"
    assert data["area"] == "USD"


def test_clean_json_response_handles_code_fences_and_extra_text():
    raw = (
        "```json\n"
        "{\n"
        '  "source": "Bank of America",\n'
        '  "source_date": null\n'
        "}\n"
        "```\n"
        "Extra text that should be ignored."
    )

    cleaned = _clean_json_response(raw)
    data = json.loads(cleaned)

    assert data["source"] == "Bank of America"
    assert data["source_date"] is None
