from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("geography", "0005_seed_uganda_boundaries"),
    ]

    operations = [
        migrations.AddField(
            model_name="region",
            name="country",
            field=models.CharField(db_index=True, default="Uganda", max_length=64),
        ),
    ]
