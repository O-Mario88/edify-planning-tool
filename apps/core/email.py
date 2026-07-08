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
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("edify.mailer")


@dataclass
class MailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None


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
        if (
            os.environ.get("EMAIL_PROVIDER") == "resend"
            and os.environ.get("RESEND_API_KEY")
        ):
            return "resend"
        return "console"

    @property
    def is_configured(self) -> bool:
        """True when email delivery is actually wired (not the console stub)."""
        return self.provider == "resend"

    def send(self, msg: MailMessage) -> dict:
        if self.provider == "resend":
            return self._send_via_resend(msg)
        # Console / dev — log the full message so a tester can complete the flow.
        logger.info("📧 [dev mail] To: %s | Subject: %s\n%s", msg.to, msg.subject, msg.text)
        return {"delivered": False, "devPreview": msg.text}

    def _send_via_resend(self, msg: MailMessage) -> dict:
        payload = {
            "from": os.environ.get("EMAIL_FROM") or "Edify Planning <noreply@edify.org>",
            "to": msg.to,
            "subject": msg.subject,
            "text": msg.text,
        }
        if msg.html:
            payload["html"] = msg.html
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.resend.com/emails",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {os.environ.get('RESEND_API_KEY', '')}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as res:
                if 200 <= res.status < 300:
                    return {"delivered": True}
                detail = res.read().decode("utf-8", "ignore")
                logger.error("Resend delivery failed (%s): %s", res.status, detail)
                return {"delivered": False}
        except Exception as exc:  # noqa: BLE001
            logger.error("Resend delivery error: %s", exc)
            return {"delivered": False}

    # ── Templates ────────────────────────────────────────────────────────
    def send_invitation(self, *, to: str, name: str, invited_by_name: str, token: str) -> dict:
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

    def send_temporary_password_notification(self, *, to: str, name: str, invited_by_name: str) -> dict:
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

    def send_password_reset_by_admin_notification(self, *, to: str, name: str, reset_by_name: str) -> dict:
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

__all__ = ["MailerService", "mailer", "MailMessage"]
