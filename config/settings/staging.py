"""Staging settings — production's hardening, without production's identity.

Staging exists to prove a release BEFORE it reaches the live app: the same
image, the same fail-closed gates, the same security posture. So this module
inherits `prod` wholesale rather than re-deriving anything, and every boot
check `prod` performs runs here too. If staging boots, the artifact boots.

Only two things change, and both are about identity rather than strictness:

``IS_PRODUCTION = False``
    `manage.py seed --demo` refuses to run when this is true, and demo data is
    the entire point of staging: it is what gives the ten-role matrix and the
    end-to-end certification journeys something to run against. Turning this
    off does NOT open a hole — the authoritative protection is the database's
    own stamp, and `seed --demo` still refuses any database stamped
    'production' regardless of what this process believes it is. A staging
    process accidentally pointed at the live database therefore still cannot
    seed demo accounts into it.

``ENVIRONMENT = "staging"``
    `prod` hardcodes "production" so a missing env var can never weaken the
    stamp guard on a live host. Staging needs its own identity for the same
    guard to work in the other direction: this process must refuse to run
    against a database stamped 'production' or 'local'.

Email and SMS fall back to the console provider here, which is correct — no
staging run should be able to send mail to a real person.

Deployment note: staging MUST use its own object-storage credentials and its
own SPACES_PREFIX. Production's secrets are encrypted per-app and cannot be
copied; sharing a prefix would let a staging test write into live evidence
storage. See `.do/staging.yaml`.
"""

from .prod import *  # noqa: F401,F403


IS_PRODUCTION = False
ENVIRONMENT = "staging"
