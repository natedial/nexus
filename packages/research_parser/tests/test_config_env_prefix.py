"""Parser settings read RESEARCH_PARSER_* names, with legacy names as fallback."""

import pytest

from src.config import get_settings

REQUIRED_SHARED = {
    "GOOGLE_DRIVE_FOLDER_ID": "folder-id",
    "NEXUS_DATABASE_URL": "postgresql://nexus:nexus@localhost:5432/nexus",
}


@pytest.fixture
def shared_env(monkeypatch):
    for name in (
        "RESEARCH_PARSER_STATE_DB_PATH",
        "STATE_DB_PATH",
        "RESEARCH_PARSER_CATCHUP_DAYS",
        "CATCHUP_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)
    for name, value in REQUIRED_SHARED.items():
        monkeypatch.setenv(name, value)


def test_shared_vars_stay_unprefixed(shared_env):
    settings = get_settings()

    assert settings.database_url == "postgresql://nexus:nexus@localhost:5432/nexus"
    assert settings.google_drive_folder_id == "folder-id"


def test_prefixed_name_is_used(shared_env, monkeypatch):
    monkeypatch.setenv("RESEARCH_PARSER_CATCHUP_DAYS", "7")

    assert get_settings().catchup_days == 7


def test_legacy_name_still_works(shared_env, monkeypatch):
    monkeypatch.setenv("CATCHUP_DAYS", "4")

    assert get_settings().catchup_days == 4


def test_prefixed_name_wins_over_legacy(shared_env, monkeypatch):
    monkeypatch.setenv("CATCHUP_DAYS", "4")
    monkeypatch.setenv("RESEARCH_PARSER_CATCHUP_DAYS", "9")

    assert get_settings().catchup_days == 9
