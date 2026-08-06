# Seeds the 6 required + 2 optional Daily Visit Batch rate keys onto the
# currently-active Cost Catalogue (mirrors 0003's _seed_active_catalogue
# shape). These are NEW keys — the legacy staff_visit_transport_primary/
# _secondary and school_visit_cost_per_school_primary/_secondary keys are
# left completely untouched for back-compat with historical cost lines.
from django.db import migrations


DEFAULT_DAILY_BATCH_SETTINGS = [
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
]


def _seed_daily_batch_keys(apps, schema_editor):
    CostCatalogue = apps.get_model("budget", "CostCatalogue")
    CostSetting = apps.get_model("budget", "CostSetting")

    active = (
        CostCatalogue.objects.filter(is_active=True).order_by("-fy", "-version").first()
    )
    fy = active.fy if active else None
    for key, label, cost in DEFAULT_DAILY_BATCH_SETTINGS:
        CostSetting.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "unit_cost": cost,
                "fy": fy,
                "catalogue": active,
                "version": 1,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("budget", "0004_costcatalogue_required_school_visits_per_day"),
    ]

    operations = [
        migrations.RunPython(_seed_daily_batch_keys, migrations.RunPython.noop),
    ]
