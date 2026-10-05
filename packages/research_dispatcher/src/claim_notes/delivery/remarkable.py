"""Own reMarkable notebook delivery for morning attention.

Writes Remarkdown-ready markdown to a drop path and optionally POSTs to a
configured Remarkdown/HTTP endpoint. Never folds into G10 Calendar or
Research From tablet pushes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import httpx


@dataclass
class RemarkablePushResult:
    title: str
    markdown_chars: int
    path: str | None = None
    http_status: int | None = None
    dry_run: bool = False


class RemarkableNotebookSender(Protocol):
    def push(self, *, title: str, markdown: str) -> RemarkablePushResult:
        ...


@dataclass
class FakeRemarkableNotebookSender:
    """Records pushes for unit tests — no tablet / network side effects."""

    pushes: list[dict[str, str]] = field(default_factory=list)

    def push(self, *, title: str, markdown: str) -> RemarkablePushResult:
        self.pushes.append({"title": title, "markdown": markdown})
        return RemarkablePushResult(
            title=title, markdown_chars=len(markdown), dry_run=True
        )


class FileRemarkableNotebookSender:
    """Write a markdown notebook into a configured drop directory."""

    def __init__(self, drop_dir: str | Path) -> None:
        self.drop_dir = Path(drop_dir)

    def push(self, *, title: str, markdown: str) -> RemarkablePushResult:
        self.drop_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_ " else "-" for ch in title).strip()
        path = self.drop_dir / f"{safe or 'morning-attention'}.md"
        path.write_text(markdown, encoding="utf-8")
        return RemarkablePushResult(
            title=title, markdown_chars=len(markdown), path=str(path)
        )


class HttpRemarkableNotebookSender:
    """Optional HTTP push (Remarkdown-compatible webhook).

    Env: RESEARCH_DISPATCHER_REMARKABLE_PUSH_URL + optional bearer token.
    Does not alter 5:55 / 6:10 tablet jobs.
    """

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

    def push(self, *, title: str, markdown: str) -> RemarkablePushResult:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        body = {"title": title, "markdown": markdown, "paginate": False}
        if self._client is not None:
            response = self._client.post(self.url, headers=headers, json=body)
        else:
            with httpx.Client(timeout=self.timeout_s) as client:
                response = client.post(self.url, headers=headers, json=body)
        response.raise_for_status()
        return RemarkablePushResult(
            title=title,
            markdown_chars=len(markdown),
            http_status=response.status_code,
        )
