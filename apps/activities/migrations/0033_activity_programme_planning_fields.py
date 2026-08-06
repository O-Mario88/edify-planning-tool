from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0032_backfill_planning_source"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="planned_school_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="activity",
            name="programme_activity_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("edtech_for_schools", "EdTech for Schools"),
                    ("school_leadership_training", "School Leadership Training"),
                    ("student_activities", "Student Activities"),
                    ("teacher_training", "Teacher Training"),
                    ("alumni", "Alumni"),
                ],
                max_length=48,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="activity",
            name="programme_delivery_mode",
            field=models.CharField(
                blank=True,
                choices=[("group", "Group"), ("cluster", "Cluster")],
                max_length=16,
                null=True,
            ),
        ),
    ]
