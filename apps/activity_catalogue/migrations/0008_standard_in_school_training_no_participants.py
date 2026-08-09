"""Standard In-School Training stops planning a participant quantity.

The scheduling drawer asked for Teachers / School leaders / Other on a
single-school training. Those three inputs wrote a PLAN into the same columns
completion later records ATTENDANCE in, so a planned figure and a verified
headcount became indistinguishable — and who is in the room is a cluster
question anyway, where participants are planned per member school.

The catalogue row is the authority the drawer is generated from, so the mode
moves here. Live activities scheduled under the old rule are cleared of the
planning values they carried: with ParticipantMode.NONE those values are a
scheduling-health failure (a participant quantity on an activity that has
none), and they are stale drawer artifacts rather than anything measured.
Completed and cancelled work is history and is never touched.
"""

from django.db import migrations

STABLE_CODE = "STANDARD_IN_SCHOOL_TRAINING"

LIVE_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
)


def no_participants(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Activity = apps.get_model("activities", "Activity")

    item = Item.objects.filter(stable_code=STABLE_CODE).first()
    if item is None:
        return

    Item.objects.filter(pk=item.pk).update(participant_mode="none")
    Activity.objects.filter(catalogue_item_id=item.pk, status__in=LIVE_STATUSES).update(
        expected_participants=None,
        participants_per_school=None,
        teachers_attended=None,
        leaders_attended=None,
        other_participants=None,
    )


def by_category(apps, schema_editor):
    """Restore the mode only. The cleared values were plans, not measurements,
    and inventing numbers to put back would be worse than the absence."""
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Item.objects.filter(stable_code=STABLE_CODE).update(participant_mode="by_category")


class Migration(migrations.Migration):
    dependencies = [
        (
            "activity_catalogue",
            "0007_remove_activityinterventionmapping_catalogue_mapping_intervention_shape_and_more",
        ),
        ("activities", "0039_cluster_participant_categories"),
    ]

    operations = [
        migrations.RunPython(no_participants, by_category),
    ]
