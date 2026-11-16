"""A signed-in person changes their own password, from their Profile.

Owner, 2026-11-16: "can you add the self password reset from the user profile
and make sure that the other is not locked out". Until now the only place an
Admin could change their own password was the Users page, which is the reset
an Admin gives somebody else: a one-time password, a forced change and a
signed-out session. Done to yourself, it locked the platform's Admin out.

This is the other thing: the person proves they know the current password,
chooses the new one, and stays signed in (the view keeps the session). A
wrong current password is refused without counting towards the sign-in
lockout: the person is already signed in, so a slip here is not a guess at
somebody's account, and counting it is how a typo would lock them out.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.security import validate_password

WRONG_CURRENT = "Your current password is not right."
MISMATCH = "The new passwords do not match."


def change_own_password(user, *, current: str, new: str, confirm: str) -> list[str]:
    """Change ``user``'s password. Returns why it was refused; empty = changed.

    The app's refresh tokens are revoked, as every other password change does:
    a password changed because it may be known should not leave the phone
    signed in on the old one. The browser session is kept by the caller.
    """
    from apps.accounts.models import RefreshToken
    from apps.audit.services import log as audit_log

    if not user.check_password(current or ""):
        return [WRONG_CURRENT]
    if new != confirm:
        return [MISMATCH]
    violations = validate_password(new, user.email)
    if violations:
        return violations

    with transaction.atomic():
        user.set_password(new)
        user.must_change_password = False
        user.password_set_at = timezone.now()
        user.save(update_fields=["password", "must_change_password", "password_set_at"])
        RefreshToken.objects.filter(user_id=user.id, revoked_at__isnull=True).update(
            revoked_at=timezone.now()
        )

    audit_log(
        action="user.password_self_changed",
        subject_kind="user",
        subject_id=user.id,
        actor_id=user.id,
        actor_role=getattr(user, "active_role", None),
        reason="Changed their own password from their Profile.",
    )
    return []
