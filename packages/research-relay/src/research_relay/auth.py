from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path

from research_relay.exceptions import ConfigError
from research_relay.oauth import OAuthTokenStore, xoauth2_payload


class GmailAuth(ABC):
    @abstractmethod
    def authenticate_imap(self, imap: object) -> None:
        raise NotImplementedError


class AppPasswordAuth(GmailAuth):
    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    def authenticate_imap(self, imap: object) -> None:
        login = getattr(imap, "login")
        login(self.username, self.password)


class OAuth2Auth(GmailAuth):
    def __init__(self, username: str, token_provider: Callable[[], str]) -> None:
        self.username = username
        self._token_provider = token_provider

    def authenticate_imap(self, imap: object) -> None:
        payload = xoauth2_payload(self.username, self._token_provider())
        authenticate = getattr(imap, "authenticate")
        authenticate("XOAUTH2", lambda _challenge: payload)


def build_auth(
    method: str,
    *,
    username: str,
    password: str | None = None,
    credentials_file: str | Path | None = None,
    token_file: str | Path | None = None,
    access_token: str | None = None,
) -> GmailAuth:
    normalized = (method or "").lower()
    if normalized == "app_password":
        if not password:
            raise ConfigError("app password authentication requires a Keychain password")
        return AppPasswordAuth(username, password)
    if normalized in {"oauth2", "oauth"}:
        if access_token:
            return OAuth2Auth(username, token_provider=lambda: str(access_token))
        if not credentials_file or not token_file:
            raise ConfigError("oauth2 requires credentials_file and token_file")
        store = OAuthTokenStore(credentials_file, token_file)
        return OAuth2Auth(username, token_provider=store.get_access_token)
    raise ConfigError(f"unknown auth method: {method}")
