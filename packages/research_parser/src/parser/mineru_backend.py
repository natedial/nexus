"""MinerU CLI-backed parser implementation."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from .artifacts import markdown_to_blocks, normalize_markdown
from .backend import BlockType, FigureRecord, ParserBackend, TextBlock, TextParseResult


class MinerUBackend(ParserBackend):
    def __init__(
        self,
        binary_path: Path,
        cli_backend: str = "pipeline",
        timeout_seconds: int = 300,
    ):
        self._binary_path = Path(binary_path)
        self._cli_backend = cli_backend
        self._timeout_seconds = timeout_seconds
        self._last_pdf_path: Path | None = None
        self._last_output_dir: Path | None = None

    def _run_cli(self, pdf_path: Path) -> Path:
        if self._last_pdf_path == pdf_path and self._last_output_dir is not None:
            return self._last_output_dir

        if not self._binary_path.exists():
            raise FileNotFoundError(f"MinerU binary not found: {self._binary_path}")

        output_dir = Path(tempfile.mkdtemp(prefix="mineru_output_"))
        command = [
            str(self._binary_path),
            "-p",
            str(pdf_path),
            "-o",
            str(output_dir),
            "-b",
            self._cli_backend,
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"MinerU timed out after {self._timeout_seconds}s"
            ) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if len(detail) > 500:
                detail = f"{detail[:500]}..."
            raise RuntimeError(f"MinerU failed with exit code {result.returncode}: {detail}")

        self._last_pdf_path = pdf_path
        self._last_output_dir = output_dir
        return output_dir

    @staticmethod
    def _find_markdown_path(output_dir: Path, pdf_path: Path) -> Path:
        stem = pdf_path.stem
        candidates = list(output_dir.rglob("*.md"))
        if not candidates:
            raise FileNotFoundError("MinerU produced no markdown output")

        preferred_names = [
            f"{stem}.md",
            "output.md",
            "document.md",
        ]
        for name in preferred_names:
            for candidate in candidates:
                if candidate.name == name:
                    return candidate

        for candidate in candidates:
            if candidate.stem == stem:
                return candidate

        return sorted(candidates)[0]

    @staticmethod
    def _find_content_list_path(output_dir: Path, pdf_path: Path) -> Path | None:
        stem = pdf_path.stem
        candidates = list(output_dir.rglob("*content_list*.json"))
        if not candidates:
            return None

        preferred_names = [
            f"{stem}_content_list.json",
            "content_list.json",
        ]
        for name in preferred_names:
            for candidate in candidates:
                if candidate.name == name:
                    return candidate

        return sorted(candidates)[0]

    @staticmethod
    def _load_markdown(markdown_path: Path) -> str:
        markdown = normalize_markdown(markdown_path.read_text(encoding="utf-8", errors="ignore"))
        if not markdown.strip():
            raise ValueError("MinerU returned empty markdown")
        return markdown

    @staticmethod
    def _coerce_page(raw_page) -> int:
        if raw_page is None:
            return 0
        try:
            return int(raw_page)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _coerce_bbox(raw_bbox) -> list[float] | None:
        if isinstance(raw_bbox, list):
            return raw_bbox
        if isinstance(raw_bbox, tuple):
            return list(raw_bbox)
        return None

    @staticmethod
    def _figure_path(base_dir: Path, raw_path: str | None) -> str | None:
        if not raw_path:
            return None
        path = Path(raw_path)
        if path.is_absolute():
            return str(path)
        return str((base_dir / path).resolve())

    @classmethod
    def _load_figures(cls, output_dir: Path, pdf_path: Path) -> list[FigureRecord]:
        content_list_path = cls._find_content_list_path(output_dir, pdf_path)
        if content_list_path is None:
            return []

        payload = json.loads(content_list_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            items = payload.get("content_list") or payload.get("items") or []
        elif isinstance(payload, list):
            items = payload
        else:
            items = []

        figures: list[FigureRecord] = []
        figure_index = 0
        base_dir = content_list_path.parent
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or item.get("category") or "").lower()
            if item_type not in {"image", "figure", "table"}:
                continue
            figure_index += 1
            raw_path = (
                item.get("img_path")
                or item.get("image_path")
                or item.get("path")
                or item.get("image")
            )
            caption = (
                item.get("caption")
                or item.get("text")
                or item.get("img_caption")
                or item.get("table_caption")
            )
            section_path = item.get("section_path") or []
            if not isinstance(section_path, list):
                section_path = []

            figures.append(
                FigureRecord(
                    figure_id=f"fig_{figure_index:03d}",
                    page=cls._coerce_page(
                        item.get("page_idx") or item.get("page") or item.get("page_no")
                    ),
                    section_path=section_path,
                    bbox=cls._coerce_bbox(item.get("bbox")),
                    caption_text=caption if isinstance(caption, str) else None,
                    image_path=cls._figure_path(base_dir, raw_path),
                    content_hash=None,
                )
            )
        return figures

    def parse_text(self, pdf_path: Path) -> TextParseResult:
        output_dir = self._run_cli(pdf_path)
        markdown_path = self._find_markdown_path(output_dir, pdf_path)
        markdown = self._load_markdown(markdown_path)
        blocks = markdown_to_blocks(markdown)
        if not blocks:
            blocks = [TextBlock(block_type=BlockType.PARAGRAPH, text=markdown.strip())]
        return TextParseResult(blocks=blocks, raw_output=markdown)

    def extract_figures(self, pdf_path: Path) -> list[FigureRecord]:
        output_dir = self._run_cli(pdf_path)
        return self._load_figures(output_dir, pdf_path)
