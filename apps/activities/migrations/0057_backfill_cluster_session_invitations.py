"""Name the invited schools on cluster sessions planned before invitations
were recorded (owner, 2026-09-23: "backfill the invited schools for older
cluster sessions").

The work is ``apps.activities.cluster_attendance.backfill_session_invitations``
— the same function the ``backfill_cluster_invitations`` command runs — so the
rule lives in one place. It reads the live models, which is why the historical
models only decide whether there is anything to do: on a database with no
undelivered cluster session (a fresh install, the test database) the live
code is never reached, and a migration further down the history can never meet
a model newer than its schema.

Reversible: the rows it writes carry ``recorded_by="backfill"`` and nothing
else writes that value.
"""

from django.db import migrations

CLUSTER_SESSION_TYPES = (
    "cluster_meeting",
    "cluster_meeting_ssa_review",
    "cluster_training",
    "cluster_training_ssa_collection",
)
UNDELIVERED = (
    "planned",
    "scheduled",
    "rescheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
)


def backfill(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    if not Activity.objects.filter(
        deleted_at__isnull=True,
        cluster_id__isnull=False,
        activity_type__in=CLUSTER_SESSION_TYPES,
        status__in=UNDELIVERED,
    ).exists():
        return
    from apps.activities.cluster_attendance import backfill_session_invitations

    backfill_session_invitations()


def unbackfill(apps, schema_editor):
    Attendance = apps.get_model("activities", "ClusterActivityAttendance")
    Attendance.objects.filter(
        recorded_by="backfill", invited=True, attended=False
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0056_training_materials_pages"),
        ("clusters", "0006_backfill_catchments_and_membership_history"),
        ("core_schools", "0004_fy_aware_core_plan"),
        ("partners", "0024_partner_assignment_return_resolution"),
        ("schools", "0022_school_ownership_transfers"),
    ]

    operations = [migrations.RunPython(backfill, unbackfill)]
