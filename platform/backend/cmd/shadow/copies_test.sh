#!/usr/bin/env bash
# Proves that `copies.sh base` leaves a base on which apply-roles.sh runs clean
# (docs/migration/61-shadow-base-roles.md), and that `copies.sh fresh` carries
# the owners and grants into both copies. It writes only the three shadow
# copies it is given; the source is read (pg_dump and SELECTs).
#
#   EDIFY_SHADOW_BASE=edify_shadow_s22_base EDIFY_SHADOW_A=edify_shadow_s22_a \
#     EDIFY_SHADOW_B=edify_shadow_s22_b platform/backend/cmd/shadow/copies_test.sh
#
# The three names are required (the defaults belong to the coordinator's
# proofs and are refused here), and each must be named edify_shadow_*.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
roles="${here}/../../../deploy/db/apply-roles.sh"
source_db="${EDIFY_SHADOW_SOURCE:-edify_gorn_dev}"
failures=0

for name in EDIFY_SHADOW_BASE EDIFY_SHADOW_A EDIFY_SHADOW_B; do
  value="${!name:-}"
  case "$value" in
    edify_shadow_base | edify_shadow_a | edify_shadow_b | "")
      echo "refused: set ${name} to your own edify_shadow_* copy (got '${value}')" >&2
      exit 2
      ;;
    edify_shadow_*) ;;
    *) echo "refused: ${name}=${value} is not a shadow copy" >&2; exit 2 ;;
  esac
done
base="$EDIFY_SHADOW_BASE"

ok() { echo "ok   $1"; }
fail() { echo "FAIL $1" >&2; failures=$((failures + 1)); }

q() { psql --no-psqlrc -At --set ON_ERROR_STOP=1 -d "$1" -c "$2"; }

# Owner of every schema, relation and function outside the system catalogs.
owners_sql="
SELECT 'schema ' || n.nspname || ' ' || pg_get_userbyid(n.nspowner)
  FROM pg_namespace n
 WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
UNION ALL
SELECT 'rel ' || n.nspname || '.' || c.relname || ' ' || pg_get_userbyid(c.relowner)
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
   AND c.relkind IN ('r', 'v', 'm', 'S', 'p', 'f')
UNION ALL
SELECT 'fn ' || n.nspname || '.' || p.proname || ' ' || pg_get_userbyid(p.proowner)
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
ORDER BY 1"

# Exact row count of every table outside the system catalogs.
counts_sql="
SELECT n.nspname || '.' || c.relname || ' ' ||
       (xpath('/row/n/text()', query_to_xml(format('SELECT count(*) AS n FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema'
   AND c.relkind IN ('r', 'p')
ORDER BY 1"

scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

# 1. The base, made by the script under test. The source is live (other
# people sign in while it is dumped), so its tables are counted before and
# after the dump: a table that did not move must match exactly, one that moved
# must hold a count between the two.
q "$source_db" "$counts_sql" | LC_ALL=C sort >"$scratch/counts_before"
EDIFY_SHADOW_SOURCE="$source_db" "${here}/copies.sh" base
q "$source_db" "$counts_sql" | LC_ALL=C sort >"$scratch/counts_after"

q "$source_db" "$owners_sql" >"$scratch/owners_source"
q "$base" "$owners_sql" >"$scratch/owners_base"
# Objects apply-roles.sh has not made yet are absent from the base; every
# object the base has must carry the source's owner.
if diff <(sort "$scratch/owners_source") <(sort "$scratch/owners_base") >/dev/null; then
  ok "base owners equal ${source_db}'s ($(wc -l <"$scratch/owners_base" | tr -d ' ') objects)"
else
  fail "base owners differ from ${source_db}'s:"
  diff <(sort "$scratch/owners_source") <(sort "$scratch/owners_base") | head -20 >&2 || true
fi
for schema in gateway_read cluster_leadership school_loans; do
  want="$(q "$source_db" "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = '${schema}'")"
  got="$(q "$base" "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = '${schema}'")"
  if [[ -n "$want" && "$got" == "$want" ]]; then ok "schema ${schema} owned by ${got}"; else fail "schema ${schema} owned by '${got}', want '${want}'"; fi
done

q "$base" "$counts_sql" | LC_ALL=C sort >"$scratch/counts_base"
# table before after base -> one verdict line per table
LC_ALL=C join "$scratch/counts_before" "$scratch/counts_after" | LC_ALL=C join - "$scratch/counts_base" |
  awk '{ lo = ($2 < $3) ? $2 : $3; hi = ($2 < $3) ? $3 : $2
         if ($2 == $3) print (($4 == $2) ? "same " : "BAD  ") $1 " " $2 " " $4
         else print (($4 >= lo && $4 <= hi) ? "live " : "BAD  ") $1 " " $2 "->" $3 " " $4 }' >"$scratch/counts_verdict"
tables="$(wc -l <"$scratch/counts_base" | tr -d ' ')"
joined="$(wc -l <"$scratch/counts_verdict" | tr -d ' ')"
if [[ "$joined" != "$tables" || "$tables" != "$(wc -l <"$scratch/counts_before" | tr -d ' ')" ]]; then
  fail "the base's tables are not the source's (${tables} in the base, ${joined} matched)"
elif grep -q '^BAD' "$scratch/counts_verdict"; then
  fail "base row counts differ:"; grep '^BAD' "$scratch/counts_verdict" | head -20 >&2 || true
else
  ok "base row counts equal ${source_db}'s: $(grep -c '^same' "$scratch/counts_verdict") tables exactly, $(grep -c '^live' "$scratch/counts_verdict" || true) written during the dump within their range"
  grep '^live' "$scratch/counts_verdict" | sed 's/^/     /' || true
fi

# 2. apply-roles.sh on the base, twice (a second run must also be clean).
url="postgresql://localhost:5432/${base}"
for run in first second; do
  if EDIFY_ENV=test EDIFY_ADMIN_DATABASE_URL="$url" "$roles" >"$scratch/roles_${run}.log" 2>&1; then
    if grep -q "ERROR" "$scratch/roles_${run}.log"; then
      fail "apply-roles.sh (${run} run) printed an ERROR"; grep "ERROR" "$scratch/roles_${run}.log" | head -5 >&2 || true
    else
      ok "apply-roles.sh ${run} run clean"
    fi
  else
    fail "apply-roles.sh ${run} run exited non-zero:"; tail -5 "$scratch/roles_${run}.log" >&2
  fi
done

# 3. What the roles files make, made by the right owners.
expect_owner() { # db kind name owner
  local got
  case "$2" in
    rel) got="$(q "$1" "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = to_regclass('$3')")" ;;
    fn) got="$(q "$1" "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE oid = to_regprocedure('$3')")" ;;
    schema) got="$(q "$1" "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = '$3'")" ;;
  esac
  if [[ "$got" == "$4" ]]; then ok "$1: $3 owned by $4"; else fail "$1: $3 owned by '${got}', want '$4'"; fi
}
expect_grant() { # db sql description
  if [[ "$(q "$1" "SELECT $2")" == "t" ]]; then ok "$1: $3"; else fail "$1: $3"; fi
}
check_made() { # db
  expect_owner "$1" rel gateway_read.decision_audit edify_audit_view_owner
  expect_owner "$1" rel gateway_read.activity_evidence_kind edify_audit_view_owner
  expect_owner "$1" schema gateway_lock edify_school_lock_owner
  expect_owner "$1" fn 'gateway_lock.lock_school(character varying)' edify_school_lock_owner
  expect_owner "$1" fn 'gateway_lock.lock_cluster(character varying)' edify_cluster_lock_owner
  expect_owner "$1" fn 'gateway_money.withdraw_unmoved_advances(character varying)' edify_advance_withdraw_owner
  expect_grant "$1" "has_table_privilege('edify_gateway_ro', 'gateway_read.decision_audit', 'SELECT')" "gateway_ro reads gateway_read.decision_audit"
  expect_grant "$1" "has_table_privilege('edify_gateway_ro', 'public.school', 'SELECT') OR has_any_column_privilege('edify_gateway_ro', 'public.school', 'SELECT')" "gateway_ro reads school columns"
  expect_grant "$1" "NOT has_table_privilege('edify_gateway_ro', 'public.school', 'UPDATE')" "gateway_ro cannot UPDATE school"
  expect_grant "$1" "NOT has_table_privilege('edify_gateway_ro', 'gateway_read.decision_audit', 'INSERT')" "gateway_ro cannot INSERT into the audit view"
}
check_made "$base"

# 4. Both copies carry the base's owners and grants.
"${here}/copies.sh" fresh
q "$base" "$owners_sql" >"$scratch/owners_base_after"
for copy in "$EDIFY_SHADOW_A" "$EDIFY_SHADOW_B"; do
  if diff "$scratch/owners_base_after" <(q "$copy" "$owners_sql") >/dev/null; then
    ok "${copy} owners equal the base's"
  else
    fail "${copy} owners differ from the base's"
  fi
  check_made "$copy"
done

if ((failures > 0)); then
  echo "${failures} check(s) failed" >&2
  exit 1
fi
echo "all checks passed"
