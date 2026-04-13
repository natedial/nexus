#!/bin/sh
set -eu

POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-3600}"
RUN_BATCH_LIMIT="${RUN_BATCH_LIMIT:-25}"
MAX_BATCHES_PER_TICK="${MAX_BATCHES_PER_TICK:-8}"
FORECAST_UPLOAD_LIMIT="${FORECAST_UPLOAD_LIMIT:-250}"

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

run_batch() {
  python -m research_analysis_layer.main run --limit "${RUN_BATCH_LIMIT}"
}

sync_forecasts() {
  if ! python -m research_analysis_layer.main sync-forecasts --upload-limit "${FORECAST_UPLOAD_LIMIT}"; then
    log "forecast sync reported unmatched or failed uploads; continuing"
  fi
}

extract_document_count() {
  python -c 'import json, sys; print(json.load(sys.stdin)["document_count"])'
}

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

log "starting hourly runner"
python -m research_analysis_layer.main doctor

while true; do
  log "tick started"
  batch_number=1

  while [ "${batch_number}" -le "${MAX_BATCHES_PER_TICK}" ]; do
    log "running batch ${batch_number} with limit ${RUN_BATCH_LIMIT}"
    batch_output="$(run_batch)"
    printf '%s\n' "${batch_output}"
    document_count="$(printf '%s\n' "${batch_output}" | extract_document_count)"

    if [ "${document_count}" -lt "${RUN_BATCH_LIMIT}" ]; then
      log "queue drained for this tick after batch ${batch_number}"
      break
    fi

    batch_number=$((batch_number + 1))
  done

  if [ "${batch_number}" -gt "${MAX_BATCHES_PER_TICK}" ]; then
    log "hit max batches per tick (${MAX_BATCHES_PER_TICK}); next tick will continue"
  fi

  log "syncing forecast candidates"
  sync_forecasts

  log "sleeping for ${POLL_INTERVAL_SECONDS} seconds"
  sleep "${POLL_INTERVAL_SECONDS}"
done
