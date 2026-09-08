"""Remove the ten rate rows that named a recipe the platform already had.

Owner, 2026-09-04: "remove all duplicate costs". `core_school_visit` and
`ssa_visit_rate` were flat lumps for what is a staff visit day, priced by
district; `core_school_training` priced a group training and reached no
catalogue item; `project_partner_lump_sum` held the same 40,000 as the
partner visit rate; and the six `programme_*` rates mirrored the
group-training recipe for an activity type nothing produced.

Deleting the rate does not touch history: every costed activity keeps its own
`ActivityScheduleCostLine` rows with the key, unit and amount it was priced
at, and `ActivityCostSnapshot` stamps the catalogue version. The label map in
costing_service keeps the retired keys so those old lines still read.
"""

from django.db import migrations

DUPLICATE_KEYS = (
    "core_school_visit",
    "core_school_training",
    "ssa_visit_rate",
    "project_partner_lump_sum",
    "programme_venue_per_day",
    "programme_participant_meal_cost_per_head",
    "programme_facilitation_per_day",
    "programme_transport_per_day",
    "programme_materials_per_participant",
    "programme_accommodation_per_night",
)


def retire(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    CostSetting.objects.filter(key__in=DUPLICATE_KEYS).delete()


def unretire(apps, schema_editor):
    """Deliberately does not restore the rates.

    Putting them back would re-create the duplication this migration exists to
    remove, and the engine no longer reads any of these keys, so a restored
    row would be an editable rate that prices nothing.
    """


class Migration(migrations.Migration):
    dependencies = [("budget", "0013_costsettinghistory_minimum_viable_cost")]
    operations = [migrations.RunPython(retire, unretire)]
