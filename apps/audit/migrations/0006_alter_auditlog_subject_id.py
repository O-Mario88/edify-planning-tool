from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("audit", "0005_alter_auditlog_actor_role"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditlog",
            name="subject_id",
            field=models.CharField(blank=True, max_length=128, null=True),
        ),
    ]
