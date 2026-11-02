#!/usr/bin/env bash
# Apply root SQL migrations. Never prints the database URL.
#
# Usage (from repo root):
#   ./migrations/apply.sh
#   ./migrations/apply.sh 005_pipeline_ops_control_plane.sql
#
# Reads RESEARCH_PARSER_DATABASE_URL, then NEXUS_DATABASE_URL, then a local default.
# Prefer loading the repo-root .env first without echoing secrets:
#   set -a && source .env && set +a && ./migrations/apply.sh 005_pipeline_ops_control_plane.sql
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="${RESEARCH_PARSER_DATABASE_URL:-${NEXUS_DATABASE_URL:-postgresql://nexus:nexus@localhost:5432/nexus}}"

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required. Install PostgreSQL client tools or run migrations from a host with psql." >&2
  exit 1
fi

if [[ "$#" -gt 0 ]]; then
  files=()
  for name in "$@"; do
    base="$(basename "$name")"
    path="$ROOT/migrations/$base"
    if [[ ! -f "$path" ]]; then
      echo "migration not found: $base" >&2
      exit 1
    fi
    files+=("$path")
  done
else
  files=("$ROOT"/migrations/[0-9]*.sql)
fi

for file in "${files[@]}"; do
  echo "Applying $(basename "$file")"
  psql "$URL" -v ON_ERROR_STOP=1 -f "$file" >/dev/null
done

echo "Migrations applied."
