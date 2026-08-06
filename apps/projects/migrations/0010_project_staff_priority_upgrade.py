from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_user_mfa_channel_mfachallenge"),
        ("projects", "0009_projectstaffassignment"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="school_focus",
            field=models.CharField(
                choices=[
                    ("all", "Client and Core Schools"),
                    ("client", "Client Schools"),
                    ("core", "Core Schools"),
                ],
                default="all",
                max_length=16,
            ),
        ),
        migrations.RenameField(
            model_name="projectstaffassignment",
            old_name="role_on_project",
            new_name="responsibility",
        ),
        migrations.AlterField(
            model_name="projectstaffassignment",
            name="responsibility",
            field=models.CharField(
                choices=[
                    ("execute", "Execute"),
                    ("supervise", "Supervise"),
                ],
                default="execute",
                max_length=24,
            ),
        ),
        migrations.AlterField(
            model_name="projectstaffassignment",
            name="staff",
            field=models.ForeignKey(
                db_column="staff_id",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="project_priority_assignments",
                to="accounts.staffprofile",
            ),
        ),
        migrations.AddField(
            model_name="projectstaffassignment",
            name="assigned_by_role",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="projectstaffassignment",
            name="start_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="projectstaffassignment",
            name="due_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
