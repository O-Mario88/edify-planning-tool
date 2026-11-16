"""Lift the sign-in lock on every Admin account (owner, 2026-11-16).

"right now admin is locked out". The Admin reset their own password from the
Users page, which signs the account out and forces a change; the sign-in
attempts that followed counted as failures, the account locked, and a locked
account is answered exactly as a wrong password is. After three lock cycles
only an Admin may unlock an account, and the locked account was the Admin.

Only the lock is lifted: the failure counters, a timed lock and an escalated
one. The password is untouched, so the account still signs in only with its
own password. Every other account keeps its lock, which is the brute-force
protection doing its job. Admin is any live account holding the Admin role,
or a Django superuser (the super-admin the seed creates).

The live database is changed only through a deploy (Claude has no console
there), so this is a data migration. It prints how many accounts it unlocked
and their ids to the deploy log. Reversing it does nothing: putting a lock
back is not a repair.
"""

from django.db import migrations
from django.db.models import Q

ADMIN_ROLE = "Admin"


def unlock_admin_accounts(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    locked = (
        User.objects.filter(deleted_at__isnull=True)
        .filter(Q(roles__contains=[ADMIN_ROLE]) | Q(is_superuser=True))
        .filter(
            Q(lockout_escalated=True)
            | Q(locked_until__isnull=False)
            | Q(failed_login_count__gt=0)
            | Q(lockout_cycle_count__gt=0)
        )
    )
    ids = sorted(str(pk) for pk in locked.values_list("id", flat=True))
    if ids:
        User.objects.filter(id__in=ids).update(
            failed_login_count=0,
            failed_login_streak_started_at=None,
            locked_until=None,
            lockout_cycle_count=0,
            lockout_escalated=False,
        )
    print(
        f"\n  [accounts.0040] unlocked {len(ids)} Admin account(s): {', '.join(ids) or 'none'}"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0039_impact_assessment_operational_admin"),
    ]

    operations = [
        migrations.RunPython(unlock_admin_accounts, migrations.RunPython.noop),
    ]
