#!/usr/bin/env bash
# Wrapper invoked by launchd (see com.ncdial.morning-research.plist.example).
# Activates the project's virtualenv (if present) and runs the daily job,
# writing timestamped logs alongside the work directory.

set -euo pipefail

PACKAGE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PACKAGE_ROOT"

if [ -f "$PACKAGE_ROOT/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$PACKAGE_ROOT/.venv/bin/activate"
fi

LOG_DIR="$PACKAGE_ROOT/work/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date -u +%Y%m%d_%H%M%S).log"

echo "Starting morning-research run at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG_FILE"

python -m morning_research >>"$LOG_FILE" 2>&1
STATUS=$?

echo "morning-research exited with status $STATUS at $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "$LOG_FILE"
exit $STATUS
