"""``{% static_v 'path' %}`` — a static URL that changes when the file does.

Static files here are served under their plain names (STORAGES["staticfiles"]
is the unhashed storage), so a browser or CDN can only cache them as long as
we dare let it: with the default sixty seconds, a page load on the live site
re-fetched every asset from a single 1-vCPU origin with a 1.5s time-to-first-
byte, and the client called the app slow (owner, 2026-09-11).

The stylesheets carry hand-bumped ``?v=`` keys in base.html. Everything else —
vendor scripts, fonts, the country boundaries — gets its key from the file's
own content here, so ``WHITENOISE_MAX_AGE`` can be long and a changed file is
still fetched fresh on the next deploy. The hash is computed once per process
per path.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()

_HASHES: dict[str, str] = {}


def static_version(path: str) -> str:
    key = _HASHES.get(path)
    if key is None:
        source = finders.find(path)
        key = ""
        if source:
            try:
                key = hashlib.md5(  # noqa: S324 — cache key, not security
                    Path(source).read_bytes(), usedforsecurity=False
                ).hexdigest()[:10]
            except OSError:
                key = ""
        _HASHES[path] = key
    return key


@register.simple_tag
def static_v(path: str) -> str:
    url = static(path)
    key = static_version(path)
    return f"{url}?v={key}" if key else url
