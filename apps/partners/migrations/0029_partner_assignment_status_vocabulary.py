"""Hold a hand-over's status to one vocabulary, in the database.

`PartnerAssignment.status` was a bare CharField, and each writer spelled the
states its own way. The vocabulary is now `PartnerAssignmentStatus`, and the
check constraint `partner_assignment_status_known` refuses anything else.

Before the constraint, any row outside the vocabulary is given the state its
own facts say it is in — dated by the partner (it has a scheduled activity),
returned (it records a return), or still waiting — and printed to the deploy
log. Rows inside the vocabulary, including the two legacy spellings readers
still match, are left exactly as they are. The reverse drops the constraint
and leaves the data alone.
"""

from __future__ import annotations

from django.db import migrations, models

KNOWN = (
    "pending_scheduling",
    "assigned",
    "partner_scheduled",
    "scheduled",
    "completed",
    "returned_to_staff",
)


def normalise_statuses(apps, schema_editor):
    PartnerAssignment = apps.get_model("partners", "PartnerAssignment")
    stray = PartnerAssignment.objects.exclude(status__in=KNOWN)
    for row in stray.only("id", "status", "scheduled_activity_id", "returned_at"):
        if row.scheduled_activity_id:
            target = "partner_scheduled"
        elif row.returned_at:
            target = "returned_to_staff"
        else:
            target = "pending_scheduling"
        print(f"  partner hand-over {row.id}: status {row.status!r} -> {target!r}")
        PartnerAssignment.objects.filter(id=row.id).update(status=target)


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0028_partnerassignment_uniq_open_partner_school_assignment"),
    ]

    operations = [
        migrations.RunPython(normalise_statuses, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="partnerassignment",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending_scheduling", "Waiting for the partner to schedule"),
                    ("assigned", "Waiting for the partner to schedule (legacy)"),
                    ("partner_scheduled", "Scheduled by the partner"),
                    ("scheduled", "Scheduled (legacy)"),
                    ("completed", "Completed"),
                    ("returned_to_staff", "Returned to staff"),
                ],
                default="assigned",
                max_length=32,
            ),
        ),
        migrations.AddConstraint(
            model_name="partnerassignment",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    (
                        "status__in",
                        [
                            "pending_scheduling",
                            "assigned",
                            "partner_scheduled",
                            "scheduled",
                            "completed",
                            "returned_to_staff",
                        ],
                    )
                ),
                name="partner_assignment_status_known",
            ),
        ),
    ]
