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

# Import the URLconf and the analytics engines now, not on the first request:
# see config/warmup.py for why (seven seconds of imports on a one-vCPU worker
# used to land on the first page load after every deploy).
from config.warmup import warm  # noqa: E402

warm()
