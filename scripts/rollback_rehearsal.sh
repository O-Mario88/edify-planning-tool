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
# Non-destructive: it only ever creates and removes a scratch database and a
# worktree THIS RUN CREATED. That sentence used to be false. `cleanup` ran
#     git worktree remove --force "$WORKTREE"
# unconditionally, as its first statement, ahead of the ownership check below
# it — so an aborted run destroyed a pre-existing worktree with uncommitted
# work in it. That is the same defect class that destroyed a developer database
# on this project: a destructive path running ahead of the guard meant to vet
# its target.
#
# Usage:
#     scripts/rollback_rehearsal.sh              # HEAD~1 against HEAD's schema
#     ROLLBACK_TO=v1.4.0 scripts/rollback_rehearsal.sh
#     KEEP_SCRATCH_ON_FAIL=1 scripts/rollback_rehearsal.sh   # keep the evidence
#
# Exit codes:
#     0  PASSED       the previous release served the current schema
#     1  FAILED       it could not
#     2  REFUSED      the rehearsal would not be safe or meaningful to run
#     3  NOT PROVEN   nothing failed, and nothing was demonstrated either

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-edify}"
PGPASSWORD="${PGPASSWORD:-edify}"
SOURCE_DB="${PGDATABASE:-edify_pm}"
SCRATCH_PREFIX="rollback_rehearsal_"
_scratch_stem="$(printf '%s' "$SOURCE_DB" | tr -c 'A-Za-z0-9_' '_')"
_scratch_suffix="$$_$(date -u +%H%M%S)"
_scratch_room=$((63 - ${#SCRATCH_PREFIX} - ${#_scratch_suffix} - 1))
# Unique per run, so two rehearsals cannot destroy each other's scratch copy
# and then both report that the previous release could not serve the schema.
SCRATCH_DB="${SCRATCH_DB:-${SCRATCH_PREFIX}${_scratch_stem:0:${_scratch_room}}_${_scratch_suffix}}"
ROLLBACK_TO="${ROLLBACK_TO:-HEAD~1}"
# Absolute. Relative to $PWD, this pointed at a different place depending on
# where the script was run from, and so did PYTHON_BIN below it — run from
# scripts/, the rehearsal died with exit 127, no FAIL line, no verdict, and
# then dropped its scratch database so there was nothing to look at.
WORKTREE="${WORKTREE:-${REPO_ROOT}/.rollback-rehearsal-worktree-$$}"
PYTHON_BIN="${PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python}"
SMOKE_TOOL="${REPO_ROOT}/scripts/restore_smoke.py"
MANIFEST_TOOL="${REPO_ROOT}/scripts/restore_manifest.py"
ARTIFACT_DIR="${ARTIFACT_DIR:-${REPO_ROOT}/.backup-rehearsal}"
KEEP_SCRATCH_ON_FAIL="${KEEP_SCRATCH_ON_FAIL:-0}"

export PGHOST PGPORT PGUSER PGPASSWORD

fail=0
unproven=0
reached_result=0
scratch_created=0
worktree_created=0

step() { printf '\n=== %s ===\n' "$1"; }

note_fail() { # note_fail <label> <detail>
  printf '  FAIL  %-46s %s\n' "$1" "$2"
  fail=1
}

note_unproven() { # note_unproven <label> <detail>
  printf '  NOT PROVEN  %-42s %s\n' "$1" "$2"
  unproven=1
}

# The single source of truth for "is this script allowed to DROP that name?".
# The refusals, the main line and the cleanup trap all consult it.
# Prints the reason and returns 0 when the name is UNSAFE; returns 1 when safe.
unsafe_scratch_reason() { # unsafe_scratch_reason <name>
  local name=${1:-}
  if [[ -z "$name" ]]; then
    echo "the scratch database name is empty"
    return 0
  fi
  # Protected names first. Behind the prefix rule this case was unreachable --
  # no protected name carries the rollback_rehearsal_ prefix -- so a reader
  # checking that the developer database was named in a guard was reading dead
  # code, and `SCRATCH_DB=edify` was refused for the wrong reason.
  case "$name" in
    postgres | template0 | template1 | edify | edify_* | test_*)
      echo "${name} is a protected database and will not be dropped"
      return 0
      ;;
  esac
  if [[ "$name" == "$SOURCE_DB" ]]; then
    echo "scratch and source database are the same name (${name})"
    return 0
  fi
  if [[ ! "$name" =~ ^rollback_rehearsal_[A-Za-z0-9_]+$ ]]; then
    echo "${name} is not of the form ${SCRATCH_PREFIX}<letters, digits, underscores>, and this script DROPs the scratch database"
    return 0
  fi
  return 1
}

aborted=0
on_err() { # on_err <exit-code> <line> <command>
  if [[ "$aborted" -eq 1 ]]; then
    return 0
  fi
  aborted=1
  printf '\n  FAIL  %-46s exit=%s at line %s: %s\n' \
    "rehearsal aborted by an unhandled error" "$1" "$2" "$3"
  fail=1
  return 0
}
# This script had no ERR trap at all, so an abort produced no FAIL line and no
# verdict of any kind -- just a shell error and an exit code nobody read.
trap 'on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR

drop_scratch() {
  local output refusal
  if [[ "$scratch_created" -ne 1 ]]; then
    return 0
  fi
  if refusal=$(unsafe_scratch_reason "$SCRATCH_DB"); then
    printf '  NOT dropping %s: %s.\n' "$SCRATCH_DB" "$refusal"
    return 1
  fi
  if output=$(psql -X -q -v ON_ERROR_STOP=1 -d postgres \
    -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\" WITH (FORCE);" 2>&1); then
    scratch_created=0
    return 0
  fi
  printf '  FAIL  %-46s %s\n' "could not drop ${SCRATCH_DB}" \
    "$(printf '%s' "$output" | tr '\n' ' ')"
  return 1
}

remove_worktree() {
  # Only ever remove a worktree THIS RUN created. There is no way to tell a
  # borrowed one from ours after the fact, so the flag is the whole guard --
  # and the previous version had no flag for the worktree at all, only for the
  # database, and removed the worktree --force before even reaching it.
  if [[ "$worktree_created" -ne 1 ]]; then
    return 0
  fi
  git -C "$REPO_ROOT" worktree remove --force "$WORKTREE" >/dev/null 2>&1 || {
    printf '  FAIL  %-46s %s\n' "could not remove the worktree" "$WORKTREE"
    return 1
  }
  worktree_created=0
  return 0
}

cleanup() {
  local code=$?
  # Disarm ERR first: bash re-fires it on an early `return` from an EXIT-trap
  # function with a pending non-zero status, printing a phantom abort under
  # the verdict it contradicts.
  trap - ERR
  if [[ "$reached_result" -eq 0 ]]; then
    printf '\n=== Result ===\n'
    if [[ "$code" -eq 2 ]]; then
      echo "  ROLLBACK REHEARSAL REFUSED -- see the REFUSING line above."
    else
      echo "  ROLLBACK REHEARSAL FAILED -- aborted before finishing (exit ${code})."
    fi
    if [[ "$code" -eq 0 ]]; then
      # cleanup never exited, so its own status became the script's, and an
      # interrupted run reported success.
      code=1
    fi
  fi
  if [[ "$code" -ne 0 && "$KEEP_SCRATCH_ON_FAIL" == "1" ]]; then
    if [[ "$scratch_created" -eq 1 ]]; then
      echo "  scratch database RETAINED for inspection: ${SCRATCH_DB}"
    fi
    if [[ "$worktree_created" -eq 1 ]]; then
      echo "  worktree RETAINED for inspection: ${WORKTREE}"
    fi
    exit "$code"
  fi
  remove_worktree || code=1
  if [[ "$scratch_created" -eq 1 ]] && ! drop_scratch; then
    code=1
  fi
  exit "$code"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

step "0. Refusals and preflight"
if refusal=$(unsafe_scratch_reason "$SCRATCH_DB"); then
  echo "REFUSING: ${refusal}."
  exit 2
fi
if [[ "$SOURCE_DB" == "$SCRATCH_PREFIX"* ]]; then
  echo "REFUSING: source ${SOURCE_DB} is itself a rollback scratch database."
  exit 2
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "REFUSING: no executable interpreter at ${PYTHON_BIN}."
  exit 2
fi
# The interpreter has to prove it is one. `-x` alone accepts /bin/true, which
# answers every invocation with silence and success.
interpreter_id="$("$PYTHON_BIN" -c \
  'import sys, psycopg; print("REHEARSAL-PY", sys.version.split()[0])' 2>&1 || true)"
if [[ "$interpreter_id" != "REHEARSAL-PY "* ]]; then
  echo "REFUSING: ${PYTHON_BIN} is not a Python that can run this rehearsal."
  echo "          It answered: ${interpreter_id:-(nothing at all)}"
  exit 2
fi
if [[ -e "$WORKTREE" ]]; then
  echo "REFUSING: ${WORKTREE} already exists."
  echo "          This run did not create it, so it will not remove it."
  exit 2
fi
existing=$(psql -X -q -A -t -v ON_ERROR_STOP=1 -d postgres \
  -c "SELECT 1 FROM pg_database WHERE datname = '${SCRATCH_DB//\'/\'\'}';")
if [[ -n "$existing" ]]; then
  echo "REFUSING: ${SCRATCH_DB} already exists on this host."
  exit 2
fi
printf '  PASS  %-46s source=%s scratch=%s\n' "refusals and preflight" "$SOURCE_DB" "$SCRATCH_DB"

mkdir -p "$ARTIFACT_DIR"
ARTIFACT_DIR="$(cd "$ARTIFACT_DIR" && pwd)"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
DUMP_FILE="${ARTIFACT_DIR}/${SOURCE_DB}-rollback-${RUN_ID}.dump"

CURRENT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
PREVIOUS_SHA="$(git -C "$REPO_ROOT" rev-parse --short "$ROLLBACK_TO")"

step "1. What is being rehearsed"
printf '  current release   %s\n' "$CURRENT_SHA"
printf '  rolling back to   %s (%s)\n' "$PREVIOUS_SHA" "$ROLLBACK_TO"

step "2. Copy the database and migrate it to the CURRENT release"
# Dumped and restored rather than CREATE DATABASE ... TEMPLATE, which needs
# exclusive access to the source and so fails against anything that is actually
# running. A rehearsal that requires downtime to rehearse is one nobody runs.
#
# --create, and the scratch database built from the artifact's own statements,
# so the copy carries the source's encoding, locale and database settings
# rather than the cluster's defaults. Errors are NOT discarded: this used to be
#     pg_dump ... | pg_restore ... >/dev/null 2>&1
# with no --exit-on-error, so a partially restored database went on to migrate
# and serve pages as though nothing had happened.
pg_dump --format=custom --compress=0 --create --file="$DUMP_FILE" -d "$SOURCE_DB"
# Ownership of the name is claimed BEFORE anything can create it. The artifact's
# database section is several statements, and a failure part way through left
# the database created and the flag clear -- so cleanup skipped the drop and a
# full copy of the source stayed on the host, unmentioned. Observed on the
# sibling script. Claiming early cannot drop anything that is not ours: the name
# matched the strict pattern, preflight proved it did not already exist, and
# drop_scratch re-asserts the pattern at the moment of the drop.
scratch_created=1
"$PYTHON_BIN" "$MANIFEST_TOOL" prepare "$DUMP_FILE" "$SCRATCH_DB" "$SOURCE_DB" \
  | psql -X -q -v ON_ERROR_STOP=1 -d postgres
pg_restore --exit-on-error -d "$SCRATCH_DB" "$DUMP_FILE"
SCRATCH_URL="postgresql://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${SCRATCH_DB}"
if ! DATABASE_URL="$SCRATCH_URL" DJANGO_SETTINGS_MODULE=config.settings.dev \
  "$PYTHON_BIN" "${REPO_ROOT}/manage.py" migrate --no-input > /dev/null; then
  note_fail "migrate the copy to the current release" "manage.py migrate failed"
  step "Result"
  reached_result=1
  echo "  ROLLBACK REHEARSAL FAILED -- the current release cannot migrate its own copy."
  exit 1
fi
echo "  copied and migrated to HEAD."

step "3. Check out the previous release"
git -C "$REPO_ROOT" worktree add --detach "$WORKTREE" "$ROLLBACK_TO" >/dev/null 2>&1
worktree_created=1
echo "  $PREVIOUS_SHA checked out at $WORKTREE"

step "4. Would the previous release try to un-migrate anything?"
# The dangerous shape. If the old code's migration graph does not contain a
# migration the new one applied, the old code is running against a schema it
# has never seen. Additive changes are fine — an old release ignores a column
# it does not know about. Destructive ones are not.
#
# This step used to have no failing path at all: both sides were counted with
#     $(... | grep -c ... || echo 0)
# under `2>/dev/null`, so a showmigrations that failed outright reported 0,
# the other side reported 0, the comparison came out equal and the step passed
# in silence. It now reads NAMES, fails when either side cannot be read, and
# fails on the one condition that actually breaks a rollback: the previous
# release expecting a migration this database does not have.
plan_names() { # plan_names <cwd> -> "app.name" per line, or non-zero
  (cd "$1" && DATABASE_URL="$SCRATCH_URL" DJANGO_SETTINGS_MODULE=config.settings.dev \
    "$PYTHON_BIN" manage.py showmigrations --plan 2>/dev/null) \
    | sed -n 's/^\[.\]  *\([^ ]*\).*$/\1/p'
}
applied_now=$(psql -X -q -A -t -v ON_ERROR_STOP=1 -d "$SCRATCH_DB" \
  -c "SELECT app||'.'||name FROM django_migrations ORDER BY 1;" | sort -u)
if ! previous_known=$(plan_names "$WORKTREE") || [[ -z "$previous_known" ]]; then
  note_fail "read the previous release's migration plan" \
    "manage.py showmigrations produced nothing in ${WORKTREE}"
  previous_known=""
else
  previous_known=$(printf '%s\n' "$previous_known" | sort -u)
fi
if [[ -z "$applied_now" ]]; then
  note_fail "read the applied migrations" "django_migrations is empty in the copy"
fi
added=$(comm -23 <(printf '%s\n' "$applied_now") <(printf '%s\n' "$previous_known") | grep -c . || true)
missing=$(comm -13 <(printf '%s\n' "$applied_now") <(printf '%s\n' "$previous_known") || true)
printf '  migrations applied on the copy              %s\n' "$(printf '%s\n' "$applied_now" | grep -c . || true)"
printf '  migrations the previous release knows of    %s\n' "$(printf '%s\n' "$previous_known" | grep -c . || true)"
if [[ "$added" -gt 0 ]]; then
  printf '  NOTE  the current release added %s migration(s) the previous one does not know.\n' "$added"
  echo   '        That is normal and safe when the change was additive. Step 5 decides it.'
fi
if [[ -n "$missing" ]]; then
  # The previous release expects schema this database does not have. Not a
  # rollback: a forward repair.
  note_fail "the previous release expects migrations this copy lacks" \
    "$(printf '%s' "$missing" | tr '\n' ' ' | cut -c1-90)"
else
  printf '  PASS  %-46s %s\n' "no migration the previous release needs is absent" "0 missing"
fi

step "5. Serve pages from the previous release against the current schema"
# The only question that matters, answered by asking the old code to work.
#
# The smoke script is copied in rather than taken from the checkout. It is
# measuring apparatus, not part of the release — and an older release predates
# it, so reading it from there tests whether the harness existed yet instead of
# whether the rollback works. That is exactly the false negative this produced
# the first time it ran. Absolute paths, so it does not depend on the cwd.
mkdir -p "${WORKTREE}/scripts"
cp "$SMOKE_TOOL" "${WORKTREE}/scripts/restore_smoke.py"
smoke_status=0
(cd "$WORKTREE" && RESTORE_SMOKE_DB="$SCRATCH_DB" "$PYTHON_BIN" scripts/restore_smoke.py) \
  || smoke_status=$?
if [[ "$smoke_status" -eq 3 ]]; then
  note_unproven "previous release serves the current schema" \
    "the copy has no account to sign in as -- nothing was exercised"
elif [[ "$smoke_status" -ne 0 ]]; then
  note_fail "previous release serves the current schema" "see the FAIL lines above"
else
  printf '  PASS  %-46s %s\n' "previous release serves the current schema" "$PREVIOUS_SHA"
fi

step "Result"
reached_result=1
if [[ "$fail" -eq 0 && "$unproven" -eq 0 ]]; then
  remove_worktree || fail=1
  drop_scratch || fail=1
fi
if [[ "$fail" -ne 0 ]]; then
  echo "  ROLLBACK REHEARSAL FAILED"
  echo "  $PREVIOUS_SHA could NOT serve the schema $CURRENT_SHA leaves behind."
  echo "  There is no rollback for this release — only forward repair. Say so in"
  echo "  the release notes before shipping it, not after."
  if [[ "$KEEP_SCRATCH_ON_FAIL" != "1" ]]; then
    echo "  Re-run with KEEP_SCRATCH_ON_FAIL=1 to keep the copy and the worktree."
  fi
  exit 1
fi
if [[ "$unproven" -ne 0 ]]; then
  echo "  ROLLBACK REHEARSAL NOT PROVEN -- nothing failed, and nothing was shown."
  exit 3
fi
echo "  ROLLBACK REHEARSAL PASSED"
echo "  $PREVIOUS_SHA can serve the schema $CURRENT_SHA leaves behind."
echo "  Rolling back is a deploy of the older image; the database stays put."
exit 0
