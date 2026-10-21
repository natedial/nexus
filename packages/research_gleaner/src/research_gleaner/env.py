from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


def load_environment() -> None:
    """Load Nexus root settings, then package settings, below process env."""
    package_root = Path(__file__).resolve().parents[2]
    repo_root = Path(__file__).resolve().parents[4]
    original_keys = set(os.environ)

    root_values = dotenv_values(repo_root / ".env")
    package_values = dotenv_values(package_root / ".env")
    for key, value in root_values.items():
        if value is not None and key not in original_keys:
            os.environ[key] = value
    for key, value in package_values.items():
        if value is not None and key not in original_keys:
            os.environ[key] = value
