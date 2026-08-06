# Data migration: stamp the database with the environment of the process
# running migrate. A dump restored elsewhere carries this stamp with it —
# which is exactly the point: a production server refuses a 'local' stamp.

from django.conf import settings as django_settings
from django.db import migrations


def stamp(apps, schema_editor):
    EnvironmentStamp = apps.get_model("system_health", "EnvironmentStamp")
    environment = getattr(django_settings, "ENVIRONMENT", "local")
    EnvironmentStamp.objects.get_or_create(
        id=1,
        defaults={"environment": environment, "stamped_by": "migration"},
    )


def unstamp(apps, schema_editor):
    EnvironmentStamp = apps.get_model("system_health", "EnvironmentStamp")
    EnvironmentStamp.objects.filter(id=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("system_health", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(stamp, unstamp),
    ]
