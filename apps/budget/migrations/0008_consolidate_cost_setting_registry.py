"""Consolidate editable costs onto one canonical rate registry.

Legacy visit allowance rows intentionally remain for historical cost-line
auditability. New costing and the Cost Catalogue management surface use the
district-specific daily keys created in migration 0005.
"""

from django.db import migrations


CANONICAL_RATES = (
    ("primary_transport_per_day", "Primary district daily transport pool", 50000),
    ("primary_lunch_per_day", "Primary district daily lunch pool", 12000),
    ("secondary_transport_per_day", "Secondary district daily transport pool", 80000),
    ("secondary_lunch_per_day", "Secondary district daily lunch pool", 12000),
    (
        "secondary_accommodation_per_night",
        "Secondary district accommodation per night",
        40000,
    ),
    (
        "secondary_overnight_dinner_per_day",
        "Secondary district overnight dinner",
        12000,
    ),
    ("secondary_breakfast_per_day", "Secondary district breakfast (optional)", 8000),
    (
        "secondary_incidentals_per_day",
        "Secondary district incidentals (optional)",
        5000,
    ),
    (
        "cluster_meeting_participant_meal_cost_per_head",
        "Participant snacks",
        10000,
    ),
    (
        "group_training_participant_meal_cost_per_head",
        "Participant meals",
        5000,
    ),
    ("group_training_facilitation_fee", "Facilitation fee", 50000),
    ("group_training_venue_cost", "Venue fee", 30000),
    (
        "partner_training_lump_sum",
        "Partner training/facilitation rate",
        16000,
    ),
    ("partner_visit_lump_sum", "Partner visit rate", 40000),
    ("core_school_visit", "Core school visit cost", 50000),
    ("core_school_training", "Core school training cost", 250000),
    ("ssa_visit_rate", "SSA visit cost", 50000),
    (
        "project_partner_lump_sum",
        "Special project partner activity rate",
        40000,
    ),
)


def consolidate_cost_setting_registry(apps, schema_editor):
    CostCatalogue = apps.get_model("budget", "CostCatalogue")
    CostSetting = apps.get_model("budget", "CostSetting")

    active = (
        CostCatalogue.objects.filter(is_active=True).order_by("-fy", "-version").first()
    )
    for key, label, default_cost in CANONICAL_RATES:
        rate, created = CostSetting.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "unit_cost": default_cost,
                "fy": active.fy if active else None,
                "version": 1,
                "catalogue": active,
            },
        )
        update_fields = []
        if rate.catalogue_id is None and active is not None:
            rate.catalogue = active
            update_fields.append("catalogue")
        if rate.fy is None and active is not None:
            rate.fy = active.fy
            update_fields.append("fy")
        # Remove the obsolete Baseline wording while preserving every value
        # and version chosen by the Country Director.
        if key == "ssa_visit_rate" and rate.label != label:
            rate.label = label
            update_fields.append("label")
        if not created and update_fields:
            rate.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0007_normalize_cluster_activity_rates"),
    ]

    operations = [
        migrations.RunPython(
            consolidate_cost_setting_registry,
            migrations.RunPython.noop,
        ),
    ]
