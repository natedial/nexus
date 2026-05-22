"""Docling-backed parser implementation."""

from __future__ import annotations

import importlib
import tempfile
from pathlib import Path

import structlog

from .artifacts import markdown_to_blocks, normalize_markdown
from .backend import BlockType, FigureRecord, ParserBackend, TextBlock, TextParseResult


class DoclingBackend(ParserBackend):
    def __init__(self):
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
            raise ImportError("Docling is not installed") from exc

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
            pipeline_options.do_ocr = False
            pipeline_options.do_table_structure = False

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

        blocks = markdown_to_blocks(markdown)
        if not blocks:
            blocks = [TextBlock(block_type=BlockType.PARAGRAPH, text=markdown.strip())]

        return TextParseResult(blocks=blocks, raw_output=markdown)

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
