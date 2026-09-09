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
from django.shortcuts import render
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
# user-independent assets -- plus exactly one page: the offline fallback, which
# is rendered without user data for this purpose (see `offline`). HTML rendered
# for a user, API responses and anything carrying a session go to the network
# every time. Caching such a page here would risk handing one signed-in user a
# page rendered for another, and would serve stale CSRF tokens; no offline
# convenience is worth either.
#
# Cache-first is only safe when the URL changes as the content does. Production
# runs CompressedManifestStaticFilesStorage, so every asset carries a content
# hash in its name and a changed file is a different URL. Development does not:
# names are stable, so a cache-first worker pins the first copy it ever saw and
# serves it past every edit. The static branch is therefore compiled out
# entirely when the names are not content-addressed -- see `_caches_static`.
#
# The fallback page is precached in both builds. It is fetched afresh at every
# install and kept in a cache named after the worker version, so a deploy --
# which changes the version, hence the worker, hence triggers an install --
# replaces it.
SERVICE_WORKER = """
const VERSION = '%(version)s';
const CACHE = 'edify-static-' + VERSION;
// Its own cache, so the passthrough build -- which caches no static asset --
// still has somewhere to keep the fallback page.
const OFFLINE_CACHE = 'edify-offline-' + VERSION;
const OFFLINE_URL = '/offline';
const OUTBOX_SYNC_TAG = 'edify-outbox';

self.addEventListener('install', (event) => {
  // Take over promptly so an updated worker is not stuck behind the old one.
  self.skipWaiting();
  event.waitUntil(
    caches.open(OFFLINE_CACHE)
      // `reload` skips the HTTP cache: the page precached is the one this
      // deploy serves, not whatever the browser kept from the previous one.
      .then((c) => c.add(new Request(OFFLINE_URL, { cache: 'reload' })))%(precache_assets)s
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      // Every cache but this build's, so a deploy does not leave the previous
      // build's assets on disk forever.
      .then((keys) => Promise.all(
        keys.filter((k) => k !== CACHE && k !== OFFLINE_CACHE).map((k) => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// Background Sync fires when connectivity returns, even with no page in the
// foreground. The outbox itself lives in the page (field-outbox.js, IndexedDB),
// so the worker only wakes whichever pages are open and lets one replay.
self.addEventListener('sync', (event) => {
  if (event.tag !== OUTBOX_SYNC_TAG) return;
  event.waitUntil(
    self.clients.matchAll({ type: 'window' }).then((clients) => {
      clients.forEach((client) => client.postMessage({ type: 'edify-outbox-replay' }));
    })
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  // A page navigation the network cannot answer gets the precached fallback.
  // Only a *failed* fetch qualifies: a 4xx or 5xx is the app answering and is
  // shown as-is. The navigation's own response is never stored -- it was
  // rendered for a user.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).catch(() => caches.match(OFFLINE_URL, { cacheName: OFFLINE_CACHE })
        .then((res) => res.text().then((html) => {
          const headers = new Headers(res.headers);
          headers.delete('Content-Length');
          headers.delete('Content-Encoding');
          return new Response(
            html.replace('data-offline-page>', 'data-offline-page data-navigation-failed="true">'),
            { headers }
          );
        })))
    );
    return;
  }
%(static_branch)s});
"""

# Installed only where asset names carry a content hash.
STATIC_FETCH_BRANCH = """
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
"""

# The fallback page is only as useful as its stylesheet. Where asset names are
# content-hashed the assets it links are immutable, so they are precached with
# it -- one by one, and tolerantly: a single missing file must not leave the
# worker uninstalled and the app without any fallback at all.
STATIC_PRECACHE = """
      .then(() => caches.match(OFFLINE_URL, { cacheName: OFFLINE_CACHE }))
      .then((res) => (res ? res.text() : ''))
      .then((html) => {
        const assets = Array.from(
          html.matchAll(/(?:href|src)="(\\/static\\/[^"]+)"/g), (m) => m[1]
        );
        return caches.open(CACHE).then((c) =>
          Promise.all(assets.map((a) => c.add(a).catch(() => null)))
        );
      })"""

# The static branch is left out entirely: the worker still installs (so the app
# stays installable, the manifest is honoured and the offline fallback works)
# but every asset request goes to the network, which is the only correct
# behaviour for assets whose URL does not change when their content does.
PASSTHROUGH_NOTE = """
  // No static branch in this build: static asset names are not content-hashed
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

    # The cached fallback is HTML too. Template-only edits (and development
    # without a manifest) must replace it rather than pinning an old screen.
    digest = hashlib.sha256(b"edify-offline-v2")
    for relative in (
        "templates/base.html",
        "templates/pages/offline.html",
        "static/js/field-outbox.js",
    ):
        digest.update((Path(settings.BASE_DIR) / relative).read_bytes())
    manifest = Path(settings.STATIC_ROOT or "") / "staticfiles.json"
    try:
        digest.update(manifest.read_bytes())
    except OSError:
        pass
    return digest.hexdigest()[:12]


@require_GET
@cache_control(max_age=0, no_cache=True)
def service_worker(request):
    """Serve the worker at the site root so its scope covers the whole app.

    Served with no-cache: a stale worker is how a PWA gets stuck on an old
    build, and the file is a few kilobytes.
    """
    hashed = _caches_static()
    body = SERVICE_WORKER % {
        "version": static_version(),
        "static_branch": STATIC_FETCH_BRANCH if hashed else PASSTHROUGH_NOTE,
        "precache_assets": STATIC_PRECACHE if hashed else "",
    }
    response = HttpResponse(body, content_type="application/javascript")
    # Belt and braces: allows the scope even if the file ever moves.
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
@cache_control(max_age=0, no_cache=True)
def offline(request):
    """The navigation fallback: precached by the worker, served when a page
    cannot be fetched.

    It is stored once per install and shown to whoever holds the phone, so it
    must render the same for everyone: nothing in the template reads the user
    or the session. The CSRF token is blanked for the same reason -- base.html
    stamps the session's token on <body>, and the precached copy must not
    carry the installing session's. csrf-sync.js restores the live cookie's
    token once the page runs. What the page *can* show is local to the device:
    the outbox in IndexedDB, listed by field-outbox.js.
    """
    from django.conf import settings

    # This trusted application script must travel with the cached fallback:
    # an uncached external script cannot read the local queue while offline.
    script = (Path(settings.BASE_DIR) / "static/js/field-outbox.js").read_text()
    return render(
        request,
        "pages/offline.html",
        {"csrf_token": "", "field_outbox_script": script},
    )
