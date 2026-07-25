"""Seed the five official personal target areas with default weights
(configurable afterwards; weights must total 100 across active areas).

The list itself lives in apps.targets.reference, which also restores these rows
on post_migrate — a data migration alone cannot, because a flushed database
never replays it. Kept as a literal copy here so this migration stays frozen in
time the way a migration must; `test_reference.py` fails if the two drift.
"""

from django.db import migrations

AREAS = [
    ("school_visits", "School Visits", 30, 1),
    ("cluster_meetings", "Cluster Meetings", 15, 2),
    ("cluster_trainings", "Cluster Trainings", 20, 3),
    ("ssa_completed", "SSA Completed", 25, 4),
    ("mscs", "MSCS", 10, 5),
]


def seed(apps, schema_editor):
    TargetArea = apps.get_model("targets", "TargetArea")

    for key, label, weight, sort in AREAS:
        TargetArea.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "weight": weight,
                "sort_order": sort,
                "active": True,
            },
        )


def unseed(apps, schema_editor):
    TargetArea = apps.get_model("targets", "TargetArea")
    TargetArea.objects.filter(key__in=[a[0] for a in AREAS]).delete()


class Migration(migrations.Migration):
    dependencies = [("targets", "0002_targetarea_targetadjustment_and_more")]
    operations = [migrations.RunPython(seed, unseed)]
