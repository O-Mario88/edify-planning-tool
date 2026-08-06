"""The super-admin also works the field as a CCEO.

0020 made the account unambiguously Admin. That is right for the platform work
and wrong for the rest of the job: the same person runs field visits, and a
single-hat account cannot reach any of it.

`roles` is the set of hats the account may wear and `active_role` is the one it
is wearing, so adding CCEO grants the field surfaces without weakening the
admin side -- /auth/switch-role moves between them and audits each switch.

Additive on purpose: existing roles are preserved rather than replaced, so this
is safe whether or not 0020 has already run, and re-running it changes nothing.
"""

from django.db import migrations


ADMIN_EMAIL = "domario@edify.org"
FIELD_ROLE = "CCEO"


def add_field_officer_role(apps, schema_editor):
    StaffProfile = apps.get_model("accounts", "StaffProfile")
    User = apps.get_model("accounts", "User")

    for user in User.objects.filter(email__iexact=ADMIN_EMAIL):
        if FIELD_ROLE not in (user.roles or []):
            user.roles = [*(user.roles or []), FIELD_ROLE]
            user.save(update_fields=["roles"])
        # Field work keys off StaffProfile, not the User row — targets, visit
        # plans and assignments all hang off it. Without one the CCEO hat opens
        # onto surfaces that cannot be populated.
        StaffProfile.objects.get_or_create(
            user_id=user.id, defaults={"onboarding_state": "active"}
        )


def remove_field_officer_role(apps, schema_editor):
    """Drop the field hat, and put the account back on Admin if it was wearing
    it. The StaffProfile is left alone: it may have accumulated real field work
    by now, and deleting it would cascade that away."""
    User = apps.get_model("accounts", "User")

    for user in User.objects.filter(email__iexact=ADMIN_EMAIL):
        roles = [r for r in (user.roles or []) if r != FIELD_ROLE]
        fields = ["roles"]
        user.roles = roles
        if user.active_role == FIELD_ROLE:
            user.active_role = "Admin"
            fields.append("active_role")
        user.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0020_admin_super_role"),
    ]

    operations = [
        migrations.RunPython(add_field_officer_role, remove_field_officer_role),
    ]
