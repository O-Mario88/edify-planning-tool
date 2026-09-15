# Cluster meetings and trainings feed their participants per head per day
# (owner, 2026-09-15). The rate row is created here for every catalogue that
# still carries the retired per-head cluster snack rate, copying that rate so
# a figure the Country Director set survives the rename; catalogues without
# one get the row from ensure_cost_reference at its default, as every other
# canonical rate does.

from django.db import migrations

NEW_KEY = "cluster_meetings_trainings_meals"
OLD_KEYS = ("cluster_meeting_participant_meal_cost_per_head", "meals_per_participant")


def forwards(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    for old_key in OLD_KEYS:
        for old in CostSetting.objects.filter(key=old_key):
            CostSetting.objects.get_or_create(
                catalogue_id=old.catalogue_id,
                key=NEW_KEY,
                defaults={
                    "label": "Cluster Meetings/ Trainings - Meals",
                    "unit_cost": old.unit_cost,
                    "approved_minimum": old.approved_minimum
                    if old.approved_minimum is not None
                    else old.unit_cost,
                    "fy": old.fy,
                    "version": 1,
                    "unit": "per participant per day",
                },
            )


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0019_materials_rate_units"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
