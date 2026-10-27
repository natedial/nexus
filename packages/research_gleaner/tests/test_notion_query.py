from datetime import UTC, datetime

import pytest

from research_gleaner.notion.query import NotionQuery, build_filter, parse_since

NOW = datetime(2026, 10, 12, 12, tzinfo=UTC)


def test_build_filter_combines_optional_constraints():
    query = NotionQuery(
        data_source_id="source-1",
        topic="Markets",
        resource_types=("Research Note", "Commentary"),
        since="24h",
    )

    result = build_filter(query, now=NOW)

    assert result is not None
    assert len(result["and"]) == 3
    assert result["and"][0]["last_edited_time"]["on_or_after"].startswith("2026-10-11T12:00")
    assert len(result["and"][2]["or"]) == 2


def test_empty_query_has_no_filter():
    assert build_filter(NotionQuery(data_source_id="source-1"), now=NOW) is None


@pytest.mark.parametrize("value", ["", "24", "0h", "-1d", "tomorrow"])
def test_invalid_since_is_rejected(value):
    with pytest.raises(ValueError):
        parse_since(value, now=NOW)
