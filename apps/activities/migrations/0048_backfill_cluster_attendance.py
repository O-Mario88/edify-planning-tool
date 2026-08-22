"""Carry the existing attendance array into rows.

`attended_school_ids` recorded who came to a cluster session, but as a string
array with no foreign key it could not be joined against, so no school-level
count could use it. The rows say the same thing in a form the counts can read.

Nothing is invented: only ids already present in the array become rows, and
only where the school still exists. A school that was deleted since the
session is dropped rather than resurrected as a dangling row.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    School = apps.get_model("schools", "School")
    Attendance = apps.get_model("activities", "ClusterActivityAttendance")

    sessions = Activity.objects.filter(cluster_id__isnull=False).exclude(
        attended_school_ids=[]
    )
    live_school_ids = set(
        School.objects.filter(deleted_at__isnull=True).values_list("id", flat=True)
    )

    rows = []
    for activity in sessions.iterator(chunk_size=500):
        seen = set()
        for school_id in activity.attended_school_ids or []:
            if school_id in seen or school_id not in live_school_ids:
                continue
            seen.add(school_id)
            rows.append(
                Attendance(
                    activity_id=activity.id,
                    school_id=school_id,
                    # The array only ever recorded attendance. Marking these
                    # invited too would be inventing a plan that was never
                    # captured — a school confirmed present was certainly
                    # asked, but that is an inference, not a record.
                    invited=False,
                    attended=True,
                    is_guest=school_id
                    not in _member_ids(School, activity.cluster_id),
                    teachers=activity.teachers_per_school,
                    leaders=activity.leaders_per_school,
                    other=activity.other_per_school,
                )
            )
        if len(rows) >= 1000:
            Attendance.objects.bulk_create(rows, ignore_conflicts=True)
            rows = []
    if rows:
        Attendance.objects.bulk_create(rows, ignore_conflicts=True)


_MEMBER_CACHE: dict[str, set] = {}


def _member_ids(School, cluster_id):
    if cluster_id not in _MEMBER_CACHE:
        _MEMBER_CACHE[cluster_id] = set(
            School.objects.filter(
                cluster_id=cluster_id, deleted_at__isnull=True
            ).values_list("id", flat=True)
        )
    return _MEMBER_CACHE[cluster_id]


def unbackfill(apps, schema_editor):
    apps.get_model("activities", "ClusterActivityAttendance").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0047_clusteractivityattendance"),
        ("schools", "0021_school_uniq_school_salesforce_account_id"),
    ]

    operations = [migrations.RunPython(backfill, unbackfill)]
