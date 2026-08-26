from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("activities", "0048_backfill_cluster_attendance"),
        ("activity_catalogue", "0012_training_course_metadata"),
    ]

    operations = [
        migrations.AddField(
            model_name="activity",
            name="training_course",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="in_school_course_deliveries",
                to="activity_catalogue.activitycatalogueitem",
            ),
        ),
        migrations.AddField(
            model_name="activity",
            name="paired_school_visit",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="paired_in_school_training",
                to="activities.activity",
            ),
        ),
        migrations.AddConstraint(
            model_name="activity",
            constraint=models.CheckConstraint(
                condition=~models.Q(("id", models.F("paired_school_visit"))),
                name="activity_pair_cannot_reference_self",
            ),
        ),
    ]
