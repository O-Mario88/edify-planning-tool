"""Every cost the activity's own (owner, 2026-10-15: "I want every cost
fetched exactly the cost of the activity, no doubling the cost, no inflating
or deflating the costs, no misleading costs").

From this release an in-school Training is the free half of a pair only while
its School Visit still makes the journey, and a night away is priced at the
rate of the post its traveller holds. Plans made before are as the old rules
left them. This puts them right, each exactly as an edit of the day would:

1. In-school Trainings whose visit was called off or removed, still at no
   cost — their day was in no budget (Nissi College Akia, 10 December 2026,
   on production). Priced as the visit day they now are
   (``pair_costing.price_stranded_pair_trainings``).
2. Planned nights away at the rate of a role the traveller was using rather
   than the post they hold (a Programme Lead's 24–26 November 2026 nights at
   the CCEO rate) — ``daily_visit_batches.repricing``.
3. Costs the CD added for an activity whose name holds "transport", typed as
   transport-company money and so requested from nobody — re-typed as the
   activity's own line.

Work whose week has left draft, whose money has moved or that is done is kept
as priced and printed. As in daily_visit_batches 0003, the historical models
only decide whether there is anything to do; nothing is started after
BUDGET_SECONDS, and ``price_stranded_pair_trainings --apply`` and
``refresh_daily_cost_allocations --apply`` pick up what is left. Not atomic:
each Training and each day commits on its own.

Reverse is a no-op.
"""

import time

from django.db import migrations
from django.db.models import Q

BUDGET_SECONDS = 12 * 60


def retype_added_costs(apps, schema_editor):
    """A cost the CD added for an activity was typed by the words in its name,
    so "Participant transport refund" read as transport-company money and was
    requested from nobody. It is one line of its activity, typed "other"
    (costing_service._line_item_type). No transport payment is ever made from
    such a line, so nothing paid is touched."""
    Line = apps.get_model("activities", "ActivityScheduleCostLine")
    count = (
        Line.objects.filter(cost_setting_key__startswith="activity:")
        .exclude(line_item_type="other")
        .update(line_item_type="other")
    )
    if count:
        print(f"\n  added activity costs re-typed: {count}")


def repair(apps, schema_editor):
    from apps.daily_visit_batches.repricing import find_days_to_reprice

    retype_added_costs(apps, schema_editor)
    Activity = apps.get_model("activities", "Activity")
    stranded = (
        Activity.objects.filter(
            activity_type="in_school_training",
            paired_school_visit__isnull=False,
            deleted_at__isnull=True,
        )
        .filter(
            Q(paired_school_visit__deleted_at__isnull=False)
            | Q(paired_school_visit__status__in=("cancelled", "rejected", "deferred"))
        )
        .exists()
    )
    # The real question, asked of the historical models: is any planned night
    # priced the wrong way?
    nights = bool(find_days_to_reprice(apps))
    trips = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="staff",
            end_date__isnull=False,
            schedule_cost_lines__cost_setting_key__contains="accommodation",
        )
        .distinct()
        .exists()
    )
    if not (stranded or nights or trips):
        return
    deadline = time.monotonic() + BUDGET_SECONDS
    print()
    if stranded:
        from apps.activities.pair_costing import price_stranded_pair_trainings

        result = price_stranded_pair_trainings(write=print, deadline=deadline)
        print(
            f"  stranded in-school trainings: {len(result['priced'])} priced, "
            f"{len(result['kept'])} kept, {len(result['left'])} left"
        )
    if nights:
        from apps.daily_visit_batches.repricing import reprice_days

        days = find_days_to_reprice()
        if days:
            result = reprice_days(days, write=print, deadline=deadline)
            print(f"  nights away re-priced: {result}")
    # Trips of several days, priced on their own and in no day batch, whose
    # nights are at a rate other than their traveller's post.
    from apps.daily_visit_batches.repricing import find_trips_to_reprice, reprice_trips

    trips = find_trips_to_reprice()
    if trips:
        result = reprice_trips(trips, write=print, deadline=deadline)
        print(f"  trips re-priced: {result}")


class Migration(migrations.Migration):
    atomic = False

    # Every app's latest migration: the live code this calls reads the live
    # models, so each of their columns has to exist before it runs (as
    # daily_visit_batches 0003).
    dependencies = [
        ("accounts", "0038_user_acting_until"),
        ("activities", "0067_hand_in_entered_work"),
        ("activity_catalogue", "0016_item_universal_training"),
        ("audit", "0008_domain_event_aggregate_id_width"),
        ("budget", "0024_management_accommodation_rate"),
        ("clusters", "0008_cluster_score_setting"),
        ("core_schools", "0012_index_slot_activity"),
        ("daily_visit_batches", "0004_costs_to_follow"),
        ("fund_requests", "0020_partner_invoice_program_lead"),
        ("geography", "0006_region_country"),
        ("hr", "0021_milestone_source_order_appends"),
        ("integrations", "0001_initial"),
        (
            "monthly_work_plan",
            "0007_monthlybudgetsubmissionsnapshot_country_funding_shortfall_and_more",
        ),
        ("notifications", "0006_push_subscription"),
        ("partners", "0034_partner_member_login"),
        ("planning", "0016_training_country_ceiling"),
        ("projects", "0014_project_staff_capacity"),
        ("routes", "0001_initial"),
        ("schools", "0025_ssa_import_row_duplicate"),
        ("ssa", "0010_one_ssa_per_school_fy"),
        ("targets", "0007_target_ledger_dirty"),
    ]

    operations = [migrations.RunPython(repair, migrations.RunPython.noop)]
