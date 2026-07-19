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
SERVICE_WORKER = """
const CACHE = 'edify-static-%(version)s';

self.addEventListener('install', (event) => {
  // Take over promptly so an updated worker is not stuck behind the old one.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

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


@require_GET
@cache_control(max_age=0, no_cache=True)
def service_worker(request):
    """Serve the worker at the site root so its scope covers the whole app.

    Served with no-cache: a stale worker is how a PWA gets stuck on an old
    build, and the file is well under a kilobyte.
    """
    from django.conf import settings

    body = SERVICE_WORKER % {"version": getattr(settings, "STATIC_VERSION", "1")}
    response = HttpResponse(body, content_type="application/javascript")
    # Belt and braces: allows the scope even if the file ever moves.
    response["Service-Worker-Allowed"] = "/"
    return response
