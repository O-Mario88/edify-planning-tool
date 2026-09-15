# Presence detail for the Who's Online table (owner, 2026-09-15).

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0028_user_roles_regional_programme_lead"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="online_since",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="user",
            name="last_seen_path",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="user",
            name="last_seen_action",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
