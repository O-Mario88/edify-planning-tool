"""
Email delivery for auth flows (invitations, password resets) — faithful port of
mailer.service.ts.

Two modes:
  • dev (default / EMAIL_PROVIDER unset) — logs the link to the console AND the
    caller returns it in the API response so an admin can copy it into the
    browser. No external dependency. Safe for local + docker-compose.
  • production (EMAIL_PROVIDER=resend + RESEND_API_KEY) — sends via Resend.

Rule: NEVER include a password in any email. Only links + context. Reset +
invite links carry a one-time token; the email contains only that link.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from .blocking_io_guard import refuse_inside_transaction

logger = logging.getLogger("edify.mailer")


@dataclass
class MailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None
    # Resend accepts base64-encoded attachment content.  Keeping this on the
    # transport DTO lets scheduled analytics reports use the same audited,
    # timeout-bounded provider as authentication mail.
    attachments: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class MailResult:
    """What the provider said about one message.

    ``accepted`` is the provider taking it, which is not the same as the
    recipient receiving it (that arrives later, as a provider event).
    ``retryable`` separates "try again later" (no network, rate limited, the
    provider's own fault) from "this message will be refused again".
    """

    accepted: bool
    provider_id: str = ""
    retryable: bool = False
    error: str = ""


#: Provider answers worth trying again: rate limited, or the provider's fault.
_RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})


class MailerService:
    """Email delivery service (console in dev, Resend in prod).

    Instantiated lazily from settings; cheap to construct. Tests can swap the
    provider by setting EMAIL_PROVIDER before construction.
    """

    @property
    def _app_base_url(self) -> str:
        return (os.environ.get("APP_BASE_URL") or "http://localhost:3000").rstrip("/")

    @property
    def provider(self) -> str:
        if os.environ.get("EMAIL_PROVIDER") == "resend" and os.environ.get(
            "RESEND_API_KEY"
        ):
            return "resend"
        return "console"

    @property
    def is_configured(self) -> bool:
        """True when email delivery is actually wired (not the console stub)."""
        return self.provider == "resend"

    def send(self, msg: MailMessage) -> dict:
        refuse_inside_transaction(f"Email to {msg.to}")
        if self.provider == "resend":
            return self._send_via_resend(msg)
        # Console / dev — the body carries password-reset and invitation
        # TOKENS, so it is logged only when explicitly opted in. A production
        # deploy that forgets RESEND_API_KEY silently falls back to this
        # provider; without the gate it would write every live token to the
        # log stream, where they outlive the email and are readable by anyone
        # with log access.
        from django.conf import settings as _s

        if getattr(_s, "EMAIL_LOG_BODIES", False) and not getattr(
            _s, "IS_PRODUCTION", False
        ):
            logger.info(
                "[dev mail] To: %s | Subject: %s\n%s", msg.to, msg.subject, msg.text
            )
        else:
            logger.info(
                "[mail] To: %s | Subject: %s | body withheld (contains tokens)",
                msg.to,
                msg.subject,
            )
        return {"delivered": False, "devPreview": msg.text}

    def deliver(self, msg: MailMessage, *, idempotency_key: str = "") -> MailResult:
        """Send one message and say exactly what happened.

        With no provider set up nothing is sent and nothing is claimed: the
        result is not accepted and not retryable. ``idempotency_key`` is
        passed to the provider, which then sends a repeat of the same key
        once — so a retry after a lost answer cannot email twice.
        """
        refuse_inside_transaction(f"Email to {msg.to}")
        if self.provider != "resend":
            return MailResult(accepted=False, error="not_configured")
        return self._resend_request(msg, idempotency_key=idempotency_key)

    def _resend_request(
        self, msg: MailMessage, *, idempotency_key: str = ""
    ) -> MailResult:
        payload = {
            "from": os.environ.get("EMAIL_FROM")
            or "Edify Planning <noreply@edify.org>",
            "to": msg.to,
            "subject": msg.subject,
            "text": msg.text,
        }
        if msg.html:
            payload["html"] = msg.html
        if msg.attachments:
            payload["attachments"] = msg.attachments
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {os.environ.get('RESEND_API_KEY', '')}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key[:256]
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            # nosec B310 - the URL is the api.resend.com constant above,
            # not a value that any caller or record can influence.
            with urllib.request.urlopen(req, timeout=15) as res:  # nosec B310
                answer = res.read().decode("utf-8", "ignore")
                if 200 <= res.status < 300:
                    try:
                        provider_id = str(json.loads(answer or "{}").get("id") or "")
                    except ValueError:
                        provider_id = ""
                    return MailResult(accepted=True, provider_id=provider_id[:128])
                logger.error("Resend delivery failed (%s)", res.status)
                return MailResult(
                    accepted=False,
                    retryable=res.status in _RETRYABLE_STATUS,
                    error=f"HTTP {res.status}",
                )
        except urllib.error.HTTPError as exc:
            # The provider's answer body can echo the message; only the
            # status is kept.
            logger.error("Resend delivery refused (%s)", exc.code)
            return MailResult(
                accepted=False,
                retryable=exc.code in _RETRYABLE_STATUS,
                error=f"HTTP {exc.code}",
            )
        except Exception as exc:  # noqa: BLE001 — network, DNS, timeout
            logger.error("Resend delivery error: %s", type(exc).__name__)
            return MailResult(accepted=False, retryable=True, error=type(exc).__name__)

    def _send_via_resend(self, msg: MailMessage) -> dict:
        return {"delivered": self._resend_request(msg).accepted}

    # ── Templates ────────────────────────────────────────────────────────
    def send_invitation(
        self, *, to: str, name: str, invited_by_name: str, token: str
    ) -> dict:
        link = f"{self._app_base_url}/set-password?token={token}"
        subject = "You have been invited to Edify Planning and Monitoring Tool"
        text = "\n".join(
            [
                f"Hello {name},",
                "",
                f"{invited_by_name} has invited you to join the Edify Planning and Monitoring Tool.",
                "",
                "To activate your account, set your password by opening this link:",
                link,
                "",
                "This invitation expires in 7 days and can only be used once.",
                "",
                "If you did not expect this invitation, you can safely ignore this email.",
                "",
                "— Edify Planning and Monitoring Tool",
            ]
        )
        return self.send(MailMessage(to=to, subject=subject, text=text))

    def send_temporary_password_notification(
        self, *, to: str, name: str, invited_by_name: str
    ) -> dict:
        link = f"{self._app_base_url}/login"
        subject = "Your account has been created on Edify Planning and Monitoring Tool"
        text = "\n".join(
            [
                f"Hello {name},",
                "",
                f"{invited_by_name} has created an account for you on the Edify Planning and Monitoring Tool.",
                "",
                "Your administrator has configured a temporary password for your account.",
                "You can log in using your email and that temporary password here:",
                link,
                "",
                "Please update your password after logging in for the first time.",
                "",
                "— Edify Planning and Monitoring Tool",
            ]
        )
        return self.send(MailMessage(to=to, subject=subject, text=text))

    def send_password_reset(self, *, to: str, name: str, token: str) -> dict:
        link = f"{self._app_base_url}/reset-password?token={token}"
        subject = "Reset your Edify Planning password"
        text = "\n".join(
            [
                f"Hello {name},",
                "",
                "We received a request to reset your password. You can set a new one here:",
                link,
                "",
                "This link expires in 45 minutes and can only be used once.",
                "",
                "If you did not request a password reset, you can safely ignore this email.",
                "",
                "— Edify Planning and Monitoring Tool",
            ]
        )
        return self.send(MailMessage(to=to, subject=subject, text=text))

    def send_password_reset_by_admin_notification(
        self, *, to: str, name: str, reset_by_name: str
    ) -> dict:
        link = f"{self._app_base_url}/login"
        subject = "Your Edify account password has been reset"
        text = "\n".join(
            [
                f"Hello {name},",
                "",
                f"Your password has been reset by {reset_by_name}.",
                "",
                "You can log in using your email and the new password provided by your administrator:",
                link,
                "",
                "You will be required to change your password after logging in.",
                "",
                "If you did not expect this change, please contact your administrator immediately.",
                "",
                "— Edify Planning and Monitoring Tool",
            ]
        )
        return self.send(MailMessage(to=to, subject=subject, text=text))


mailer = MailerService()

__all__ = ["MailerService", "mailer", "MailMessage", "MailResult"]
