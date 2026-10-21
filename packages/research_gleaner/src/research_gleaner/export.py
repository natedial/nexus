from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from research_gleaner.models import CaptureBatch


def write_capture_batch(batch: CaptureBatch, path: Path) -> Path:
    target = path.expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(batch.to_dict(), indent=2, ensure_ascii=False) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        text=True,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        Path(temporary_name).replace(target)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return target
