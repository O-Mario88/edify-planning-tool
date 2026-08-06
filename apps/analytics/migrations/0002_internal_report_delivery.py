from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("analytics", "0001_analytics_user_preferences"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="analyticsreportschedule",
            name="recipient_email",
        ),
    ]
