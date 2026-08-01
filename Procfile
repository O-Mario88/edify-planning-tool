# DigitalOcean requires Gunicorn's worker temp directory to be writable. Keep
# ASGI support through Uvicorn so realtime/SSE endpoints are not downgraded to
# the WSGI fallback.
web: gunicorn --worker-tmp-dir /dev/shm --bind 0.0.0.0:${PORT:-8080} --worker-class uvicorn.workers.UvicornWorker --access-logfile - --error-logfile - config.asgi:application
worker: python manage.py runscheduler
release: python manage.py migrate --noinput
