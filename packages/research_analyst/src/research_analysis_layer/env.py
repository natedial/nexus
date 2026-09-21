"""Environment lookup for the analysis layer.

Values resolve in this order: the process environment, then this package's
`.env` (analyst-owned settings), then the repo-root `.env` (credentials shared
by the whole pipeline).

Analyst-owned names are prefixed `RESEARCH_ANALYST_`. Shared names
(`NEXUS_DATABASE_URL`, `RESEARCH_PROCESSING_ROOT`, ...) stay unprefixed. The
pre-monorepo unprefixed names are still accepted as a deprecated fallback.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

ENV_PREFIX = "RESEARCH_ANALYST_"

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PACKAGE_ROOT.parents[1]

_loaded = False


def _load_file(path: Path) -> None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        line = line.removeprefix("export ")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def load_env_files(*, force: bool = False) -> None:
    """Populate `os.environ` from the package and root `.env` files."""
    global _loaded
    if _loaded and not force:
        return
    _loaded = True
    # Package file first: an already-set key is never overwritten, so the
    # package value wins over the root value.
    _load_file(PACKAGE_ROOT / ".env")
    _load_file(REPO_ROOT / ".env")


def env(
    name: str,
    default: str | None = None,
    *,
    legacy: str | Sequence[str] | None = None,
) -> str | None:
    """Read `RESEARCH_ANALYST_<name>`, then any deprecated fallback names.

    `legacy` defaults to the unprefixed `name`, which is how these variables
    were spelled before the packages moved into one repo.
    """
    load_env_files()
    if legacy is None:
        fallbacks: tuple[str, ...] = (name,)
    elif isinstance(legacy, str):
        fallbacks = (legacy,)
    else:
        fallbacks = tuple(legacy)
    for candidate in (f"{ENV_PREFIX}{name}", *fallbacks):
        value = os.getenv(candidate)
        if value is not None:
            return value
    return default
