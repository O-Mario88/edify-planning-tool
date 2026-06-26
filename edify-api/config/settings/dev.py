"""Development settings — permissive defaults for local work."""
from .base import *  # noqa: F401,F403

DEBUG = True
IS_PRODUCTION = False
NODE_ENV = "development"

# Reflective CORS when no allowlist is configured (dev convenience).
if not CORS_ORIGINS:
    CORS_ALLOW_ALL_ORIGINS = True

# Allow the in-process runserver + the Next.js dev server.
ALLOWED_HOSTS = ["*"]

# Email stays in console mode (log + return link in the response) in dev.
EMAIL_PROVIDER = "console"
