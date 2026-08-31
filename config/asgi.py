"""
ASGI config for the Edify API.

ASGI is required for the realtime SSE stream (streaming responses). The
background scheduler runs in its own deployment process, never in web workers.
Production serves this application through Gunicorn with Uvicorn workers.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
