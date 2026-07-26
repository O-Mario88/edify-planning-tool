#!/usr/bin/env bash
#
# Rollback rehearsal.
#
# Rolling back is the thing you do when a release is already hurting people, at
# the point when nobody wants to discover a surprise. So the surprise gets
# discovered here instead.
#
# What a rollback actually is: the application goes back to the previous
# release; the DATABASE DOES NOT. Nobody un-migrates a production database
# under pressure — reversing a migration that dropped a column does not bring
# the data back, and reversing one that added a table is fine but pointless.
# The real question is therefore narrower and more useful:
#
#     Does the PREVIOUS release run against the CURRENT schema?
#
# If yes, rollback is a deploy of an older image and nothing more. If no, there
# is no rollback — only forward repair — and that is worth knowing before the
# incident rather than during it.
#
# This answers it by checking out the previous release into a worktree,
# pointing it at a restored copy of the database migrated to HEAD, and asking
# it to serve pages.
#
# Non-destructive: only ever creates and drops its own scratch database and
# worktree.
#
# Usage:
#     scripts/rollback_rehearsal.sh              # HEAD~1 against HEAD's schema
#     ROLLBACK_TO=v1.4.0 scripts/rollback_rehearsal.sh
#
# Exit code is 0 only if the previous release could serve the current schema.

set -Eeuo pipefail

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-edify}"
PGPASSWORD="${PGPASSWORD:-edify}"
SOURCE_DB="${PGDATABASE:-edify_pm}"
SCRATCH_DB="rollback_rehearsal_${SOURCE_DB}"
ROLLBACK_TO="${ROLLBACK_TO:-HEAD~1}"
WORKTREE="${WORKTREE:-.rollback-rehearsal-worktree}"
PYTHON_BIN="${PYTHON_BIN:-$PWD/.venv/bin/python}"

export PGHOST PGPORT PGUSER PGPASSWORD

fail=0
step() { printf '\n=== %s ===\n' "$1"; }
check() {
  if [[ "$2" == "$3" ]]; then
    printf '  PASS  %-46s %s\n' "$1" "$3"
  else
    printf '  FAIL  %-46s expected=%s actual=%s\n' "$1" "$2" "$3"
    fail=1
  fi
}

cleanup() {
  git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
  psql -X -q -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\";" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [[ "$SCRATCH_DB" == "$SOURCE_DB" ]]; then
  echo "REFUSING: scratch and source database are the same name." >&2
  exit 2
fi

CURRENT_SHA="$(git rev-parse --short HEAD)"
PREVIOUS_SHA="$(git rev-parse --short "$ROLLBACK_TO")"

step "0. What is being rehearsed"
printf '  current release   %s\n' "$CURRENT_SHA"
printf '  rolling back to   %s (%s)\n' "$PREVIOUS_SHA" "$ROLLBACK_TO"

step "1. Copy the database and migrate it to the CURRENT release"
# Dumped and restored rather than CREATE DATABASE ... TEMPLATE, which needs
# exclusive access to the source and so fails against anything that is actually
# running. A rehearsal that requires downtime to rehearse is one nobody runs.
psql -X -q -d postgres -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\";"
psql -X -q -d postgres -c "CREATE DATABASE \"$SCRATCH_DB\";"
pg_dump -d "$SOURCE_DB" -Fc | pg_restore -d "$SCRATCH_DB" --no-owner --no-privileges >/dev/null 2>&1
DATABASE_URL="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${SCRATCH_DB}" \
  DJANGO_SETTINGS_MODULE=config.settings.dev \
  "$PYTHON_BIN" manage.py migrate --no-input >/dev/null
echo "  copied and migrated to HEAD."

step "2. Check out the previous release"
git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true
git worktree add --detach "$WORKTREE" "$ROLLBACK_TO" >/dev/null 2>&1
echo "  $PREVIOUS_SHA checked out at $WORKTREE"

step "3. Would the previous release try to un-migrate anything?"
# The dangerous shape. If the old code's migration graph does not contain a
# migration the new one applied, the old code is running against a schema it
# has never seen. Additive changes are fine — an old release ignores a column
# it does not know about. Destructive ones are not.
current_leaf=$(DATABASE_URL="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${SCRATCH_DB}" \
  DJANGO_SETTINGS_MODULE=config.settings.dev \
  "$PYTHON_BIN" manage.py showmigrations --plan 2>/dev/null | grep -c '^\[X\]' || echo 0)
previous_known=$(cd "$WORKTREE" && DATABASE_URL="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${SCRATCH_DB}" \
  DJANGO_SETTINGS_MODULE=config.settings.dev \
  "$PYTHON_BIN" manage.py showmigrations --plan 2>/dev/null | grep -c '^\[' || echo 0)
printf '  migrations applied by the current release   %s\n' "$current_leaf"
printf '  migrations the previous release knows of    %s\n' "$previous_known"
if [[ "$previous_known" -lt "$current_leaf" ]]; then
  printf '  NOTE  the current release added %s migration(s) the previous one does not know.\n' \
    "$((current_leaf - previous_known))"
  echo   '        That is normal and safe when the change was additive. The next'
  echo   '        step is what actually decides it.'
fi

step "4. Serve pages from the previous release against the current schema"
# The only question that matters, answered by asking the old code to work.
#
# The smoke script is copied in rather than taken from the checkout. It is
# measuring apparatus, not part of the release — and an older release predates
# it, so reading it from there tests whether the harness existed yet instead of
# whether the rollback works. That is exactly the false negative this produced
# the first time it ran.
cp scripts/restore_smoke.py "$WORKTREE/scripts/restore_smoke.py"
if (cd "$WORKTREE" && RESTORE_SMOKE_DB="$SCRATCH_DB" PGPASSWORD="$PGPASSWORD" \
      "$PYTHON_BIN" scripts/restore_smoke.py); then
  check "previous release serves the current schema" "0" "0"
else
  check "previous release serves the current schema" "0" "1"
fi

step "Result"
if [[ "$fail" -eq 0 ]]; then
  echo "  ROLLBACK REHEARSAL PASSED"
  echo "  $PREVIOUS_SHA can serve the schema $CURRENT_SHA leaves behind."
  echo "  Rolling back is a deploy of the older image; the database stays put."
  exit 0
fi
echo "  ROLLBACK REHEARSAL FAILED" >&2
echo "  $PREVIOUS_SHA could NOT serve the schema $CURRENT_SHA leaves behind." >&2
echo "  There is no rollback for this release — only forward repair. Say so in" >&2
echo "  the release notes before shipping it, not after." >&2
exit 1
