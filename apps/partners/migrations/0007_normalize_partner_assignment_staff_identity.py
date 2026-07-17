"""Repair PartnerAssignment owner ids to the canonical StaffProfile identity.

Early planning drawers stored ``User.id`` in ``assigning_staff_id`` while
Core Schools stored ``StaffProfile.id``.  Activities created when a partner
later schedules the assignment need one consistent monitor identity for My
Plan scope, message recipients, and audit attribution.
"""

from django.db import migrations


def normalize_partner_assignment_staff_identity(apps, schema_editor):
    PartnerAssignment = apps.get_model("partners", "PartnerAssignment")
    StaffProfile = apps.get_model("accounts", "StaffProfile")

    profile_ids = set(StaffProfile.objects.values_list("id", flat=True))
    profiles_by_user = dict(StaffProfile.objects.values_list("user_id", "id"))

    for assignment in PartnerAssignment.objects.exclude(
        assigning_staff_id__isnull=True
    ).exclude(assigning_staff_id="").iterator():
        current = assignment.assigning_staff_id
        # Existing StaffProfile ids are already canonical.  A legacy User id
        # becomes the linked StaffProfile id when one exists; admins without
        # a profile deliberately retain their User id as the documented
        # compatibility fallback.
        if current in profile_ids:
            continue
        canonical = profiles_by_user.get(current)
        if canonical:
            PartnerAssignment.objects.filter(pk=assignment.pk).update(
                assigning_staff_id=canonical
            )


def reverse_noop(apps, schema_editor):
    # The prior User id cannot be reconstructed unambiguously after repair.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0016_migrate_legacy_permanent_locks"),
        ("partners", "0006_partneractivityallowance"),
    ]

    operations = [
        migrations.RunPython(
            normalize_partner_assignment_staff_identity,
            reverse_noop,
        ),
    ]
