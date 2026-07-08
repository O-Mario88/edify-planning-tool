# Generated for the money-integrity migration: float money columns → integer
# UGX (BigIntegerField). Floors stray fractional values, then alters the type.
# (quantity stays a Decimal — admin items may be fractional, e.g. 1.5 days.)
from django.db import migrations, models


def _floor_money(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as c:
        for table, col in (
            ("admin_budget_line", "unit_cost"),
            ("admin_budget_line", "total_cost"),
            ("monthly_work_plan_budget", "program_total"),
            ("monthly_work_plan_budget", "admin_total"),
            ("monthly_work_plan_budget", "total_amount"),
        ):
            c.execute(
                f"UPDATE {table} SET {col} = floor({col}::numeric) WHERE {col} IS NOT NULL"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("monthly_work_plan", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_floor_money, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="adminbudgetline",
            name="quantity",
            field=models.DecimalField(decimal_places=2, default=1, max_digits=12),
        ),
        migrations.AlterField(
            model_name="adminbudgetline",
            name="total_cost",
            field=models.BigIntegerField(),
        ),
        migrations.AlterField(
            model_name="adminbudgetline",
            name="unit_cost",
            field=models.BigIntegerField(),
        ),
        migrations.AlterField(
            model_name="monthlyworkplanbudget",
            name="admin_total",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="monthlyworkplanbudget",
            name="program_total",
            field=models.BigIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name="monthlyworkplanbudget",
            name="total_amount",
            field=models.BigIntegerField(default=0),
        ),
    ]
