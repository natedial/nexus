#!/bin/bash
set -euo pipefail

PACKAGE_ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${RESEARCH_GLEANER_PYTHON:-$PACKAGE_ROOT/.venv/bin/python3}"

if [[ ! -x "$PYTHON" ]]; then
    echo "research-gleaner: Python not found or not executable: $PYTHON" >&2
    echo "research-gleaner: install the package venv or set RESEARCH_GLEANER_PYTHON" >&2
    exit 2
fi

# Load the reMarkable token from the gleaner's own file so that tools which
# rewrite ~/.rmapi (e.g. rmapi) cannot break this job. Never echo the value.
# An explicitly set REMARKABLE_TOKEN wins; a missing file falls back to ~/.rmapi.
TOKEN_FILE="${RESEARCH_GLEANER_REMARKABLE_TOKEN_FILE:-$HOME/.config/research-gleaner/remarkable_token.json}"
if [[ -z "${REMARKABLE_TOKEN:-}" && -f "$TOKEN_FILE" && -r "$TOKEN_FILE" ]]; then
    REMARKABLE_TOKEN="$(cat -- "$TOKEN_FILE")"
    export REMARKABLE_TOKEN
fi

cd "$PACKAGE_ROOT"
exec "$PYTHON" -m research_gleaner remarkable
