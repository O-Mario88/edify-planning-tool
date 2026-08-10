"""Existing activities get the executor type their delivery type implies.

Everything scheduled before certified-agency booking existed was either staff
work or an assigned partner that chose its own date. Neither is a certified
agency booking, so the mapping is exact and needs no guessing — a later
repair pass reclassifies genuine agency bookings from evidence, not from a
migration's assumption.
"""

from django.db import migrations


def set_executor_type(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    Activity.objects.filter(delivery_type="partner").update(executor_type="partner")
    Activity.objects.exclude(delivery_type="partner").update(executor_type="staff")


def unset_executor_type(apps, schema_editor):
    Activity = apps.get_model("activities", "Activity")
    Activity.objects.update(executor_type="staff")


class Migration(migrations.Migration):
    dependencies = [("activities", "0036_activity_executor_type")]

    operations = [
        migrations.RunPython(set_executor_type, unset_executor_type),
    ]
