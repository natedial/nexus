from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from distill_tool.chunking import (
    FALLBACK_MIN_CHARS,
    FALLBACK_TARGET_CHARS,
    PAGE_MARKER_REGEX,
    Page,
    apply_page_overlap,
    has_structural_headings,
    split_fallback_chunks,
    split_pages,
)
from distill_tool.embeddings import EmbeddingConfig, EmbeddingModel
from distill_tool.keywords import extract_keywords, load_dictionary
from distill_tool.storage import ChunkRecord, RunInfo, init_db, save_embeddings, store_chunks, store_run


@dataclass(frozen=True)
class DistillResult:
    run_info: RunInfo
    chunks: list[ChunkRecord]
    chunk_ids: list[str]
    embeddings_path: Path
    db_path: Path


def distill_file(
    file_path: str | Path,
    db_path: str | Path,
    npz_path: str | Path,
    dictionary_path: str | Path | None = None,
    model_name: str = "all-MiniLM-L6-v2",
    max_keywords: int = 20,
    overlap_paragraphs: int = 1,
    page_marker_regex: str | None = None,
    fallback_target_chars: int = FALLBACK_TARGET_CHARS,
    fallback_min_chars: int = FALLBACK_MIN_CHARS,
    batch_size: int = 32,
    skip_embeddings: bool = False,
) -> DistillResult:
    file_path = Path(file_path)
    markdown = file_path.read_text(encoding="utf-8")
    return distill_markdown(
        markdown=markdown,
        source_path=str(file_path),
        db_path=db_path,
        npz_path=npz_path,
        dictionary_path=dictionary_path,
        model_name=model_name,
        max_keywords=max_keywords,
        overlap_paragraphs=overlap_paragraphs,
        page_marker_regex=page_marker_regex,
        fallback_target_chars=fallback_target_chars,
        fallback_min_chars=fallback_min_chars,
        batch_size=batch_size,
        skip_embeddings=skip_embeddings,
    )


def distill_markdown(
    markdown: str,
    db_path: str | Path,
    npz_path: str | Path,
    dictionary_path: str | Path | None = None,
    model_name: str = "all-MiniLM-L6-v2",
    max_keywords: int = 20,
    overlap_paragraphs: int = 1,
    page_marker_regex: str | None = None,
    fallback_target_chars: int = FALLBACK_TARGET_CHARS,
    fallback_min_chars: int = FALLBACK_MIN_CHARS,
    batch_size: int = 32,
    source_path: str | None = None,
    skip_embeddings: bool = False,
    embedding_model: EmbeddingModel | None = None,
) -> DistillResult:
    marker_re = None
    if page_marker_regex:
        import re

        marker_re = re.compile(page_marker_regex, re.MULTILINE)

    pages = (
        split_pages(markdown, marker_re)
        if marker_re
        else split_pages(markdown)
    )
    if not marker_re and len(pages) == 1:
        pages = split_fallback_chunks(
            pages[0].text,
            target_chars=fallback_target_chars,
            min_chars=fallback_min_chars,
        )
    else:
        refined_pages: list[Page] = []
        for page in pages:
            if len(page.text) <= fallback_target_chars and not has_structural_headings(page.text):
                refined_pages.append(page)
                continue

            split_page_chunks = split_fallback_chunks(
                page.text,
                target_chars=fallback_target_chars,
                min_chars=fallback_min_chars,
            )
            if len(split_page_chunks) <= 1:
                refined_pages.append(page)
                continue

            refined_pages.extend(Page(number=page.number, text=chunk.text) for chunk in split_page_chunks)
        pages = refined_pages
    pages = apply_page_overlap(pages, overlap_paragraphs=overlap_paragraphs)

    dictionary = load_dictionary(dictionary_path)

    run_id = str(uuid.uuid4())
    chunks, texts = _build_chunks(
        pages=pages,
        dictionary=dictionary,
        max_keywords=max_keywords,
        source_path=source_path,
        run_id=run_id,
    )

    if skip_embeddings:
        embeddings = np.empty((len(texts), 0), dtype="float32")
        embedding_dim = 0
    else:
        model = embedding_model
        if model is None:
            embedding_config = EmbeddingConfig(model_name=model_name, batch_size=batch_size)
            model = EmbeddingModel(embedding_config)
        embeddings = model.embed(texts)
        embedding_dim = embeddings.shape[1] if embeddings.size else 0

    run_info = RunInfo(
        run_id=run_id,
        model_name=model_name,
        embedding_dim=embedding_dim,
        source=source_path or "inline",
        dictionary_path=str(dictionary_path) if dictionary_path else None,
        params={
            "max_keywords": max_keywords,
            "overlap_paragraphs": overlap_paragraphs,
            "page_marker_regex": page_marker_regex or PAGE_MARKER_REGEX,
            "fallback_target_chars": fallback_target_chars,
            "fallback_min_chars": fallback_min_chars,
            "batch_size": batch_size,
            "skip_embeddings": skip_embeddings,
        },
    )

    chunk_ids = [chunk.chunk_id for chunk in chunks]
    db_path = Path(db_path)
    npz_path = Path(npz_path)

    init_db(db_path)
    store_run(db_path, run_info)
    store_chunks(db_path, chunks)
    save_embeddings(npz_path, chunk_ids, embeddings)

    return DistillResult(
        run_info=run_info,
        chunks=chunks,
        chunk_ids=chunk_ids,
        embeddings_path=npz_path,
        db_path=db_path,
    )


def _build_chunks(
    pages: list[Page],
    dictionary: list[str],
    max_keywords: int,
    source_path: str | None,
    run_id: str,
) -> tuple[list[ChunkRecord], list[str]]:
    chunks: list[ChunkRecord] = []
    texts: list[str] = []

    for idx, page in enumerate(pages):
        keywords = extract_keywords(page.text, dictionary=dictionary, max_keywords=max_keywords)
        keywords_json = json.dumps([keyword.__dict__ for keyword in keywords])
        text_hash = _hash_text(page.text)
        chunk_id = _hash_text(f"{source_path}|{page.number}|{idx}|{text_hash}")
        chunks.append(
            ChunkRecord(
                chunk_id=chunk_id,
                run_id=run_id,
                source_path=source_path,
                page_number=page.number,
                chunk_index=idx,
                text=page.text,
                keywords_json=keywords_json,
                text_hash=text_hash,
            )
        )
        texts.append(page.text)

    return chunks, texts


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
