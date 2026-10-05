"""Bring the plans already made up to the rules of 2026-10-05.

Owner, 2026-10-05:

* "a week accommodation is 4 days because the fifth day they travel back and
  sleep and eat dinner from home. But transport, breakfast and lunch remains
  for 5 days. If the schedule is up to Saturday, then accommodation and dinner
  is for 5 days."
* "the accommodation for program leads, cd, IA and accountant should be
  separate from the accommodation of CCEO."
* "when calculating on the weekly request, it can just fetch the school visit
  cost since it is a school visit" (an in-school training).

New plans follow all three as they are saved. This re-prices the plans made
before them, each exactly as an edit of the day would:

1. In-school Trainings still carrying the visit cost their School Visit
   should carry. Activities migration 0061 moved these under a time limit and
   printed the rest for a command; the pairs it did not reach are still the
   wrong way round, so their visits read "No Budget" on My Plan and "Cost
   setup required" on the Work Plan. The same mover carries on from there.
2. Planned days in a secondary district still priced with a night and a
   dinner on the day the traveller comes home, or with the CCEO's
   accommodation rate for a traveller who is not a CCEO.
3. Planned work of several days (a camp, a conference, a field event) still
   priced with a night and a dinner on its last day. Asked whether such
   events drop them too, the owner said yes.

A day whose week has left draft, whose money has moved or whose work is done
is kept as it was priced, and printed. As in activities 0057, 0058, 0060 and
0061, the historical models only decide whether there is anything to do, so
on a database with nothing to move (a fresh install, the test database) the
live code is never reached.

This runs in App Platform's pre-deploy job, which is stopped at 30 minutes and
fails the whole deployment (see activities 0061). So the migration is not
atomic: each pair and each day commits on its own, nothing is started after
BUDGET_SECONDS, and what is left is printed for
`move_in_school_training_cost_to_visit --apply` and
`refresh_daily_cost_allocations --apply`. A deployment stopped anyway keeps
what it moved.

Reverse is a no-op.
"""

import time

from django.db import migrations

#: Well inside the pre-deploy job's 30 minutes, which also covers the job's
#: start-up and the other migrations.
BUDGET_SECONDS = 18 * 60


def reprice(apps, schema_editor):
    from apps.activities.pair_costing import (
        find_pair_trainings_carrying_cost,
        move_pair_costs_to_visits,
    )
    from apps.daily_visit_batches.repricing import (
        find_days_to_reprice,
        find_trips_to_reprice,
        reprice_days,
        reprice_trips,
    )

    deadline = time.monotonic() + BUDGET_SECONDS

    pairs = find_pair_trainings_carrying_cost(apps)
    if pairs:
        print(
            f"\nMoving the cost of {len(pairs)} in-school Training(s) to their visits:"
        )
        result = move_pair_costs_to_visits(pairs, deadline=deadline)
        print(f"Moved {len(result['moved'])}, kept {len(result['skipped'])}.")
        if result["left"]:
            print(
                f"{len(result['left'])} not reached: run `python manage.py "
                "move_in_school_training_cost_to_visit --apply`."
            )

    days = find_days_to_reprice(apps)
    if days:
        print(f"\nRe-pricing {len(days)} planned day(s) in a secondary district:")
        result = reprice_days(days, deadline=deadline)
        print(f"Re-priced {len(result['repriced'])}, kept {len(result['skipped'])}.")
        if result["left"]:
            print(
                f"{len(result['left'])} not reached: run `python manage.py "
                "refresh_daily_cost_allocations --apply`."
            )

    trips = find_trips_to_reprice(apps)
    if trips:
        print(f"\nRe-pricing {len(trips)} planned trip(s) of several days:")
        result = reprice_trips(trips, deadline=deadline)
        print(f"Re-priced {len(result['repriced'])}, kept {len(result['skipped'])}.")
        if result["left"]:
            print(f"{len(result['left'])} not reached and still priced the old way.")


class Migration(migrations.Migration):
    atomic = False

    # Every app's latest migration: the live code this calls reads the live
    # models, so each of their columns has to exist before it runs.
    dependencies = [
        ("accounts", "0037_user_admin_is_never_cceo"),
        ("activities", "0064_partner_date_set_by"),
        ("activity_catalogue", "0014_mapping_review"),
        ("audit", "0008_domain_event_aggregate_id_width"),
        ("budget", "0024_management_accommodation_rate"),
        ("clusters", "0007_cluster_facilitating_partner"),
        ("core_schools", "0010_in_school_training_visit_in_the_package"),
        (
            "daily_visit_batches",
            "0002_dailyvisitbatch_actual_field_cost_per_school_and_more",
        ),
        ("fund_requests", "0018_weekly_funding_source"),
        ("geography", "0006_region_country"),
        (
            "monthly_work_plan",
            "0007_monthlybudgetsubmissionsnapshot_country_funding_shortfall_and_more",
        ),
        ("notifications", "0005_repoint_dead_workflow_links"),
        ("partners", "0031_data_collection_handovers_apart"),
        ("planning", "0014_execution_period_snapshot"),
        ("projects", "0014_project_staff_capacity"),
        ("routes", "0001_initial"),
        ("schools", "0023_repair_school_holder_assignments"),
        ("ssa", "0009_ssa_record_source_and_return"),
        ("targets", "0007_target_ledger_dirty"),
    ]

    operations = [migrations.RunPython(reprice, migrations.RunPython.noop)]
