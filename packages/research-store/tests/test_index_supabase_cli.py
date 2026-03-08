from __future__ import annotations

import os
from argparse import Namespace
from pathlib import Path

from distill_tool.index_supabase_cli import main, run_indexing_worker
from distill_tool.supabase_indexer import IndexingStats


def test_main_loads_env_file_and_uses_values(monkeypatch, capsys) -> None:
    loaded: list[str] = []

    def _fake_load_dotenv(*, dotenv_path: str) -> None:
        loaded.append(dotenv_path)
        os.environ["SUPABASE_URL"] = "https://from-env-file.supabase.co"
        os.environ["SUPABASE_KEY"] = "from-env-file-key"

    captured_kwargs = {}

    def _fake_index_pending_documents(**kwargs):
        captured_kwargs.update(kwargs)
        return IndexingStats(scanned=1, claimed=1, indexed=1, failed=0, reclaimed=0)

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    monkeypatch.setattr("distill_tool.index_supabase_cli.load_dotenv", _fake_load_dotenv)
    monkeypatch.setattr(
        "distill_tool.index_supabase_cli.index_pending_documents",
        _fake_index_pending_documents,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "distill-index-supabase",
            "--env-file",
            "custom.env",
            "--poll-limit",
            "3",
        ],
    )

    main()
    out = capsys.readouterr().out

    assert loaded == ["custom.env"]
    assert captured_kwargs["supabase_url"] == "https://from-env-file.supabase.co"
    assert captured_kwargs["supabase_key"] == "from-env-file-key"
    assert captured_kwargs["poll_limit"] == 3
    assert "Supabase indexing complete (scanned=1, claimed=1, indexed=1, failed=0, reclaimed=0)" in out


def test_run_indexing_worker_continuous_mode_aggregates_cycles_and_sleeps() -> None:
    args = Namespace(
        supabase_url="https://example.supabase.co",
        supabase_key="service-key",
        db_path=Path("chunks.sqlite"),
        npz_path=Path("embeddings.npz"),
        dictionary=None,
        model="all-MiniLM-L6-v2",
        max_keywords=20,
        overlap_paragraphs=1,
        page_marker_regex=None,
        fallback_target_chars=2000,
        fallback_min_chars=700,
        batch_size=32,
        no_embeddings=False,
        poll_limit=5,
        stale_processing_seconds=900.0,
        index_version="v1",
        table="parsed_research",
        schema="public",
        continuous=True,
        poll_interval_seconds=7.0,
        error_backoff_seconds=11.0,
        max_cycles=2,
    )

    calls: list[dict[str, object]] = []
    sleeps: list[float] = []
    results = [
        IndexingStats(scanned=2, claimed=2, indexed=2, failed=0, reclaimed=1),
        IndexingStats(scanned=0, claimed=0, indexed=0, failed=0, reclaimed=0),
    ]

    def _fake_index_once(**kwargs):
        calls.append(kwargs)
        return results[len(calls) - 1]

    total = run_indexing_worker(
        args,
        index_once=_fake_index_once,
        sleep_fn=sleeps.append,
    )

    assert len(calls) == 2
    assert calls[0]["stale_processing_seconds"] == 900.0
    assert sleeps == [7.0]
    assert total == IndexingStats(scanned=2, claimed=2, indexed=2, failed=0, reclaimed=1)


def test_run_indexing_worker_continuous_mode_retries_after_errors() -> None:
    args = Namespace(
        supabase_url="https://example.supabase.co",
        supabase_key="service-key",
        db_path=Path("chunks.sqlite"),
        npz_path=Path("embeddings.npz"),
        dictionary=None,
        model="all-MiniLM-L6-v2",
        max_keywords=20,
        overlap_paragraphs=1,
        page_marker_regex=None,
        fallback_target_chars=2000,
        fallback_min_chars=700,
        batch_size=32,
        no_embeddings=False,
        poll_limit=5,
        stale_processing_seconds=900.0,
        index_version="v1",
        table="parsed_research",
        schema="public",
        continuous=True,
        poll_interval_seconds=7.0,
        error_backoff_seconds=11.0,
        max_cycles=2,
    )

    sleeps: list[float] = []
    calls = {"count": 0}

    def _fake_index_once(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary failure")
        return IndexingStats(scanned=1, claimed=1, indexed=1, failed=0, reclaimed=0)

    total = run_indexing_worker(
        args,
        index_once=_fake_index_once,
        sleep_fn=sleeps.append,
    )

    assert calls["count"] == 2
    assert sleeps == [11.0]
    assert total == IndexingStats(scanned=1, claimed=1, indexed=1, failed=0, reclaimed=0)
