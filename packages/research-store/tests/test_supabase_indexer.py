from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from distill_tool.supabase_indexer import (
    EmbeddingCorpus,
    IndexingStats,
    SupabaseDocument,
    extract_full_text,
    index_pending_documents,
)


def test_extract_full_text_returns_trimmed_text() -> None:
    row = {"id": 10, "parsed_data": {"full_text": "  sample text  "}}
    assert extract_full_text(row) == "sample text"


def test_extract_full_text_raises_when_missing() -> None:
    row = {"id": 11, "parsed_data": {"themes": []}}
    with pytest.raises(ValueError, match="missing parsed_data.full_text"):
        extract_full_text(row)


def test_embedding_corpus_upsert_replaces_existing_chunk() -> None:
    corpus = EmbeddingCorpus(
        chunk_ids=np.array(["a", "b"]),
        embeddings=np.array([[1.0, 0.0], [0.5, 0.5]], dtype="float32"),
    )
    corpus.upsert(
        np.array(["b", "c"]),
        np.array([[0.9, 0.1], [0.2, 0.8]], dtype="float32"),
    )

    assert corpus.chunk_ids.tolist() == ["a", "b", "c"]
    assert corpus.embeddings.shape == (3, 2)
    # "b" must be replaced with the incoming vector.
    assert np.allclose(corpus.embeddings[1], np.array([0.9, 0.1], dtype="float32"))


def test_embedding_corpus_upsert_raises_on_dimension_mismatch() -> None:
    corpus = EmbeddingCorpus(
        chunk_ids=np.array(["a"]),
        embeddings=np.array([[1.0, 0.0]], dtype="float32"),
    )
    with pytest.raises(ValueError, match="dimension mismatch"):
        corpus.upsert(
            np.array(["b"]),
            np.array([[0.1, 0.2, 0.3]], dtype="float32"),
        )


def test_index_pending_documents_marks_indexed_and_failed(tmp_path: Path, monkeypatch) -> None:
    class FakeClient:
        def __init__(self):
            self.indexed: list[int] = []
            self.failed: list[int] = []

        def fetch_pending_documents(self, *, limit: int) -> list[SupabaseDocument]:
            assert limit == 5
            return [
                SupabaseDocument(id=101, parsed_data={"full_text": "doc 101 body"}),
                SupabaseDocument(id=202, parsed_data={"full_text": "doc 202 body"}),
            ]

        def claim_document(self, *, doc_id: int, batch_id: int) -> bool:
            assert batch_id > 0
            return True

        def mark_indexed(self, *, doc_id: int, batch_id: int, index_version: str) -> None:
            assert batch_id > 0
            assert index_version == "v-test"
            self.indexed.append(doc_id)

        def mark_failed(self, *, doc_id: int, batch_id: int, error: str) -> None:
            assert batch_id > 0
            assert error
            self.failed.append(doc_id)

    fake_client = FakeClient()

    def _fake_client_factory(**kwargs):
        return fake_client

    def _fake_distill_markdown(**kwargs):
        source_path = kwargs["source_path"]
        npz_path = Path(kwargs["npz_path"])
        if source_path == "supabase:202":
            raise RuntimeError("simulated failure")

        chunk_id = f"{source_path}:chunk-1"
        embeddings = np.array([[0.4, 0.6]], dtype="float32")
        np.savez_compressed(
            npz_path,
            chunk_ids=np.array([chunk_id]),
            embeddings=embeddings,
        )

    monkeypatch.setattr("distill_tool.supabase_indexer.SupabaseRestClient", _fake_client_factory)
    monkeypatch.setattr("distill_tool.supabase_indexer.distill_markdown", _fake_distill_markdown)

    db_path = tmp_path / "chunks.sqlite"
    npz_path = tmp_path / "embeddings.npz"
    stats: IndexingStats = index_pending_documents(
        supabase_url="https://example.supabase.co",
        supabase_key="service-key",
        db_path=db_path,
        npz_path=npz_path,
        poll_limit=5,
        index_version="v-test",
    )

    assert stats == IndexingStats(scanned=2, claimed=2, indexed=1, failed=1)
    assert fake_client.indexed == [101]
    assert fake_client.failed == [202]

    saved = np.load(npz_path)
    assert saved["chunk_ids"].tolist() == ["supabase:101:chunk-1"]
    assert saved["embeddings"].shape == (1, 2)
