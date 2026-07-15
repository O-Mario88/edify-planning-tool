web: daphne -b 0.0.0.0 -p ${PORT:-4000} config.asgi:application
worker: python manage.py runscheduler
release: python manage.py migrate --noinput
