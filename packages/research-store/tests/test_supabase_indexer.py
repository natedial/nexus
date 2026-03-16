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
    distilled: list[tuple[str, str | None]] = []

    class FakeClient:
        def __init__(self):
            self.indexed: list[int] = []
            self.failed: list[int] = []
            self.reclaimed: list[int] = []

        def fetch_stale_processing_documents(
            self, *, limit: int, stale_before_batch_id: int
        ) -> list[SupabaseDocument]:
            assert limit == 5
            assert stale_before_batch_id > 0
            return [
                SupabaseDocument(
                    id=99,
                    source_date="2026-03-08",
                    parsed_data={"full_text": "doc 99 body"},
                )
            ]

        def fetch_pending_documents(self, *, limit: int) -> list[SupabaseDocument]:
            assert limit == 4
            return [
                SupabaseDocument(
                    id=101,
                    source_date="2026-03-07",
                    parsed_data={"full_text": "doc 101 body"},
                ),
                SupabaseDocument(
                    id=202,
                    source_date=None,
                    parsed_data={"full_text": "doc 202 body"},
                ),
            ]

        def reclaim_document(self, *, doc_id: int, batch_id: int, stale_before_batch_id: int) -> bool:
            assert batch_id > 0
            assert stale_before_batch_id > 0
            self.reclaimed.append(doc_id)
            return True

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
        distilled.append((source_path, kwargs.get("source_date")))
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
        stale_processing_seconds=3600,
        index_version="v-test",
    )

    assert stats == IndexingStats(scanned=3, claimed=3, indexed=2, failed=1, reclaimed=1)
    assert fake_client.reclaimed == [99]
    assert fake_client.indexed == [99, 101]
    assert fake_client.failed == [202]
    assert distilled == [
        ("supabase:99", "2026-03-08"),
        ("supabase:101", "2026-03-07"),
        ("supabase:202", None),
    ]

    saved = np.load(npz_path)
    assert saved["chunk_ids"].tolist() == ["supabase:99:chunk-1", "supabase:101:chunk-1"]
    assert saved["embeddings"].shape == (2, 2)


def test_index_pending_documents_skips_stale_reclaim_when_disabled(tmp_path: Path, monkeypatch) -> None:
    class FakeClient:
        def fetch_stale_processing_documents(self, *, limit: int, stale_before_batch_id: int) -> list[SupabaseDocument]:
            raise AssertionError("stale reclaim should be disabled")

        def fetch_pending_documents(self, *, limit: int) -> list[SupabaseDocument]:
            assert limit == 1
            return []

    monkeypatch.setattr("distill_tool.supabase_indexer.SupabaseRestClient", lambda **kwargs: FakeClient())

    stats = index_pending_documents(
        supabase_url="https://example.supabase.co",
        supabase_key="service-key",
        db_path=tmp_path / "chunks.sqlite",
        npz_path=tmp_path / "embeddings.npz",
        poll_limit=1,
        stale_processing_seconds=0,
    )

    assert stats == IndexingStats(scanned=0, claimed=0, indexed=0, failed=0, reclaimed=0)
