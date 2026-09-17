# A cluster meeting is priced apart from a cluster training (owner,
# 2026-09-17: "cluster meeting is not fetching the right cost for cluster
# meeting"). It could not be: the two shared one catalogue row, so the
# Country Director had no way to make them differ.
#
# The meeting's row is created here for every catalogue that carries the
# shared one, copying its figure — splitting the rate must not reprice
# anything on its own. The Country Director then sets the meeting's price,
# and the shared row stays as the training's.

from django.db import migrations

SHARED_KEY = "cluster_meetings_trainings"
NEW_KEY = "cluster_meeting"


def forwards(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    for shared in CostSetting.objects.filter(key=SHARED_KEY):
        CostSetting.objects.get_or_create(
            catalogue_id=shared.catalogue_id,
            key=NEW_KEY,
            defaults={
                "label": "Cluster Meeting",
                "unit_cost": shared.unit_cost,
                "approved_minimum": shared.approved_minimum
                if shared.approved_minimum is not None
                else shared.unit_cost,
                "fy": shared.fy,
                "version": 1,
                "unit": "per meeting",
            },
        )
    # The shared row is the training's alone from here on, and says so.
    CostSetting.objects.filter(key=SHARED_KEY).update(label="Cluster Training")


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0020_cluster_meals_rate"),
    ]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
