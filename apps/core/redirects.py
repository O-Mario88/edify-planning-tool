"""Redirect only to somewhere on this site.

Views here build redirect targets by interpolating a value into a path — an
activity id, a thread id, a fiscal year off the query string. Most of those
values come from a URL segment the router has already constrained, so the
result is a local path in practice. "In practice" is the problem: the check
lives in a route pattern several files away, and a value that starts with `//`
turns `redirect("/my-plan//evil.example")` into a protocol-relative jump to
another host. An open redirect on an authenticated app is a credible phishing
primitive — the link genuinely does come from this domain.

`local_redirect` is the one place that decision is made. It uses Django's own
`url_has_allowed_host_and_scheme`, which rejects absolute URLs,
protocol-relative URLs and anything with a scheme, and falls back to a known
page rather than refusing to respond.
"""

from __future__ import annotations

from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

# Where a rejected target lands. The dashboard exists for every role.
DEFAULT_FALLBACK = "/dashboard"


def is_local_path(target: str) -> bool:
    """True when `target` is a path on this site and nothing else."""
    if not target or not target.startswith("/") or target.startswith("//"):
        return False
    # allowed_hosts=None means "no host is acceptable", which is the point:
    # a target that names any host at all is not a local path.
    return url_has_allowed_host_and_scheme(
        target, allowed_hosts=None, require_https=False
    )


def local_redirect(target: str, *, fallback: str = DEFAULT_FALLBACK):
    """Redirect to `target` when it is a local path, else to `fallback`."""
    return redirect(target if is_local_path(target) else fallback)
