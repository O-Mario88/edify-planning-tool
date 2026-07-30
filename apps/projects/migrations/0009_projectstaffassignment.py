import apps.core.cuid
import apps.core.models
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0019_user_mfa_channel_mfachallenge"),
        ("projects", "0008_project_budget_ceiling_ugx_project_status_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectStaffAssignment",
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
                ("fy", models.CharField(max_length=16)),
                (
                    "role_on_project",
                    models.CharField(blank=True, max_length=64, null=True),
                ),
                (
                    "assigned_by",
                    models.CharField(blank=True, max_length=30, null=True),
                ),
                ("notes", models.TextField(blank=True, null=True)),
                ("is_active", models.BooleanField(default=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="staff_assignments",
                        to="projects.project",
                    ),
                ),
                (
                    "staff",
                    models.ForeignKey(
                        db_constraint=False,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="+",
                        to="accounts.staffprofile",
                    ),
                ),
            ],
            options={"db_table": "project_staff_assignment"},
        ),
        migrations.AddConstraint(
            model_name="projectstaffassignment",
            constraint=models.UniqueConstraint(
                fields=("project", "staff", "fy"),
                name="uniq_project_staff_fy",
            ),
        ),
    ]
