from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0007_normalize_partner_assignment_staff_identity"),
    ]

    operations = [
        migrations.AddField(
            model_name="partnerassignment",
            name="purpose_of_visit",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
    ]
