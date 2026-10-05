"""Morning-attention run watermark (since-last-run LIBRARY window)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class RunWatermarkStore:
    """Persist the last successful morning-attention run timestamp."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def read(self) -> datetime | None:
        if not self.path.is_file():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        raw = payload.get("last_run_at")
        if not raw:
            return None
        text = str(raw).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        stamp = datetime.fromisoformat(text)
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)

    def write(self, when: datetime | None = None) -> datetime:
        stamp = when or datetime.now(timezone.utc)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"last_run_at": stamp.astimezone(timezone.utc).isoformat()}, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return stamp
