#!/usr/bin/env bash
#
# Backup / restore rehearsal.
#
# A backup that has never been restored is not a backup, it is a file. This
# script proves the round trip end to end: dump the live database, create a
# scratch database FROM THE DUMP'S OWN CREATE DATABASE STATEMENT, restore into
# it, and verify the restored copy against a manifest of what the dump actually
# contained.
#
# WHY IT NO LONGER USES THRESHOLDS
#
# It used to verify a restore with three floors -- the dump must exceed 100,000
# bytes, the restored copy must carry at least 50 tables and at least 20
# foreign keys -- and with per-table row counts read from the LIVE SOURCE at
# verification time. Measured against this schema with EVERY TABLE EMPTY:
# the dump is 1,778,821 bytes (17.8x the floor), the wiped database still has
# 308 tables (6.2x) and 382 constraints (19.1x), and every row-count comparison
# is 0 == 0, so it printed "PASS all table row counts 308 tables identical".
# The gate passed a database that had been wiped.
#
# WHY IT NO LONGER LOOKS ONLY AT ROWS
#
# Replacing the floors with row digests closed the row-shaped hole and left
# everything else open. Measured, on restores the row-digest version certified:
# every GRANT discarded (--no-privileges), so the application role got
# "permission denied for table school"; every ALTER DATABASE ... SET discarded
# (no --create); the scratch database created with a bare CREATE DATABASE, so
# it took its LOCALE from the cluster's template1 rather than from the source,
# and inherited whatever a colleague had left in template1; materialised views
# recomputed rather than restored; 1,881 missing indexes, a missing schema, a
# CHECK weakened to CHECK (true), an FK that gained ON DELETE CASCADE, missing
# triggers, functions, views and large objects -- none of it looked at. The
# dump file could even be swapped for a different one between the hash and the
# restore and the run still printed PASSED.
#
# So: the dump is taken with --create and WITH privileges and ownership; the
# scratch database is created by replaying the artifact's own database-level
# statements; and scripts/restore_manifest.py compares the restored copy
# against the whole of what the dump contained -- schemas, relations, columns,
# indexes, constraint DEFINITIONS, views, matviews, routines, triggers,
# policies, extensions, comments, ACLs, large objects, database settings and
# locale, per-table row counts and content digests, and sequence positions
# read out of the ARTIFACT rather than off the live source.
#
# It is deliberately non-destructive to the source. It only ever CREATEs and
# DROPs its own scratch database, whose name must match a fixed pattern, is
# unique to this run, and is refused if it already exists.
#
# Usage:
#     scripts/backup_restore_rehearsal.sh                # rehearse against dev
#     PGDATABASE=edify_staging scripts/backup_restore_rehearsal.sh
#     KEEP_SCRATCH_ON_FAIL=1 scripts/backup_restore_rehearsal.sh   # keep evidence
#
# Exit codes:
#     0  PASSED       every verification passed
#     1  FAILED       something is wrong with the backup or the restore
#     2  REFUSED      the rehearsal would not be safe or meaningful to run
#     3  NOT PROVEN   nothing failed, and nothing was demonstrated either --
#                     an empty or never-used source cannot evidence a round
#                     trip. Distinct from 1 so "your backup is broken" and
#                     "this run could not tell" are not the same answer.

set -Eeuo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PGHOST="${PGHOST:-127.0.0.1}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-edify}"
PGPASSWORD="${PGPASSWORD:-edify}"
SOURCE_DB="${PGDATABASE:-edify_pm}"
SCRATCH_PREFIX="restore_rehearsal_"

# Unique per run. A name derived from the source alone meant two runs against
# the same database -- a nightly gate and one manual run, a CI matrix, a retry
# -- silently destroyed each other's scratch database and BOTH then reported
# "restored copy differs from the dump", which is the one message an operator
# has to be able to trust. It also meant the next run deleted the copy the
# previous run had been told to retain for post-mortem.
_scratch_stem="$(printf '%s' "$SOURCE_DB" | tr -c 'A-Za-z0-9_' '_')"
_scratch_suffix="$$_$(date -u +%H%M%S)"
# Postgres identifiers are capped at 63 bytes; keep the prefix and the run id
# and give up the middle, which is only there to be recognisable.
_scratch_room=$((63 - ${#SCRATCH_PREFIX} - ${#_scratch_suffix} - 1))
SCRATCH_DB="${SCRATCH_DB:-${SCRATCH_PREFIX}${_scratch_stem:0:${_scratch_room}}_${_scratch_suffix}}"

# Absolute, so the rehearsal writes its 8 MB copy of production-shaped data
# into a known place rather than into whatever directory it happened to be run
# from -- which was outside .gitignore's reach and outside anyone's cleanup.
ARTIFACT_DIR="${ARTIFACT_DIR:-${REPO_ROOT}/.backup-rehearsal}"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
# Absolute, so the rehearsal works from any working directory. A relative
# ".venv/bin/python" silently missed whenever the script was not run from the
# repository root, and the run then skipped its only real check and still
# printed PASSED.
PYTHON_BIN="${PYTHON_BIN:-${REPO_ROOT}/.venv/bin/python}"
MANIFEST_TOOL="${REPO_ROOT}/scripts/restore_manifest.py"
SMOKE_TOOL="${REPO_ROOT}/scripts/restore_smoke.py"
KEEP_SCRATCH_ON_FAIL="${KEEP_SCRATCH_ON_FAIL:-0}"

# PGPASSWORD is exported, not embedded in the connection strings below, for two
# reasons: child processes (restore_manifest.py, restore_smoke.py, pg_dump,
# pg_restore) all read it from the environment, and a password in argv is
# visible to every user on the host via `ps`.
export PGHOST PGPORT PGUSER PGPASSWORD

SOURCE_DSN="host=${PGHOST} port=${PGPORT} user=${PGUSER} dbname=${SOURCE_DB}"

fail=0
unproven=0
reached_result=0
scratch_created=0
scratch_retained=0
drop_attempted=0

# Everything goes to stdout, deliberately. note_fail used to write to stderr
# while check() wrote to stdout, so half the failures vanished under
# `2>/dev/null` and the order of a combined log was not reliable. The exit code
# is the machine-readable verdict; the log should read in the order it happened.
step() { printf '\n=== %s ===\n' "$1"; }

note_fail() { # note_fail <label> <detail>
  printf '  FAIL  %-42s %s\n' "$1" "$2"
  fail=1
}

note_unproven() { # note_unproven <label> <detail>
  printf '  NOT PROVEN  %-38s %s\n' "$1" "$2"
  unproven=1
}

check() { # check <label> <expected> <actual>
  if [[ -z "${2:-}" && -z "${3:-}" ]]; then
    # Two empty strings are equal, which is how this check used to pass on a
    # database where the query returned no rows at all. Nothing compared is
    # not the same as everything matched.
    printf '  FAIL  %-42s no value on either side -- the query returned nothing\n' "$1"
    fail=1
  elif [[ "$2" == "$3" ]]; then
    printf '  PASS  %-42s %s\n' "$1" "$3"
  else
    printf '  FAIL  %-42s expected=%s actual=%s\n' "$1" "$2" "$3"
    fail=1
  fi
}

# ON_ERROR_STOP so a SQL error is a failure rather than a message scrolled past
# with a zero exit code.
psql_dst() { psql -X -q -A -t -v ON_ERROR_STOP=1 -d "$SCRATCH_DB" -c "$1"; }

manifest_rowcount() { # manifest_rowcount <table> -> the count the dump holds
  "$PYTHON_BIN" "$MANIFEST_TOOL" rowcount "$MANIFEST_FILE" "$1"
}

# The single source of truth for "is this script allowed to DROP that name?".
# The refusals, the main line and the cleanup trap all consult it, so no
# destructive path can act on a name the refusals would have rejected.
# Splitting those apart is how a cleanup path ends up dropping the very
# database the guard was written to protect. It has done exactly that.
# Prints the reason and returns 0 when the name is UNSAFE; returns 1 when safe.
unsafe_scratch_reason() { # unsafe_scratch_reason <name>
  local name=${1:-}
  if [[ -z "$name" ]]; then
    echo "the scratch database name is empty"
    return 0
  fi
  # Protected names are tested FIRST. Behind the prefix rule this case was
  # unreachable -- no protected name carries the restore_rehearsal_ prefix --
  # so `SCRATCH_DB=edify` was refused with the wrong reason, and a reader
  # checking that the developer database was named in a guard was reading dead
  # code.
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
  # A strict pattern, not just a prefix. SCRATCH_DB is interpolated into
  # DROP DATABASE and CREATE DATABASE; hand-rolled "\"" quoting around an
  # arbitrary string is one missing escape away from being an injection, and
  # was previously stopped only by Postgres's own refusal to run DROP DATABASE
  # inside a transaction block -- i.e. by luck.
  if [[ ! "$name" =~ ^restore_rehearsal_[A-Za-z0-9_]+$ ]]; then
    echo "${name} is not of the form ${SCRATCH_PREFIX}<letters, digits, underscores>, and this script DROPs the scratch database"
    return 0
  fi
  return 1
}

# An unhandled error used to abort the run silently: no FAIL line, no Result
# section, and the EXIT trap then dropped the scratch database, so there was
# nothing left to look at either. Say what happened, and say it before exiting.
aborted=0
on_err() { # on_err <exit-code> <line> <command>
  # set -E makes the ERR trap inherited by functions, so one failing command
  # fires it once inside the function and again as the failure unwinds. Report
  # the abort once, at the innermost point, which is where the line number is
  # actually useful.
  if [[ "$aborted" -eq 1 ]]; then
    return 0
  fi
  aborted=1
  printf '\n  FAIL  %-42s exit=%s at line %s: %s\n' \
    "rehearsal aborted by an unhandled error" "$1" "$2" "$3"
  fail=1
  return 0
}
trap 'on_err "$?" "$LINENO" "$BASH_COMMAND"' ERR

# drop_scratch: the one statement in this script that destroys data.
# Loud, checked, and never silently best-effort. The previous version ran
# `psql ... >/dev/null 2>&1 || true`: one open session was enough to make the
# drop fail, and the script then printed PASSED, exited 0, and left a near-copy
# of production data on the host with no message at all.
drop_scratch() {
  local output
  if [[ "$scratch_created" -ne 1 ]]; then
    return 0
  fi
  local refusal
  # Re-assert the naming invariant at the moment of the drop, not only at the
  # moment of the decision.
  if refusal=$(unsafe_scratch_reason "$SCRATCH_DB"); then
    printf '  NOT dropping %s: %s.\n' "$SCRATCH_DB" "$refusal"
    return 1
  fi
  # WITH (FORCE) terminates sessions still attached. Safe precisely because
  # this database is provably ours: the name is unique to this run and the
  # rehearsal refused to start if it already existed.
  if output=$(psql -X -q -v ON_ERROR_STOP=1 -d postgres \
    -c "DROP DATABASE IF EXISTS \"$SCRATCH_DB\" WITH (FORCE);" 2>&1); then
    scratch_created=0
    return 0
  fi
  printf '  FAIL  %-42s %s\n' "could not drop scratch database ${SCRATCH_DB}" \
    "$(printf '%s' "$output" | tr '\n' ' ')"
  return 1
}

cleanup() {
  local code=$?
  # Disarm ERR before anything else. Bash re-fires the ERR trap on an early
  # `return` from an EXIT-trap function with a pending non-zero status, so
  # every failing run used to end with
  #   FAIL rehearsal aborted by an unhandled error exit=1 at line 1: exit 1
  # printed directly underneath the verdict it contradicted.
  trap - ERR
  if [[ "$reached_result" -eq 0 ]]; then
    printf '\n=== Result ===\n'
    if [[ "$code" -eq 2 ]]; then
      # A refusal is not a failed rehearsal. It is a rehearsal that declined to
      # start, and calling it FAILED sends somebody looking for a broken backup.
      echo "  RESTORE REHEARSAL REFUSED -- see the REFUSING line above."
    else
      echo "  RESTORE REHEARSAL FAILED -- aborted before finishing (exit ${code})."
    fi
    if [[ "$code" -eq 0 ]]; then
      # A trap that runs with $? = 0 but never reached the Result section is a
      # run that was interrupted. It used to fall out of cleanup with the
      # status of its last command -- `|| true` -- so Ctrl-C reported success
      # and CI recorded a PASS.
      code=1
    fi
  fi
  if [[ "$scratch_created" -eq 1 ]]; then
    if [[ "$code" -ne 0 && "$KEEP_SCRATCH_ON_FAIL" == "1" ]]; then
      echo "  scratch database RETAINED for inspection: ${SCRATCH_DB}"
      echo "  drop it yourself when you are done with it."
    elif [[ "$drop_attempted" -eq 1 ]]; then
      # The main line already tried and already said so. Do not say it twice.
      code=1
    elif ! drop_scratch; then
      echo "  a copy of ${SOURCE_DB} is still on this host as ${SCRATCH_DB}."
      code=1
    fi
  fi
  exit "$code"
}
# Installed before anything that can fail, so an abort still produces a Result
# section. It used to be installed 74 lines after the ERR trap, and a failure
# in between -- `mkdir -p "$ARTIFACT_DIR"`, say -- ended the run with no
# verdict line at all.
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

step "0. Refusals and preflight"
# These refusals are the reason the script may drop a database at all, so they
# have to be able to fire. The original guard compared SOURCE_DB with a name
# built as "restore_rehearsal_${SOURCE_DB}", a strict superstring of it by
# construction -- the equality could never hold and the guard was dead code.
if refusal=$(unsafe_scratch_reason "$SCRATCH_DB"); then
  echo "REFUSING: ${refusal}."
  exit 2
fi
if [[ "$SOURCE_DB" == "$SCRATCH_PREFIX"* ]]; then
  echo "REFUSING: source ${SOURCE_DB} is itself a rehearsal scratch database."
  echo "          Rehearsing one would let a concurrent run drop it mid-flight."
  exit 2
fi
printf '  PASS  %-42s source=%s scratch=%s\n' "scratch name refusals" "$SOURCE_DB" "$SCRATCH_DB"

# The interpreter is required, not optional. The manifest capture, the manifest
# verification and the application smoke test all run through it. This used to
# be checked only at step 7, where a missing interpreter downgraded the single
# check that exercises the product to a WARN -- and the run still printed
# "RESTORE REHEARSAL PASSED" and exited 0. A rehearsal that silently skips its
# only real check must not report success.
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "REFUSING: no executable interpreter at ${PYTHON_BIN}."
  echo "          Set PYTHON_BIN, or create the virtualenv. The rehearsal cannot"
  echo "          verify anything without it, and will not pretend otherwise."
  exit 2
fi
# -x alone was not enough. PYTHON_BIN=/bin/true is executable, answers every
# invocation with silence and success, and the run then produced no manifest,
# no verification, no FAIL line and no smoke test -- while steps 3, 6 and 7 all
# failed to notice. So the interpreter has to prove it is one, by echoing back a
# token it could only have produced by importing what the rehearsal needs.
interpreter_id="$("$PYTHON_BIN" -c \
  'import sys, psycopg; print("REHEARSAL-PY", sys.version.split()[0], psycopg.__version__)' \
  2>&1 || true)"
if [[ "$interpreter_id" != "REHEARSAL-PY "* ]]; then
  echo "REFUSING: ${PYTHON_BIN} is not a Python that can read a manifest."
  echo "          It answered: ${interpreter_id:-(nothing at all)}"
  echo "          The rehearsal cannot verify anything without it, and will not"
  echo "          pretend otherwise by skipping the checks and printing PASSED."
  exit 2
fi
for tool in "$MANIFEST_TOOL" "$SMOKE_TOOL"; do
  if [[ ! -r "$tool" ]]; then
    echo "REFUSING: required tool missing at ${tool}."
    exit 2
  fi
done
printf '  PASS  %-42s %s (%s)\n' "interpreter present" "$PYTHON_BIN" "${interpreter_id#REHEARSAL-PY }"

# The scratch database must not already exist. It never should -- the name
# carries this run's pid -- and if it does, something else owns it. Dropping it
# unasked is how the previous version destroyed the post-mortem copy a
# KEEP_SCRATCH_ON_FAIL run had just been told to retain.
existing=$(psql -X -q -A -t -v ON_ERROR_STOP=1 -d postgres \
  -c "SELECT 1 FROM pg_database WHERE datname = '${SCRATCH_DB//\'/\'\'}';")
if [[ -n "$existing" ]]; then
  echo "REFUSING: ${SCRATCH_DB} already exists on this host."
  echo "          This run did not create it, so it will not drop it. Drop it"
  echo "          yourself, or set SCRATCH_DB to a name that is free."
  exit 2
fi
printf '  PASS  %-42s %s\n' "scratch database is free" "$SCRATCH_DB"

mkdir -p "$ARTIFACT_DIR"
ARTIFACT_DIR="$(cd "$ARTIFACT_DIR" && pwd)"
DUMP_FILE="${ARTIFACT_DIR}/${SOURCE_DB}-${RUN_ID}.dump"
MANIFEST_FILE="${ARTIFACT_DIR}/${SOURCE_DB}-${RUN_ID}.manifest.json"

step "1. Dump ${SOURCE_DB} and describe the dump"
# Custom format: parallel-restorable and the format the runbook specifies for
# real backups, so this rehearses the actual artifact rather than a plain-SQL
# stand-in that might restore differently.
#
# The dump and the manifest share one REPEATABLE READ snapshot
# (pg_export_snapshot -> pg_dump --snapshot=<id> -> read the manifest in the
# same still-open transaction), so the reference describes the bytes in the
# dump file and not whatever the source drifted to afterwards.
if ! REHEARSAL_DSN="$SOURCE_DSN" "$PYTHON_BIN" "$MANIFEST_TOOL" \
  capture "$MANIFEST_FILE" "$DUMP_FILE"; then
  note_fail "capture dump and manifest" "restore_manifest.py capture failed"
  step "Result"
  reached_result=1
  echo "  RESTORE REHEARSAL FAILED -- see FAIL lines above."
  exit 1
fi
echo "  wrote ${DUMP_FILE}"
echo "  wrote ${MANIFEST_FILE}"

# Replaces the "dump is implausibly small" byte floor with the question it was
# standing in for: does this snapshot contain anything worth round-tripping.
# Exit 3 is "not proven", which is a different answer from "broken".
evidence_status=0
"$PYTHON_BIN" "$MANIFEST_TOOL" evidence "$MANIFEST_FILE" || evidence_status=$?
if [[ "$evidence_status" -eq 3 ]]; then
  unproven=1
elif [[ "$evidence_status" -ne 0 ]]; then
  fail=1
fi

step "2. Restore into scratch database ${SCRATCH_DB}"
# The artifact is hashed HERE, immediately before it is read, and again
# immediately after. Hashing it once at capture time proved nothing: the same
# process tree had written the same bytes seconds earlier, so the check could
# not fail. Swapping the dump file between the hash and the restore was
# demonstrated to produce a full PASS on a database that had lost 1,881
# indexes, a whole schema and every large object.
if ! "$PYTHON_BIN" "$MANIFEST_TOOL" checkdump "$MANIFEST_FILE" "$DUMP_FILE" "before restore"; then
  fail=1
fi

# The scratch database is created by replaying the ARTIFACT'S OWN database
# statements -- CREATE DATABASE with the source's TEMPLATE, ENCODING, locale
# provider and locale, then its ALTER DATABASE ... SET settings -- rather than
# by a bare `CREATE DATABASE`, which took the cluster's locale from template1
# and carried no settings. A plain CREATE DATABASE also inherits template1's
# contents: a function planted there turned up in the "restored copy" and
# nothing objected.
# SOURCE_DB is passed so the artifact has to agree about which database it is
# a dump of. A wholesale substitution is then refused outright rather than
# restored and inspected.
# Ownership of the name is claimed BEFORE anything can create it, not after
# the whole replay succeeds. The artifact's database section is several
# statements -- CREATE DATABASE, then ALTER DATABASE ... OWNER, then its
# settings -- and a failure part way through leaves the database created and
# the flag clear, so cleanup skipped the drop and an 8 MB copy of the source
# was left on the host with no message at all. Observed, twice, on the very
# run that found the retargeting bug below it.
#
# Claiming early cannot drop anything that is not ours: the name matched the
# strict pattern, preflight proved it did not already exist, and drop_scratch
# re-asserts the pattern at the moment of the drop. The worst case is a DROP of
# a database this run tried and failed to create, which is the intended
# outcome.
scratch_created=1
if ! "$PYTHON_BIN" "$MANIFEST_TOOL" prepare "$DUMP_FILE" "$SCRATCH_DB" "$SOURCE_DB" \
  | psql -X -q -v ON_ERROR_STOP=1 -d postgres; then
  note_fail "create scratch database from the artifact" "see the error above"
  step "Result"
  reached_result=1
  echo "  RESTORE REHEARSAL FAILED -- see FAIL lines above."
  exit 1
fi
echo "  created ${SCRATCH_DB} from the artifact's own CREATE DATABASE"

# --exit-on-error so a partial restore is a failure, not a warning we scroll
# past. Owner and privileges are NOT suppressed: a backup restored without its
# GRANTs is a database the application cannot read, and the gate used to
# certify exactly that on every run.
pg_restore --exit-on-error -d "$SCRATCH_DB" "$DUMP_FILE"
echo "  restored."

if ! "$PYTHON_BIN" "$MANIFEST_TOOL" checkdump "$MANIFEST_FILE" "$DUMP_FILE" "after restore"; then
  note_fail "the dump file changed while it was being restored" \
    "the copy below was not built from the artifact this run verified"
fi

step "3. Verify the restored copy against the dump's own manifest"
# This replaces three vacuous floors (>= 100,000 bytes, >= 50 tables, >= 20
# foreign keys -- a wiped database cleared all three) and the row counts that
# were read from the live source at verification time. See restore_manifest.py
# for what is compared; it is the whole database, not only the rows.
SCRATCH_DSN="host=${PGHOST} port=${PGPORT} user=${PGUSER} dbname=${SCRATCH_DB}"
if ! REHEARSAL_DSN="$SCRATCH_DSN" "$PYTHON_BIN" "$MANIFEST_TOOL" verify "$MANIFEST_FILE"; then
  note_fail "restored copy matches the dump" "see the FAIL lines above"
fi

step "4. Verify migration state matches"
# Expected comes from the manifest -- i.e. from the dump -- not from the live
# source, which may have migrated since the dump was taken.
if ! expected_migrations=$(manifest_rowcount django_migrations); then
  note_fail "django_migrations in the dump" "the dump carries no django_migrations table"
  expected_migrations=""
fi
if ! dst_migrations=$(psql_dst "SELECT count(*) FROM django_migrations;"); then
  note_fail "read django_migrations from the restore" "query failed"
  dst_migrations=""
fi
check "django_migrations rows" "$expected_migrations" "$dst_migrations"

if ! dst_last=$(psql_dst "SELECT app||'.'||name FROM django_migrations ORDER BY id DESC LIMIT 1;"); then
  note_fail "read latest migration from the restore" "query failed"
  dst_last=""
fi
if [[ -z "$dst_last" ]]; then
  note_fail "latest migration applied" "the restored copy has no migration rows at all"
else
  printf '  PASS  %-42s %s\n' "latest migration applied" "$dst_last"
fi

step "5. Verify referential integrity in the restored copy"
# pg_restore recreates FK constraints but does not re-validate existing rows.
# NOT VALID constraints would silently accept broken references, so assert
# every foreign key on the restored database is in the validated state.
#
# The old ">= 20 foreign keys" floor that sat here is gone: a wiped database
# carries 382 of them. Step 3 compares every constraint's DEFINITION against
# the dump, which is the check the floor was pretending to be.
if ! notvalid=$(psql_dst "SELECT count(*) FROM pg_constraint WHERE contype='f' AND NOT convalidated;"); then
  note_fail "read FK validation state" "query failed"
  notvalid=""
fi
check "unvalidated foreign keys" "0" "$notvalid"

# `fk_total=$(... || echo "?")` used to swallow a failed query and print
# "(? foreign key constraints present and validated)" with no FAIL at all.
if ! fk_total=$(psql_dst "SELECT count(*) FROM pg_constraint WHERE contype='f';"); then
  note_fail "count foreign key constraints" "query failed on the restored copy"
else
  echo "  (${fk_total} foreign key constraints present and validated)"
fi

step "6. Verify the environment stamp survived"
# What the stamp actually guards, corrected. An earlier version of this comment
# claimed the preserved stamp "stops a production dump from being booted
# locally by accident". It does not.
# apps/system_health/environment_guard.py::validate_environment is called from
# exactly ONE place -- apps/core/management/commands/production_preflight.py,
# which the production entrypoint runs explicitly. It is NOT called at
# django.setup(). Nothing refuses a local boot against restored production
# data: step 7 below boots Django against this restored copy under
# config.settings.dev (DEBUG=True, ALLOWED_HOSTS=['*']) and the stamp raises no
# objection.
# So the stamp is evidence that production_preflight will refuse a mispointed
# PRODUCTION deploy. It is not a local boot gate, and this step asserts only
# what is true: the stamp is in the dump, and it came back intact.
if ! stamp_rows=$(manifest_rowcount environment_stamp); then
  note_fail "environment stamp" "the dump carries no environment_stamp table"
elif [[ -z "$stamp_rows" ]]; then
  # Empty is not zero and is not a pass. This step used to fall through an
  # `elif [[ "$stamp_rows" == "0" ]]` to the else branch and PRINT PASS when
  # the row count came back as an empty string -- the same "nothing compared
  # is not everything matched" defect that had just been fixed in check().
  note_fail "environment stamp" "could not read the stamp row count from the manifest"
elif [[ "$stamp_rows" == "0" ]]; then
  note_fail "environment stamp" "the source is unstamped -- production_preflight has nothing to compare (run manage.py stamp_environment)"
else
  if ! value=$(psql_dst "SELECT environment FROM environment_stamp ORDER BY id LIMIT 1;"); then
    note_fail "environment stamp preserved" "query failed on the restored copy"
    value=""
  fi
  if [[ -n "$value" ]]; then
    printf '  PASS  %-42s %s\n' "environment stamp preserved" "$value"
  else
    note_fail "environment stamp preserved" "table restored but carries no stamp row"
  fi
fi

step "7. Drive the application against the restored copy"
# Structure restoring correctly is necessary and is not the question anyone
# cares about after an incident, which is whether the product works. A sequence
# left behind its table, a missing extension, a view restored before its table
# -- none of those move a row count, and all of them show up on the first page
# somebody opens. So open some pages.
#
# PGPASSWORD is exported at the top of this script, so restore_smoke.py builds
# a DATABASE_URL that can actually authenticate. It used to be left unset here
# and the smoke test fell back to a hardcoded default.
BEFORE_SMOKE="${ARTIFACT_DIR}/${SOURCE_DB}-${RUN_ID}.before-smoke.json"
AFTER_SMOKE="${ARTIFACT_DIR}/${SOURCE_DB}-${RUN_ID}.after-smoke.json"
REHEARSAL_DSN="$SCRATCH_DSN" "$PYTHON_BIN" "$MANIFEST_TOOL" snapshot "$BEFORE_SMOKE"

smoke_status=0
RESTORE_SMOKE_DB="$SCRATCH_DB" "$PYTHON_BIN" "$SMOKE_TOOL" || smoke_status=$?
if [[ "$smoke_status" -eq 3 ]]; then
  note_unproven "application smoke test" \
    "the restored copy has no account to sign in as -- see the NOT PROVEN lines above"
elif [[ "$smoke_status" -ne 0 ]]; then
  note_fail "application smoke test against the restored copy" "see the FAIL lines above"
fi

# The smoke test claims to be read-only. It used to say so in its docstring
# while inserting 331 rows across 13 tables -- audit_log, domain_event_log,
# notification, django_session, the fiscal-year rollover the middleware
# self-heals -- and changing fields of `school` and `user` in place. So an
# operator who kept the scratch copy for post-mortem and re-verified it was
# handed 27 phantom failures with the signature of real corruption. The claim
# is now checked rather than asserted: verify the copy again and require it to
# be byte-identical to the one step 3 verified.
REHEARSAL_DSN="$SCRATCH_DSN" "$PYTHON_BIN" "$MANIFEST_TOOL" snapshot "$AFTER_SMOKE"
if ! "$PYTHON_BIN" "$MANIFEST_TOOL" compare "$BEFORE_SMOKE" "$AFTER_SMOKE" \
  "smoke test left the copy unchanged"; then
  note_fail "the smoke test wrote to the restored copy" \
    "the evidence has been altered by the thing measuring it"
  echo "  the two readings are at ${BEFORE_SMOKE}"
  echo "                      and ${AFTER_SMOKE}"
  BEFORE_SMOKE="" AFTER_SMOKE=""
fi
# Transient: two readings of the scratch copy, kept only when they disagreed.
# The dump and its manifest are the artifacts worth keeping; these are not.
[[ -n "$BEFORE_SMOKE" ]] && rm -f "$BEFORE_SMOKE" "$AFTER_SMOKE"
true

# The copy is dropped HERE, on the main line, where a failure to drop it can
# still be reported as a failure of the run. In the EXIT trap it could only be
# best-effort, and it was: one open session made the drop fail silently while
# the script printed PASSED and left a near-copy of production data behind.
if [[ "$fail" -eq 0 || "$KEEP_SCRATCH_ON_FAIL" != "1" ]]; then
  step "8. Remove the scratch copy"
  drop_attempted=1
  if drop_scratch; then
    echo "  dropped ${SCRATCH_DB}"
  else
    # A rehearsal that leaves a near-copy of production data on the host has
    # not finished, whatever its verifications said. The previous version ran
    # the drop as `psql ... >/dev/null 2>&1 || true` inside the EXIT trap: one
    # open session made it fail, nothing was printed, and the run still
    # reported PASSED and exited 0 with the copy sitting there.
    note_fail "scratch copy removed" \
      "a copy of ${SOURCE_DB} is still on this host as ${SCRATCH_DB}"
  fi
else
  scratch_retained=1
fi

step "Result"
reached_result=1
if [[ "$fail" -ne 0 ]]; then
  echo "  RESTORE REHEARSAL FAILED -- see FAIL lines above."
  if [[ "$scratch_retained" -eq 1 ]]; then
    echo "  scratch database RETAINED for inspection: ${SCRATCH_DB}"
  else
    echo "  Re-run with KEEP_SCRATCH_ON_FAIL=1 to retain the scratch copy for inspection."
  fi
  echo "  Artifacts retained: ${DUMP_FILE}"
  echo "                      ${MANIFEST_FILE}"
  exit 1
fi
if [[ "$unproven" -ne 0 ]]; then
  echo "  RESTORE REHEARSAL NOT PROVEN -- nothing failed, and nothing was shown."
  echo "  The round trip was faithful. The source had nothing in it worth"
  echo "  round-tripping, so this run is not evidence that backups preserve data."
  echo "  Artifacts retained: ${DUMP_FILE}"
  echo "                      ${MANIFEST_FILE}"
  exit 3
fi
echo "  RESTORE REHEARSAL PASSED -- restored copy verified against the dump's manifest."
echo "  Artifacts retained: ${DUMP_FILE}"
echo "                      ${MANIFEST_FILE}"
exit 0
