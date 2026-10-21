"""Shared pytest guardrails for research_analyst.

Prevents unattended suite runs from OOMing a workstation:

- per-test timeout via pytest-timeout (see pyproject.toml)
- process address-space cap via RLIMIT_AS / RLIMIT_DATA (enforced on Linux;
  macOS does not enforce RLIMIT_AS — soft RSS check below covers that)
- soft per-test RSS ceiling (~2 GiB) that fails the test instead of killing the host
- ``heavy`` tests are skipped by default (opt in with ``-m heavy``)

Override defaults with env vars:

- ``RESEARCH_ANALYST_TEST_TIMEOUT`` — seconds (pytest-timeout; config default 60)
- ``RESEARCH_ANALYST_TEST_RSS_MB`` — soft RSS fail threshold (default 2048)
- ``RESEARCH_ANALYST_TEST_AS_MB`` — RLIMIT_AS / RLIMIT_DATA soft+hard cap (default 4096)
- ``RESEARCH_ANALYST_TEST_SKIP_RLIMIT=1`` — skip setting resource limits
"""

from __future__ import annotations

import os
import resource
import sys

import pytest

# Soft RSS fail threshold. macOS does not enforce RLIMIT_AS; this is the
# cross-platform backstop so a runaway test fails instead of OOM-killing the host.
DEFAULT_RSS_LIMIT_MB = 2048
# Virtual address-space / data-segment cap for the test process (Linux).
DEFAULT_AS_LIMIT_MB = 4096


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return int(raw)


def _current_rss_mb() -> float:
    """Current resident set size in MiB (not lifetime peak)."""
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/self/status", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("VmRSS:"):
                        # VmRSS is in kB.
                        return int(line.split()[1]) / 1024.0
        except OSError:
            pass
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024.0 * 1024.0)
    return usage / 1024.0


def _apply_process_memory_limit() -> None:
    if os.environ.get("RESEARCH_ANALYST_TEST_SKIP_RLIMIT") == "1":
        return
    limit_mb = _env_int("RESEARCH_ANALYST_TEST_AS_MB", DEFAULT_AS_LIMIT_MB)
    limit_bytes = limit_mb * 1024 * 1024
    for name in ("RLIMIT_AS", "RLIMIT_DATA"):
        attr = getattr(resource, name, None)
        if attr is None:
            continue
        try:
            soft, hard = resource.getrlimit(attr)
            # Never raise an existing lower hard limit; only tighten.
            new_hard = hard if hard != resource.RLIM_INFINITY else limit_bytes
            new_hard = min(new_hard, limit_bytes)
            new_soft = min(soft if soft != resource.RLIM_INFINITY else limit_bytes, new_hard)
            resource.setrlimit(attr, (new_soft, new_hard))
        except (ValueError, OSError):
            # macOS / restricted containers may reject these; soft RSS still applies.
            continue


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "heavy: memory- or CPU-heavy test; skipped by default (run with -m heavy)",
    )
    timeout_override = os.environ.get("RESEARCH_ANALYST_TEST_TIMEOUT")
    if timeout_override:
        config.option.timeout = float(timeout_override)
    _apply_process_memory_limit()


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Skip heavy tests unless explicitly selected."""
    markexpr = (config.option.markexpr or "").strip()
    if "heavy" in markexpr:
        return
    skip_heavy = pytest.mark.skip(
        reason="heavy tests are opt-in; run with: pytest -m heavy"
    )
    for item in items:
        if "heavy" in item.keywords:
            item.add_marker(skip_heavy)


@pytest.fixture(autouse=True)
def _rss_guard():
    """Fail a test whose process RSS exceeds the soft ceiling."""
    limit_mb = _env_int("RESEARCH_ANALYST_TEST_RSS_MB", DEFAULT_RSS_LIMIT_MB)
    yield
    rss_mb = _current_rss_mb()
    if rss_mb > limit_mb:
        pytest.fail(
            f"test process RSS {rss_mb:.0f} MiB exceeded soft limit "
            f"{limit_mb} MiB (set RESEARCH_ANALYST_TEST_RSS_MB to override)"
        )
