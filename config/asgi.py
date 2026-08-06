"""
ASGI config for the Edify API.

ASGI is required for the realtime SSE stream (streaming responses) and the
in-process background scheduler. Served in production via uvicorn/gunicorn.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")

application = get_asgi_application()
