from django.db import migrations


def assign_unsupervised_cceos(apps, schema_editor):
    StaffProfile = apps.get_model("accounts", "StaffProfile")
    StaffSupervisorAssignment = apps.get_model("accounts", "StaffSupervisorAssignment")

    pl1 = StaffProfile.objects.filter(user__email="pl1@edify.org").first()
    if not pl1:
        pl1 = StaffProfile.objects.filter(user__active_role="Program Lead").first()

    if not pl1:
        return

    # Find CCEOs without any supervisor assignment
    cceos = StaffProfile.objects.filter(
        user__active_role="CCEO",
        deleted_at__isnull=True,
    ).exclude(supervisor_links__isnull=False)

    for cceo in cceos:
        StaffSupervisorAssignment.objects.get_or_create(
            supervisee=cceo,
            supervisor=pl1,
        )


def reverse_assignment(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0029_presence_activity"),
    ]

    operations = [
        migrations.RunPython(assign_unsupervised_cceos, reverse_assignment),
    ]
