#!/usr/bin/env bash
# Creates the gateway's read-only database role on a DEVELOPMENT, TEST or
# STAGING database. It changes roles and grants only: no table, column, index,
# constraint or row of the existing schema is touched.
#
# Usage:
#   EDIFY_ENV=development EDIFY_ADMIN_DATABASE_URL=postgresql://localhost:5432/edify_gorn_dev \
#     platform/deploy/db/apply-roles.sh
#
# The script refuses to run without an explicit non-production environment,
# against a URL that looks like the production database, or (outside staging)
# against any host that is not this machine.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
env_name="${EDIFY_ENV:-}"
url="${EDIFY_ADMIN_DATABASE_URL:-}"

case "$env_name" in
  development | test | staging) ;;
  *)
    echo "refused: EDIFY_ENV must be development, test or staging (got '${env_name}')" >&2
    exit 2
    ;;
esac
if [[ -z "$url" ]]; then
  echo "refused: EDIFY_ADMIN_DATABASE_URL is required (DATABASE_URL is never read)" >&2
  exit 2
fi

lowered="$(printf '%s' "$url" | tr '[:upper:]' '[:lower:]')"
markers="edify-production-db,edifyplanning.app,${EDIFY_DB_PRODUCTION_MARKERS:-}"
IFS=',' read -r -a marker_list <<<"$markers"
for marker in "${marker_list[@]}"; do
  marker="$(printf '%s' "$marker" | tr '[:upper:]' '[:lower:]' | xargs)"
  if [[ -n "$marker" && "$lowered" == *"$marker"* ]]; then
    echo "refused: the database URL matches the production marker '${marker}'" >&2
    exit 2
  fi
done

# host part of postgresql://user:pass@HOST:port/db (empty for a socket URL)
host="$(printf '%s' "$lowered" | sed -E 's#^[a-z]+://([^@/]*@)?([^:/?]*).*#\2#')"
if [[ "$env_name" != "staging" ]]; then
  case "$host" in
    "" | localhost | 127.0.0.1 | "[::1]") ;;
    *)
      echo "refused: ${env_name} roles are applied to a local database only (host '${host}')" >&2
      exit 2
      ;;
  esac
fi

echo "applying gateway roles: environment=${env_name} host=${host:-local socket}"
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/roles.sql"
# The Cluster Leader Portal's Go-owned schema and its owner and writer roles.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/cluster_roles.sql"
# The School Loan Application Portal's Go-owned schema and its roles.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/loan_roles.sql"
# The Smart Route Planner's Go-owned schema (location reports) and its roles.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/routes_roles.sql"
# Edify Global's country registry: the countries, their settings, each school's
# and each account's country.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/country_roles.sql"
# Signing in, which Go owns: exactly the existing sign-in's columns.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/identity_roles.sql"
# The Decision Log's narrow view of the audit chain: decision rows, subject keys only.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/decision_log_roles.sql"
# Which forms an activity has in (its evidence kinds), after the file above.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/evidence_roles.sql"
# Scheduling a school visit, the first save Go makes: exactly its writes.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/activities_roles.sql"
# Cancelling a visit withdraws its unmoved advances through one narrow function.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/advance_withdraw_roles.sql"
# Completing a staff school visit hands it in through one narrow function.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/completion_roles.sql"
# Programme Lead approval and return through two narrow functions (M9).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/pl_review_roles.sql"
# Native Go notification delivery and read-state transitions (M11).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/notification_roles.sql"
# Native Go day-pool costing settlement and durable activity events (Step 1).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/costing_settle_roles.sql"
# The transport obligation, advances, weekly request and monthly draft of a priced day.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/day_money_roles.sql"
# Native Go security incident & partner login release relay replacements (Step 2).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/relay_ops_roles.sql"
# Native Go cluster leader account onboarding (Batch 10).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/cluster_onboard_roles.sql"
# Native Go loan ledger writer with idempotency-key deduplication (Batch 10).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/loans_ledger_roles.sql"
# Native Go field ops writers: evidence, IA verification, SSA, partners (Batch 11).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/field_ops_roles.sql"
# Native Go finance & money writers: weekly requests, advances, monthly budgets (Batch 12).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/finance_roles.sql"
# Native Go workforce ops writers: profile, leave, escalations, help feedback (Batch 13).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/workforce_ops_roles.sql"
# Native Go support ticket workflow (Step 3A).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/support_roles.sql"
# Native Go messaging read-thread, reply, compose, star, archive (Step 3C).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/messaging_roles.sql"
# Native Go standalone scheduler operational jobs (Step 4).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/scheduler_jobs_roles.sql"
# Native Go Settings two-step verification update (Batch 19).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/settings_roles.sql"
# Native Go School Actions & School Profile Drawer writers (Batches 22-23).
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/school_actions_roles.sql"
# Snoozing a To-Do from Today: one table's insert and its three updated columns.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/todo_roles.sql"
# Undoing a snooze removes that one row through one narrow function.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/todo_unsnooze_roles.sql"
# The presence stamp for requests Go answers: one narrow function, its columns only.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/presence_roles.sql"
# My Professional Development's read writes the same rows the existing read does.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/mypd_roles.sql"
echo "done"
