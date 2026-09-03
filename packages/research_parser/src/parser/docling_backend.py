"""Docling-backed parser implementation."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

import structlog

from .artifacts import markdown_to_blocks, normalize_markdown
from .backend import BlockType, FigureRecord, ParserBackend, TextBlock, TextParseResult


class DoclingBackend(ParserBackend):
    def __init__(self, *, do_ocr: bool = False):
        self.do_ocr = do_ocr
        self._converter = None
        self._logger = structlog.get_logger()
        self._last_document = None
        self._last_conv_res = None

    def _get_converter(self):
        if self._converter is not None:
            return self._converter

        try:
            module = importlib.import_module("docling.document_converter")
        except Exception as exc:
            raise ImportError(f"Docling is not available: {exc}") from exc

        if not hasattr(module, "DocumentConverter"):
            raise ImportError("Docling DocumentConverter not found")

        # Prefer enabling picture image generation when available.
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.document_converter import PdfFormatOption

            pipeline_options = PdfPipelineOptions()
            pipeline_options.images_scale = 2.0
            pipeline_options.generate_picture_images = True
            pipeline_options.do_ocr = self.do_ocr
            pipeline_options.do_table_structure = True
            if self.do_ocr:
                try:
                    from docling.datamodel.pipeline_options import EasyOcrOptions

                    pipeline_options.ocr_options = EasyOcrOptions(force_full_page_ocr=False)
                except Exception:
                    pass
            try:
                from docling.datamodel.pipeline_options import (
                    TableFormerMode,
                    TableStructureOptions,
                )

                pipeline_options.table_structure_options = TableStructureOptions(
                    mode=TableFormerMode.FAST
                )
            except Exception:
                pass

            self._converter = module.DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
                }
            )
        except Exception:
            self._converter = module.DocumentConverter()
        return self._converter

    def _convert(self, pdf_path: Path):
        converter = self._get_converter()
        if hasattr(converter, "convert"):
            result = converter.convert(str(pdf_path))
        elif hasattr(converter, "convert_document"):
            result = converter.convert_document(str(pdf_path))
        else:
            raise RuntimeError("Docling converter has no known convert method")
        document = getattr(result, "document", result)
        self._last_document = document
        self._last_conv_res = result
        return document

    def _extract_markdown(self, pdf_path: Path) -> str:
        document = self._convert(pdf_path)
        for attr in ("export_to_markdown", "to_markdown"):
            fn = getattr(document, attr, None)
            if callable(fn):
                return fn()

        for attr in ("markdown", "md"):
            value = getattr(document, attr, None)
            if isinstance(value, str):
                return value

        for attr in ("export_to_text", "to_text"):
            fn = getattr(document, attr, None)
            if callable(fn):
                return fn()

        value = getattr(document, "text", None)
        if isinstance(value, str):
            return value

        raise RuntimeError("Docling output does not expose markdown or text")

    def _extract_document(self, pdf_path: Path):
        return self._convert(pdf_path)

    @staticmethod
    def _resolve_value(value):
        if callable(value):
            try:
                return value()
            except Exception:
                return None
        return value

    def parse_text(self, pdf_path: Path) -> TextParseResult:
        markdown = normalize_markdown(self._extract_markdown(pdf_path))
        if not markdown or not markdown.strip():
            raise ValueError("Empty markdown returned")

        blocks = blocks_from_docling_document(self._last_document)
        if not blocks:
            blocks = markdown_to_blocks(markdown)
        if not blocks:
            blocks = [TextBlock(block_type=BlockType.PARAGRAPH, text=markdown.strip())]

        return TextParseResult(
            blocks=blocks,
            raw_output=markdown,
            source_page_count=_source_page_count(self._last_document, self._last_conv_res),
        )

    def extract_figures(self, pdf_path: Path) -> list[FigureRecord]:
        try:
            document = self._last_document
            conv_res = self._last_conv_res
            if document is None or conv_res is None:
                document = self._extract_document(pdf_path)
                conv_res = self._last_conv_res
        except Exception:
            return []

        figures = []
        try:
            from docling_core.types.doc import PictureItem
        except Exception:
            PictureItem = None

        temp_dir = Path(tempfile.mkdtemp(prefix="docling_figures_"))
        picture_counter = 0
        for item, _level in document.iterate_items() if hasattr(document, "iterate_items") else []:
            if PictureItem is not None and not isinstance(item, PictureItem):
                continue
            picture_counter += 1
            image_path = None
            caption = self._resolve_value(getattr(item, "caption_text", None))
            if caption is None:
                caption = self._resolve_value(getattr(item, "caption", None))
            if caption is None:
                caption = self._resolve_value(getattr(item, "title", None))

            page = self._resolve_value(getattr(item, "page", None))
            if page is None:
                page = self._resolve_value(getattr(item, "page_num", None))
            if page is None:
                page = 0

            bbox = self._resolve_value(getattr(item, "bbox", None))
            if bbox is None:
                bbox = self._resolve_value(getattr(item, "bounding_box", None))

            # Try to resolve an image path or bytes
            raw_image = None
            if hasattr(item, "image_path"):
                image_path = self._resolve_value(getattr(item, "image_path"))
                if image_path:
                    image_path = str(image_path)
            if image_path is None:
                for attr in ("image", "pil_image", "data", "bytes", "image_bytes"):
                    if hasattr(item, attr):
                        raw_image = self._resolve_value(getattr(item, attr))
                        break
            if image_path is None and raw_image is not None:
                out_path = temp_dir / f"figure_{picture_counter:03d}.png"
                try:
                    if hasattr(raw_image, "save"):
                        raw_image.save(out_path)
                        image_path = str(out_path)
                    elif isinstance(raw_image, (bytes, bytearray)):
                        out_path.write_bytes(raw_image)
                        image_path = str(out_path)
                except Exception:
                    image_path = None
            if image_path is None and hasattr(item, "get_image") and conv_res is not None:
                out_path = temp_dir / f"figure_{picture_counter:03d}.png"
                try:
                    image_obj = item.get_image(conv_res.document)
                    image_obj.save(out_path, "PNG")
                    image_path = str(out_path)
                except Exception:
                    image_path = None
            if image_path is None:
                image_attrs = sorted(
                    [
                        a
                        for a in dir(item)
                        if "image" in a.lower() or "path" in a.lower()
                    ]
                )
                self._logger.info(
                    "Docling figure missing image data",
                    index=picture_counter,
                    available_attrs=image_attrs,
                )

            figures.append(
                FigureRecord(
                    figure_id=f"fig_{picture_counter:03d}",
                    page=int(page) if page is not None else 0,
                    section_path=[],
                    bbox=bbox,
                    caption_text=caption,
                    image_path=image_path,
                    content_hash=None,
                )
            )
        if picture_counter == 0:
            figure_attrs = sorted(
                [a for a in dir(document) if "fig" in a.lower() or "image" in a.lower()]
            )
            self._logger.info(
                "Docling figures not found",
                available_attrs=figure_attrs,
            )
        return figures


def _source_page_count(document, conv_res) -> int | None:
    for obj in (conv_res, document):
        if obj is None:
            continue
        pages = getattr(obj, "pages", None)
        if pages is None:
            pass
        else:
            try:
                count = len(pages)
            except TypeError:
                count = 0
            if count > 0:
                return count
        for attr in ("page_count", "num_pages"):
            value = getattr(obj, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if isinstance(value, int) and value > 0:
                return value
    return None


_HEADING_LABELS = {
    "title",
    "section_header",
    "section-header",
    "heading",
    "subtitle",
    "document_index",
}
_LIST_LABELS = {"list_item", "list-item"}
_TABLE_LABELS = {"table"}
_PICTURE_LABELS = {"picture", "image", "figure", "chart"}
_CAPTION_LABELS = {"caption", "footnote"}


def blocks_from_docling_document(document) -> list[TextBlock]:
    """Build page-aware blocks from a Docling document, if item iteration is available."""
    if document is None:
        return []

    blocks: list[TextBlock] = []
    for item, level in _iter_docling_items(document):
        block = _block_from_docling_item(item, level, document)
        if block is not None:
            blocks.append(block)
    return blocks


def _iter_docling_items(document):
    iterate = getattr(document, "iterate_items", None)
    if not callable(iterate):
        return

    try:
        entries = iterate()
    except TypeError:
        try:
            entries = iterate(traverse_pictures=True)
        except Exception:
            return
    except Exception:
        return

    for entry in entries:
        if isinstance(entry, tuple) and entry:
            item = entry[0]
            nested_level = entry[1] if len(entry) > 1 else 0
            yield item, nested_level
        else:
            yield entry, 0


def _block_from_docling_item(item, level, document) -> TextBlock | None:
    label = _normalize_label(getattr(item, "label", None) or type(item).__name__)
    page, bbox = _item_page_bbox(item)
    text = _item_text(item, document, label)
    if not text:
        if label not in _PICTURE_LABELS:
            return None
        text = ""

    if label in _HEADING_LABELS:
        heading_level = getattr(item, "level", None)
        if not isinstance(heading_level, int) or heading_level <= 0:
            heading_level = 1 if label == "title" else max(int(level or 0) + 1, 1)
        return TextBlock(
            block_type=BlockType.HEADING,
            text=text,
            page=page,
            level=min(heading_level, 6),
            bbox=bbox,
        )
    if label in _LIST_LABELS:
        return TextBlock(
            block_type=BlockType.LIST_ITEM,
            text=text,
            page=page,
            bbox=bbox,
        )
    if label in _TABLE_LABELS:
        return TextBlock(
            block_type=BlockType.TABLE,
            text=text,
            page=page,
            bbox=bbox,
        )
    if label in _PICTURE_LABELS:
        return TextBlock(
            block_type=BlockType.FIGURE_REF,
            text=text or "Figure",
            page=page,
            bbox=bbox,
        )
    if label in _CAPTION_LABELS:
        return TextBlock(
            block_type=BlockType.CAPTION,
            text=text,
            page=page,
            bbox=bbox,
        )
    if not text:
        return None
    return TextBlock(
        block_type=BlockType.PARAGRAPH,
        text=text,
        page=page,
        bbox=bbox,
    )


def _normalize_label(label) -> str:
    value = getattr(label, "value", None)
    text = value if isinstance(value, str) else str(label or "")
    text = text.strip().lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.replace(" ", "_")


def _item_page_bbox(item) -> tuple[int | None, list[float] | None]:
    prov = getattr(item, "prov", None) or []
    first = prov[0] if prov else item
    page = getattr(first, "page_no", None)
    if page is None:
        page = getattr(first, "page", None)
    if page is None:
        page = getattr(item, "page_no", None)
    bbox = getattr(first, "bbox", None)
    if bbox is None:
        bbox = getattr(item, "bbox", None)
    return _coerce_page(page), _coerce_bbox(bbox)


def _coerce_page(page) -> int | None:
    try:
        value = int(page)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _coerce_bbox(bbox) -> list[float] | None:
    if bbox is None:
        return None
    if isinstance(bbox, (list, tuple)):
        try:
            return [float(value) for value in bbox]
        except (TypeError, ValueError):
            return None
    coords = []
    for attr in ("l", "t", "r", "b"):
        value = getattr(bbox, attr, None)
        if value is None:
            coords = []
            break
        coords.append(value)
    if len(coords) == 4:
        try:
            return [float(value) for value in coords]
        except (TypeError, ValueError):
            return None
    for attr in ("as_tuple", "to_tuple", "tolist", "to_list"):
        fn = getattr(bbox, attr, None)
        if callable(fn):
            try:
                return _coerce_bbox(fn())
            except Exception:
                continue
    return None


def _item_text(item, document, label: str) -> str:
    if label in _TABLE_LABELS:
        table_text = _table_text(item, document)
        if table_text:
            return table_text
    if label in _PICTURE_LABELS:
        caption = _caption_text(item, document)
        if caption:
            return caption

    for attr in ("text", "orig"):
        value = getattr(item, attr, None)
        if callable(value):
            try:
                value = value()
            except TypeError:
                try:
                    value = value(document)
                except Exception:
                    value = None
            except Exception:
                value = None
        if isinstance(value, str) and value.strip():
            return value.strip()

    get_text = getattr(item, "get_text", None)
    if callable(get_text):
        try:
            value = get_text()
        except TypeError:
            try:
                value = get_text(document)
            except Exception:
                value = None
        except Exception:
            value = None
        if isinstance(value, str) and value.strip():
            return value.strip()

    return _caption_text(item, document)


def _caption_text(item, document) -> str:
    caption = getattr(item, "caption_text", None)
    if callable(caption):
        try:
            caption = caption(document)
        except TypeError:
            try:
                caption = caption()
            except Exception:
                caption = None
        except Exception:
            caption = None
    if isinstance(caption, str) and caption.strip():
        return caption.strip()
    caption = getattr(item, "caption", None)
    if isinstance(caption, str) and caption.strip():
        return caption.strip()
    return ""


def _table_text(item, document) -> str:
    for attr in ("export_to_markdown", "to_markdown"):
        fn = getattr(item, attr, None)
        if not callable(fn):
            continue
        for args in ((), (document,), (),):
            try:
                value = fn(*args) if args else fn()
            except TypeError:
                continue
            except Exception:
                value = None
            if isinstance(value, str) and value.strip():
                return value.strip()

    for attr in ("export_to_dataframe", "to_dataframe"):
        fn = getattr(item, attr, None)
        if not callable(fn):
            continue
        frame = None
        for args in ((document,), ()):
            try:
                frame = fn(*args) if args else fn()
                break
            except TypeError:
                continue
            except Exception:
                frame = None
        to_markdown = getattr(frame, "to_markdown", None)
        if callable(to_markdown):
            try:
                value = to_markdown(index=False)
            except TypeError:
                try:
                    value = to_markdown()
                except Exception:
                    value = None
            except Exception:
                value = None
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""

