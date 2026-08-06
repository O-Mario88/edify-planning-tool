from django.db import migrations


def seed_catalogue(apps, schema_editor):
    # Historical no-op. This migration originally called the LIVE seeder,
    # which broke fresh-database replays the moment the model grew columns in
    # a later migration (0004): live code selected fields the 0002-era schema
    # did not have. Seeding is owned by reference_data now —
    # apps.activity_catalogue.apps registers ensure_catalogue_reference on
    # post_migrate, which runs after the full chain (and after every flush),
    # so fresh and existing databases both end up seeded.
    return


class Migration(migrations.Migration):
    dependencies = [
        ("activity_catalogue", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_catalogue, migrations.RunPython.noop),
    ]
