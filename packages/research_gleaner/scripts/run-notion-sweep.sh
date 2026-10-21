#!/bin/bash
set -euo pipefail

PACKAGE_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${RESEARCH_GLEANER_PYTHON:-$PACKAGE_ROOT/.venv/bin/python3}"

if [[ ! -x "$PYTHON" ]]; then
    echo "research-gleaner: Python not found or not executable: $PYTHON" >&2
    echo "research-gleaner: install the package venv or set RESEARCH_GLEANER_PYTHON" >&2
    exit 2
fi

cd "$PACKAGE_ROOT"
exec "$PYTHON" -m research_gleaner notion
