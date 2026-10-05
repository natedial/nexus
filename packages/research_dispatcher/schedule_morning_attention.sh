#!/bin/bash
# FALLBACK ONLY — prefer Proey's owned weekday ~06:25 ET routine.
# Canonical: run_morning_attention.py --handoff-dir … then Proey connectors
# (reMarkable + Grok Bot), same as 5:55/6:10. Do NOT change those schedules.
#
# Empty day is silent (script still exits 0; handoff.json says silent=true).

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

NOTES_JSONL="${RESEARCH_DISPATCHER_MORNING_NOTES_JSONL:-fixtures/claim_notes/claim_notes.jsonl}"
ARG_MAP="${RESEARCH_DISPATCHER_MORNING_ARGUMENT_MAP_JSON:-}"
WATERMARK="${RESEARCH_DISPATCHER_MORNING_WATERMARK:-state/morning_attention_last_run.json}"
HANDOFF="${RESEARCH_DISPATCHER_MORNING_HANDOFF_DIR:-state/morning_attention_handoff}"
LIBRARY_JSON="${RESEARCH_DISPATCHER_MORNING_LIBRARY_JSON:-}"

ARGS=(--watermark "$WATERMARK" --handoff-dir "$HANDOFF")
if [ -n "$LIBRARY_JSON" ]; then
  ARGS+=(--library-json "$LIBRARY_JSON")
fi
if [ -n "$ARG_MAP" ]; then
  ARGS+=(--argument-map-json "$ARG_MAP")
else
  ARGS+=(--notes-jsonl "$NOTES_JSONL")
fi

exec python src/claim_notes/run_morning_attention.py "${ARGS[@]}"
