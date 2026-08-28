from datetime import datetime, timezone

from django.db import migrations


VERSION = "Rollout 2026.08"


def publish(apps, schema_editor):
    apps.get_model("help_center", "HelpReleaseNote").objects.get_or_create(
        version_label=VERSION,
        defaults={
            "title": "Production rollout scope and operating requirements",
            "summary": (
                "Salesforce and NetSuite reconciliation remains a manual process: "
                "the platform validates and stores a human-entered reference but does "
                "not contact either external system. Field workflows also require a "
                "working internet connection; offline submissions are cancelled rather "
                "than queued or replayed."
            ),
            "published_at": datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
        },
    )


def unpublish(apps, schema_editor):
    apps.get_model("help_center", "HelpReleaseNote").objects.filter(
        version_label=VERSION
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("help_center", "0008_alter_helparticleroleaccess_role")]
    operations = [migrations.RunPython(publish, unpublish)]
