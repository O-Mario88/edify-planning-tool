from django.db import migrations


ADMIN_EMAIL = "domario@edify.org"


def grant_admin_every_permission(apps, schema_editor):
    Permission = apps.get_model("accounts", "Permission")
    RolePermission = apps.get_model("accounts", "RolePermission")
    User = apps.get_model("accounts", "User")

    for permission in Permission.objects.all().iterator():
        RolePermission.objects.get_or_create(role="Admin", permission=permission)

    # Production has one bootstrap administrator. Keep its identity and
    # password intact while making the role assignment unambiguous.
    User.objects.filter(email__iexact=ADMIN_EMAIL).update(
        roles=["Admin"],
        active_role="Admin",
        is_active=True,
        status="active",
        is_staff=True,
        is_superuser=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_user_mfa_channel_mfachallenge"),
    ]

    operations = [
        migrations.RunPython(grant_admin_every_permission, migrations.RunPython.noop),
    ]
