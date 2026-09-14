"""Disposable functional-test settings; never used by the running application."""

import os

if os.environ.get("TEST_DATABASE_NAME") != "edify_controls_audit_test":
    raise RuntimeError("Audit settings require the named disposable test database.")
from config.settings.dev import *  # noqa: F403

PASSWORD_HASHERS = [  # noqa: F405
    "django.contrib.auth.hashers.MD5PasswordHasher",
    *PASSWORD_HASHERS,  # noqa: F405
]
# Django does not isolate Redis caches when it isolates test databases.
# Keep every worker's cache and realtime transport in its own process.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "controls-audit-" + os.environ.get("PYTEST_XDIST_WORKER", "serial"),
    }
}
REDIS_URL = None
