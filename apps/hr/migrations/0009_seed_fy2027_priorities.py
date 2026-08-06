from django.db import migrations


def seed_priorities(apps, schema_editor):
    # Historical no-op. The FY2027 priority milestones resolve their Activity
    # Catalogue rules by stable code, and catalogue seeding now runs on
    # post_migrate — so at THIS point the catalogue is empty and every rule
    # lookup silently missed, leaving verified Activities with no milestone
    # credit. Seeding is owned by reference_data now (apps/hr/apps.py), which
    # runs after the catalogue and also restores rows after a flush.
    return


class Migration(migrations.Migration):
    dependencies = [
        ("activity_catalogue", "0002_seed_edify_catalogue"),
        ("hr", "0008_milestonemetricdefinition_strategicpriority_code_and_more"),
    ]

    operations = [
        migrations.RunPython(seed_priorities, migrations.RunPython.noop),
    ]
