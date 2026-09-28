"""An in-school Training costs 0; its School Visit carries the visit cost.

Owner, 2026-09-28: "in-school training should register both visits and
training on the same day and use the visit cost. training cost for in-school
training should be 0 since it is part of school visit and the school visit is
already costed."

Pairs scheduled before this change have the cost on the Training and none on
the visit. Fund requests and the missing-cost checks now leave the Training
out instead of the visit (``apps.activities.pair_costing``), so each
undelivered pair is re-priced once here: the Training drops to 0 and its
visit takes the visit cost, joining that day's visit pool. A pair whose money
has already moved is kept as it was and printed; the
``move_in_school_training_cost_to_visit`` command lists what is left.

As in 0057, 0058 and 0060, the historical models only decide whether there is
anything to do, so on a database with no such pairs (a fresh install, the
test database) the live code is never reached.

This runs in App Platform's pre-deploy job, which is stopped at 30 minutes
and fails the whole deployment. Re-pricing a pair is some 300 queries, and
production's pairs ran past that limit in one transaction: the deployments
of 46fea0d, eb26575 and 7189780 each failed in this job and were rolled back
(2026-09-28). So the migration is not atomic. Each pair commits on its own,
no pair is started after BUDGET_SECONDS, and whatever is left is printed for
the command's --apply. A deployment stopped anyway keeps the pairs it moved,
and the next one carries on from there.

Reverse is a no-op.
"""

import time

from django.db import migrations

#: Well inside the pre-deploy job's 30 minutes, which also covers the job's
#: start-up and the other migrations.
BUDGET_SECONDS = 20 * 60


def move_costs(apps, schema_editor):
    from apps.activities.pair_costing import (
        find_pair_trainings_carrying_cost,
        move_pair_costs_to_visits,
    )

    ids = find_pair_trainings_carrying_cost(apps)
    if not ids:
        return
    print(f"\nMoving the cost of {len(ids)} in-school Training(s) to their visits:")
    result = move_pair_costs_to_visits(ids, deadline=time.monotonic() + BUDGET_SECONDS)
    print(f"Moved {len(result['moved'])}, kept {len(result['skipped'])}.")
    if result["left"]:
        print(
            f"{len(result['left'])} not reached in {BUDGET_SECONDS // 60} minutes: "
            "run `python manage.py move_in_school_training_cost_to_visit --apply`."
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("accounts", "0031_staffprofile_google_drive_folder_url"),
        ("activities", "0060_refile_fy_boundary_rows"),
        ("activity_catalogue", "0014_mapping_review"),
        ("audit", "0008_domain_event_aggregate_id_width"),
        ("budget", "0022_group_training_meals_rate"),
        ("core_schools", "0005_credit_core_package_work"),
        (
            "daily_visit_batches",
            "0002_dailyvisitbatch_actual_field_cost_per_school_and_more",
        ),
        ("fund_requests", "0018_weekly_funding_source"),
        (
            "monthly_work_plan",
            "0007_monthlybudgetsubmissionsnapshot_country_funding_shortfall_and_more",
        ),
        ("notifications", "0005_repoint_dead_workflow_links"),
        ("schools", "0022_school_ownership_transfers"),
    ]

    operations = [migrations.RunPython(move_costs, migrations.RunPython.noop)]
