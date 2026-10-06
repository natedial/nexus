"""One-line Grok Bot chat ping for morning attention.

NOT SMTP email. Destination: Nate's 1:1 chat with Proey — the same place as
the 5:55 / 6:10 pings. Emit a one-line ping for Proey's Grok Bot connector
(handoff file and/or optional webhook). Never use EMAIL_TO.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx


@dataclass
class ChatPingResult:
    body: str
    channel: str = "grok_bot"
    path: str | None = None
    http_status: int | None = None
    dry_run: bool = False
    silent: bool = False


class ChatPingSender(Protocol):
    def send(self, *, body: str) -> ChatPingResult:
        ...


@dataclass
class FakeGrokBotChatPingSender:
    """Records Grok Bot pings for unit tests — no network / inbox side effects."""

    messages: list[dict[str, str]] = field(default_factory=list)

    def send(self, *, body: str) -> ChatPingResult:
        self.messages.append({"body": body, "channel": "grok_bot"})
        return ChatPingResult(body=body, channel="grok_bot", dry_run=True)


class HandoffGrokBotChatPingSender:
    """Write the one-line ping for Proey's Grok Bot connector (canonical)."""

    def __init__(self, handoff_dir: str | Path) -> None:
        self.handoff_dir = Path(handoff_dir)

    def send(self, *, body: str) -> ChatPingResult:
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        path = self.handoff_dir / "chat-ping.txt"
        path.write_text(body.rstrip() + "\n", encoding="utf-8")
        return ChatPingResult(body=body, channel="grok_bot", path=str(path))


class HttpGrokBotChatPingSender:
    """Optional webhook if Proey exposes a Grok Bot ping URL (not SMTP)."""

    def __init__(
        self,
        *,
        url: str,
        token: str | None = None,
        timeout_s: float = 30.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.url = url
        self.token = (token or "").strip() or None
        self.timeout_s = timeout_s
        self._client = client

    def send(self, *, body: str) -> ChatPingResult:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        payload = {"channel": "grok_bot", "text": body, "body": body}
        if self._client is not None:
            response = self._client.post(self.url, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.post(self.url, headers=headers, json=payload)
        response.raise_for_status()
        return ChatPingResult(
            body=body, channel="grok_bot", http_status=response.status_code
        )


# Back-compat alias — always Grok Bot, never SMTP.
FakeChatPingSender = FakeGrokBotChatPingSender
