from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0033_activity_programme_planning_fields"),
    ]

    operations = [
        migrations.AlterField(
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
                    ("training", "Training"),
                    ("school_visit", "School Visit"),
                    ("youth_camp", "Youth Camp"),
                    ("admin", "Admin"),
                    ("programme_event", "Programme Event"),
                ],
                max_length=48,
                null=True,
            ),
        ),
        migrations.AlterField(
            model_name="activity",
            name="programme_delivery_mode",
            field=models.CharField(
                blank=True,
                choices=[
                    ("group", "Group"),
                    ("cluster", "Cluster"),
                    ("in_school", "In-school Training"),
                    ("online", "Online"),
                    ("visit", "School Visit"),
                    ("admin", "Admin"),
                ],
                max_length=16,
                null=True,
            ),
        ),
    ]
