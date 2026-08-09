from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0038_activity_schools_invited"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="teachers_per_school",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="activity",
            name="leaders_per_school",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="activity",
            name="other_per_school",
            field=models.IntegerField(blank=True, null=True),
        ),
    ]
