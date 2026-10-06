#!/bin/bash
# FALLBACK ONLY — prefer Proey's owned weekday ~06:25 ET routine.
# Canonical live path: --library-json (Research Notes since last run) + --handoff-dir.
# No fixtures required. Empty library → silent (handoff.json silent=true).
# Do NOT change 5:55 / 6:10 schedules.

set -euo pipefail
cd "$(dirname "$0")"

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  . venv/bin/activate
fi

export TZ="${TZ:-America/New_York}"

WATERMARK="${RESEARCH_DISPATCHER_MORNING_WATERMARK:-state/morning_attention_last_run.json}"
HANDOFF="${RESEARCH_DISPATCHER_MORNING_HANDOFF_DIR:-state/morning_attention_handoff}"
LIBRARY_JSON="${RESEARCH_DISPATCHER_MORNING_LIBRARY_JSON:-}"
NOTES_JSONL="${RESEARCH_DISPATCHER_MORNING_NOTES_JSONL:-}"
ARG_MAP="${RESEARCH_DISPATCHER_MORNING_ARGUMENT_MAP_JSON:-}"

ARGS=(--watermark "$WATERMARK" --handoff-dir "$HANDOFF")

if [ -n "$LIBRARY_JSON" ]; then
  ARGS+=(--library-json "$LIBRARY_JSON")
fi
if [ -n "$ARG_MAP" ]; then
  ARGS+=(--argument-map-json "$ARG_MAP")
elif [ -n "$NOTES_JSONL" ]; then
  ARGS+=(--notes-jsonl "$NOTES_JSONL")
fi

if [ -z "$LIBRARY_JSON" ] && [ -z "$ARG_MAP" ] && [ -z "$NOTES_JSONL" ]; then
  echo "Set RESEARCH_DISPATCHER_MORNING_LIBRARY_JSON to the Proey Research Notes JSON (since last run)." >&2
  echo "Live path needs no fixtures. See docs/morning-attention-ops.md." >&2
  exit 1
fi

exec python src/claim_notes/run_morning_attention.py "${ARGS[@]}"
