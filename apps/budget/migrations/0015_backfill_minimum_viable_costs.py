"""Give every live rate a Minimum Viable Cost.

`approved_minimum` is what the CCEO and the Programme Lead see while they
plan: `costing_service.minimum_cost` prices the planned quantities from these
rates and deliberately refuses to fall back to the operational ones, so an
unset minimum shows the planner a dash and a "not set in the active CD Cost
Catalogue" message. Nothing had ever written the field — neither the seed nor
`ensure_cost_reference` — so on 2026-09-05 every one of the fourteen live
rates was blank and every planning preview totalled nothing while the plan
behind it accumulated the full operational cost.

The backfill sets each minimum to its own published operational rate. That is
the one value that states no new policy: the approved rate is the floor until
the Country Director lowers it in Cost Settings, which is exactly what the
field is for. It also cannot trip the governance check, which flags an
operational rate that has fallen BELOW its approved minimum.

Only rates on an active catalogue are touched. A superseded card is an audit
record of what was published at the time and is left as it was.
"""

from django.db import migrations
from django.db.models import F


def backfill(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    CostSetting.objects.filter(
        approved_minimum__isnull=True,
        catalogue__is_active=True,
    ).update(approved_minimum=F("unit_cost"))


def clear(apps, schema_editor):
    """Not reversible in practice: which minimums the CD has since set by hand
    is not recoverable from here, and clearing them all would blank the
    planner's figure again."""


class Migration(migrations.Migration):
    dependencies = [("budget", "0014_retire_duplicate_cost_rates")]
    operations = [migrations.RunPython(backfill, clear)]
