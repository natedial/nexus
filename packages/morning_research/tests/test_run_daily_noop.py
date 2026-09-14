"""Orchestration no-op / dry-run path tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from morning_research.config import Settings
from morning_research.drive_pull import DrivePullResult
from morning_research.models import CandidateDoc, RunState
from morning_research.state import load_state, save_state
from morning_research import run_daily as run_daily_mod


def test_run_daily_noop_updates_state(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    work_dir = tmp_path / "work"
    settings = Settings(
        google_credentials_path=tmp_path / "creds.json",
        google_drive_folder_id="folder",
        notion_token="token",
        notion_database_id="db",
        morning_research_state_path=state_path,
        morning_research_work_dir=work_dir,
        dry_run=True,
    )

    class FakePuller:
        def __init__(self, *args, **kwargs):
            pass

        def pull(self, **kwargs):
            return DrivePullResult(candidates=[], skipped_duplicates=[], total_listed=0)

    monkeypatch.setattr(run_daily_mod, "DrivePuller", FakePuller)

    code = run_daily_mod.run_daily(settings)
    assert code == 0
    assert state_path.exists()
    text = state_path.read_text(encoding="utf-8")
    assert "last_successful_run" in text
    assert datetime.now(timezone.utc).strftime("%Y-%m-%d") in text


def test_dry_run_with_candidates_does_not_touch_state(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "state.json"
    work_dir = tmp_path / "work"
    prior = RunState(last_successful_run="2026-07-20T12:00:00Z")
    save_state(state_path, prior)

    now = datetime(2026, 7, 25, tzinfo=timezone.utc)
    candidate = CandidateDoc(
        file_id="abc",
        name="doc.pdf",
        mime_type="application/pdf",
        modified_time=now,
        created_time=now,
        size_bytes=10_000,
        content_hash="sha256:abc",
        local_path=tmp_path / "doc.pdf",
    )

    class FakePuller:
        def __init__(self, *args, **kwargs):
            pass

        def pull(self, **kwargs):
            return DrivePullResult(
                candidates=[candidate], skipped_duplicates=[], total_listed=1
            )

    class FakeNotion:
        def __init__(self, *args, **kwargs):
            pass

        def fetch_prior_notes_to_markdown(self, *args, **kwargs):
            return []

    monkeypatch.setattr(run_daily_mod, "DrivePuller", FakePuller)
    monkeypatch.setattr(run_daily_mod, "NotionClient", FakeNotion)

    settings = Settings(
        google_credentials_path=tmp_path / "creds.json",
        google_drive_folder_id="folder",
        notion_token="token",
        notion_database_id="db",
        morning_research_state_path=state_path,
        morning_research_work_dir=work_dir,
        dry_run=True,
    )
    assert run_daily_mod.run_daily(settings) == 0
    loaded = load_state(state_path)
    assert loaded.last_successful_run == "2026-07-20T12:00:00Z"
    assert loaded.processed_documents == {}
