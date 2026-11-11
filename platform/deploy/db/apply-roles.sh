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
# Signing in, which Go owns: exactly the existing sign-in's columns.
psql "$url" --set ON_ERROR_STOP=1 --quiet --file "${here}/identity_roles.sql"
echo "done"
