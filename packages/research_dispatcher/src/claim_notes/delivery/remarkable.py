"""Own reMarkable notebook delivery for morning attention.

Canonical path: write Remarkdown-ready markdown for Proey's reMarkable
connector (same connector the 5:55 and 6:10 routines already use). Default
title: "Morning Attention YYYY-MM-DD". Place the notebook next to the G10
Calendar and Research From notebooks — own notebook, never folded into those
pushes. Optional HTTP push is secondary.
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
    silent: bool = False


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


class HandoffRemarkableNotebookSender:
    """Write markdown for Proey's reMarkable connector (canonical handoff)."""

    def __init__(self, handoff_dir: str | Path) -> None:
        self.handoff_dir = Path(handoff_dir)

    def push(self, *, title: str, markdown: str) -> RemarkablePushResult:
        self.handoff_dir.mkdir(parents=True, exist_ok=True)
        path = self.handoff_dir / "morning-attention.md"
        path.write_text(markdown, encoding="utf-8")
        meta = self.handoff_dir / "notebook-title.txt"
        meta.write_text(title.strip() + "\n", encoding="utf-8")
        return RemarkablePushResult(
            title=title, markdown_chars=len(markdown), path=str(path)
        )


FileRemarkableNotebookSender = HandoffRemarkableNotebookSender


class HttpRemarkableNotebookSender:
    """Optional HTTP push — demoted vs Proey connector handoff."""

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
