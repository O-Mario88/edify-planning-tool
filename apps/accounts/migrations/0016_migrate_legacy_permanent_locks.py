"""Data migration: safely migrate legacy "permanent lock" records to the new
lockout_escalated flag (Issue 3 of the audit — auth lockout unification).

Before this fix, apps/frontend/views/auth_views.py hand-set
`locked_until = now + timedelta(days=36500)` (a ~100-year lock, meant as
"permanent, requires admin to unlock") on the threshold-th failed login.
The new AuthenticationLockoutService reads `lockout_escalated` (a real
boolean, not a magic date far in the future) to decide "requires admin
unlock regardless of locked_until expiry" -- so any row using the old
100-year-lock convention needs migrating to keep meaning the same thing:
still locked, still requires an admin action, not silently unlocked.

Idempotent: only touches rows matching the legacy signature
(locked_until more than 30 days out AND lockout_escalated not already set)
-- re-running finds nothing to do the second time. Produces before/after
counts via RunPython's logging so a repair run is auditable.

Safety: no data is deleted. locked_until is intentionally left as-is (still
correctly reports "locked", just no longer the ONLY signal) -- an admin
unlock still clears both fields together (see AuthenticationLockoutService
.admin_unlock). Fast: a single bounded UPDATE, not a per-row Python loop,
and only ever touches the (presumably small) set of already-locked
accounts.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import migrations
from django.utils import timezone


def migrate_legacy_permanent_locks(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    cutoff = timezone.now() + timedelta(days=30)
    legacy_locked = User.objects.filter(
        locked_until__gt=cutoff,
        lockout_escalated=False,
    )
    before_count = legacy_locked.count()
    if before_count:
        legacy_locked.update(lockout_escalated=True, lockout_cycle_count=1)
    print(  # noqa: T201 — visible in `manage.py migrate` output, this is the audit trail
        f"[0016_migrate_legacy_permanent_locks] {before_count} legacy permanently-locked "
        f"account(s) migrated to lockout_escalated=True."
    )


def reverse_migrate_legacy_permanent_locks(apps, schema_editor):
    # Deliberately a no-op: we cannot distinguish "escalated by this
    # migration" from "escalated by real usage after this migration ran"
    # once time has passed, and un-escalating an account on a schema
    # rollback would be a security regression, not a safe reversal.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0015_user_failed_login_streak_started_at_and_more"),
    ]

    operations = [
        migrations.RunPython(
            migrate_legacy_permanent_locks,
            reverse_migrate_legacy_permanent_locks,
        ),
    ]
