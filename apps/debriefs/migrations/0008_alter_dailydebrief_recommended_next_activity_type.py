from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("debriefs", "0007_weeklydebriefreport_weeklyreportdistribution"),
    ]

    operations = [
        migrations.AlterField(
            model_name="dailydebrief",
            name="recommended_next_activity_type",
            field=models.CharField(
                blank=True,
                choices=[
                    ("school_visit", "School Visit"),
                    ("follow_up_visit", "Follow-Up Visit"),
                    ("baseline_ssa", "SSA Visit"),
                    ("ssa_refresh", "SSA Refresh"),
                    ("cluster_meeting", "Cluster Meeting"),
                    ("cluster_training", "Cluster Training"),
                    ("core_visit", "Core Visit"),
                    ("core_training", "Core Training"),
                    ("partner_coaching", "Partner Coaching"),
                    ("leadership_follow_up", "Leadership Follow-Up"),
                    ("finance_follow_up", "Finance Follow-Up"),
                    ("data_cleanup", "Data Cleanup"),
                    ("no_further_action", "No Further Action"),
                ],
                max_length=32,
                null=True,
            ),
        ),
    ]
