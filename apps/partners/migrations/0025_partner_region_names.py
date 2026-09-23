"""A partner may work in more than one region (owner, 2026-09-23).

`region_names` holds what the single `region_name` column could not: every
region the organisation works in. That column stays, holding the first of them,
because the register, the oversight grouping, the targets table and the profile
all read it.

The backfill keeps the two in step for organisations that already exist: each
one's single region becomes a one-item list, so the tick-list opens showing
what was already recorded rather than showing nothing.
"""

import django.contrib.postgres.fields
from django.db import migrations, models


def carry_the_single_region_into_the_list(apps, schema_editor):
    Partner = apps.get_model("partners", "Partner")
    for partner in Partner.objects.exclude(region_name__isnull=True).exclude(
        region_name=""
    ):
        if not partner.region_names:
            partner.region_names = [partner.region_name]
            partner.save(update_fields=["region_names"])


def drop_the_list(apps, schema_editor):
    """Reversing costs nothing: the single column was never stopped being written."""


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0024_partner_assignment_return_resolution"),
    ]

    operations = [
        migrations.AddField(
            model_name="partner",
            name="region_names",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=255),
                blank=True,
                default=list,
                size=None,
            ),
        ),
        migrations.RunPython(carry_the_single_region_into_the_list, drop_the_list),
    ]
