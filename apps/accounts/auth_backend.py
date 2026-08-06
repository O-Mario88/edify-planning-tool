"""LockoutEnforcingModelBackend — wraps Django's ModelBackend so that
EVERY call to django.contrib.auth.authenticate() enforces
AuthenticationLockoutService, including paths this codebase doesn't
directly control the view code for: Django's own /admin/login/.

Before this fix, AUTHENTICATION_BACKENDS was plain ModelBackend, which only
checks password + is_active — Django admin login was a THIRD, completely
unguarded login path with zero lockout enforcement, independent of the two
already-known-divergent custom paths (web session login, DRF API login).

apps/frontend/views/auth_views.py::login_view and
apps.accounts.auth_services.login() (the DRF path) are also migrated to
call django.contrib.auth.authenticate() rather than hand-rolling their own
password/lockout checks — so all three surfaces run through this one
backend, which is itself a thin wrapper around AuthenticationLockoutService
(the actual policy lives there, not here).
"""

from __future__ import annotations

from django.contrib.auth.backends import ModelBackend

from .lockout_service import AuthenticationLockoutService
from .models import User


class LockoutEnforcingModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        email = username or kwargs.get(User.USERNAME_FIELD)
        if email is None or password is None:
            return None
        email = email.strip().lower()

        user = User.objects.filter(email=email, deleted_at__isnull=True).first()
        if user is None:
            # Run the password hasher anyway (constant-time-ish) to avoid
            # leaking "no such account" via response timing, matching
            # ModelBackend's own no-such-user behavior.
            User().set_password(password)
            return None

        # Reject before checking the password — locked means locked,
        # regardless of whether this attempt would have had the right
        # password (don't let a locked-out attacker "test" the lock state
        # by seeing whether the error message changes). Still run the real
        # password check (result discarded) so a locked account takes
        # roughly the same time to reject as an unlocked one — otherwise the
        # lockout branch's early return is a response-timing side channel
        # distinguishing "locked" from every other rejection (SEC-02).
        state = AuthenticationLockoutService.check_lockout(user)
        if state.locked:
            user.check_password(password)
            return None

        # Lifecycle gate (a "pending"/"suspended"/etc. account may not sign
        # in through ANY surface, including /admin/, even with is_staff and
        # the correct password) — does not count as a failed attempt
        # (that's a status problem, not a brute-force signal).
        if user.status != "active":
            return None

        if not user.check_password(password) or not self.user_can_authenticate(user):
            AuthenticationLockoutService.record_failed_attempt(user.id)
            return None

        AuthenticationLockoutService.record_success(user.id)
        return user
