#!/usr/bin/env sh
# Pre-deploy step: apply migrations, then optionally seed. Mirrors the NestJS
# entrypoint (prisma migrate deploy + RUN_SEED).
set -e

# Migrating on container start is right for single-instance deployments
# (docker-compose, Railway) where nothing else will do it. It is wrong on a
# platform that can start several replicas at once: they would each run
# `migrate` against the same database simultaneously.
#
# DigitalOcean App Platform therefore sets RUN_MIGRATIONS=false on the web
# service and runs migrations once, in the PRE_DEPLOY job, before any new
# container takes traffic. The default stays true so existing deployments
# behave exactly as before.
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  echo "▶ Applying Django migrations..."
  python manage.py migrate --noinput
else
  echo "▶ Skipping migrations (RUN_MIGRATIONS=false; handled by pre-deploy job)."
fi

if [ "${RUN_SEED:-false}" = "true" ]; then
  echo "▶ Seeding (RUN_SEED=true)..."
  python manage.py seed ${SEED_ARGS:-}
fi

# Database checks must run after Django's app registry is ready (never from an
# AppConfig.ready hook) and before a production process accepts work. The
# pre-deploy migrate job intentionally does not reach this branch.
case "${DJANGO_SETTINGS_MODULE:-}:$*" in
  config.settings.prod:*daphne*|config.settings.prod:*gunicorn*|config.settings.prod:*runscheduler*)
    echo "▶ Running production preflight..."
    python manage.py production_preflight
    ;;
esac

echo "▶ Starting edify-api (Django + DRF)..."
exec "$@"
