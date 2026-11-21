#!/usr/bin/env bash
# Rehearses an end-to-end PostgreSQL backup, restore into an isolated local
# database, least-privilege role application (apply-roles.sh), and read-only
# verification WITHOUT Django.
#
# Usage:
#   EDIFY_ENV=test EDIFY_SOURCE_DB_URL=postgresql://localhost:5432/edify_gorn_test \
#     platform/deploy/db/rehearse-backup-restore.sh
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source_url="${EDIFY_SOURCE_DB_URL:-postgresql://localhost:5432/edify_gorn_test}"
restore_db="${EDIFY_RESTORE_DB:-edify_gorn_restore_test}"
dump_file="$(mktemp /tmp/edify-uganda-backup-XXXXXX.dump)"
trap 'rm -f "$dump_file"' EXIT

# Guardrail: local only, never production.
case "$source_url" in
  *edify-production-db*|*edifyplanning.app*)
    echo "refused: production marker in source URL" >&2
    exit 2
    ;;
esac

t0="$(date +%s)"
# Dump data schemas only (ephemeral gateway_* SECURITY DEFINER schemas are
# recreated cleanly by apply-roles.sh after restore).
pg_dump --format=custom --no-owner --no-privileges \
  --schema=public \
  --schema=cluster_leadership \
  --schema=school_loans \
  --schema=field_routes \
  --schema=country_registry \
  --file="$dump_file" "$source_url"
t_dump="$(date +%s)"

base_url="${source_url%/*}"
psql "${base_url}/postgres" --set ON_ERROR_STOP=1 --quiet \
  -c "DROP DATABASE IF EXISTS ${restore_db};" \
  -c "CREATE DATABASE ${restore_db};"
# Pre-install required PostgreSQL extensions (e.g. pg_trgm for school name GIN index).
psql "${base_url}/${restore_db}" --set ON_ERROR_STOP=1 --quiet \
  -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"

toc_file="$(mktemp /tmp/edify-uganda-toc-XXXXXX.list)"
trap 'rm -f "$dump_file" "$toc_file"' EXIT
pg_restore --list "$dump_file" | grep -v "SCHEMA - public" > "$toc_file"
pg_restore --no-owner --no-privileges --use-list="$toc_file" --dbname="${base_url}/${restore_db}" "$dump_file"
t_restore="$(date +%s)"

EDIFY_ENV=test EDIFY_ADMIN_DATABASE_URL="${base_url}/${restore_db}" "${here}/apply-roles.sh"
t_roles="$(date +%s)"

src_schools="$(psql "$source_url" -At -c "SELECT count(*) FROM school WHERE deleted_at IS NULL")"
dst_schools="$(psql "${base_url}/${restore_db}" -At -c "SELECT count(*) FROM school WHERE deleted_at IS NULL")"
src_acts="$(psql "$source_url" -At -c "SELECT count(*) FROM activity WHERE deleted_at IS NULL")"
dst_acts="$(psql "${base_url}/${restore_db}" -At -c "SELECT count(*) FROM activity WHERE deleted_at IS NULL")"

psql "${base_url}/postgres" --set ON_ERROR_STOP=1 --quiet -c "DROP DATABASE IF EXISTS ${restore_db};"

if [[ "$src_schools" != "$dst_schools" || "$src_acts" != "$dst_acts" ]]; then
  echo "FAIL: count mismatch schools=${src_schools}/${dst_schools} activities=${src_acts}/${dst_acts}" >&2
  exit 1
fi

echo "PASS: backup=$((t_dump - t0))s restore=$((t_restore - t_dump))s roles=$((t_roles - t_restore))s total=$((t_roles - t0))s schools=${dst_schools} activities=${dst_acts}"
