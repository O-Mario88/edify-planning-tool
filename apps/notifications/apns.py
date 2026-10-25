"""Apple's push service (APNs): how a notification reaches the iOS app.

The phone decides whether it shows Edify's notifications (Settings → Edify →
Notifications); this module only sends. Its three outcomes are Web Push's
(apps.notifications.webpush), so the delivery code treats every phone alike:

* `PushGone`: the device will never take another message (the app was
  deleted, the phone restored or reset). Forget it.
* `PushRejected`: this request will be refused however often it is sent.
  Record why; do not retry.
* `PushUnavailable`: Apple could not take it now (busy, down, no network, a
  signature that just expired). The outbox retries with backoff.

Requests are signed with the team's APNs key (a ``.p8`` file from the Apple
Developer account: settings ``APNS_KEY_ID``, ``APNS_TEAM_ID`` and
``APNS_PRIVATE_KEY``), as a short-lived ES256 token that Apple accepts for up
to an hour and wants reused, not made per message. Apple speaks HTTP/2 only.
"""

from __future__ import annotations

import json
import re
import threading
import time

from django.conf import settings

from .webpush import PushGone, PushRejected, PushUnavailable

__all__ = [
    "PushGone",
    "PushRejected",
    "PushUnavailable",
    "configured",
    "forget_token",
    "send",
    "valid_token",
]

HOSTS = {
    "production": "https://api.push.apple.com",
    "development": "https://api.sandbox.push.apple.com",
}
#: Apple refuses a signature older than an hour, and throttles one made more
#: often than every twenty minutes: renewed at fifty.
TOKEN_LIFETIME_SECONDS = 50 * 60
#: The reasons Apple gives for a device that is never coming back.
GONE_REASONS = {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}
TIMEOUT_SECONDS = 10.0
#: What iOS hands an app for its push address: hex, 32 bytes today, and
#: Apple warns the length may grow. Never an address of anything else.
_TOKEN = re.compile(r"^[0-9a-fA-F]{64,200}$")

_lock = threading.Lock()
_token: tuple[str, float] | None = None


def configured() -> bool:
    return bool(
        getattr(settings, "APNS_KEY_ID", "")
        and getattr(settings, "APNS_TEAM_ID", "")
        and getattr(settings, "APNS_PRIVATE_KEY", "")
    )


def valid_token(token: str) -> bool:
    """Is ``token`` the device token iOS gives an app (a raw APNs token)?"""
    return bool(_TOKEN.match(token or ""))


def forget_token() -> None:
    """Drop the signature in hand, so the next request makes a new one."""
    global _token
    with _lock:
        _token = None


def _signature() -> str:
    global _token
    import jwt

    now = time.time()
    with _lock:
        if _token and now - _token[1] < TOKEN_LIFETIME_SECONDS:
            return _token[0]
        # A key pasted into an environment variable often has its line
        # breaks written as "\n".
        key = settings.APNS_PRIVATE_KEY.replace("\\n", "\n")
        token = jwt.encode(
            {"iss": settings.APNS_TEAM_ID, "iat": int(now)},
            key,
            algorithm="ES256",
            headers={"kid": settings.APNS_KEY_ID},
        )
        _token = (token, now)
        return token


def _post(url: str, headers: dict, body: bytes) -> tuple[int, str]:
    """One HTTP/2 request; Apple's status and body. The seam tests replace."""
    import httpx

    with httpx.Client(http2=True, timeout=TIMEOUT_SECONDS) as client:
        response = client.post(url, headers=headers, content=body)
    return response.status_code, response.text


def _reason(text: str) -> str:
    try:
        return str(json.loads(text or "{}").get("reason", ""))
    except (ValueError, AttributeError):
        return ""


def send(
    device_token: str,
    message: dict,
    *,
    priority: str = "normal",
    collapse_id: str = "",
    expires_in: int = 24 * 60 * 60,
) -> None:
    """Send ``message`` (``title``, ``body``, ``url``) to one iPhone.

    ``collapse_id`` makes a re-send replace the copy already on the phone;
    ``expires_in`` is how long Apple holds it for a phone that is off.
    Raises `PushGone`, `PushRejected` or `PushUnavailable`.
    """
    import httpx

    if not configured():
        raise PushRejected("APNs is not configured on this deployment.")
    environment = getattr(settings, "APNS_ENVIRONMENT", "production")
    host = HOSTS.get(environment, HOSTS["production"])
    payload = {
        "aps": {
            "alert": {
                "title": message.get("title", ""),
                "body": message.get("body", ""),
            },
            "sound": "default",
            # Notifications of one kind stack together in the tray.
            "thread-id": str(message.get("category") or "edify"),
        },
        "url": message.get("url", "/notifications"),
        "id": message.get("id", ""),
    }
    headers = {
        "authorization": f"bearer {_signature()}",
        "apns-topic": settings.APNS_TOPIC,
        "apns-push-type": "alert",
        # 10 is "now"; 5 lets the phone wait for a moment that spares its
        # battery, which an ordinary notice can afford.
        "apns-priority": "10" if priority in ("high", "urgent") else "5",
        "apns-expiration": str(int(time.time()) + int(expires_in)),
    }
    if collapse_id:
        # Apple allows at most 64 bytes.
        headers["apns-collapse-id"] = collapse_id[:64]
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    try:
        status, text = _post(f"{host}/3/device/{device_token}", headers, body)
    except httpx.HTTPError as exc:
        raise PushUnavailable(f"{type(exc).__name__}: {exc}") from exc
    if status == 200:
        return
    reason = _reason(text)
    detail = f"{status} {reason}".strip()
    if status == 410 or reason in GONE_REASONS:
        raise PushGone(detail)
    if status == 403 and reason == "ExpiredProviderToken":
        forget_token()
        raise PushUnavailable(detail)
    if status == 429 or status >= 500:
        raise PushUnavailable(detail)
    raise PushRejected(detail)
