#!/bin/sh
set -eu

# RESEARCH_ANALYST_* is canonical; the unprefixed names are a deprecated fallback.
POLL_INTERVAL_SECONDS="${RESEARCH_ANALYST_POLL_INTERVAL_SECONDS:-${POLL_INTERVAL_SECONDS:-3600}}"

log() {
  printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$*"
}

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

log "starting hourly runner"
python -m research_analysis_layer.main doctor

while true; do
  python -m research_analysis_layer.hourly_tick

  log "sleeping for ${POLL_INTERVAL_SECONDS} seconds"
  sleep "${POLL_INTERVAL_SECONDS}"
done
