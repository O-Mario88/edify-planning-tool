"""SMS delivery, deliberately the same shape as apps.core.email.

One channel of the two-factor code goes over SMS, so this exists for the same
reason the mailer does and answers to the same rules:

  • dev (default / SMS_PROVIDER unset) — the message is not sent anywhere. It
    carries a live authentication code, so the body is logged only behind the
    same explicit opt-in the mailer uses; otherwise the log records that a
    message went out and withholds what was in it. A production deploy that
    forgets its credentials falls back to this provider, and without the gate
    every code would land in a log stream where it outlives the SMS and is
    readable by anyone with log access.

  • africastalking (SMS_PROVIDER=africastalking + SMS_API_KEY + SMS_USERNAME) —
    sends over Africa's Talking, which covers the Ugandan networks this is
    deployed against.

Adding a provider is one method and one branch in `send`. What must not change
is the contract: `send` returns whether the provider accepted the message and
never raises, because a failed SMS must degrade into "we could not reach you on
that number" rather than a stack trace on the login page.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from dataclasses import dataclass

from .blocking_io_guard import refuse_inside_transaction

logger = logging.getLogger("edify.sms")

# The provider round-trip sits inside a login request, so it is bounded well
# below anything a person would wait through.
REQUEST_TIMEOUT_SECONDS = 10


@dataclass
class SmsMessage:
    to: str
    text: str


class SmsService:
    """SMS delivery (console in dev, Africa's Talking in production).

    Instantiated lazily from the environment and cheap to construct, so tests
    can swap the provider by setting SMS_PROVIDER before construction.
    """

    @property
    def provider(self) -> str:
        if (
            os.environ.get("SMS_PROVIDER") == "africastalking"
            and os.environ.get("SMS_API_KEY")
            and os.environ.get("SMS_USERNAME")
        ):
            return "africastalking"
        return "console"

    @property
    def is_configured(self) -> bool:
        """True when SMS is actually wired up, rather than stubbed.

        The MFA enrolment surface asks this before offering SMS as a channel:
        letting someone enrol onto a channel that cannot deliver would lock
        them out of their own account at the next sign-in.
        """
        return self.provider == "africastalking"

    def send(self, msg: SmsMessage) -> dict:
        refuse_inside_transaction(f"SMS to {msg.to}")
        if self.provider == "africastalking":
            return self._send_via_africastalking(msg)

        from django.conf import settings as _s

        if getattr(_s, "SMS_LOG_BODIES", False) and not getattr(
            _s, "IS_PRODUCTION", False
        ):
            logger.info("[dev sms] To: %s\n%s", msg.to, msg.text)
        else:
            logger.info(
                "[sms] To: %s | body withheld (contains a one-time code)", msg.to
            )
        return {"delivered": False, "devPreview": msg.text}

    def _send_via_africastalking(self, msg: SmsMessage) -> dict:
        payload = urllib.parse.urlencode(
            {
                "username": os.environ.get("SMS_USERNAME", ""),
                "to": msg.to,
                "message": msg.text,
                "from": os.environ.get("SMS_SENDER_ID", "") or "",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://api.africastalking.com/version1/messaging",
            data=payload,
            method="POST",
            headers={
                "apiKey": os.environ.get("SMS_API_KEY", ""),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        try:
            # nosec B310 - the URL is the api.africastalking.com constant
            # above, not a value any caller or record can influence.
            with urllib.request.urlopen(  # nosec B310
                req, timeout=REQUEST_TIMEOUT_SECONDS
            ) as res:
                body = res.read().decode("utf-8", "ignore")
                if not 200 <= res.status < 300:
                    logger.error("SMS delivery failed (%s): %s", res.status, body)
                    return {"delivered": False}
                return {"delivered": self._accepted(body)}
        except Exception as exc:  # noqa: BLE001
            # Never raise into the login flow. The caller turns this into a
            # message about the number, not an error page.
            logger.error("SMS delivery error: %s", exc)
            return {"delivered": False}

    @staticmethod
    def _accepted(body: str) -> bool:
        """A 200 is not delivery. Africa's Talking answers 200 with a per-
        recipient status, and an invalid number comes back inside that
        envelope — treating the status code as success would tell someone
        their code was on its way to a number that had refused it."""
        try:
            recipients = json.loads(body)["SMSMessageData"]["Recipients"]
        except Exception:  # noqa: BLE001
            logger.error("SMS response could not be read: %s", body[:200])
            return False
        if not recipients:
            logger.error("SMS accepted for no recipients: %s", body[:200])
            return False
        return all(str(r.get("statusCode")) in {"101", "102"} for r in recipients)


sms = SmsService()

__all__ = ["SmsService", "SmsMessage", "sms"]
