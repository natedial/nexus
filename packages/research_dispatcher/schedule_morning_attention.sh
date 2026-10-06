#!/bin/bash
# FALLBACK ONLY — prefer Proey's owned weekday ~06:25 ET routine.
# Canonical live path: analyst export-dispatch-batch → --argument-map-json
# (or RESEARCH_DISPATCHER_MORNING_ARGUMENT_MAP_JSON / --analyst-batch-dir).
# LIBRARY --library-json is demoted (no claim projection). Empty claims → silent.
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
ARG_MAP="${RESEARCH_DISPATCHER_MORNING_ARGUMENT_MAP_JSON:-${RESEARCH_DISPATCHER_ANALYST_BATCH_PATH:-}}"
BATCH_DIR="${RESEARCH_DISPATCHER_MORNING_ANALYST_BATCH_DIR:-}"
NOTES_JSONL="${RESEARCH_DISPATCHER_MORNING_NOTES_JSONL:-}"
# Demoted — ignored for claims if present.
LIBRARY_JSON="${RESEARCH_DISPATCHER_MORNING_LIBRARY_JSON:-}"

ARGS=(--watermark "$WATERMARK" --handoff-dir "$HANDOFF" --since-watermark)

if [ -n "$ARG_MAP" ]; then
  ARGS+=(--argument-map-json "$ARG_MAP")
elif [ -n "$BATCH_DIR" ]; then
  ARGS+=(--analyst-batch-dir "$BATCH_DIR")
elif [ -n "$NOTES_JSONL" ]; then
  ARGS+=(--notes-jsonl "$NOTES_JSONL")
else
  echo "Set RESEARCH_DISPATCHER_MORNING_ARGUMENT_MAP_JSON (export-dispatch-batch JSON)" >&2
  echo "or RESEARCH_DISPATCHER_MORNING_ANALYST_BATCH_DIR (dir with latest.json)." >&2
  echo "See docs/morning-attention-ops.md." >&2
  exit 1
fi

if [ -n "$LIBRARY_JSON" ]; then
  # Demoted diagnostics only.
  ARGS+=(--library-json "$LIBRARY_JSON")
fi

exec python src/claim_notes/run_morning_attention.py "${ARGS[@]}"
