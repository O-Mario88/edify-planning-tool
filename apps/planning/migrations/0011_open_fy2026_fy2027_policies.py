"""The Uganda FY2026 and FY2027 planning policies (owner brief, 2026-09-15).

* FY2026 keeps running to 30 September 2026 and its planning is already open.
* FY2027 (1 October 2026 – 30 September 2027) opens for planning on
  15 September 2026, while FY2026 is still being closed. Nothing in FY2027 is
  delivered before 1 October 2026.
* A school visit follow-up does not need a prior training in either year.

Only these two rows are written. No activity, budget, rate card or closed
record is touched.
"""

from datetime import date, datetime, timezone

from django.db import migrations

POLICIES = (
    {
        "fy": "2026",
        "planning_open_at": datetime(2025, 7, 1, tzinfo=timezone.utc),
        "execution_start": date(2025, 10, 1),
        "execution_end": date(2026, 9, 30),
        "notes": "FY2026 runs to 30 September 2026.",
    },
    {
        "fy": "2027",
        # 15 September 2026, 00:00 in Kampala (UTC+3).
        "planning_open_at": datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc),
        "execution_start": date(2026, 10, 1),
        "execution_end": date(2027, 9, 30),
        "notes": "FY2027 opened for planning by the owner's brief of 2026-09-15.",
    },
)


def create_policies(apps, schema_editor):
    Policy = apps.get_model("planning", "FiscalYearPlanningPolicy")
    for row in POLICIES:
        Policy.objects.get_or_create(
            country="Uganda",
            fy=row["fy"],
            defaults={
                "planning_open_at": row["planning_open_at"],
                "execution_start": row["execution_start"],
                "execution_end": row["execution_end"],
                "follow_up_visit_requires_prior_training": False,
                "opened_by": "migration",
                "updated_by": "migration",
                "notes": row["notes"],
            },
        )


class Migration(migrations.Migration):
    dependencies = [("planning", "0010_fiscal_year_planning_policy")]

    operations = [migrations.RunPython(create_policies, migrations.RunPython.noop)]
