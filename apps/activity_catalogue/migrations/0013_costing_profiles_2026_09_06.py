"""Catalogue items take the costing profiles the 2026-09-06 cost catalogue
prices by: a core-school visit carries the Core Staff/Partner Visit rate, a
student conference or camp carries the Student Conference rate.

Other items keep their profile; the Country Director assigns ONETEST,
TOT_TRAINING and PROPRIETOR_CONFERENCE to the items that need them.
"""

from django.db import migrations

CORE_VISIT_NAMES = ("Core School Visits/Meetings School visits",)
STUDENT_EVENT_PREFIX = "Student "


def forwards(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Item.objects.filter(display_name__in=CORE_VISIT_NAMES, costing_profile="STAFF_SCHOOL_VISIT").update(
        costing_profile="CORE_SCHOOL_VISIT"
    )
    Item.objects.filter(
        display_name__startswith=STUDENT_EVENT_PREFIX, costing_profile="PROGRAMME_EVENT"
    ).update(costing_profile="STUDENT_CONFERENCE")


def backwards(apps, schema_editor):
    Item = apps.get_model("activity_catalogue", "ActivityCatalogueItem")
    Item.objects.filter(costing_profile="CORE_SCHOOL_VISIT").update(costing_profile="STAFF_SCHOOL_VISIT")
    Item.objects.filter(costing_profile="STUDENT_CONFERENCE").update(costing_profile="PROGRAMME_EVENT")


class Migration(migrations.Migration):
    dependencies = [("activity_catalogue", "0012_training_course_metadata")]
    operations = [migrations.RunPython(forwards, backwards)]
