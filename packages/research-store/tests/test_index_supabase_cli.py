from __future__ import annotations

import os

from distill_tool.index_supabase_cli import main
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
        return IndexingStats(scanned=1, claimed=1, indexed=1, failed=0)

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
    assert "Supabase indexing complete (scanned=1, claimed=1, indexed=1, failed=0)" in out
