from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0019_alter_activity_focus_intervention_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="submitted_to_ia_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
