#!/usr/bin/env bash
#
# BACKUP-01 — move the live database onto a tier that has backups, and prove
# the copy arrived intact.
#
# docs/runbooks.md §12 describes this as five manual steps. Five manual steps
# performed under time pressure, during or just before an incident, is how the
# verification step gets skipped — and the verification step is the entire
# point. This is those steps as one command that cannot skip its own check.
#
# WHAT IT DOES NOT DO
#
# It does not cut over. It does not touch the running app, change any spec, or
# alter DNS. It gets the new cluster to a state you can prove is correct, and
# then stops and tells you what it proved. Pointing production at the new
# cluster stays a human decision made with the evidence in hand.
#
# It does not write to the source. The source is production. This script
# connects to it read-only: one pg_dump inside a REPEATABLE READ snapshot, and
# nothing else. There is no DROP, no TRUNCATE, no ALTER anywhere in it that
# targets the source, and the preflight refuses if source and target resolve to
# the same database.
#
# WHAT IT PROVES
#
# The same thing scripts/backup_restore_rehearsal.sh proves, against the real
# migration rather than a scratch copy: that every row digest, index,
# constraint definition, view, matview, routine, trigger, policy, privilege,
# comment, large object, database setting, locale and sequence position in the
# target matches the dump that was taken from the source. Not a row count. Not
# a table count. The comparison that ISSUE-008 was written because the old gate
# did not make.
#
# Usage:
#     SOURCE_URL="postgresql://…/live"  \
#     TARGET_URL="postgresql://…/new"   \
#     scripts/migrate_to_managed_cluster.sh
#
#     ARTIFACT_DIR=/mnt/backups scripts/…    # where the dump and manifest land
#     RESUME=1 scripts/…                     # reuse an existing artifact pair
#     ALLOW_NONEMPTY_TARGET=1 scripts/…      # target already has objects
#
# Exit codes:
#     0  VERIFIED     the copy matches the dump; safe to cut over
#     1  FAILED       something is wrong; DO NOT cut over
#     2  REFUSED      preconditions not met; nothing was done
#
set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python}"
MANIFEST_TOOL="${REPO_ROOT}/scripts/restore_manifest.py"
ARTIFACT_DIR="${ARTIFACT_DIR:-${REPO_ROOT}/.migration}"
RESUME="${RESUME:-0}"
ALLOW_NONEMPTY_TARGET="${ALLOW_NONEMPTY_TARGET:-0}"

step()  { printf '\n=== %s ===\n' "$1"; }
pass()  { printf '  PASS  %-46s %s\n' "$1" "${2:-}"; }
fail()  { printf '  FAIL  %-46s %s\n' "$1" "${2:-}"; }

refuse() {
  printf '\nREFUSING: %s\n' "$1"
  printf '  Nothing has been changed. A refusal is not a failed migration and\n'
  printf '  it is certainly not a successful one.\n'
  exit 2
}

# A verdict is printed exactly once, by this trap, so there is no path that
# ends without one. The old backup gate could abort silently and leave the
# operator reading the last thing that scrolled past.
verdict_printed=0
on_exit() {
  local code=$?
  trap - ERR
  if [[ "$verdict_printed" -eq 0 && "$code" -ne 2 ]]; then
    printf '\n=== Result ===\n'
    printf '  MIGRATION FAILED — aborted before verifying (exit %s).\n' "$code"
    printf '  DO NOT cut over. The target is in an unknown state.\n'
    [[ "$code" -eq 0 ]] && code=1
  fi
  exit "$code"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

step "0. Preflight"

[[ -n "${SOURCE_URL:-}" ]] || refuse "SOURCE_URL is not set. It must point at the LIVE database."
[[ -n "${TARGET_URL:-}" ]] || refuse "TARGET_URL is not set. It must point at the NEW managed cluster."
[[ -x "$PYTHON_BIN" ]] || refuse "no interpreter at ${PYTHON_BIN}."
[[ -r "$MANIFEST_TOOL" ]] || refuse "missing ${MANIFEST_TOOL}."

for tool in pg_dump pg_restore psql; do
  command -v "$tool" >/dev/null 2>&1 || refuse "${tool} is not on PATH."
done

# The interpreter has to prove it is one. `/bin/true` is executable, answers
# everything with silence and success, and would turn every check below into a
# no-op while the run still reported success. That exact defect shipped in the
# backup gate this script's verifier replaced.
interpreter_id="$("$PYTHON_BIN" -c \
  'import sys, psycopg; print("MIGRATE-PY", sys.version.split()[0])' 2>&1 || true)"
[[ "$interpreter_id" == "MIGRATE-PY "* ]] || refuse \
  "${PYTHON_BIN} cannot read a manifest. It answered: ${interpreter_id:-(nothing)}"
pass "interpreter" "${interpreter_id#MIGRATE-PY }"

# Identity, not string equality: two different URLs can name one database.
source_id="$(psql -X -A -t -v ON_ERROR_STOP=1 -d "$SOURCE_URL" \
  -c "SELECT current_setting('cluster_name', true) || '|' || \
      inet_server_addr()::text || '|' || inet_server_port()::text || '|' || \
      current_database() || '|' || system_identifier::text \
      FROM pg_control_system();" 2>&1)" \
  || refuse "cannot connect to SOURCE_URL: ${source_id}"
target_id="$(psql -X -A -t -v ON_ERROR_STOP=1 -d "$TARGET_URL" \
  -c "SELECT current_setting('cluster_name', true) || '|' || \
      inet_server_addr()::text || '|' || inet_server_port()::text || '|' || \
      current_database() || '|' || system_identifier::text \
      FROM pg_control_system();" 2>&1)" \
  || refuse "cannot connect to TARGET_URL: ${target_id}"

if [[ "$source_id" == "$target_id" ]]; then
  refuse "SOURCE_URL and TARGET_URL are the same database (${source_id}).
          Restoring a database over itself is not a migration."
fi
pass "source and target are different databases" ""

source_db="$(psql -X -A -t -d "$SOURCE_URL" -c 'SELECT current_database()')"
target_db="$(psql -X -A -t -d "$TARGET_URL" -c 'SELECT current_database()')"
printf '  source: %s\n  target: %s\n' "$source_db" "$target_db"

# Restoring into a database that already holds objects merges two datasets and
# the result matches neither. Refused by default rather than discovered later.
target_objects="$(psql -X -A -t -v ON_ERROR_STOP=1 -d "$TARGET_URL" -c \
  "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname NOT IN ('pg_catalog','information_schema')
     AND n.nspname NOT LIKE 'pg_toast%' AND c.relkind IN ('r','p','m','S');")"
if [[ "$target_objects" -ne 0 && "$ALLOW_NONEMPTY_TARGET" != "1" ]]; then
  refuse "the target already holds ${target_objects} relation(s).
          Restoring on top of them merges two datasets into one that matches
          neither. Use a fresh database, or set ALLOW_NONEMPTY_TARGET=1 if you
          have decided that is what you want."
fi
pass "target is empty" "${target_objects} relation(s)"

mkdir -p "$ARTIFACT_DIR"
ARTIFACT_DIR="$(cd "$ARTIFACT_DIR" && pwd)"
DUMP_FILE="${ARTIFACT_DIR}/${source_db}-migration.dump"
MANIFEST_FILE="${ARTIFACT_DIR}/${source_db}-migration.manifest.json"

step "1. Take a verified dump of the LIVE database (read-only)"

if [[ "$RESUME" == "1" && -s "$DUMP_FILE" && -s "$MANIFEST_FILE" ]]; then
  pass "reusing existing artifact" "$(basename "$DUMP_FILE")"
  if ! "$PYTHON_BIN" "$MANIFEST_TOOL" checkdump "$MANIFEST_FILE" "$DUMP_FILE" "resume"; then
    fail "the retained dump does not match its manifest" \
         "re-run without RESUME=1"
    printf '\n=== Result ===\n  MIGRATION FAILED — the artifact on disk is not the one described.\n'
    verdict_printed=1
    exit 1
  fi
else
  # The manifest is read inside the dump's own exported snapshot, so it
  # describes the bytes in the file rather than whatever the source drifted to
  # while the dump was running. That is what makes step 4 mean anything on a
  # database still taking writes.
  if ! REHEARSAL_DSN="$SOURCE_URL" "$PYTHON_BIN" "$MANIFEST_TOOL" \
       capture "$MANIFEST_FILE" "$DUMP_FILE"; then
    fail "capture" "could not dump and describe the source"
    printf '\n=== Result ===\n  MIGRATION FAILED — no usable backup was taken. Nothing was changed.\n'
    verdict_printed=1
    exit 1
  fi
fi
pass "dump" "$(du -h "$DUMP_FILE" | cut -f1) at ${DUMP_FILE}"
pass "manifest" "$(basename "$MANIFEST_FILE")"

# Is there anything in here worth migrating? An empty source restores
# perfectly and proves nothing, and "0 rows moved successfully" should not read
# as success.
evidence_status=0
"$PYTHON_BIN" "$MANIFEST_TOOL" evidence "$MANIFEST_FILE" || evidence_status=$?
if [[ "$evidence_status" -eq 3 ]]; then
  fail "the source has nothing in it" \
       "migrating an empty database proves nothing about the real one"
  printf '\n=== Result ===\n  NOT PROVEN — the source is empty. Check SOURCE_URL points at production.\n'
  verdict_printed=1
  exit 1
fi

step "2. Restore into the new cluster"

if ! "$PYTHON_BIN" "$MANIFEST_TOOL" checkdump "$MANIFEST_FILE" "$DUMP_FILE" "before restore"; then
  fail "the dump changed after it was written" "not restoring an artifact this run cannot vouch for"
  printf '\n=== Result ===\n  MIGRATION FAILED — artifact integrity. Nothing was restored.\n'
  verdict_printed=1
  exit 1
fi

# --exit-on-error so a partial restore is a failure rather than a warning
# scrolled past.
#
# Note what is NOT here: --no-owner and --no-privileges. Both are omitted
# deliberately, and omitting is the whole mechanism — there is no "keep the
# owners" flag to pass. (An earlier draft wrote `--no-owner=false` reaching for
# one; pg_restore rejected it outright, which is the only reason this comment
# is not describing a silent behaviour change.) A database restored without its
# GRANTs is one the application role cannot read, and it looks perfectly
# healthy from psql as the owner — the failure surfaces as "permission denied
# for table school" the moment real traffic arrives.
restore_log="${ARTIFACT_DIR}/pg_restore.log"
if ! pg_restore --exit-on-error -d "$TARGET_URL" "$DUMP_FILE" \
     >"$restore_log" 2>&1; then
  fail "pg_restore" "see ${restore_log}"
  tail -20 "$restore_log" | sed 's/^/      /'
  printf '\n=== Result ===\n  MIGRATION FAILED — the restore did not complete. DO NOT cut over.\n'
  verdict_printed=1
  exit 1
fi
pass "restored" "$(basename "$DUMP_FILE")"

if ! "$PYTHON_BIN" "$MANIFEST_TOOL" checkdump "$MANIFEST_FILE" "$DUMP_FILE" "after restore"; then
  fail "the dump changed while it was being restored" \
       "the copy was not built from the artifact this run verified"
  printf '\n=== Result ===\n  MIGRATION FAILED — DO NOT cut over.\n'
  verdict_printed=1
  exit 1
fi

step "3. Verify the copy against the dump — the step this script exists for"

if ! REHEARSAL_DSN="$TARGET_URL" "$PYTHON_BIN" "$MANIFEST_TOOL" verify "$MANIFEST_FILE"; then
  fail "the copy differs from the backup" "see the FAIL lines above"
  printf '\n=== Result ===\n'
  printf '  MIGRATION FAILED — the new cluster does not match the source.\n'
  printf '  DO NOT cut over. The source is untouched and still authoritative.\n'
  verdict_printed=1
  exit 1
fi

step "4. Does the new cluster actually have a backup yet?"

# A tier that CAN take backups is not the same as this cluster HAVING one, and
# BACKUP-01 is about the difference. Reported either way; not fatal, because
# the first automatic backup is typically hours away.
if command -v doctl >/dev/null 2>&1 && [[ -n "${DO_CLUSTER_ID:-}" ]]; then
  backups="$(doctl databases backups "$DO_CLUSTER_ID" --format Created --no-header 2>&1 || true)"
  if [[ -z "$(printf '%s' "$backups" | tr -d '[:space:]')" ]]; then
    printf '  ....  %-46s %s\n' "no backup taken yet" \
      "the tier supports them; this cluster has none so far"
  else
    pass "backups exist on the target" "$(printf '%s' "$backups" | wc -l) found"
  fi
else
  printf '  ....  %-46s %s\n' "not checked" \
    "set DO_CLUSTER_ID and install doctl to confirm backups exist"
fi

step "Result"
verdict_printed=1
cat <<EOF
  MIGRATION VERIFIED — the new cluster matches the backup taken from the
  source, on every comparison scripts/restore_manifest.py makes.

  The source is UNTOUCHED and is still the authoritative database. Nothing has
  been cut over: this script does not change the running app.

  To cut over, in this order:
    1. Put the app in maintenance, so no write lands only on the old database.
    2. Re-run this script with RESUME=0 to capture and verify again — the
       delta since the dump above is the window of writes you would lose.
    3. Point DATABASE_URL at the new cluster and deploy.
    4. Confirm 'doctl databases backups <cluster-id>' returns a backup before
       you consider BACKUP-01 closed.
    5. Keep the old database for at least a week. Do not release it the same
       day.

  Artifacts kept: ${DUMP_FILE}
                  ${MANIFEST_FILE}
EOF
exit 0
