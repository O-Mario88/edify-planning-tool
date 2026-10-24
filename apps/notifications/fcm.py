"""Firebase Cloud Messaging: one message to the Edify app on one phone.

The brief of 2026-10-23: the Capacitor app on Android and iPhone gets the
same notifications as a browser does. An app's web view cannot use Web Push,
so the app registers with Firebase instead and hands this server its device
token (`push.register_app`). Firebase delivers to Android itself and to an
iPhone through Apple's push service (APNs), using the APNs key the owner
uploads to the Firebase project, so one sender serves both.

This is the wire half, the counterpart of `webpush`:

* **Signing in** — the FCM HTTP v1 API takes an OAuth access token, which is
  had for a JWT signed with the project's service-account key (RFC 7523),
  kept until shortly before it expires. Written against ``PyJWT`` and
  ``requests``, which the platform already ships, rather than adding the
  Firebase Admin SDK and its dependency tree for two requests.
* **Sending** — the notification's title and text, and the address a tap
  opens, as string data. A repeat of the same notification replaces the one
  already shown (an Android tag, an APNs collapse id).
* **Answers** — sorted into the three outcomes `webpush` defines, so the
  delivery path treats a phone and a browser alike: `PushGone` (the app was
  removed or its token replaced: forget the device), `PushRejected` (the same
  request will fail again, often the server's own set-up) and
  `PushUnavailable` (try again later).

Only two addresses are ever posted to, both fixed here: Google's token
endpoint and FCM's send endpoint. A device token travels in the body, so
nothing a phone sends can point this server anywhere else.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from django.conf import settings

from .webpush import PushGone, PushRejected, PushUnavailable

__all__ = [
    "ANDROID_CHANNEL",
    "configured",
    "forget_token",
    "message_for",
    "send",
    "valid_token",
]

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://fcm.googleapis.com/v1/projects/{project}/messages:send"
SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
#: The Android notification channel the app creates (static/js/native-push.js):
#: its name is what a person sees in the phone's notification settings.
ANDROID_CHANNEL = "edify"
#: An access token is good for an hour; one this close to expiry is renewed.
_RENEW_BEFORE_SECONDS = 5 * 60
_ASSERTION_LIFETIME_SECONDS = 60 * 60
#: An FCM registration token: an instance id, a colon and a signed key, in the
#: URL-safe alphabet. Seen at around 160 characters; the bounds are generous.
_TOKEN = re.compile(r"^[A-Za-z0-9_\-]+:[A-Za-z0-9_\-.]+$")
_TOKEN_MIN, _TOKEN_MAX = 32, 4096
#: What an iPhone app built without Firebase hands over instead: Apple's raw
#: 32-byte device token in hex, which FCM cannot address.
_RAW_APNS = re.compile(r"^[0-9a-fA-F]{64}$")
_RETRYABLE_CODES = frozenset({"UNAVAILABLE", "INTERNAL", "QUOTA_EXCEEDED"})
_GONE_CODES = frozenset({"UNREGISTERED", "SENDER_ID_MISMATCH"})


@dataclass(frozen=True)
class ServiceAccount:
    project_id: str
    client_email: str
    private_key: str
    key_id: str


# ── This deployment's Firebase key ──────────────────────────────────────────
@lru_cache(maxsize=4)
def _parse(raw: str) -> ServiceAccount | None:
    text = (raw or "").strip()
    if not text:
        return None
    if not text.startswith("{"):
        try:
            text = base64.b64decode(text, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    fields = (data.get("project_id"), data.get("client_email"), data.get("private_key"))
    if not all(isinstance(value, str) and value.strip() for value in fields):
        return None
    return ServiceAccount(
        project_id=data["project_id"].strip(),
        client_email=data["client_email"].strip(),
        private_key=data["private_key"],
        key_id=str(data.get("private_key_id") or ""),
    )


def _account() -> ServiceAccount | None:
    raw = (getattr(settings, "FCM_SERVICE_ACCOUNT_JSON", "") or "").strip()
    path = (getattr(settings, "FCM_SERVICE_ACCOUNT_FILE", "") or "").strip()
    if not raw and path:
        try:
            raw = Path(path).read_text(encoding="utf-8")
        except OSError:
            return None
    return _parse(raw)


def configured() -> bool:
    """App push is on only where the deployment has its Firebase key."""
    return _account() is not None


# ── Signing in ──────────────────────────────────────────────────────────────
_lock = threading.Lock()
_held: dict[tuple[str, str], tuple[str, float]] = {}


def forget_token() -> None:
    """Drop the access token held, so the next send signs in afresh."""
    with _lock:
        _held.clear()


def _assertion(account: ServiceAccount, now: float) -> str:
    import jwt

    return jwt.encode(
        {
            "iss": account.client_email,
            "scope": SCOPE,
            "aud": TOKEN_URL,
            "iat": int(now),
            "exp": int(now) + _ASSERTION_LIFETIME_SECONDS,
        },
        account.private_key,
        algorithm="RS256",
        headers={"kid": account.key_id} if account.key_id else None,
    )


def _access_token(account: ServiceAccount, *, timeout: float) -> str:
    import requests

    key = (account.client_email, account.key_id)
    now = time.time()
    with _lock:
        held = _held.get(key)
    if held and held[1] - _RENEW_BEFORE_SECONDS > now:
        return held[0]
    try:
        response = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": _assertion(account, now),
            },
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise PushUnavailable(f"{type(exc).__name__}: {exc}") from exc
    status = response.status_code
    if status == 429 or status >= 500:
        raise PushUnavailable(f"Google sign-in answered {status}")
    try:
        body = response.json()
    except ValueError:
        body = {}
    body = body if isinstance(body, dict) else {}
    token = body.get("access_token")
    if status != 200 or not token:
        # The key was refused (revoked, deleted, or another project's): the
        # set-up is wrong and every send will fail the same way.
        raise PushRejected(
            f"Google refused the Firebase key ({status} {body.get('error', '')})"
        )
    expires = now + float(body.get("expires_in") or 3600)
    with _lock:
        _held[key] = (token, expires)
    return token


# ── Device tokens ───────────────────────────────────────────────────────────
def valid_token(token: str) -> bool:
    """Is ``token`` an FCM registration token (and not a raw APNs one)?"""
    token = token or ""
    if not (_TOKEN_MIN <= len(token) <= _TOKEN_MAX):
        return False
    return bool(_TOKEN.match(token)) and not _RAW_APNS.match(token)


# ── Sending ─────────────────────────────────────────────────────────────────
def message_for(
    token: str, payload: dict, *, ttl: int, urgent: bool, collapse: str
) -> dict:
    """The FCM v1 message for one device: shown by the phone itself, with
    the notification's id and address as data for the tap."""
    data = {key: str(value) for key, value in payload.items() if value is not None}
    collapse = (collapse or "edify")[:64]
    return {
        "token": token,
        "notification": {
            "title": str(payload.get("title") or "Edify"),
            "body": str(payload.get("body") or ""),
        },
        "data": data,
        "android": {
            "priority": "HIGH" if urgent else "NORMAL",
            "ttl": f"{int(ttl)}s",
            "collapse_key": collapse,
            "notification": {
                "tag": str(payload.get("tag") or "edify"),
                "channel_id": ANDROID_CHANNEL,
                # A locked phone shows that Edify has something, not what:
                # no school, person or amount on the lock screen.
                "visibility": "PRIVATE",
            },
        },
        "apns": {
            "headers": {
                "apns-priority": "10" if urgent else "5",
                "apns-collapse-id": collapse,
                "apns-expiration": str(int(time.time()) + int(ttl)),
            },
            "payload": {
                "aps": {
                    "sound": "default",
                    "thread-id": str(payload.get("category") or "edify"),
                }
            },
        },
    }


def _error_parts(body) -> tuple[str, set[str], str]:
    """``(message, error codes, status word)`` of an FCM error answer."""
    error = body.get("error") if isinstance(body, dict) else None
    error = error if isinstance(error, dict) else {}
    details = error.get("details")
    details = details if isinstance(details, list) else []
    codes = {
        str(item["errorCode"])
        for item in details
        if isinstance(item, dict) and item.get("errorCode")
    }
    return str(error.get("message") or ""), codes, str(error.get("status") or "")


def _failure(status: int, body) -> Exception:
    """The outcome a refused send stands for."""
    message, codes, word = _error_parts(body)
    detail = f"{status} {', '.join(sorted(codes)) or word} {message}".strip()[:240]
    if "THIRD_PARTY_AUTH_ERROR" in codes:
        # Apple refused the APNs key uploaded to Firebase: the set-up, not
        # the phone. The device is kept for when the key is fixed.
        return PushRejected(detail)
    if status == 404 or codes & _GONE_CODES:
        return PushGone(detail)
    if status == 400 and "registration token" in message.lower():
        return PushGone(detail)
    if status == 401:
        # The access token expired or was revoked early: sign in again.
        forget_token()
        return PushUnavailable(detail)
    if status == 429 or status >= 500 or codes & _RETRYABLE_CODES:
        return PushUnavailable(detail)
    return PushRejected(detail)


def send(
    token: str,
    payload: dict,
    *,
    ttl: int,
    urgent: bool,
    collapse: str,
    timeout: float = 10.0,
) -> str:
    """Send ``payload`` to the app on the device with ``token``; the message
    name FCM gave it. Raises `PushGone`, `PushRejected` or `PushUnavailable`.
    """
    import requests

    account = _account()
    if account is None:
        raise PushRejected("App push is not configured on this deployment.")
    if not valid_token(token):
        raise PushGone("That is not an FCM registration token.")
    access = _access_token(account, timeout=timeout)
    message = message_for(token, payload, ttl=ttl, urgent=urgent, collapse=collapse)
    try:
        response = requests.post(
            SEND_URL.format(project=account.project_id),
            json={"message": message},
            headers={"Authorization": f"Bearer {access}"},
            timeout=timeout,
            allow_redirects=False,
        )
    except requests.RequestException as exc:
        raise PushUnavailable(f"{type(exc).__name__}: {exc}") from exc
    try:
        body = response.json()
    except ValueError:
        body = None
    if response.status_code == 200:
        return str(body.get("name", "")) if isinstance(body, dict) else ""
    raise _failure(response.status_code, body)
