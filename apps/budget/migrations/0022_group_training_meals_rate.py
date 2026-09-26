# A group training feeds its participants per head per day (session costing
# spec, 2026-09-26: participant_meals_total = participant_count x meal rate,
# for a staff-run or a partner-run training). From 2026-09-20 until then a
# training fed nobody per head; before that it fed them from the cluster
# meals row it shared with the meeting.
#
# The training's own row is created here for every catalogue that carries
# the cluster meals row, copying that figure and its minimum, so a price the
# Country Director set for feeding a cluster's participants is the starting
# price for feeding a training's, and the Country Director then prices the
# two apart, as the meeting and training session rates were split on
# 2026-09-17. Catalogues without one get the row from ensure_cost_reference
# at its default, as every other canonical rate does.

from django.db import migrations

CLUSTER_MEALS_KEY = "cluster_meetings_trainings_meals"
NEW_KEY = "group_training_meals"


def forwards(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    for cluster in CostSetting.objects.filter(key=CLUSTER_MEALS_KEY):
        CostSetting.objects.get_or_create(
            catalogue_id=cluster.catalogue_id,
            key=NEW_KEY,
            defaults={
                "label": "Group Training - Participant Meals",
                "unit_cost": cluster.unit_cost,
                "approved_minimum": cluster.approved_minimum
                if cluster.approved_minimum is not None
                else cluster.unit_cost,
                "fy": cluster.fy,
                "version": 1,
                "unit": "per participant per day",
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0021_cluster_meeting_rate"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
