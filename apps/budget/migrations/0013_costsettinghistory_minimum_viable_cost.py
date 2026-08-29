from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0012_alter_costcatalogue_kind"),
    ]

    operations = [
        migrations.AddField(
            model_name="costsettinghistory",
            name="old_approved_minimum",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="costsettinghistory",
            name="new_approved_minimum",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddConstraint(
            model_name="costsettinghistory",
            constraint=models.CheckConstraint(
                condition=models.Q(new_approved_minimum__isnull=True)
                | models.Q(new_approved_minimum__gte=0),
                name="cost_history_new_minimum_non_negative",
            ),
        ),
        migrations.AddConstraint(
            model_name="costsettinghistory",
            constraint=models.CheckConstraint(
                condition=models.Q(old_approved_minimum__isnull=True)
                | models.Q(old_approved_minimum__gte=0),
                name="cost_history_old_minimum_non_negative",
            ),
        ),
    ]
