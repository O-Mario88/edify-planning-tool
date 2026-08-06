from django.db import migrations, models
import django.db.models.deletion

import apps.core.cuid
import apps.core.models


class Migration(migrations.Migration):
    dependencies = [
        ("hr", "0009_seed_fy2027_priorities"),
    ]

    operations = [
        migrations.CreateModel(
            name="FiscalYearRollover",
            fields=[
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, db_index=True),
                ),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    apps.core.models.CuidField(
                        default=apps.core.cuid.cuid,
                        max_length=30,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("fy", models.CharField(max_length=16, unique=True)),
                ("previous_fy", models.CharField(max_length=16)),
                ("initiated_by", models.CharField(default="system", max_length=64)),
                ("started_at", models.DateTimeField()),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("summary", models.JSONField(blank=True, default=dict)),
                (
                    "performance_cycle",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rollovers",
                        to="hr.performancecycle",
                    ),
                ),
                (
                    "strategic_priority_cycle",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rollovers",
                        to="hr.strategicprioritycycle",
                    ),
                ),
            ],
            options={
                "db_table": "hr_fiscal_year_rollover",
                "ordering": ["-fy"],
            },
        ),
    ]
