#!/usr/bin/env bash
#
# Backup / restore rehearsal.
#
# A backup that has never been restored is not a backup, it is a file. This
# script proves the round trip end to end: dump the live database, restore it
# into a scratch database, and verify the restored copy independently -- row
# counts per table, migration state, and referential integrity.
#
# It is deliberately non-destructive to the source. It only ever CREATEs and
# DROPs the scratch database, whose name carries a fixed prefix and is
# refused if it collides with the source.
#
# Usage:
#     scripts/backup_restore_rehearsal.sh                # rehearse against dev
#     PGDATABASE=edify_staging scripts/backup_restore_rehearsal.sh
#
# Exit code is 0 only if every verification passed.

set -Eeuo pipefail

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-edify}"
SOURCE_DB="${PGDATABASE:-edify_pm}"
SCRATCH_DB="restore_rehearsal_${SOURCE_DB}"
ARTIFACT_DIR="${ARTIFACT_DIR:-./.backup-rehearsal}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP_FILE="${ARTIFACT_DIR}/${SOURCE_DB}-${STAMP}.dump"

export PGHOST PGPORT PGUSER

if [[ "$SCRATCH_DB" == "$SOURCE_DB" ]]; then
  echo "REFUSING: scratch and source database are the same name." >&2
  exit 2
fi

mkdir -p "$ARTIFACT_DIR"

psql_src() { psql -X -q -A -t -d "$SOURCE_DB" -c "$1"; }
psql_dst() { psql -X -q -A -t -d "$SCRATCH_DB" -c "$1"; }

fail=0
step() { printf '\n=== %s ===\n' "$1"; }
check() { # check <label> <expected> <actual>
  if [[ "$2" == "$3" ]]; then
    printf '  PASS  %-42s %s\n' "$1" "$3"
  else
    printf '  FAIL  %-42s expected=%s actual=%s\n' "$1" "$2" "$3"
    fail=1
  fi
}

cleanup() {
  # Always drop the scratch database, including on failure, so a botched
  # rehearsal cannot leave a stale near-copy of production data lying around.
  psql -X -q -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

step "1. Dump ${SOURCE_DB}"
# Custom format: parallel-restorable and the format the runbook specifies for
# real backups, so this rehearses the actual artifact rather than a plain-SQL
# stand-in that might restore differently.
pg_dump --format=custom --no-owner --no-privileges -d "$SOURCE_DB" -f "$DUMP_FILE"
dump_bytes=$(wc -c < "$DUMP_FILE" | tr -d ' ')
echo "  wrote ${DUMP_FILE} (${dump_bytes} bytes)"
if [[ "$dump_bytes" -lt 100000 ]]; then
  echo "  FAIL  dump is implausibly small -- treating as a failed backup" >&2
  exit 1
fi

step "2. Restore into scratch database ${SCRATCH_DB}"
psql -X -q -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\";"
psql -X -q -d postgres -c "CREATE DATABASE \"$SCRATCH_DB\";"
# --exit-on-error so a partial restore is a failure, not a warning we scroll
# past. Postgres emits no errors on a clean round trip.
pg_restore --no-owner --no-privileges --exit-on-error -d "$SCRATCH_DB" "$DUMP_FILE"
echo "  restored."

step "3. Verify row counts table by table"
# Compare every public table's exact row count. This is the assertion that a
# dump/restore actually preserved the data, rather than the schema alone.
tables=$(psql_src "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;")
table_count=0
mismatched=0
for t in $tables; do
  src=$(psql_src "SELECT count(*) FROM \"$t\";")
  dst=$(psql_dst "SELECT count(*) FROM \"$t\";")
  table_count=$((table_count + 1))
  if [[ "$src" != "$dst" ]]; then
    printf '  FAIL  %-42s source=%s restored=%s\n' "$t" "$src" "$dst"
    mismatched=$((mismatched + 1))
    fail=1
  fi
done
if [[ "$mismatched" -eq 0 ]]; then
  printf '  PASS  %-42s %s tables identical\n' "all table row counts" "$table_count"
fi
if [[ "$table_count" -lt 50 ]]; then
  echo "  FAIL  only ${table_count} tables found -- schema did not restore" >&2
  fail=1
fi

step "4. Verify migration state matches"
src_migrations=$(psql_src "SELECT count(*) FROM django_migrations;")
dst_migrations=$(psql_dst "SELECT count(*) FROM django_migrations;")
check "django_migrations rows" "$src_migrations" "$dst_migrations"

src_last=$(psql_src "SELECT app||'.'||name FROM django_migrations ORDER BY id DESC LIMIT 1;")
dst_last=$(psql_dst "SELECT app||'.'||name FROM django_migrations ORDER BY id DESC LIMIT 1;")
check "latest migration applied" "$src_last" "$dst_last"

step "5. Verify referential integrity in the restored copy"
# pg_restore recreates FK constraints but does not re-validate existing rows.
# NOT VALID constraints would silently accept broken references, so assert
# every foreign key on the restored database is in the validated state.
notvalid=$(psql_dst "SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated;")
check "unvalidated foreign keys" "0" "$notvalid"

fk_total=$(psql_dst "SELECT count(*) FROM pg_constraint WHERE contype='f';")
echo "  (${fk_total} foreign key constraints present and validated)"
if [[ "$fk_total" -lt 20 ]]; then
  echo "  FAIL  implausibly few foreign keys -- constraints did not restore" >&2
  fail=1
fi

step "6. Verify the environment stamp survived"
# The boot gate refuses to start against a database stamped for a different
# environment. A restored copy keeps the source's stamp, which is correct and
# is exactly what stops a production dump from being booted locally by
# accident -- so assert it is present rather than absent.
stamp=$(psql_dst "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name='environment_stamp';" 2>/dev/null || echo 0)
if [[ "$stamp" == "1" ]]; then
  value=$(psql_dst "SELECT environment FROM environment_stamp LIMIT 1;" 2>/dev/null || echo "")
  if [[ -n "$value" ]]; then
    printf '  PASS  %-42s %s\n' "environment stamp preserved" "$value"
  else
    printf '  WARN  %-42s table present but unstamped\n' "environment stamp"
  fi
else
  printf '  WARN  %-42s no stamp table in this database\n' "environment stamp"
fi

step "Result"
if [[ "$fail" -eq 0 ]]; then
  echo "  RESTORE REHEARSAL PASSED -- ${table_count} tables, ${src_migrations} migrations verified."
  echo "  Artifact retained: ${DUMP_FILE}"
  exit 0
fi
echo "  RESTORE REHEARSAL FAILED -- see FAIL lines above." >&2
exit 1
