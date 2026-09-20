# DigitalOcean requires Gunicorn's worker temp directory to be writable. Keep
# ASGI support through Uvicorn so realtime/SSE endpoints are not downgraded to
# the WSGI fallback.
web: python manage.py production_preflight && exec gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:${PORT:-8080} --worker-class uvicorn.workers.UvicornWorker --workers ${WEB_CONCURRENCY:-3} --timeout ${WEB_TIMEOUT_SECONDS:-60} --graceful-timeout ${WEB_GRACEFUL_TIMEOUT_SECONDS:-30} --access-logfile - --error-logfile - config.asgi:application
worker: python manage.py production_preflight && exec python manage.py runscheduler
release: python manage.py migrate_locked --noinput
