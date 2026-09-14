#!/usr/bin/env python3
"""Read-only Gmail API probe: list recent message subjects and labels.

Uses the same OAuth token as research-relay (scope https://mail.google.com/).
Does not change labels, mark mail read, or send anything.

Examples:
  python3 scripts/gmail_api_probe.py
  python3 scripts/gmail_api_probe.py --query "newer_than:2d"
  python3 scripts/gmail_api_probe.py --query "label:relay/pending"
  python3 scripts/gmail_api_probe.py --query "subject:the title I see in Proton"
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from research_relay.cli import _resolve_config
from research_relay.config import load_config
from research_relay.exceptions import ConfigError, TemporaryRelayError
from research_relay.oauth import OAuthTokenStore

_API = "https://gmail.googleapis.com/gmail/v1/users/me"
_WANTED_HEADERS = ("Subject", "From", "Date", "To")


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    try:
        cfg = load_config(_resolve_config(args.config))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if cfg.auth.method != "oauth2":
        print("this probe needs auth.method = oauth2", file=sys.stderr)
        return 2
    if cfg.auth.credentials_file is None or cfg.auth.token_file is None:
        print("oauth credentials_file and token_file are required", file=sys.stderr)
        return 2

    store = OAuthTokenStore(cfg.auth.credentials_file, cfg.auth.token_file)
    try:
        token = store.get_access_token()
    except (ConfigError, TemporaryRelayError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    query = args.query
    if query is None:
        query = "newer_than:3d"

    try:
        profile = _get(token, f"{_API}/profile")
        labels = _label_map(_get(token, f"{_API}/labels").get("labels") or [])
        listed = _get(
            token,
            f"{_API}/messages",
            {"maxResults": str(args.max), "q": query},
        )
    except ProbeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    email = profile.get("emailAddress", "?")
    total = listed.get("resultSizeEstimate", 0)
    messages = listed.get("messages") or []

    print(f"account: {email}")
    print(f"query:   {query!r}")
    print(f"matched: {total} (showing {len(messages)})")
    if listed.get("nextPageToken"):
        print("note:    more pages exist; raise --max or narrow --query")
    print()

    if not messages:
        print("Gmail API returned no messages for that query.")
        print("If Proton shows mail that this does not, try a broader query,")
        print("e.g. --query ''  or  --query 'in:anywhere newer_than:7d'")
        return 0

    for index, stub in enumerate(messages, start=1):
        message_id = stub.get("id", "")
        try:
            detail = _get(
                token,
                f"{_API}/messages/{message_id}",
                {
                    "format": "metadata",
                    "metadataHeaders": list(_WANTED_HEADERS),
                },
            )
        except ProbeError as exc:
            print(f"{index}. id={message_id}  fetch failed: {exc}")
            continue
        headers = _headers(detail)
        label_ids = detail.get("labelIds") or []
        named = [_format_label(label_id, labels) for label_id in label_ids]
        print(f"{index}. {headers.get('Subject') or '(no subject)'}")
        print(f"   From:   {headers.get('From') or '?'}")
        print(f"   Date:   {headers.get('Date') or '?'}")
        print(f"   Labels: {', '.join(named) if named else '(none)'}")
        print(f"   id:     {message_id}")
        print()

    return 0


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--config",
        default=None,
        help="TOML config (default: $RESEARCH_RELAY_CONFIG or ~/.config/research-relay/config.toml)",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Gmail search string (default: newer_than:3d). Empty string = no filter.",
    )
    parser.add_argument("--max", type=int, default=10, help="Max messages to print (default 10)")
    return parser.parse_args(argv)


def _get(token: str, url: str, params: dict | None = None) -> dict:
    if params:
        pairs: list[tuple[str, str]] = []
        for key, value in params.items():
            if isinstance(value, list):
                pairs.extend((key, str(item)) for item in value)
            elif value is not None:
                pairs.append((key, str(value)))
        url = f"{url}?{urlencode(pairs)}"
    request = Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    context = ssl.create_default_context()
    try:
        with urlopen(request, timeout=30, context=context) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        hint = ""
        if exc.code == 403 and "Gmail API has not been used" in body:
            hint = " Enable the Gmail API on the same Google Cloud project as the OAuth client."
        elif exc.code == 401:
            hint = " Token rejected; try: research-relay auth"
        raise ProbeError(f"Gmail API HTTP {exc.code}.{hint}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ProbeError(f"Gmail API request failed: {exc.__class__.__name__}") from exc
    except json.JSONDecodeError as exc:
        raise ProbeError("Gmail API response was not JSON") from exc
    if not isinstance(payload, dict):
        raise ProbeError("Gmail API response was not an object")
    return payload


def _headers(message: dict) -> dict[str, str]:
    payload = message.get("payload") or {}
    found: dict[str, str] = {}
    for item in payload.get("headers") or []:
        name = str(item.get("name") or "")
        if name in _WANTED_HEADERS and name not in found:
            found[name] = str(item.get("value") or "")
    return found


def _label_map(labels: list) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for label in labels:
        label_id = str(label.get("id") or "")
        name = str(label.get("name") or label_id)
        if label_id:
            mapping[label_id] = name
    return mapping


def _format_label(label_id: str, labels: dict[str, str]) -> str:
    name = labels.get(label_id)
    if name and name != label_id:
        return f"{name} ({label_id})"
    return label_id


class ProbeError(Exception):
    pass


if __name__ == "__main__":
    raise SystemExit(main())
