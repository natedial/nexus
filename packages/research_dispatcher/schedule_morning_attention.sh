#!/bin/bash
# Morning attention — weekdays ~06:25 America/New_York (after 06:10 digest).
# Does NOT change 5:55 / 6:10 tablet pushes. Own surface only.
#
# Cron (with CRON_TZ=America/New_York):
#   25 6 * * 1-5 /path/to/packages/research_dispatcher/schedule_morning_attention.sh
#
# launchd: see launchd/com.researchdispatcher.morning-attention.plist

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

ARGS=(--watermark "$WATERMARK")
if [ -n "$ARG_MAP" ]; then
  ARGS+=(--argument-map-json "$ARG_MAP")
else
  ARGS+=(--notes-jsonl "$NOTES_JSONL")
fi

exec python src/claim_notes/run_morning_attention.py "${ARGS[@]}"
