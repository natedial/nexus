from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from research_relay.auth import OAuth2Auth, build_auth
from research_relay.exceptions import ConfigError
from research_relay.oauth import (
    GMAIL_IMAP_SCOPE,
    OAuthTokenStore,
    authorization_url,
    load_client_config,
    pkce_challenge,
    xoauth2_payload,
)


class DummyImap:
    def __init__(self) -> None:
        self.logged_in = None
        self.auth = None

    def login(self, user: str, password: str) -> None:
        self.logged_in = (user, password)

    def authenticate(self, mechanism: str, callback) -> None:
        self.auth = (mechanism, callback(b""))


def test_xoauth2_payload_format() -> None:
    payload = xoauth2_payload("user@gmail.com", "ya29.token")
    assert payload == b"user=user@gmail.com\x01auth=Bearer ya29.token\x01\x01"


def test_oauth_imap_uses_xoauth2_not_password_login() -> None:
    auth = OAuth2Auth("user@gmail.com", token_provider=lambda: "ya29.token")
    imap = DummyImap()
    auth.authenticate_imap(imap)
    assert imap.logged_in is None
    assert imap.auth is not None
    assert imap.auth[0] == "XOAUTH2"
    assert b"ya29.token" in imap.auth[1]
    assert b"user=user@gmail.com" in imap.auth[1]


def test_factory_builds_oauth_from_access_token() -> None:
    auth = build_auth("oauth2", username="u@gmail.com", access_token="tok")
    assert isinstance(auth, OAuth2Auth)


def test_factory_oauth_requires_paths_without_token() -> None:
    with pytest.raises(ConfigError):
        build_auth("oauth2", username="u@gmail.com")


def test_load_desktop_client_config(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text(
        """
        {
          "installed": {
            "client_id": "abc.apps.googleusercontent.com",
            "client_secret": "secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"]
          }
        }
        """,
        encoding="utf-8",
    )
    client = load_client_config(path)
    assert client.client_id == "abc.apps.googleusercontent.com"
    assert client.client_secret == "secret"
    assert client.token_uri == "https://oauth2.googleapis.com/token"


def test_reject_web_client_json(tmp_path: Path) -> None:
    path = tmp_path / "client.json"
    path.write_text('{"web": {"client_id": "x", "client_secret": "y"}}', encoding="utf-8")
    with pytest.raises(ConfigError, match="Desktop"):
        load_client_config(path)


def test_token_store_returns_unexpired_access_token(tmp_path: Path) -> None:
    token_path = tmp_path / "token.json"
    expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    token_path.write_text(
        f'{{"access_token": "live-token", "refresh_token": "refresh", "expiry": "{expiry}"}}',
        encoding="utf-8",
    )
    store = OAuthTokenStore(
        credentials_file=tmp_path / "missing.json",
        token_file=token_path,
    )
    assert store.get_access_token() == "live-token"


def test_token_store_refreshes_expired_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    creds = tmp_path / "client.json"
    creds.write_text(
        """
        {
          "installed": {
            "client_id": "abc.apps.googleusercontent.com",
            "client_secret": "secret",
            "token_uri": "https://oauth2.googleapis.com/token"
          }
        }
        """,
        encoding="utf-8",
    )
    token_path = tmp_path / "token.json"
    expiry = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    token_path.write_text(
        f'{{"access_token": "old", "refresh_token": "refresh-me", "expiry": "{expiry}"}}',
        encoding="utf-8",
    )

    def fake_refresh(client, refresh_token: str) -> dict:
        assert refresh_token == "refresh-me"
        assert client.client_id.startswith("abc")
        return {
            "access_token": "new-token",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    monkeypatch.setattr("research_relay.oauth.refresh_access_token", fake_refresh)
    store = OAuthTokenStore(credentials_file=creds, token_file=token_path)
    assert store.get_access_token() == "new-token"
    saved = token_path.read_text(encoding="utf-8")
    assert "new-token" in saved
    assert "refresh-me" in saved


def test_pkce_challenge_is_s256() -> None:
    verifier, challenge = pkce_challenge()
    assert len(verifier) >= 43
    assert challenge != verifier
    assert "=" not in challenge


def test_authorization_url_includes_gmail_imap_scope() -> None:
    url = authorization_url(
        client_id="abc.apps.googleusercontent.com",
        redirect_uri="http://127.0.0.1:8765/",
        code_challenge="challenge",
        state="xyz",
    )
    assert "mail.google.com" in url
    assert "googleapis.com%2Fauth%2Fdrive" in url or "auth/drive" in url
    assert GMAIL_IMAP_SCOPE.replace(":", "%3A") in url or "mail.google.com" in url
    assert "code_challenge_method=S256" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url
