from __future__ import annotations

import base64
import hashlib
import json
import secrets
import ssl
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen
import webbrowser

from research_relay.exceptions import ConfigError, TemporaryRelayError

GMAIL_IMAP_SCOPE = "https://mail.google.com/"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive"
GOOGLE_SCOPES = f"{GMAIL_IMAP_SCOPE} {DRIVE_SCOPE}"
_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class GoogleClientConfig:
    client_id: str
    client_secret: str
    auth_uri: str
    token_uri: str


def xoauth2_payload(username: str, access_token: str) -> bytes:
    return f"user={username}\x01auth=Bearer {access_token}\x01\x01".encode("utf-8")


def pkce_challenge() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:64]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    scope: str = GOOGLE_SCOPES,
    auth_uri: str = _AUTH_ENDPOINT,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope,
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
    }
    return f"{auth_uri}?{urlencode(params)}"


def load_client_config(path: str | Path) -> GoogleClientConfig:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise ConfigError(f"OAuth credentials file not found: {file_path}")
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"OAuth credentials JSON is invalid: {exc}") from exc
    if "web" in data and "installed" not in data:
        raise ConfigError(
            "OAuth client must be a Desktop app JSON, not a Web application client"
        )
    block = data.get("installed")
    if not isinstance(block, dict):
        raise ConfigError("OAuth credentials JSON is missing the Desktop (installed) client")
    client_id = str(block.get("client_id") or "").strip()
    client_secret = str(block.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        raise ConfigError("OAuth credentials JSON is missing client_id or client_secret")
    return GoogleClientConfig(
        client_id=client_id,
        client_secret=client_secret,
        auth_uri=str(block.get("auth_uri") or _AUTH_ENDPOINT),
        token_uri=str(block.get("token_uri") or _DEFAULT_TOKEN_URI),
    )


def refresh_access_token(client: GoogleClientConfig, refresh_token: str) -> dict:
    return _token_request(
        client.token_uri,
        {
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )


def exchange_authorization_code(
    client: GoogleClientConfig,
    *,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict:
    return _token_request(
        client.token_uri,
        {
            "client_id": client.client_id,
            "client_secret": client.client_secret,
            "code": code,
            "code_verifier": code_verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )


class OAuthTokenStore:
    def __init__(self, credentials_file: str | Path, token_file: str | Path) -> None:
        self.credentials_file = Path(credentials_file).expanduser()
        self.token_file = Path(token_file).expanduser()

    def get_access_token(self) -> str:
        data = self._load()
        if data.get("access_token") and not _expired(data.get("expiry")):
            return str(data["access_token"])
        refresh = str(data.get("refresh_token") or "")
        if not refresh:
            raise ConfigError(
                f"OAuth token file {self.token_file} has no refresh_token; run: research-relay auth"
            )
        client = load_client_config(self.credentials_file)
        refreshed = refresh_access_token(client, refresh)
        access = str(refreshed.get("access_token") or "")
        if not access:
            raise TemporaryRelayError("Google token refresh did not return an access token")
        data["access_token"] = access
        if refreshed.get("refresh_token"):
            data["refresh_token"] = refreshed["refresh_token"]
        expires_in = int(refreshed.get("expires_in") or 3600)
        data["expiry"] = (
            datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in - 60))
        ).isoformat()
        self.save(data)
        return access

    def save(self, data: dict) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, indent=2) + "\n"
        self.token_file.write_text(payload, encoding="utf-8")
        self.token_file.chmod(0o600)

    def _load(self) -> dict:
        if not self.token_file.is_file():
            raise ConfigError(
                f"OAuth token file not found: {self.token_file}. Run: research-relay auth"
            )
        try:
            data = json.loads(self.token_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"OAuth token file is invalid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ConfigError("OAuth token file must contain a JSON object")
        return data


def run_authorization_flow(
    *,
    credentials_file: str | Path,
    token_file: str | Path,
    redirect_port: int = 0,
    open_browser: bool = True,
) -> Path:
    client = load_client_config(credentials_file)
    verifier, challenge = pkce_challenge()
    state = secrets.token_urlsafe(24)
    httpd = HTTPServer(("127.0.0.1", int(redirect_port or 0)), _OAuthCallbackHandler)
    try:
        port = httpd.server_address[1]
        redirect_uri = f"http://127.0.0.1:{port}/"
        url = authorization_url(
            client_id=client.client_id,
            redirect_uri=redirect_uri,
            code_challenge=challenge,
            state=state,
            auth_uri=client.auth_uri,
        )
        print("Open this URL in a browser signed in as the Gmail account:")
        print(url)
        if open_browser:
            webbrowser.open(url)
        httpd.timeout = 300
        httpd.handle_request()
        error = getattr(httpd, "auth_error", None)
        if error:
            raise ConfigError(f"Google OAuth error: {error}")
        if getattr(httpd, "auth_state", None) != state:
            raise ConfigError("OAuth state mismatch; refusing to continue")
        code = getattr(httpd, "auth_code", None)
        if not code:
            raise ConfigError("OAuth callback did not include an authorization code")
        tokens = exchange_authorization_code(
            client, code=code, redirect_uri=redirect_uri, code_verifier=verifier
        )
        if not tokens.get("refresh_token"):
            raise ConfigError(
                "Google did not return a refresh_token. Re-run auth and ensure the consent screen "
                "is shown (prompt=consent) and that you are using a Desktop OAuth client."
            )
        expires_in = int(tokens.get("expires_in") or 3600)
        store = OAuthTokenStore(credentials_file, token_file)
        store.save(
            {
                "access_token": tokens.get("access_token", ""),
                "refresh_token": tokens["refresh_token"],
                "token_type": tokens.get("token_type", "Bearer"),
                "scope": tokens.get("scope", GOOGLE_SCOPES),
                "expiry": (
                    datetime.now(timezone.utc) + timedelta(seconds=max(60, expires_in - 60))
                ).isoformat(),
            }
        )
        print(f"Saved OAuth token to {store.token_file} (mode 600).")
        return store.token_file
    finally:
        httpd.server_close()


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        self.server.auth_code = (query.get("code") or [None])[0]
        self.server.auth_state = (query.get("state") or [None])[0]
        self.server.auth_error = (query.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        if self.server.auth_code:
            self.wfile.write(b"Gmail OAuth succeeded. You can close this window.")
        else:
            self.wfile.write(b"Gmail OAuth did not return a code. You can close this window.")

    def log_message(self, format: str, *args: object) -> None:
        return


def _expired(expiry: object) -> bool:
    if not expiry:
        return True
    try:
        parsed = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= parsed


def _token_request(token_uri: str, fields: dict[str, str]) -> dict:
    body = urlencode(fields).encode("utf-8")
    request = Request(
        token_uri,
        data=body,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    context = ssl.create_default_context()
    try:
        with urlopen(request, timeout=30, context=context) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise TemporaryRelayError(f"Google OAuth token endpoint HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise TemporaryRelayError(f"Google OAuth token request failed: {exc.__class__.__name__}") from exc
    except json.JSONDecodeError as exc:
        raise TemporaryRelayError("Google OAuth token response was not JSON") from exc
    if not isinstance(payload, dict):
        raise TemporaryRelayError("Google OAuth token response was not an object")
    if payload.get("error"):
        raise TemporaryRelayError("Google OAuth token endpoint returned an error")
    return payload
