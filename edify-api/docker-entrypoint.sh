#!/bin/sh
set -e

# Apply pending migrations before the app boots. Idempotent — no-op when the
# database is already up to date.
echo "[entrypoint] applying database migrations…"

# The consolidated baseline (00000000000000_init) replaced 26 incremental
# migrations. On a DB created from the OLD migrations, `migrate deploy` fails
# because the baseline re-creates objects that already exist ("type EdifyRole
# already exists"). When that happens, mark the baseline as already-applied
# (so Prisma stops trying to re-run it) and reconcile the schema with `db push`
# (which creates only the objects the old DB is missing — e.g. the 5 budget-
# automation tables). This block self-reverts: once the baseline is recorded,
# `migrate deploy` succeeds on every subsequent boot and this path is skipped.
if ! npx prisma migrate deploy 2>/tmp/migrate-err.log; then
  if grep -qi "already exists" /tmp/migrate-err.log; then
    echo "[entrypoint] baseline objects already present — marking 00000000000000_init applied + reconciling schema…"
    npx prisma migrate resolve --applied 00000000000000_init || true
    # Reconcile the DB to the current schema: creates tables/columns the
    # pre-consolidation DB lacks (no destructive changes without --accept-data-loss).
    npx prisma db push --skip-generate
  else
    echo "[entrypoint] migrate deploy failed:"; cat /tmp/migrate-err.log
    exit 1
  fi
fi

# Optionally seed on first boot (guarded inside the seed; safe to re-run).
if [ "$RUN_SEED" = "true" ]; then
  echo "[entrypoint] seeding…"
  npx prisma db seed || echo "[entrypoint] seed skipped/failed (non-fatal)"
fi

echo "[entrypoint] starting: $*"
exec "$@"
