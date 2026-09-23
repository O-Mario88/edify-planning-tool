"""The address of the client that sent a request, as the platform saw it.

Every consumer — the login and route rate limits, the audit context, the
sign-in record — used to take the LEFTMOST ``X-Forwarded-For`` entry. That
entry is whatever the client sent: a proxy appends the address it saw, it does
not replace what came before. Sending a different ``X-Forwarded-For`` on every
request therefore bought a fresh per-address login window each time (AUD-010
bypassed), and wrote an address of the caller's choosing into the audit trail.

The trustworthy address is the one a trusted hop added, so it is read, in
order, from:

1. ``settings.CLIENT_IP_HEADER`` — a header the platform edge sets itself.
   DigitalOcean App Platform puts the connecting client's address in
   ``DO-Connecting-IP`` and uses ``X-Forwarded-For`` for its own ingress hop,
   so production reads ``HTTP_DO_CONNECTING_IP`` (config/settings/prod.py).
2. ``X-Forwarded-For``, counted ``settings.TRUSTED_PROXY_HOPS`` entries from
   the RIGHT — only as many as there are proxies we operate. Zero (the
   default) ignores the header entirely.
3. ``REMOTE_ADDR`` — the peer that actually opened the connection.

A value that is not an IP address is skipped rather than trusted, so the result
is always a real address or ``None``.
"""

from __future__ import annotations

import ipaddress

from django.conf import settings


def _address(value) -> str | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def client_ip(request) -> str | None:
    """The client's address from the nearest trusted source, or ``None``."""
    meta = request.META
    header = getattr(settings, "CLIENT_IP_HEADER", "") or ""
    if header:
        found = _address(meta.get(header))
        if found:
            return found
    hops = int(getattr(settings, "TRUSTED_PROXY_HOPS", 0) or 0)
    if hops > 0:
        chain = [
            part.strip()
            for part in (meta.get("HTTP_X_FORWARDED_FOR") or "").split(",")
            if part.strip()
        ]
        if chain:
            found = _address(chain[-min(hops, len(chain))])
            if found:
                return found
    return _address(meta.get("REMOTE_ADDR"))


def throttle_ident(request) -> str:
    """The key a per-address rate limit counts against.

    The trusted client address when there is one. Otherwise the raw
    ``REMOTE_ADDR``, which the server sets and the client cannot choose, so it
    is safe to count against even when it does not parse as an address. Only
    when neither exists do requests share the ``unknown`` window.
    """
    return (
        client_ip(request)
        or (request.META.get("REMOTE_ADDR") or "").strip()
        or "unknown"
    )
