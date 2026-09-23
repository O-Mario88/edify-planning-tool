"""Local production-shaped settings for load, soak and profiling runs.

Development settings run with DEBUG on, which records every SQL statement in
memory and renders debug error pages: both distort a latency or memory
measurement. Production settings cannot boot without live secrets and object
storage. This sits between them: development's local storage and demo-data
permissions, production's request path.

It is never deployed. It exists so `scripts/load_test.py`, the soak harness and
the route sweep measure the code path production runs, against a disposable
local database.
"""

import os

from .base import _as_int
from .dev import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = ["*"]

# Production's admission control. prod.py sets 6 per process without a pool.
WEB_MAX_CONCURRENT_REQUESTS = _as_int(os.environ.get("WEB_MAX_CONCURRENT_REQUESTS"), 6)

# Serve application static files straight from the source tree, the way the
# browser harnesses need them, without a collectstatic step.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = False
