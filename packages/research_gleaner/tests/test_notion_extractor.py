from research_gleaner.models import CaptureIntent
from research_gleaner.notion.extractor import ColorRule, NotionExtractor


class FakeNotionClient:
    def __init__(self, children):
        self.children = children

    def paginate(self, fetch_page):
        return fetch_page(start_cursor=None)["results"]

    def list_block_children(self, block_id, *, start_cursor=None, page_size=100):
        return {"results": self.children.get(block_id, []), "has_more": False}


def rich_text(text, color="default"):
    return {"plain_text": text, "annotations": {"color": color}}


def page():
    return {
        "id": "page-1",
        "url": "https://notion.so/page-1",
        "last_edited_time": "2026-10-12T12:00:00Z",
        "properties": {
            "Name": {"type": "title", "title": [rich_text("Rates outlook")]},
            "Topics": {"type": "multi_select", "multi_select": [{"name": "Markets"}]},
            "Resource Type": {
                "type": "multi_select",
                "multi_select": [{"name": "Research Note"}],
            },
        },
    }


def test_extracts_and_merges_adjacent_colored_text_with_heading_context():
    client = FakeNotionClient(
        {
            "page-1": [
                {
                    "id": "heading-1",
                    "type": "heading_1",
                    "has_children": False,
                    "heading_1": {"rich_text": [rich_text("Key findings")]},
                },
                {
                    "id": "paragraph-1",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {
                        "rich_text": [
                            rich_text("Rates ", "green"),
                            rich_text("stay high", "green"),
                            rich_text(" through 2027."),
                        ]
                    },
                },
            ]
        }
    )

    captures = NotionExtractor(client).extract_page(page())

    assert len(captures) == 1
    assert captures[0].text == "Rates stay high"
    assert captures[0].heading_path == ("Key findings",)
    assert captures[0].locator.char_start == 0
    assert captures[0].locator.char_end == 15
    assert captures[0].intent == CaptureIntent.HOLD


def test_explicit_color_rule_sets_route():
    client = FakeNotionClient(
        {
            "page-1": [
                {
                    "id": "paragraph-1",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": [rich_text("Investigate this", "yellow")]},
                }
            ]
        }
    )

    captures = NotionExtractor(
        client,
        color_rules={"yellow": ColorRule(CaptureIntent.RESEARCH)},
    ).extract_page(page())

    assert captures[0].intent == CaptureIntent.RESEARCH


def test_identical_table_cells_have_distinct_capture_ids():
    client = FakeNotionClient(
        {
            "page-1": [
                {"id": "table-1", "type": "table", "has_children": True, "table": {}},
            ],
            "table-1": [
                {
                    "id": "row-1",
                    "type": "table_row",
                    "table_row": {
                        "cells": [
                            [rich_text("Same", "blue")],
                            [rich_text("Same", "blue")],
                        ]
                    },
                }
            ],
        }
    )

    captures = NotionExtractor(client).extract_page(page())

    assert len(captures) == 2
    assert captures[0].capture_id != captures[1].capture_id
    assert captures[0].locator.metadata["cell_index"] == 0
    assert captures[1].locator.metadata["cell_index"] == 1


def test_synced_block_cycle_is_bounded():
    client = FakeNotionClient(
        {
            "page-1": [
                {
                    "id": "sync-1",
                    "type": "synced_block",
                    "has_children": False,
                    "synced_block": {"synced_from": {"block_id": "sync-2"}},
                }
            ],
            "sync-2": [
                {
                    "id": "sync-2-child",
                    "type": "synced_block",
                    "has_children": False,
                    "synced_block": {"synced_from": {"block_id": "sync-2"}},
                },
                {
                    "id": "paragraph-1",
                    "type": "paragraph",
                    "has_children": False,
                    "paragraph": {"rich_text": [rich_text("Once", "purple")]},
                },
            ],
        }
    )

    captures = NotionExtractor(client).extract_page(page())

    assert [capture.text for capture in captures] == ["Once"]
