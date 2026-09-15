# The printing and photocopying rates are charged by the page (owner,
# 2026-09-15): printing pages x rate, photocopying pages x copies x rate.
# The basis shown under each rate on Cost Settings says so; rows created
# before this carried the old "per session" basis. Only the label of the
# basis changes -- never a rate the Country Director set.

from django.db import migrations

UNITS = {
    "printing_training_materials": "per page",
    "photocopying_training_materials": "per page per copy",
}


def forwards(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    for key, unit in UNITS.items():
        CostSetting.objects.filter(key=key, unit="per session").update(unit=unit)


def backwards(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    for key, unit in UNITS.items():
        CostSetting.objects.filter(key=key, unit=unit).update(unit="per session")


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0018_retire_staff_visit_rates"),
    ]

    operations = [migrations.RunPython(forwards, backwards)]
