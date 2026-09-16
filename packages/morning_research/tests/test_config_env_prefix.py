"""Settings read MORNING_RESEARCH_* names, with legacy names as fallback."""

import pytest

from morning_research.config import get_settings

PACKAGE_OWNED = ("MORNING_RESEARCH_DRY_RUN", "DRY_RUN")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in PACKAGE_OWNED:
        monkeypatch.delenv(name, raising=False)


def test_prefixed_name_is_used(monkeypatch):
    monkeypatch.setenv("MORNING_RESEARCH_DRY_RUN", "true")

    assert get_settings().dry_run is True


def test_legacy_name_still_works(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")

    assert get_settings().dry_run is True


def test_prefixed_name_wins_over_legacy(monkeypatch):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("MORNING_RESEARCH_DRY_RUN", "false")

    assert get_settings().dry_run is False


def test_shared_vars_stay_unprefixed(monkeypatch):
    monkeypatch.setenv("NOTION_TOKEN", "secret-token")
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-key")

    settings = get_settings()

    assert settings.notion_token == "secret-token"
    assert settings.supabase_enabled is True
