"""AuthenticationLockoutService — the ONE canonical login-lockout policy
(Issue 3 of the audit). Every login surface (web session login, DRF API
login, Django admin login via LockoutEnforcingModelBackend) calls this and
only this — no login path may compute its own lockout logic.

Policy (the "safer enterprise default", explicitly directed — see
docs/auth-lockout-policy.md for the full writeup and the two systems this
replaces):
  1. AUTH_MAX_FAILED_LOGINS consecutive failures -> a TEMPORARY lock of
     AUTH_LOCKOUT_DURATION_MINUTES that auto-expires. Never permanent from a
     single burst.
  2. If AUTH_LOCKOUT_ESCALATION_COUNT separate lock cycles happen within
     AUTH_LOCKOUT_ESCALATION_WINDOW_HOURS of each other, the account
     escalates: locked until an admin explicitly unlocks it
     (AUTH_REQUIRE_ADMIN_UNLOCK_AFTER_ESCALATION), not on a timer.
  3. A failed-attempt streak older than AUTH_FAILED_LOGIN_RESET_WINDOW_MINUTES
     doesn't count toward the threshold (matches "successful login resets
     the counter" for someone who simply stopped, rather than got locked).
  4. All state changes are atomic (select_for_update) so concurrent
     requests can never race past the threshold.
  5. Every escalation, admin lock, and admin unlock is audited.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone


def _max_failed() -> int:
    return getattr(settings, "AUTH_MAX_FAILED_LOGINS", 10)


def _lockout_minutes() -> int:
    return getattr(settings, "AUTH_LOCKOUT_DURATION_MINUTES", 15)


def _escalation_count() -> int:
    return getattr(settings, "AUTH_LOCKOUT_ESCALATION_COUNT", 3)


def _escalation_window_hours() -> int:
    return getattr(settings, "AUTH_LOCKOUT_ESCALATION_WINDOW_HOURS", 24)


def _require_admin_unlock_after_escalation() -> bool:
    return getattr(settings, "AUTH_REQUIRE_ADMIN_UNLOCK_AFTER_ESCALATION", True)


def _reset_window_minutes() -> int:
    return getattr(settings, "AUTH_FAILED_LOGIN_RESET_WINDOW_MINUTES", 30)


@dataclass(frozen=True)
class LockoutState:
    locked: bool
    escalated: bool
    locked_until: object | None  # datetime | None
    remaining_seconds: int


class AuthenticationLockoutService:
    """Stateless — every method takes the User row and does its own atomic
    read-modify-write. Safe to call from any process/thread/request."""

    # ── Read-only status check (called BEFORE checking a password) ──────────
    @staticmethod
    def check_lockout(user) -> LockoutState:
        now = timezone.now()
        if user.lockout_escalated:
            return LockoutState(
                locked=True, escalated=True, locked_until=None, remaining_seconds=-1
            )
        if user.locked_until and user.locked_until > now:
            remaining = int((user.locked_until - now).total_seconds())
            return LockoutState(
                locked=True,
                escalated=False,
                locked_until=user.locked_until,
                remaining_seconds=remaining,
            )
        return LockoutState(
            locked=False, escalated=False, locked_until=None, remaining_seconds=0
        )

    # ── Failure path ──────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def record_failed_attempt(user_id: str) -> LockoutState:
        """Atomically increments the failed-attempt counter for the row
        locked via select_for_update — concurrent callers serialize on this
        row, so two simultaneous wrong-password requests can never both
        read count=N-1 and both fail to trip the threshold."""
        from .models import User

        user = User.objects.select_for_update().get(id=user_id)
        now = timezone.now()

        # A stale streak (older than the reset window) doesn't count — start fresh.
        reset_cutoff = now - timedelta(minutes=_reset_window_minutes())
        if (
            user.failed_login_streak_started_at
            and user.failed_login_streak_started_at < reset_cutoff
        ):
            user.failed_login_count = 0
            user.failed_login_streak_started_at = None

        if user.failed_login_count == 0:
            user.failed_login_streak_started_at = now
        user.failed_login_count += 1

        update_fields = ["failed_login_count", "failed_login_streak_started_at"]

        if user.failed_login_count >= _max_failed():
            # A lock cycle just fired. Is it within the escalation window of
            # the last one?
            window_cutoff = now - timedelta(hours=_escalation_window_hours())
            if user.last_lockout_at and user.last_lockout_at >= window_cutoff:
                user.lockout_cycle_count += 1
            else:
                user.lockout_cycle_count = 1
            user.last_lockout_at = now
            user.failed_login_count = 0
            user.failed_login_streak_started_at = None
            update_fields += ["lockout_cycle_count", "last_lockout_at"]

            if (
                user.lockout_cycle_count >= _escalation_count()
                and _require_admin_unlock_after_escalation()
            ):
                user.lockout_escalated = True
                user.locked_until = None
                update_fields += ["lockout_escalated", "locked_until"]
                AuthenticationLockoutService._audit(
                    action="auth.lockout_escalated",
                    user=user,
                    reason=f"{user.lockout_cycle_count} lockout cycles within "
                    f"{_escalation_window_hours()}h -- admin unlock required.",
                )
                AuthenticationLockoutService._notify_admins_of_escalation(user)
            else:
                user.locked_until = now + timedelta(minutes=_lockout_minutes())
                update_fields.append("locked_until")
                AuthenticationLockoutService._audit(
                    action="auth.lockout_started",
                    user=user,
                    reason=f"{_max_failed()} consecutive failed logins -- "
                    f"locked {_lockout_minutes()} minute(s).",
                )

        user.save(update_fields=update_fields)
        return AuthenticationLockoutService.check_lockout(user)

    # ── Success path ──────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def record_success(user_id: str) -> None:
        from .models import User

        User.objects.select_for_update().filter(id=user_id).update(
            failed_login_count=0,
            failed_login_streak_started_at=None,
            locked_until=None,
            last_login_at=timezone.now(),
        )
        # Deliberately NOT clearing lockout_cycle_count/lockout_escalated on
        # a mere successful login -- escalation state only clears via an
        # explicit admin_unlock (a correct password after enough failed
        # attempts to have escalated should never be reachable anyway,
        # since check_lockout blocks the attempt before the password is
        # even checked; this is a defense-in-depth guarantee, not the
        # primary gate).

    # ── Admin actions ─────────────────────────────────────────────────────────
    @staticmethod
    @transaction.atomic
    def admin_unlock(user_id: str, actor) -> None:
        from .models import User

        User.objects.select_for_update().filter(id=user_id).update(
            failed_login_count=0,
            failed_login_streak_started_at=None,
            locked_until=None,
            lockout_cycle_count=0,
            lockout_escalated=False,
        )
        AuthenticationLockoutService._audit(
            action="auth.admin_unlock",
            user_id=user_id,
            actor=actor,
            reason="Administrator manually unlocked the account.",
        )

    @staticmethod
    @transaction.atomic
    def admin_lock(user_id: str, actor, reason: str) -> None:
        from .models import User

        User.objects.select_for_update().filter(id=user_id).update(
            lockout_escalated=True,
            locked_until=None,
        )
        AuthenticationLockoutService._audit(
            action="auth.admin_lock",
            user_id=user_id,
            actor=actor,
            reason=reason or "Administrator manually locked the account.",
        )

    # ── Admin notification (fires identically regardless of which login
    # surface — web, API, or Django admin — triggered the escalation) ───────
    @staticmethod
    def _notify_admins_of_escalation(user) -> None:
        try:
            from apps.core.rbac import EdifyRole
            from apps.notifications.services import WorkflowNotificationService

            from .models import User

            admin_users = User.objects.filter(
                roles__contains=[EdifyRole.ADMIN.value],
                is_active=True,
                deleted_at__isnull=True,
            )
            WorkflowNotificationService.trigger(
                event_type="account_lockout",
                category="general",
                priority="high",
                title=f"Account Locked: {user.name}",
                body=f"{user.email} has been locked after repeated failed-login lockout "
                "cycles and requires an administrator to unlock it.",
                context_type="User",
                context_id=user.id,
                recipients=admin_users,
            )
        except Exception:  # noqa: BLE001 — a locked-out login must never itself crash on notify failure
            import logging

            logging.getLogger("edify.auth").exception(
                "Failed to notify admins of account escalation"
            )

    # ── Audit ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _audit(
        *, action: str, reason: str, user=None, user_id: str | None = None, actor=None
    ) -> None:
        try:
            from apps.audit.services import log as audit_log

            audit_log(
                action=action,
                subject_kind="User",
                subject_id=user_id or (user.id if user else None),
                actor_id=getattr(actor, "id", None) or "system",
                actor_role=getattr(actor, "active_role", None) or "System",
                success=True,
                reason=reason,
            )
        except Exception:  # noqa: BLE001 — a locked-out login must never itself crash on audit failure
            pass
