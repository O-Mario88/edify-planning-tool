import apps.core.cuid
import apps.core.models
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounts", "0016_migrate_legacy_permanent_locks"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnalyticsDashboardPreference",
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
                ("visible_cards", models.JSONField(default=list)),
                (
                    "layout",
                    models.CharField(
                        choices=[("grid", "Standard grid"), ("compact", "Compact")],
                        default="grid",
                        max_length=16,
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analytics_dashboard_preference",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "analytics_dashboard_preference"},
        ),
        migrations.CreateModel(
            name="AnalyticsReportSchedule",
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
                ("recipient_email", models.EmailField(max_length=254)),
                (
                    "frequency",
                    models.CharField(
                        choices=[
                            ("daily", "Daily"),
                            ("weekly", "Weekly"),
                            ("monthly", "Monthly"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "output_format",
                    models.CharField(
                        choices=[("csv", "CSV")], default="csv", max_length=8
                    ),
                ),
                ("categories", models.JSONField(default=list)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("next_run_at", models.DateTimeField(db_index=True)),
                ("last_attempt_at", models.DateTimeField(blank=True, null=True)),
                ("last_delivered_at", models.DateTimeField(blank=True, null=True)),
                (
                    "last_error",
                    models.CharField(blank=True, default="", max_length=512),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analytics_report_schedule",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"db_table": "analytics_report_schedule"},
        ),
        migrations.AddIndex(
            model_name="analyticsreportschedule",
            index=models.Index(
                fields=["is_active", "next_run_at"],
                name="analytics_r_is_acti_3b3302_idx",
            ),
        ),
    ]
