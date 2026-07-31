from django.db import migrations


PROGRAMME_CODES = (
    "STUDENT_TRAINING_YOUTH_CAMPS",
    "STUDENT_LEADERSHIP_CAMPS",
    "STUDENT_CONFERENCE_CAMPS",
    "TEACHER_LEADERSHIP_CONFERENCE",
)


def use_programme_event_rates(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Item.objects.filter(
        stable_code__in=PROGRAMME_CODES,
        costing_profile="GROUP_YOUTH_CAMP",
    ).update(costing_profile="PROGRAMME_EVENT")


def restore_legacy_profile(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Item.objects.filter(
        stable_code__in=PROGRAMME_CODES,
        costing_profile="PROGRAMME_EVENT",
    ).update(costing_profile="GROUP_YOUTH_CAMP")


class Migration(migrations.Migration):
    dependencies = [
        ("activity_catalogue", "0005_alter_activitycatalogueitem_activity_type_and_more"),
    ]

    operations = [
        migrations.RunPython(use_programme_event_rates, restore_legacy_profile),
    ]
