from django.db import migrations


def seed_priorities(apps, schema_editor):
    from apps.hr.priority_seeding import seed_fy2027_priorities

    seed_fy2027_priorities(actor_id="migration")


class Migration(migrations.Migration):
    dependencies = [
        ("activity_catalogue", "0002_seed_edify_catalogue"),
        ("hr", "0008_milestonemetricdefinition_strategicpriority_code_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_priorities, migrations.RunPython.noop),
    ]
