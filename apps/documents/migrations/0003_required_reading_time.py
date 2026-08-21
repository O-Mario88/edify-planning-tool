from django.db import migrations, models


def set_canonical_reading_times(apps, schema_editor):
    DocumentAsset = apps.get_model("documents", "DocumentAsset")
    DocumentAsset.objects.filter(slug="edify-safeguarding-policy").update(
        required_reading_minutes=4
    )
    DocumentAsset.objects.filter(slug="edify-apostles-creed").update(
        required_reading_minutes=1
    )


def clear_canonical_reading_times(apps, schema_editor):
    DocumentAsset = apps.get_model("documents", "DocumentAsset")
    DocumentAsset.objects.filter(
        slug__in=("edify-safeguarding-policy", "edify-apostles-creed")
    ).update(required_reading_minutes=0)


class Migration(migrations.Migration):
    dependencies = [("documents", "0002_seed_first_login_agreements")]

    operations = [
        migrations.AddField(
            model_name="documentasset",
            name="required_reading_minutes",
            field=models.PositiveIntegerField(
                default=0,
                help_text=(
                    "Minimum active time in the Edify viewer before reading is "
                    "marked complete. Set by the uploader for each policy or manual."
                ),
            ),
        ),
        migrations.RunPython(
            set_canonical_reading_times,
            reverse_code=clear_canonical_reading_times,
        ),
    ]
