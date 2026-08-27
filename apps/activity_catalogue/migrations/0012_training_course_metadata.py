from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "activity_catalogue",
            "0011_remove_activityinterventionmapping_uniq_catalogue_intervention_mode_and_more",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="activitycatalogueitem",
            name="is_training_course",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="activitycatalogueitem",
            name="training_category",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="activitycatalogueitem",
            name="ssa_indicator_label",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
