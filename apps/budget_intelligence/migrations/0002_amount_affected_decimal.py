"""amount_affected was the one money column stored as a float (AEGIS review,
2026-09-12); every other amount on the platform is a decimal."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("budget_intelligence", "0001_initial")]
    operations = [
        migrations.AlterField(
            model_name="budgetintelligenceinsight",
            name="amount_affected",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=16, null=True
            ),
        ),
    ]
