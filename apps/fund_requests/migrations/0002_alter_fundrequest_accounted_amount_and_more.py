# Generated for the money-integrity migration: float money columns → integer
# UGX (BigIntegerField). Floors stray fractional values, then alters the type.
from django.db import migrations, models


def _floor_money(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as c:
        for table, col in (
            ("fund_request", "total_amount"),
            ("fund_request", "disbursed_amount"),
            ("fund_request", "accounted_amount"),
            ("fund_request", "returned_amount"),
            ("fund_request_item", "amount"),
        ):
            c.execute(f"UPDATE {table} SET {col} = floor({col}::numeric) WHERE {col} IS NOT NULL")


class Migration(migrations.Migration):

    dependencies = [
        ("fund_requests", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_floor_money, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="fundrequest",
            name="accounted_amount",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="fundrequest",
            name="disbursed_amount",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="fundrequest",
            name="returned_amount",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="fundrequest",
            name="total_amount",
            field=models.BigIntegerField(),
        ),
        migrations.AlterField(
            model_name="fundrequestitem",
            name="amount",
            field=models.BigIntegerField(),
        ),
    ]
