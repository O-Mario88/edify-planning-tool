from django.db import migrations


def seed_catalogue(apps, schema_editor):
    # The seeder uses stable-code upserts and one atomic transaction.  It is
    # also exposed as a dry-run management command for controlled reruns.
    from apps.activity_catalogue.seeding import seed_activity_catalogue

    seed_activity_catalogue(actor_id="migration")


class Migration(migrations.Migration):
    dependencies = [
        ("activity_catalogue", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_catalogue, migrations.RunPython.noop),
    ]
