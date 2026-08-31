"""Enable the planned headcount for per-head meals without inventing old counts."""

from django.db import migrations


def enable_planned_headcount(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Item.objects.filter(
        stable_code="STANDARD_IN_SCHOOL_TRAINING", participant_mode="none"
    ).update(participant_mode="direct_total")


def restore_previous_mode(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Item.objects.filter(
        stable_code="STANDARD_IN_SCHOOL_TRAINING", participant_mode="direct_total"
    ).update(participant_mode="none")


class Migration(migrations.Migration):
    dependencies = [("activity_catalogue", "0012_training_course_metadata")]
    operations = [migrations.RunPython(enable_planned_headcount, restore_previous_mode)]
