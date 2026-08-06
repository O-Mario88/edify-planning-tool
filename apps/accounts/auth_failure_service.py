"""AuthenticationFailureService — the ONE canonical PUBLIC failure response
for every pre-authentication login surface (web session login, DRF API
login; Django admin login shares LockoutEnforcingModelBackend's enforcement
and already renders its own generic built-in message).

SEC-02: an unknown email, a wrong password, and a locked/escalated account
must be externally indistinguishable — identical message, identical HTTP
status — so a caller cannot enumerate which accounts exist or which are
locked. The real cause is still recorded on the tamper-evident audit chain
so an Admin investigating a support request can see what actually happened.
"""

from __future__ import annotations

GENERIC_LOGIN_ERROR = "Invalid email or password."


class AuthenticationFailureService:
    @staticmethod
    def reject(*, email: str, user=None, reason: str) -> str:
        """Audit the real cause; return the one public-facing message every
        login surface must show regardless of `reason`."""
        try:
            from apps.audit.services import log as audit_log

            audit_log(
                action="auth.login_failed",
                subject_kind="User",
                subject_id=user.id if user else None,
                actor_id=(user.id if user else None) or "anonymous",
                actor_role=getattr(user, "active_role", None) or "Unknown",
                success=False,
                reason=reason,
                payload={"email": email},
            )
        except Exception:  # noqa: BLE001 — a rejected login must never itself crash on audit failure
            pass
        return GENERIC_LOGIN_ERROR
