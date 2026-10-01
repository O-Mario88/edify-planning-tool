"""Hold a hand-over's status to one vocabulary, in the database.

`PartnerAssignment.status` was a bare CharField, and each writer spelled the
states its own way. The vocabulary is now `PartnerAssignmentStatus`, and the
check constraint `partner_assignment_status_known` refuses anything else on
every row written from now on.

No existing row is rewritten. The vocabulary keeps every legacy spelling the
platform's readers still match (``assigned``, ``partner_pending_schedule``,
``scheduled``, ``completed``, ``returned``, ``cancelled``), and the
constraint is added NOT VALID: Postgres
then checks rows as they are inserted or updated and does not fail the
deploy over a spelling nobody knew production held. Any such row is printed
to the deploy log here, by status, so it can be looked at and the constraint
validated afterwards (``ALTER TABLE partner_assignment VALIDATE CONSTRAINT
partner_assignment_status_known``). Rewriting them on a guess could reopen a
hand-over that had been called off.
"""

from __future__ import annotations

from django.db import migrations, models

KNOWN = (
    "pending_scheduling",
    "partner_scheduled",
    "returned_to_staff",
    "assigned",
    "partner_pending_schedule",
    "scheduled",
    "completed",
    "returned",
    "cancelled",
)

CONSTRAINT = "partner_assignment_status_known"


def report_unknown_statuses(apps, schema_editor):
    from django.db.models import Count

    PartnerAssignment = apps.get_model("partners", "PartnerAssignment")
    unknown = (
        PartnerAssignment.objects.exclude(status__in=KNOWN)
        .values("status")
        .annotate(n=Count("id"))
        .order_by("status")
    )
    for row in unknown:
        print(
            f"  partner hand-over status outside the vocabulary: "
            f"{row['status']!r} on {row['n']} row(s) — left as it is; the "
            f"row cannot be saved again until its status is corrected."
        )


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0028_partnerassignment_uniq_open_partner_school_assignment"),
    ]

    operations = [
        migrations.RunPython(report_unknown_statuses, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="partnerassignment",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending_scheduling", "Waiting for the partner to schedule"),
                    ("partner_scheduled", "Scheduled by the partner"),
                    ("returned_to_staff", "Returned to staff"),
                    ("assigned", "Waiting for the partner to schedule (legacy)"),
                    (
                        "partner_pending_schedule",
                        "Waiting for the partner to schedule (legacy)",
                    ),
                    ("scheduled", "Scheduled (legacy)"),
                    ("completed", "Completed (legacy)"),
                    ("returned", "Returned (legacy)"),
                    ("cancelled", "Cancelled (legacy)"),
                ],
                default="assigned",
                max_length=32,
            ),
        ),
        # The model state gains the constraint; the database gains it NOT
        # VALID, so existing rows are not checked (see the module docstring).
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="partnerassignment",
                    constraint=models.CheckConstraint(
                        condition=models.Q(("status__in", list(KNOWN))),
                        name=CONSTRAINT,
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        f"ALTER TABLE partner_assignment ADD CONSTRAINT {CONSTRAINT} "
                        "CHECK (status IN ("
                        + ", ".join(f"'{value}'" for value in KNOWN)
                        + ")) NOT VALID"
                    ),
                    reverse_sql=(
                        f"ALTER TABLE partner_assignment DROP CONSTRAINT {CONSTRAINT}"
                    ),
                ),
            ],
        ),
    ]
