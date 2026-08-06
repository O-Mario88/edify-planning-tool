"""Progressive Web App plumbing: manifest and service worker.

Both are served by Django rather than as static files, for two different
reasons.

The manifest must be rendered because production runs
``CompressedManifestStaticFilesStorage``, which gives every static file a
content-hashed name. A checked-in ``manifest.json`` with literal
``/static/icons/icon-192.png`` paths resolves in development and 404s in
production, taking installability with it. Resolving the icon URLs through
``static()`` gives the hashed name in whichever environment is running.

The service worker must be served from the site root because a worker's
default scope is the directory it is served from. At ``/static/js/sw.js`` it
would only control ``/static/js/`` -- useless. Serving it at ``/sw.js`` scopes
it to the whole origin.
"""

from pathlib import Path

from django.http import HttpResponse, JsonResponse
from django.templatetags.static import static
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

APP_NAME = "Edify Planning & Monitoring"
APP_SHORT_NAME = "Edify"
# Sampled from the icon artwork by build_app_icons.
BRAND = "#2d4862"


@require_GET
@cache_control(max_age=3600)
def manifest(request):
    """Web app manifest. Content type matters -- browsers ignore text/plain."""
    return JsonResponse(
        {
            "name": APP_NAME,
            "short_name": APP_SHORT_NAME,
            "description": (
                "Plan activities, track field work and monitor school "
                "performance across Uganda."
            ),
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "orientation": "any",
            "background_color": BRAND,
            "theme_color": BRAND,
            "icons": [
                {
                    "src": static("icons/icon-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": static("icons/icon-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
                # Android adaptive icons crop to a circle; these carry the
                # safe-zone padding so the crop takes background, not logo.
                {
                    "src": static("icons/icon-maskable-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "maskable",
                },
                {
                    "src": static("icons/icon-maskable-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
            ],
        },
        content_type="application/manifest+json",
    )


# The worker is deliberately small. This app is authenticated and CSRF-bearing,
# so the cache is restricted to same-origin GETs under /static/ -- versioned,
# user-independent assets. HTML, API responses and anything carrying a session
# go to the network every time. Caching a rendered page here would risk handing
# one signed-in user a page rendered for another, and would serve stale CSRF
# tokens; no offline convenience is worth either.
#
# Cache-first is only safe when the URL changes as the content does. Production
# runs CompressedManifestStaticFilesStorage, so every asset carries a content
# hash in its name and a changed file is a different URL. Development does not:
# names are stable, so a cache-first worker pins the first copy it ever saw and
# serves it past every edit. The static branch is therefore compiled out
# entirely when the names are not content-addressed -- see `_caches_static`.
SERVICE_WORKER = """
const CACHE = 'edify-static-%(version)s';

self.addEventListener('install', (event) => {
  // Take over promptly so an updated worker is not stuck behind the old one.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      // Every cache but this build's, so a deploy does not leave the previous
      // build's assets on disk forever.
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});
%(fetch_handler)s"""

# Installed only where asset names carry a content hash.
STATIC_FETCH_HANDLER = """
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  // Only versioned static assets. Everything else -- pages, APIs, anything
  // with a session -- falls through to the network untouched.
  if (!url.pathname.startsWith('/static/')) return;

  event.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res && res.status === 200 && res.type === 'basic') {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    }).catch(() => hit))
  );
});
"""

# No fetch handler at all: the worker still installs (so the app stays
# installable and the manifest is honoured) but every request goes to the
# network, which is the only correct behaviour for assets whose URL does not
# change when their content does.
PASSTHROUGH_NOTE = """
// No fetch handler in this build: static asset names are not content-hashed
// here, so anything cached would be served past the next edit.
"""


def _caches_static() -> bool:
    """True when static file names carry a content hash.

    Anything else -- the development server, or a deployment that has not
    enabled a hashing storage -- must not be cached by URL, because the URL
    stops being a promise about the bytes behind it.
    """
    from django.conf import settings

    backend = (
        settings.STORAGES.get("staticfiles", {}).get("BACKEND", "")
        if hasattr(settings, "STORAGES")
        else ""
    )
    return "Manifest" in backend


def static_version() -> str:
    """A token that changes exactly when the static assets change.

    The cache name is built from it, and `activate` deletes every cache that
    is not the current one -- so a token that never moves means a cache that
    is never cleared. It was hardcoded to "1" through a missing setting, which
    is how the worker came to hold assets indefinitely.
    """
    import hashlib
    import os

    from django.conf import settings

    override = os.environ.get("STATIC_VERSION") or os.environ.get("RELEASE_SHA")
    if override:
        return override[:12]

    # The manifest lists every asset and its content hash, so hashing it gives
    # one token that moves whenever any asset does.
    manifest = Path(settings.STATIC_ROOT or "") / "staticfiles.json"
    try:
        return hashlib.sha256(manifest.read_bytes()).hexdigest()[:12]
    except OSError:
        return "unversioned"


@require_GET
@cache_control(max_age=0, no_cache=True)
def service_worker(request):
    """Serve the worker at the site root so its scope covers the whole app.

    Served with no-cache: a stale worker is how a PWA gets stuck on an old
    build, and the file is well under a kilobyte.
    """
    body = SERVICE_WORKER % {
        "version": static_version(),
        "fetch_handler": (
            STATIC_FETCH_HANDLER if _caches_static() else PASSTHROUGH_NOTE
        ),
    }
    response = HttpResponse(body, content_type="application/javascript")
    # Belt and braces: allows the scope even if the file ever moves.
    response["Service-Worker-Allowed"] = "/"
    return response
