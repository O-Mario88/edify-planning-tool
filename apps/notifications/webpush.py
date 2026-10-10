"""Web Push: one encrypted message to one browser's push service.

Owner's brief, 2026-10-10: "implement the notification requirement as a real
mobile notification architecture, not a UI drawer pretending to be phone
notifications ... Backend Event → Notification Service → Push Subscription →
Phone OS → Notification Center → Lock Screen."

This is the wire half of that: the standards a phone's browser (or an
installed PWA) accepts a notification by.

* **RFC 8291** (Message Encryption for Web Push) with the ``aes128gcm``
  content coding of **RFC 8188**: the payload is encrypted to the key the
  browser made when it subscribed, so the push service that carries it —
  Google's, Mozilla's, Apple's, Microsoft's — cannot read it.
* **RFC 8292** (VAPID): each request is signed with this deployment's key, so
  the push service knows who is sending and only this server can send to the
  subscriptions made with its public key.

It is written against ``cryptography`` and ``PyJWT``, which the platform
already ships, rather than adding a push library and its own dependency tree
for some sixty lines of key agreement.

A subscription's endpoint is a URL the browser hands us, so it is user input
that this server would then POST to: `allowed_endpoint` accepts only https
URLs on the push services browsers actually use (`PUSH_SERVICE_HOSTS`), which
keeps the sender from being pointed at an internal address.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

__all__ = [
    "PUSH_SERVICE_HOSTS",
    "PushGone",
    "PushRejected",
    "PushUnavailable",
    "allowed_endpoint",
    "application_server_key",
    "configured",
    "encrypt",
    "generate_vapid_keys",
    "send",
]

#: The push services of the browsers that implement Web Push: Chrome, Edge,
#: Opera, Samsung Internet and every Chromium (FCM), Firefox (Mozilla
#: autopush), Safari on iOS, iPadOS and macOS (Apple), and legacy Edge
#: (Windows Notification Service). A host matches itself or a subdomain.
PUSH_SERVICE_HOSTS = (
    "fcm.googleapis.com",
    "android.googleapis.com",
    "updates.push.services.mozilla.com",
    "push.services.mozilla.com",
    "push.apple.com",
    "notify.windows.com",
)

#: One record: the payloads here are a title, a line of text and an address.
_RECORD_SIZE = 4096
#: A push service must accept 4096 bytes; the plaintext leaves room for the
#: header (86), the padding delimiter (1) and the GCM tag (16).
MAX_PLAINTEXT = 3900
#: How long a signature is good for. RFC 8292 allows up to 24 hours.
_VAPID_LIFETIME_SECONDS = 12 * 60 * 60


class PushGone(Exception):
    """The subscription no longer exists (404, 410): the browser's permission
    was withdrawn, the app was uninstalled, or the subscription expired. It
    is never coming back and must be forgotten."""


class PushRejected(Exception):
    """The push service refused this message for good (400, 401, 403, 413):
    retrying the same request cannot succeed."""


class PushUnavailable(Exception):
    """The push service could not take the message now (429, 5xx, no
    network): worth another attempt later."""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64url(text: str) -> bytes:
    text = (text or "").strip()
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def allowed_endpoint(endpoint: str) -> bool:
    """Is ``endpoint`` an https address on a browser's push service?"""
    try:
        parts = urlsplit(endpoint or "")
    except ValueError:
        return False
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host or parts.username or parts.password:
        return False
    extra = tuple(getattr(settings, "WEBPUSH_EXTRA_HOSTS", ()) or ())
    return any(
        host == allowed or host.endswith("." + allowed)
        for allowed in (*PUSH_SERVICE_HOSTS, *extra)
    )


# ── This deployment's key ───────────────────────────────────────────────────
def generate_vapid_keys() -> tuple[str, str]:
    """A new key pair as ``(public, private)``, both base64url: the public
    one is the uncompressed P-256 point a browser subscribes with, the
    private one the raw 32-byte scalar."""
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64url(public), _b64url(private)


def application_server_key() -> str:
    """The public key a browser subscribes with, base64url; "" when push is
    not configured here."""
    return (getattr(settings, "WEBPUSH_VAPID_PUBLIC_KEY", "") or "").strip()


def configured() -> bool:
    """Push is on only where the deployment has its key pair."""
    return bool(
        application_server_key()
        and (getattr(settings, "WEBPUSH_VAPID_PRIVATE_KEY", "") or "").strip()
    )


def _private_key() -> ec.EllipticCurvePrivateKey:
    raw = _unb64url(settings.WEBPUSH_VAPID_PRIVATE_KEY)
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def _vapid_header(endpoint: str) -> str:
    """``Authorization: vapid t=<signed token>, k=<public key>`` (RFC 8292):
    the token names the push service it is for and expires."""
    import jwt

    parts = urlsplit(endpoint)
    token = jwt.encode(
        {
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(time.time()) + _VAPID_LIFETIME_SECONDS,
            "sub": getattr(settings, "WEBPUSH_SUBJECT", "") or "mailto:admin@edify.org",
        },
        _private_key(),
        algorithm="ES256",
    )
    return f"vapid t={token}, k={application_server_key()}"


# ── RFC 8291 ────────────────────────────────────────────────────────────────
def _hkdf(length: int, salt: bytes, info: bytes, key: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(
        key
    )


def encrypt(
    plaintext: bytes,
    p256dh: str,
    auth: str,
    *,
    _sender_key: ec.EllipticCurvePrivateKey | None = None,
    _salt: bytes | None = None,
) -> bytes:
    """``plaintext`` encrypted to a subscription's keys (``p256dh``: the
    browser's public key; ``auth``: its 16-byte secret, both base64url), as
    one ``aes128gcm`` record with its header.

    ``_sender_key`` and ``_salt`` are fresh for every message; a test passes
    them to reproduce the RFC's worked example."""
    if len(plaintext) > MAX_PLAINTEXT:
        raise ValueError("A push payload must fit one record.")
    receiver_public = _unb64url(p256dh)
    auth_secret = _unb64url(auth)
    receiver = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), receiver_public
    )
    sender = _sender_key or ec.generate_private_key(ec.SECP256R1())
    sender_public = sender.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    shared = sender.exchange(ec.ECDH(), receiver)
    # The input keying material binds both public keys and the browser's
    # secret, so only that browser can derive the content key.
    ikm = _hkdf(
        32,
        auth_secret,
        b"WebPush: info\x00" + receiver_public + sender_public,
        shared,
    )
    salt = _salt or os.urandom(16)
    key = _hkdf(16, salt, b"Content-Encoding: aes128gcm\x00", ikm)
    nonce = _hkdf(12, salt, b"Content-Encoding: nonce\x00", ikm)
    # 0x02 closes the last (and only) record.
    sealed = AESGCM(key).encrypt(nonce, plaintext + b"\x02", None)
    header = (
        salt + struct.pack("!I", _RECORD_SIZE) + bytes([len(sender_public)])
    ) + sender_public
    return header + sealed


@dataclass(frozen=True)
class Target:
    """Where one message goes: a subscription's endpoint and keys."""

    endpoint: str
    p256dh: str
    auth: str


def send(
    target: Target,
    payload: dict,
    *,
    ttl: int = 24 * 60 * 60,
    urgency: str = "normal",
    topic: str = "",
    timeout: float = 10.0,
) -> int:
    """POST ``payload`` to the subscription's push service; the status it
    answered with (201 Created, or 200/202/204 on some services).

    ``ttl`` is how long the service keeps the message for a phone that is
    off or out of signal before dropping it; ``topic`` lets a newer message
    with the same topic replace an older one that is still waiting, so a
    phone that comes back is not handed two of the same.

    Raises `PushGone`, `PushRejected` or `PushUnavailable`.
    """
    import requests

    if not configured():
        raise PushRejected("Web Push is not configured on this deployment.")
    if not allowed_endpoint(target.endpoint):
        raise PushRejected("The endpoint is not a browser push service.")
    body = encrypt(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        target.p256dh,
        target.auth,
    )
    headers = {
        "Authorization": _vapid_header(target.endpoint),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(int(ttl)),
        "Urgency": urgency
        if urgency in ("very-low", "low", "normal", "high")
        else "normal",
    }
    if topic:
        # A topic is at most 32 characters of the URL-safe base64 alphabet.
        headers["Topic"] = topic[:32]
    try:
        response = requests.post(
            target.endpoint,
            data=body,
            headers=headers,
            timeout=timeout,
            # A push service answers the address it was given: following a
            # redirect would send the message somewhere the allow-list never
            # saw.
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise PushUnavailable(f"{type(exc).__name__}: {exc}") from exc
    status = response.status_code
    if status in (200, 201, 202, 204):
        return status
    detail = f"{status} {(response.text or '')[:200]}".strip()
    if status in (404, 410):
        raise PushGone(detail)
    if status == 429 or status >= 500:
        raise PushUnavailable(detail)
    raise PushRejected(detail)
