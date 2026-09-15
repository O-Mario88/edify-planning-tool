# Printing and photocopying of training materials are planned by the page
# (owner, 2026-09-15): printing pages x the per-page rate, photocopying pages
# x copies x the per-page rate. Stored so a reschedule re-prices the same
# materials.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0055_ssa_deviation_reason"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="printing_pages",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="activity",
            name="photocopy_pages",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="activity",
            name="photocopy_copies",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
