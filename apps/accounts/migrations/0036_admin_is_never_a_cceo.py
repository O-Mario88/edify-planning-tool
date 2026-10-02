"""An Admin account is never a CCEO.

Owner, 2026-10-02: "remove admin from being a cceo. Admin should never be a
CCEO".

0021 gave the super-admin a second hat so the same person could run the
platform and work the field from one account, and the seed kept re-asserting
it. Roles are counted where they are held, so that account stood in every list
of CCEOs — team rosters, targets, the monitors — as an officer with a target
and no work. This takes the hat off again, for every account holding Admin and
not only the one 0021 named:

  - CCEO leaves `roles` on any account that also holds Admin;
  - an Admin account acting as a CCEO goes back to acting as Admin.

Every account changed is printed to the deploy log by id. 0037 then adds
`user_admin_is_never_cceo` so it cannot come back; the two are separate
migrations so the constraint is built on rows already put right.

The StaffProfile is left alone, as 0021's own reverse leaves it: it may carry
real field work by now, and deleting it would cascade that away. Schools and
activities filed to such an account stay where they are; moving them to a CCEO
is a decision for a person, not for a migration.

Historical models only, so a later schema migration in the same run cannot
break it. Reverse is a no-op: the hat is not put back.
"""

from __future__ import annotations

from django.db import migrations

ADMIN = "Admin"
CCEO = "CCEO"


def take_the_cceo_hat_off_admins(apps, schema_editor):
    User = apps.get_model("accounts", "User")

    changed = []
    for user in User._base_manager.filter(roles__contains=[ADMIN]).order_by("id"):
        fields = []
        if CCEO in (user.roles or []):
            user.roles = [role for role in user.roles if role != CCEO]
            fields.append("roles")
        if user.active_role == CCEO:
            user.active_role = ADMIN
            fields.append("active_role")
        if fields:
            user.save(update_fields=fields)
            changed.append((user.id, fields))

    for user_id, fields in changed:
        print(
            f"  accounts.0036: Admin account {user_id} is no longer a CCEO "
            f"({', '.join(fields)})."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0035_staff_activity_sessions"),
    ]

    operations = [
        migrations.RunPython(take_the_cceo_hat_off_admins, migrations.RunPython.noop),
    ]
