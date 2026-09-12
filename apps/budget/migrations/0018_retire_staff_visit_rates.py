"""Remove the Client Staff Visit, Core Staff Visit and SSA Support rate rows.

Owner, 2026-09-12: "The school visit cost should be removed for both core and
client for the staff because we are adding transport + lunch then divide by
the number of schools planned for that day; for a secondary district,
transport + lunch + breakfast + dinner + accommodation divided the same way."
That division is the Daily Visit Batch pool, which already prices every staff
school visit; the two staff rates were the flat amount each school paid on
top. SSA Support is partner work and "the same cost as follow up and other
partner school visit related activities", so it is priced as the partner
visit rate and its own row goes.

History is untouched: every costed activity keeps its own
`ActivityScheduleCostLine` rows with the key, unit and amount it was priced
at, and the costing_service label map keeps both keys so old lines still
read. Partner visit rates and the OneTest rate stay.
"""

from django.db import migrations

STAFF_VISIT_RATE_KEYS = ("client_staff_visit", "core_staff_visit", "ssa_support")


def retire(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    CostSetting.objects.filter(key__in=STAFF_VISIT_RATE_KEYS).delete()


def unretire(apps, schema_editor):
    """Deliberately does not restore the rates: the engine no longer reads
    them, so a restored row would be an editable rate that prices nothing."""


class Migration(migrations.Migration):
    dependencies = [("budget", "0017_cost_setting_catalogue_item")]
    operations = [migrations.RunPython(retire, unretire)]
