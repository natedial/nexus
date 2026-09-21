#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="${RESEARCH_PARSER_DATABASE_URL:-${NEXUS_DATABASE_URL:-postgresql://nexus:nexus@localhost:5432/nexus}}"

if ! command -v psql >/dev/null 2>&1; then
  echo "psql is required. Install PostgreSQL client tools or run migrations from a host with psql." >&2
  exit 1
fi

for file in "$ROOT"/migrations/[0-9]*.sql; do
  echo "Applying $(basename "$file")"
  psql "$URL" -v ON_ERROR_STOP=1 -f "$file"
done

echo "Migrations applied to $URL"
