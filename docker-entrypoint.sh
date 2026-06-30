#!/usr/bin/env sh
# Pre-deploy step: apply migrations, then optionally seed. Mirrors the NestJS
# entrypoint (prisma migrate deploy + RUN_SEED).
set -e

echo "▶ Applying Django migrations..."
python manage.py migrate --noinput

if [ "${RUN_SEED:-false}" = "true" ]; then
  echo "▶ Seeding (RUN_SEED=true)..."
  python manage.py seed ${SEED_ARGS:-}
fi

echo "▶ Starting edify-api (Django + DRF)..."
exec "$@"
