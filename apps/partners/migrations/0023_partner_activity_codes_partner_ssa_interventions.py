"""A partner may do more than one thing (owner, 2026-09-22).

The two arrays hold what the single `ssa_intervention` column could not: every
intervention the organisation covers and every catalogue activity it may be
given. That column stays, holding the first of them, because the register, the
oversight grouping and the profile all read it.

The backfill is what keeps the two in step for organisations that already
exist: each one's single intervention becomes a one-item list, so the tick-list
opens showing what was already recorded rather than showing nothing.
"""

import django.contrib.postgres.fields
from django.db import migrations, models


def carry_the_single_intervention_into_the_list(apps, schema_editor):
    Partner = apps.get_model("partners", "Partner")
    for partner in Partner.objects.exclude(ssa_intervention__isnull=True).exclude(
        ssa_intervention=""
    ):
        if not partner.ssa_interventions:
            partner.ssa_interventions = [partner.ssa_intervention]
            partner.save(update_fields=["ssa_interventions"])


def drop_the_list(apps, schema_editor):
    """Reversing costs nothing: the single column was never stopped being written."""


class Migration(migrations.Migration):
    dependencies = [
        ("partners", "0022_partner_user_setup_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="partner",
            name="activity_codes",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=96),
                blank=True,
                default=list,
                size=None,
            ),
        ),
        migrations.AddField(
            model_name="partner",
            name="ssa_interventions",
            field=django.contrib.postgres.fields.ArrayField(
                base_field=models.CharField(max_length=64),
                blank=True,
                default=list,
                size=None,
            ),
        ),
        migrations.RunPython(
            carry_the_single_intervention_into_the_list, drop_the_list
        ),
    ]
