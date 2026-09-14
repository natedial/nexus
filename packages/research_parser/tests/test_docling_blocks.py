from types import SimpleNamespace

from src.parser import BlockType, blocks_from_docling_document


class _Prov:
    def __init__(self, page_no, bbox):
        self.page_no = page_no
        self.bbox = bbox


class _Item:
    def __init__(
        self,
        label,
        text,
        page_no=1,
        bbox=None,
        level=None,
        table_md=None,
        require_doc=False,
    ):
        self.label = label
        self.text = text
        self.level = level
        self.prov = [_Prov(page_no, bbox)]
        self._table_md = table_md
        self._require_doc = require_doc

    def export_to_markdown(self, *args, doc=None, **kwargs):
        if self._require_doc and doc is None and not args:
            raise AssertionError("export_to_markdown called without doc")
        return self._table_md


class _Document:
    def __init__(self, items):
        self._items = items

    def iterate_items(self):
        for item in self._items:
            yield item, 0


def test_blocks_from_docling_document_preserve_page_type_and_bbox():
    document = _Document(
        [
            _Item("title", "Rates Outlook", page_no=1, bbox=[1, 2, 3, 4], level=1),
            _Item("paragraph", "Duration should rally.", page_no=1, bbox=[5, 6, 7, 8]),
            _Item("list_item", "Own the front end", page_no=2),
            _Item("table", "", page_no=2, table_md="| Tenor | Yield |\n| 2y | 3.8 |"),
            _Item("picture", "", page_no=3),
        ]
    )
    document._items[-1].caption_text = "Vol surface"

    blocks = blocks_from_docling_document(document)

    assert [block.block_type for block in blocks] == [
        BlockType.HEADING,
        BlockType.PARAGRAPH,
        BlockType.LIST_ITEM,
        BlockType.TABLE,
        BlockType.FIGURE_REF,
    ]
    assert blocks[0].page == 1
    assert blocks[0].bbox == [1.0, 2.0, 3.0, 4.0]
    assert blocks[2].page == 2
    assert "| Tenor | Yield |" in blocks[3].text
    assert blocks[4].text == "Vol surface"
    assert blocks[4].page == 3


def test_blocks_from_docling_document_returns_empty_without_items():
    assert blocks_from_docling_document(None) == []
    assert blocks_from_docling_document(SimpleNamespace()) == []


def test_table_export_passes_document_as_doc():
    document = _Document(
        [_Item("table", "", page_no=1, table_md="| a | b |\n| 1 | 2 |", require_doc=True)]
    )

    blocks = blocks_from_docling_document(document)

    assert len(blocks) == 1
    assert blocks[0].block_type == BlockType.TABLE
    assert "| a | b |" in blocks[0].text
