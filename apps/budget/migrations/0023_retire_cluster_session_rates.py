"""Remove the Cluster Training and Cluster Meeting rate rows.

Owner, 2026-10-01: "remove the dead cluster training and cluster meeting
rows". Both were per-session rates charged on top of what a session spends:
one row shared by meetings and trainings from 2026-09-06
(`cluster_meetings_trainings`), the meeting given its own on 2026-09-17
(`cluster_meeting`). The session costing spec of 2026-09-26 stopped charging
either: a cluster meeting is its participants' snacks, the room, the handouts
and the staff member's day, and a cluster training adds the facilitator. The
rows stayed on Cost Settings, editable and pricing nothing.

History is untouched: a meeting or training priced while a rate was charged
keeps its own `ActivityScheduleCostLine` with the key, unit and amount it was
priced at, `CostSettingHistory` keeps every change made to the rows, and the
costing_service maps keep both keys so those lines still read. The keys join
`RETIRED_COST_SETTING_KEYS`, so neither can be created or edited again.
"""

from django.db import migrations

SESSION_RATE_KEYS = ("cluster_meetings_trainings", "cluster_meeting")


def retire(apps, schema_editor):
    CostSetting = apps.get_model("budget", "CostSetting")
    rows = CostSetting.objects.filter(
        key__in=SESSION_RATE_KEYS, catalogue_item__isnull=True
    )
    for row in rows.order_by("catalogue_id", "key"):
        print(
            f"[0023_retire_cluster_session_rates] removing {row.key} "
            f"({row.label}) at UGX {row.unit_cost} from catalogue "
            f"{row.catalogue_id}, row {row.id}."
        )
    rows.delete()


def unretire(apps, schema_editor):
    """Deliberately does not restore the rates: the engine no longer reads
    them, so a restored row would be an editable rate that prices nothing."""


class Migration(migrations.Migration):
    dependencies = [("budget", "0022_group_training_meals_rate")]
    operations = [migrations.RunPython(retire, unretire)]
