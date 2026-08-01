"""Build-time settings whose only job is to run ``collectstatic``.

The Docker build collects static assets into the image. It used to do that
under ``config.settings.prod``, which meant satisfying that module's
fail-closed production gate with a hand-maintained list of placeholder
environment variables baked into a ``RUN`` line.

That arrangement broke twice. Every time the gate gained a new required
setting — the JWT/SECRET_KEY length floor, then the whole Spaces block — the
placeholder list silently fell behind and the image stopped building. The
failure always landed on someone trying to deploy, not on the commit that
caused it.

The gate exists to stop a *server* from starting with an unsafe configuration.
``collectstatic`` is not a server: it opens no socket, reads no secret, and
touches no database. Running it under the production gate never bought any
safety; it only created a list that had to be kept in sync with a list.

So the build runs here instead. This module takes development defaults from
``base`` and overrides exactly the two things static collection depends on:
``DEBUG`` off, and the same staticfiles backend production serves with. The
manifest this produces is therefore byte-identical to one collected under
``prod``, and there is no placeholder list left to drift.

Nothing should ever serve traffic with these settings. ``DJANGO_SETTINGS_MODULE``
in the runtime image stays ``config.settings.prod``; this module is named only
on the single build-stage ``collectstatic`` command.
"""

from .base import *  # noqa: F401,F403
from .base import STATICFILES_STORAGE_BACKEND, STORAGES as _BASE_STORAGES

# Collect the un-minified debug variants of nothing: DEBUG only affects which
# finders warn, but leaving it on in a build step is misleading.
DEBUG = False

# Only the staticfiles entry matters here. The default/private_uploads backends
# stay on base's local-filesystem versions: collectstatic never touches them,
# and pointing them at Spaces would require the credentials this module exists
# to avoid needing.
STORAGES = {
    **_BASE_STORAGES,
    "staticfiles": {"BACKEND": STATICFILES_STORAGE_BACKEND},
}
