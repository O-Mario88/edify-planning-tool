# Generated for the money-integrity migration: float money columns → integer
# UGX (BigIntegerField). All existing UGX values are whole numbers; this step
# floors any stray fractional value (defensive) then alters the column type.
from django.db import migrations, models


def _floor_money(apps, schema_editor):
    """Floor money columns to whole UGX before the float→bigint type change."""
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as c:
        for table, col in (
            ("cost_setting", "unit_cost"),
            ("cost_setting_history", "new_unit_cost"),
            ("cost_setting_history", "old_unit_cost"),
            ("monthly_fund_request", "amount"),
        ):
            c.execute(f"UPDATE {table} SET {col} = floor({col}::numeric) WHERE {col} IS NOT NULL")


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_floor_money, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="costsetting",
            name="unit_cost",
            field=models.BigIntegerField(),
        ),
        migrations.AlterField(
            model_name="costsettinghistory",
            name="new_unit_cost",
            field=models.BigIntegerField(),
        ),
        migrations.AlterField(
            model_name="costsettinghistory",
            name="old_unit_cost",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="monthlyfundrequest",
            name="amount",
            field=models.BigIntegerField(),
        ),
    ]
