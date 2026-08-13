"""Central CostingService — the single entry point for activity cost.

Every scheduling path (school visit, partner visit, cluster training, cluster
meeting, reschedule, partner self-schedule) calls THIS service to persist the
activity cost. No other module computes or persists activity cost. The service:

  • preview(input)        — itemized cost from the ACTIVE catalogue (no writes);
                            its blockers[] are the funded-scheduling gate that
                            activities.services.create() enforces for dated work.
  • apply_to_activity()   — the canonical budget-line writer: clears + rebuilds
                             ActivityScheduleCostLine rows, stamps catalogue
                             id/version onto every line, sets est_cost_cents.

Money is integer UGX throughout. The pure engine (costing.py::cost_for_activity)
is reused unchanged; this service wraps it with catalogue resolution + persistence.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest

from .costing import ActivityCost, CostLine, cost_for_activity
from .models import CostCatalogue, CostSetting
from .reference import CANONICAL_RATE_KEYS


# ── Catalogue + rate resolution ──────────────────────────────────────────────
def active_catalogue(fy: str | None = None) -> CostCatalogue | None:
    """The active CD Cost Catalogue used by the management page and pricing."""
    from django.conf import settings

    from apps.core.fy import get_operational_fy

    resolved_fy = str(fy or get_operational_fy())
    country = getattr(settings, "COUNTRY", "Uganda")
    return (
        CostCatalogue.objects.filter(
            country=country,
            fy=resolved_fy,
            is_active=True,
        )
        .order_by("-version")
        .first()
    )


def _rate_card(
    catalogue: CostCatalogue | None,
) -> tuple[dict[str, int], dict[str, CostSetting]]:
    """Return (rates dict, settings-by-key) for pricing.

    Only rows attached to this exact catalogue may price work. An orphaned or
    differently-versioned row is not visible on the active CD Cost Catalogue
    page, so accepting it here would make that page cease to be authoritative.
    """
    if catalogue is None:
        return {}, {}

    settings = {
        setting.key: setting
        for setting in CostSetting.objects.filter(
            catalogue=catalogue,
            key__in=CANONICAL_RATE_KEYS,
        )
    }
    rates = {key: s.unit_cost for key, s in settings.items()}
    return rates, settings


# Human label for each catalogue rate key, for clear blocker messages.
_KEY_LABEL = {
    "staff_visit_transport_primary": "Staff visit transport (primary district)",
    "staff_visit_transport_secondary": "Staff visit transport (secondary district)",
    "breakfast": "Breakfast",
    "lunch": "Lunch",
    "dinner": "Dinner",
    "accommodation": "Accommodation per night",
    "meals_per_participant": "Group training participant meal cost",
    "cluster_meeting_cost": "Cluster meeting participant meal cost",
    "venue": "Venue cost",
    "training_session_fee": "Facilitation fee",
    "mobilisation_per_participant": "Mobilisation cost per participant",
    "partner_visit_lump_sum": "Partner visit rate",
    "partner_training_lump_sum": "Partner training/facilitation rate",
    "project_partner_lump_sum": "Project partner rate",
    "school_visit_cost_per_school": "School visit cost per school",
    "school_visit_cost_per_school_primary": "School visit cost per school (primary)",
    "school_visit_cost_per_school_secondary": "School visit cost per school (secondary)",
    "group_training_participant_meal_cost_per_head": "Participant meals",
    "group_training_venue_cost": "Venue fee",
    "group_training_facilitation_fee": "Facilitation fee",
    "cluster_meeting_participant_meal_cost_per_head": "Participant snacks",
    "partner_visit_rate": "Partner visit rate",
    "primary_transport_per_day": "Primary district daily transport pool",
    "primary_lunch_per_day": "Primary district daily lunch pool",
    "secondary_transport_per_day": "Secondary district daily transport pool",
    "secondary_lunch_per_day": "Secondary district daily lunch pool",
    "secondary_accommodation_per_night": "Secondary district accommodation per night",
    "secondary_overnight_dinner_per_day": "Secondary district overnight dinner",
    "secondary_breakfast_per_day": "Secondary district breakfast (optional)",
    "secondary_incidentals_per_day": "Secondary district incidentals (optional)",
    "programme_venue_per_day": "Programme event venue (per day)",
    "programme_participant_meal_cost_per_head": "Programme participant meals",
    "programme_facilitation_per_day": "Programme facilitation (per day)",
    "programme_transport_per_day": "Programme transport (per day)",
    "programme_materials_per_participant": "Programme materials",
    "programme_accommodation_per_night": "Programme accommodation (per night)",
}


_COSTING_PROFILE_ACTIVITY_TYPE = {
    "IN_SCHOOL_TRAINING": "in_school_training",
    "CLUSTER_TRAINING": "cluster_training",
    "CLUSTER_MEETING": "cluster_meeting",
    "ONLINE_TRAINING": "training",
    "STAFF_SCHOOL_VISIT": "school_visit",
    "ADMIN_PARTNER_MEETING": "partner_activity",
    "SSA_DATA_GATHERING": "baseline_ssa_visit",
    "GROUP_YOUTH_CAMP": "training",
    "PROGRAMME_EVENT": "programme_event",
}


def _profiled_input(input: dict) -> dict:
    """Resolve the explicit Activity Catalogue costing profile centrally."""
    profile = input.get("costingProfile")
    if not profile:
        return input
    activity_type = _COSTING_PROFILE_ACTIVITY_TYPE.get(profile)
    if not activity_type:
        raise BadRequest(
            f"Unknown Activity Catalogue costing profile '{profile}'. "
            "Country Director configuration must be repaired before scheduling."
        )
    return {**input, "activityType": activity_type}


def _missing_label(key: str) -> str:
    return _KEY_LABEL.get(key, key.replace("_", " ").title())


# ── Preview ──────────────────────────────────────────────────────────────────
def preview(input: dict) -> dict:
    """Compute an itemized cost preview from the active catalogue. No writes.

    Returns: {catalogueId, catalogueVersion, currency, amount, lines[],
              costMissing, missingItems[], blockers[], canSchedule}.
    A blocker is raised-candidate text naming the exact missing cost item so the
    UI can show e.g. "Group training participant meal cost is not set."."""
    input = _profiled_input(input)
    fy = input.get("fy")
    catalogue = active_catalogue(fy)
    rates, _by_key = _rate_card(catalogue)
    cost = cost_for_activity(input, rates)
    missing = cost.missing_items
    blockers = [
        f"{_missing_label(k)} is not set in the active CD Cost Catalogue."
        for k in missing
    ]
    if catalogue is None:
        blockers.insert(
            0, "No active CD Cost Catalogue — publish one before scheduling."
        )
    return {
        "catalogueId": catalogue.id if catalogue else None,
        "catalogueVersion": catalogue.version if catalogue else None,
        "currency": "UGX",
        "amount": int(cost.amount),
        "lines": [_serialize_line(line) for line in cost.lines],
        "costMissing": cost.cost_missing or catalogue is None,
        "missingItems": missing,
        "blockers": blockers,
        "canSchedule": (not cost.cost_missing) and catalogue is not None,
    }


def activity_cost_coverage(items, catalogue: CostCatalogue | None = None) -> list[dict]:
    """Describe how every governed Activity is covered by the CD rate card.

    Cost settings are reusable ingredients, so duplicating the same meal or
    transport rate into 28 activity-specific rows would create conflicting
    sources of truth. This projection keeps the rates canonical while making
    each Activity Catalogue title, its recipe, and any missing ingredient
    visible on the CD Cost Catalogue page.

    ``items`` should prefetch ``intervention_mappings``; the function performs
    one rate-card read regardless of catalogue size and no per-item queries.
    """
    catalogue = catalogue or active_catalogue()
    rates, _by_key = _rate_card(catalogue)
    rows: list[dict] = []
    for item in items:
        profiled = _profiled_input(
            {
                "activityType": item.workflow_kind,
                "costingProfile": item.costing_profile,
                "deliveryType": "staff",
                "districtType": "primary",
                "expectedParticipants": 1,
                "days": 1,
            }
        )
        cost = cost_for_activity(profiled, rates)
        mappings = [m for m in item.intervention_mappings.all() if m.active]
        intervention = next(
            (m.get_intervention_display() for m in mappings if m.is_primary),
            "Administrative / inherited",
        )
        component_labels = []
        for line in cost.lines:
            if line.label not in component_labels:
                component_labels.append(line.label.split(" [Rate basis:", 1)[0])
        rows.append(
            {
                "stable_code": item.stable_code,
                "name": item.display_name,
                "activity_type": item.get_activity_type_display(),
                "delivery_method": item.get_delivery_method_display(),
                "intervention": intervention,
                "costing_profile": item.costing_profile.replace("_", " ").title(),
                "components": component_labels,
                "missing": [_missing_label(key) for key in cost.missing_items],
                "ready": catalogue is not None and not cost.cost_missing,
            }
        )
    return rows


# NOTE: an `assert_schedulable(input)` gate used to live here, whose docstring
# claimed it was "called by every scheduling path" — it had ZERO callers. The
# real funded-scheduling gate is the inline preview-blocker check inside
# activities.services.create() (dated work only), and its extra
# participants-required rule would have broken the deliberate
# default-25-participants pricing. Removed rather than left lying (2026-08-12
# audit L-1).


def _serialize_line(line: CostLine) -> dict:
    return {
        "label": line.label,
        "key": line.key,
        "unit": line.unit,
        "qty": line.qty,
        "amount": int(line.amount),
        "missing": line.missing,
        "lineItemType": _line_item_type(line.key),
    }


def _line_item_type(key: str) -> str:
    """A stable line-item category (transport / lunch / venue / facilitation /
    participant_meals / lump_sum …) for itemized budget reporting."""
    if "school_visit_cost_per_school" in key:
        return "school_visit"
    if key == "group_training_participant_meal_cost_per_head":
        return "participant_meals"
    if key == "group_training_venue_cost":
        return "venue"
    if key == "group_training_facilitation_fee":
        return "facilitation"
    if key == "cluster_meeting_participant_meal_cost_per_head":
        return "cluster_meeting_participant_meals"
    if key == "partner_visit_rate":
        return "partner_visit"
    # Daily Visit Batch keys (primary_transport_per_day, secondary_lunch_per_day,
    # etc.) — explicit branches since the generic substring/exact-match checks
    # below wouldn't catch lunch/accommodation/dinner/breakfast variants.
    if key in ("primary_transport_per_day", "secondary_transport_per_day"):
        return "transport"
    if key in ("primary_lunch_per_day", "secondary_lunch_per_day"):
        return "lunch"
    if key == "secondary_accommodation_per_night":
        return "accommodation"
    if key == "secondary_overnight_dinner_per_day":
        return "dinner"
    if key == "secondary_breakfast_per_day":
        return "breakfast"
    if key == "secondary_incidentals_per_day":
        return "incidentals"
    if "transport" in key:
        return "transport"
    if key in ("breakfast", "lunch", "dinner", "accommodation"):
        return key
    if key == "venue":
        return "venue"
    if key == "training_session_fee":
        return "facilitation"
    if key in ("meals_per_participant",):
        return "participant_meals"
    if key in ("mobilisation_per_participant",):
        return "mobilisation"
    if key in ("cluster_meeting_cost",):
        return "cluster_meeting_participant_meals"
    if "lump_sum" in key:
        return "lump_sum"
    return "other"


# ── Persist (the canonical budget-line writer) ───────────────────────────────
def _programme_period_specs(cost, activity, planned_date):
    """§9 cross-period allocation for multi-day activities.

    Returns [(line, service_date, qty, amount, key_suffix)] — one spec per
    persisted budget line. A single-month activity keeps one line per
    component dated at its start. When the range crosses a month boundary,
    day-scaled components are split into one line per month carrying the days
    that month actually hosts, dated at that month's first service day (the
    documented within-month rule: funding is drawn ahead of delivery).

    TOTAL-PRESERVING BY CONSTRUCTION. An earlier version divided each line's
    quantity by the number of days, which silently DELETED any component
    whose quantity did not scale per day (`1 // 3 == 0` dropped a whole venue
    fee) and rounded participant meals down. Here the split is driven by the
    line's own amount using largest-remainder, and the per-month amounts are
    asserted to re-sum to the original — a cross-period activity can never
    cost less than a same-month one.

    Key suffixes (``#mYYYYMM``) keep the one-component-per-key database
    constraint meaningful: a component may legitimately recur once per month.
    """
    from datetime import timedelta

    end = activity.end_date
    if not (
        planned_date
        and end
        and end > planned_date
        and (end.year, end.month) != (planned_date.year, planned_date.month)
    ):
        return [(line, planned_date, line.qty, line.amount, "") for line in cost.lines]

    days = [
        planned_date + timedelta(days=i) for i in range((end - planned_date).days + 1)
    ]
    months: list[tuple[int, int]] = []
    for d in days:
        if (d.year, d.month) not in months:
            months.append((d.year, d.month))
    first_day_in_month: dict[tuple[int, int], object] = {}
    for d in days:
        first_day_in_month.setdefault((d.year, d.month), d)
    days_in_month = {
        ym: sum(1 for d in days if (d.year, d.month) == ym) for ym in months
    }

    # Components that accrue per service day. Anything else (materials,
    # registration, a one-off deposit) belongs to the first service day.
    PER_DAY_KEYS = {
        "programme_venue_per_day",
        "programme_facilitation_per_day",
        "programme_transport_per_day",
        "programme_participant_meal_cost_per_head",
        "programme_accommodation_per_night",
        "group_training_participant_meal_cost_per_head",
        "group_training_facilitation_fee",
        "group_training_venue_cost",
    }

    def _largest_remainder(total: int, weights: list[int]) -> list[int]:
        """Split `total` across `weights`, preserving the total exactly."""
        weight_sum = sum(weights)
        if weight_sum <= 0:
            return [total] + [0] * (len(weights) - 1)
        raw = [total * w / weight_sum for w in weights]
        floors = [int(x) for x in raw]
        shortfall = total - sum(floors)
        order = sorted(range(len(raw)), key=lambda i: raw[i] - floors[i], reverse=True)
        for i in range(shortfall):
            floors[order[i % len(order)]] += 1
        return floors

    specs = []
    for line in cost.lines:
        if line.key not in PER_DAY_KEYS or not line.amount:
            specs.append((line, planned_date, line.qty, line.amount, ""))
            continue
        # Accommodation is slept every night except the last day.
        if line.key.endswith("accommodation_per_night"):
            nights = days[:-1]
            weights = [
                sum(1 for d in nights if (d.year, d.month) == ym) for ym in months
            ]
        else:
            weights = [days_in_month[ym] for ym in months]
        amounts = _largest_remainder(int(line.amount), weights)
        qtys = _largest_remainder(int(line.qty), weights)
        assert sum(amounts) == int(line.amount), (line.key, amounts, line.amount)
        for ym, amount, qty in zip(months, amounts, qtys):
            if amount or qty:
                specs.append(
                    (
                        line,
                        first_day_in_month[ym],
                        qty,
                        amount,
                        f"#m{ym[0]:04d}{ym[1]:02d}",
                    )
                )
    return specs


def apply_to_activity(
    activity: Activity,
    input: dict,
    responsible_user_id: str | None = None,
    precomputed_cost: ActivityCost | None = None,
) -> ActivityCost:
    """Price the activity from the active catalogue and PERSIST its budget lines.

    Clears any prior ActivityScheduleCostLine rows, then writes one row per cost
    item — each stamped with catalogue_id + catalogue_version + line_item_type +
    currency. Sets activity.est_cost_cents + cost_missing. Idempotent: safe on
    create, reschedule, and partner self-schedule (re-prices every time).

    `responsible_user_id` (the scheduler/owner) is forwarded to the auto-created
    advance requests so the right user confirms funding. Falls back to the
    activity's responsible_staff_id.

    `precomputed_cost`: when given, skips `cost_for_activity` entirely and uses
    this ActivityCost as-is — used by Daily Visit Batch pricing, where the cost
    is computed from a shared daily pool divided across sibling activities
    rather than from this activity's own input alone. Every other write below
    (date derivation, line persistence, catalogue provenance, advance-request
    sync) is reused unchanged.

    Returns the ActivityCost (amount + lines) so callers can return a preview in
    the same response as the schedule."""
    input = _profiled_input(input)
    fy = input.get("fy") or activity.fy
    catalogue = active_catalogue(fy)
    rates, settings_by_key = _rate_card(catalogue)
    cost = (
        precomputed_cost
        if precomputed_cost is not None
        else cost_for_activity(input, rates)
    )

    catalogue_id = catalogue.id if catalogue else None
    catalogue_version = catalogue.version if catalogue else None

    # Determine planned_date, week_start_date, week_end_date, month, quarter, fiscal_year
    from datetime import timedelta
    from apps.core.fy import get_operational_fy, get_quarter_for_date

    scheduled_date = activity.scheduled_date
    planned_date = None
    week_start = None
    week_end = None
    month = None
    quarter = None
    fiscal_year = None

    if scheduled_date:
        # A schedule is shown in the team's operational timezone.  Using the
        # raw UTC date here can put an evening booking into the wrong My Plan
        # week/month (and overwrite the correct values derived at creation).
        planned_date = timezone.localtime(scheduled_date).date()
        # Monday is weekday 0, Sunday is 6
        week_start = planned_date - timedelta(days=planned_date.weekday())
        week_end = week_start + timedelta(days=6)
        month = planned_date.month
        quarter = get_quarter_for_date(planned_date)
        fiscal_year = get_operational_fy(planned_date)

        # Save these on the activity
        activity.planned_date = planned_date
        activity.week_start_date = week_start
        activity.week_end_date = week_end
        activity.fiscal_year = fiscal_year
        activity.month = month
        activity.quarter = quarter
        activity.fy = fiscal_year

    from apps.fund_requests.models import (
        AdvanceRequest,
        AdvanceRequestStatus,
        FundRequest,
        FundRequestStatus,
        WeeklyFundRequest,
    )
    from apps.fund_requests.weekly_service import REBUILDABLE_WEEKLY_STATUSES

    # The finance-lock guards, the clear-and-rebuild of the cost lines and the
    # activity's own cost-field save must all happen in ONE transaction, with
    # the inspected rows locked. The guards used to run before the atomic
    # block with no locks at all — a confirmation or weekly submission landing
    # between the check and the delete was CASCADE-erased with the lines, the
    # exact vanishing-record scenario the guards describe (2026-08-12 audit
    # M-2). Locking also means a crash mid-sequence can no longer leave a
    # scheduled Activity with zero budget lines.
    with transaction.atomic():
        # Lock every advance on this activity's lines. A concurrent
        # confirm_advance()/weekly submit updating one of these rows now
        # blocks until this transaction commits (or commits first, in which
        # case the guards below see the confirmed status and refuse).
        locked_advances = list(
            AdvanceRequest.objects.select_for_update(of=("self",)).filter(
                budget_line__activity=activity
            )
        )
        # A cost line's disbursed/accounted/reimbursed AdvanceRequest (or its
        # WeeklyFundRequestLine) CASCADEs on the line's own deletion — clearing
        # the lines below would silently erase that financial record. Once
        # money has actually moved, this snapshot is locked history; the
        # caller must use a formal amendment/variance workflow instead.
        if any(
            adv.status
            in (
                AdvanceRequestStatus.DISBURSED,
                AdvanceRequestStatus.ACCOUNTABILITY_PENDING,
                AdvanceRequestStatus.ACCOUNTED,
                AdvanceRequestStatus.REIMBURSEMENT_SUBMITTED,
                AdvanceRequestStatus.REIMBURSEMENT_DISBURSED,
                AdvanceRequestStatus.REIMBURSED,
            )
            for adv in locked_advances
        ):
            raise BadRequest(
                "This activity already has a disbursed or accounted advance — its "
                "cost snapshot is locked. Use a budget amendment instead of "
                "rescheduling to change its cost."
            )

        # Confirmed-but-not-yet-disbursed money is frozen too: the clear-and-
        # rebuild would CASCADE-delete a CONFIRMED_FOR_ADVANCE advance (the
        # confirmation silently vanishes and is recreated as pending) while the
        # approved weekly request keeps its stale total with a missing line.
        # The unstick path is the accountant returning the advance.
        if any(
            adv.status
            in (
                AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE,
                AdvanceRequestStatus.SUBMITTED_TO_ACCOUNTANT,
            )
            for adv in locked_advances
        ):
            raise BadRequest(
                "This activity's advance is already confirmed and sitting in the "
                "accountant's queue. Ask the accountant to return the advance "
                "first, then reschedule."
            )

        # A submitted or approved weekly request is its own finance snapshot.
        # Its child advances can still be pending at this point, so the
        # advance checks alone would not stop a rebuild from removing an
        # approved request line. Lock ALL carrying requests (any status) so a
        # concurrent submission serializes with this rebuild, then refuse on
        # the frozen ones. A RETURNED request is back in the owner's hands —
        # re-pricing is the legitimate next step, and the generator rebuilds
        # its lines from the corrected schedule.
        carrying_wfr_ids = list(
            WeeklyFundRequest.objects.filter(
                lines__activity_budget_line__activity=activity
            )
            .values_list("id", flat=True)
            .distinct()
        )
        locked_wfrs = list(
            WeeklyFundRequest.objects.select_for_update().filter(
                id__in=carrying_wfr_ids
            )
        )
        if any(w.status not in REBUILDABLE_WEEKLY_STATUSES for w in locked_wfrs):
            raise BadRequest(
                "This activity is already included in a submitted or approved "
                "weekly fund request. Return that request before changing its cost."
            )

        # A submitted/approved MONTHLY FundRequest is equally a finance
        # snapshot, but its items reference cost lines by a bare CharField id
        # (no FK) — the rebuild would leave those payable item rows dangling
        # with live amounts and no source line. Any returned/rejected status
        # is back in the owner's hands (matching services.submit's
        # resubmittable set — the plain RETURNED trio alone made every
        # returned_by_* monthly request an un-fixable dead end).
        line_ids = list(
            ActivityScheduleCostLine.objects.filter(activity=activity).values_list(
                "id", flat=True
            )
        )
        repriceable_fr_statuses = [
            FundRequestStatus.DRAFT,
            FundRequestStatus.RETURNED,
            FundRequestStatus.REJECTED,
            FundRequestStatus.RETURNED_BY_PL,
            FundRequestStatus.RETURNED_BY_CD,
            FundRequestStatus.RETURNED_BY_RVP,
            FundRequestStatus.RETURNED_BY_ACCOUNTANT,
        ]
        carrying_fr_ids = list(
            FundRequest.objects.filter(
                items__activity_schedule_cost_line_id__in=line_ids
            )
            .values_list("id", flat=True)
            .distinct()
        )
        locked_frs = list(
            FundRequest.objects.select_for_update().filter(id__in=carrying_fr_ids)
        )
        if any(fr.status not in repriceable_fr_statuses for fr in locked_frs):
            raise BadRequest(
                "This activity is already included in a submitted or approved "
                "monthly fund request. Return that request before changing its cost."
            )

        ActivityScheduleCostLine.objects.filter(activity=activity).delete()

        # Tag Core activity budget lines
        tag = None
        if activity.activity_type == "core_visit":
            tag = (
                "Core Partner Activity"
                if activity.delivery_type == "partner"
                else "Core Visit"
            )
        elif activity.activity_type == "core_training":
            tag = (
                "Core Partner Activity"
                if activity.delivery_type == "partner"
                else "Core Training"
            )

        # §9: each budget line carries its own service/allocation date so a
        # multi-day activity crossing a month (or quarter/FY) boundary lands
        # its cost in the periods the work actually happens in. Single-month
        # activities keep the activity's own period stamps unchanged.
        line_specs = _programme_period_specs(cost, activity, planned_date)

        def _line_periods(service_date):
            if service_date is None:
                return planned_date, week_start, week_end, month, quarter, fiscal_year
            ws = service_date - timedelta(days=service_date.weekday())
            return (
                service_date,
                ws,
                ws + timedelta(days=6),
                service_date.month,
                get_quarter_for_date(service_date),
                get_operational_fy(service_date),
            )

        rows = []
        for line, service_date, qty, amount, key_suffix in line_specs:
            l_date, l_ws, l_we, l_month, l_quarter, l_fy = _line_periods(service_date)
            rows.append(
                ActivityScheduleCostLine(
                    activity=activity,
                    cost_setting_key=f"{line.key}{key_suffix}",
                    label=line.label,
                    unit_cost=0 if line.unit is None else int(line.unit),
                    quantity=int(qty),
                    amount=int(amount),
                    cost_setting_version=(
                        settings_by_key[line.key].version
                        if line.key in settings_by_key
                        else 1
                    ),
                    catalogue_id=catalogue_id,
                    catalogue_version=catalogue_version,
                    activity_catalogue_item_id=activity.catalogue_item_id,
                    activity_catalogue_version=activity.catalogue_version,
                    costing_profile=activity.costing_profile_snapshot,
                    line_item_type=_line_item_type(line.key),
                    currency="UGX",
                    description=f"[{tag}] {line.label}" if tag else line.label,
                    total_cost=int(amount),
                    planned_date=l_date,
                    week_start_date=l_ws,
                    week_end_date=l_we,
                    month=l_month,
                    quarter=l_quarter,
                    fiscal_year=l_fy,
                    responsible_user=responsible_user_id
                    or activity.responsible_staff_id,
                    responsible_role=None,
                    school=activity.school,
                    cluster=activity.cluster,
                    partner_id=activity.assigned_partner_id or None,
                    project_id=activity.project_id,
                )
            )
        ActivityScheduleCostLine.objects.bulk_create(rows)
        activity.est_cost_cents = int(cost.amount)
        activity.cost_missing = cost.cost_missing or catalogue is None
        activity.save(
            update_fields=[
                "est_cost_cents",
                "cost_missing",
                "planned_date",
                "week_start_date",
                "week_end_date",
                "fiscal_year",
                "month",
                "quarter",
                "fy",
                "updated_at",
            ]
        )

    # Auto-create weekly advance requests from the freshly-written budget lines
    # (the responsible user confirms before the Accountant may disburse). Only
    # when not cost-missing — a blocked activity carries no fundable advance.
    if not activity.cost_missing:
        from apps.fund_requests.advance_service import sync_for_activity

        sync_for_activity(activity, responsible_user_id=responsible_user_id)
    return cost


__all__ = [
    "active_catalogue",
    "preview",
    "apply_to_activity",
]
