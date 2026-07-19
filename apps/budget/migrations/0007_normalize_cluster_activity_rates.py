"""Add the fixed cluster meeting/training rate keys without losing rates.

Older installations used broad training and cluster-meeting rate keys.  This
migration copies their current values into the small canonical recipe used by
planning, requests and budgets.  Old rows intentionally remain for historical
schedule-line auditability, but are not used for new work.
"""

from django.db import migrations


CANONICAL_RATES = (
    (
        "cluster_meeting_participant_meal_cost_per_head",
        "Participant snacks",
        ("cluster_meeting_cost",),
        10000,
    ),
    (
        "group_training_participant_meal_cost_per_head",
        "Participant meals",
        ("meals_per_participant",),
        5000,
    ),
    (
        "group_training_facilitation_fee",
        "Facilitation fee",
        ("training_session_fee",),
        50000,
    ),
    (
        "group_training_venue_cost",
        "Venue fee",
        ("venue",),
        30000,
    ),
)


def normalize_cluster_activity_rates(apps, schema_editor):
    CostCatalogue = apps.get_model("budget", "CostCatalogue")
    CostSetting = apps.get_model("budget", "CostSetting")

    active = CostCatalogue.objects.filter(is_active=True).order_by("-fy", "-version").first()
    for key, label, legacy_keys, default_cost in CANONICAL_RATES:
        existing = CostSetting.objects.filter(key=key).first()
        if existing:
            # Keep a CD's actual rate, but make the catalogue wording clear.
            if existing.label != label:
                existing.label = label
                existing.save(update_fields=["label"])
            continue

        source = CostSetting.objects.filter(key__in=legacy_keys).order_by("-updated_at").first()
        CostSetting.objects.create(
            key=key,
            label=label,
            unit_cost=source.unit_cost if source else default_cost,
            fy=source.fy if source else (active.fy if active else None),
            version=source.version if source else 1,
            created_by=source.created_by if source else None,
            catalogue=source.catalogue if source else active,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0006_budgetamendment"),
    ]

    operations = [
        migrations.RunPython(
            normalize_cluster_activity_rates,
            migrations.RunPython.noop,
        ),
    ]
