"""Central CostingService — the single entry point for activity cost.

Every scheduling path (school visit, partner visit, cluster training, cluster
meeting, reschedule, partner self-schedule) calls THIS service. No other module
computes or persists activity cost. The service:

  • preview(input)        — itemized cost from the ACTIVE catalogue (no writes).
  • assert_schedulable()  — raises BadRequest naming the exact missing rate.
  • apply_to_activity()   — the canonical budget-line writer: clears + rebuilds
                             ActivityScheduleCostLine rows, stamps catalogue
                             id/version onto every line, sets est_cost_cents.

Money is integer UGX throughout. The pure engine (costing.py::cost_for_activity)
is reused unchanged; this service wraps it with catalogue resolution + persistence.
"""
from __future__ import annotations

from django.db.models import Q

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import BadRequest

from .costing import ActivityCost, CostLine, cost_for_activity
from .models import CostCatalogue, CostSetting


# ── Catalogue + rate resolution ──────────────────────────────────────────────
def active_catalogue(fy: str | None = None) -> CostCatalogue | None:
    """The active CD Cost Catalogue for a fiscal year (default = operational FY)."""
    qs = CostCatalogue.objects.filter(is_active=True)
    if fy:
        qs = qs.filter(fy=fy)
    return qs.order_by("-version").first()


def _rate_card(catalogue: CostCatalogue | None) -> tuple[dict[str, int], dict[str, CostSetting]]:
    """Return (rates dict, settings-by-key) for pricing.

    Prefers rates attached to the active catalogue; MERGES in any unattached
    CostSetting rows (back-compat for rates created before a catalogue existed
    or in tests that create rates directly). This keeps a single source of truth
    — the rate value is always the latest CostSetting for a key — while still
    recognizing the catalogue concept for provenance/versioning."""
    # Only rates belonging to THIS catalogue (plus unattached back-compat rows)
    # may price the activity — otherwise the catalogue id/version stamped onto
    # the budget line would not describe the rates actually used. Unattached
    # rows load first so a catalogue-attached key always wins.
    if catalogue is not None:
        qs = CostSetting.objects.filter(
            Q(catalogue=catalogue) | Q(catalogue__isnull=True)
        )
        settings: dict[str, CostSetting] = {}
        for s in qs:
            # Catalogue-attached keys always win; unattached rows only fill gaps.
            if s.catalogue_id == catalogue.id or s.key not in settings:
                settings[s.key] = s
    else:
        settings = {s.key: s for s in CostSetting.objects.all()}
    rates = {key: s.unit_cost for key, s in settings.items()}
    return rates, settings


# Human label for each catalogue rate key, for clear blocker messages.
_KEY_LABEL = {
    "staff_visit_transport_primary": "Staff visit transport (primary district)",
    "staff_visit_transport_secondary": "Staff visit transport (secondary district)",
    "breakfast": "Breakfast", "lunch": "Lunch", "dinner": "Dinner",
    "accommodation": "Accommodation per night",
    "meals_per_participant": "Group training participant meal cost",
    "cluster_meeting_cost": "Cluster meeting participant meal cost",
    "venue": "Venue cost", "training_session_fee": "Facilitation fee",
    "mobilisation_per_participant": "Mobilisation cost per participant",
    "partner_visit_lump_sum": "Partner visit rate",
    "partner_training_lump_sum": "Partner training/facilitation rate",
    "project_partner_lump_sum": "Project partner rate",
    "school_visit_cost_per_school": "School visit cost per school",
    "school_visit_cost_per_school_primary": "School visit cost per school (primary)",
    "school_visit_cost_per_school_secondary": "School visit cost per school (secondary)",
    "group_training_participant_meal_cost_per_head": "Group training participant meal cost per head",
    "group_training_venue_cost": "Group training venue cost",
    "group_training_facilitation_fee": "Group training facilitation fee",
    "cluster_meeting_participant_meal_cost_per_head": "Cluster meeting participant meal cost per head",
    "partner_visit_rate": "Partner visit rate",
}


def _missing_label(key: str) -> str:
    return _KEY_LABEL.get(key, key.replace("_", " ").title())


# ── Preview ──────────────────────────────────────────────────────────────────
def preview(input: dict) -> dict:
    """Compute an itemized cost preview from the active catalogue. No writes.

    Returns: {catalogueId, catalogueVersion, currency, amount, lines[],
              costMissing, missingItems[], blockers[], canSchedule}.
    A blocker is raised-candidate text naming the exact missing cost item so the
    UI can show e.g. "Group training participant meal cost is not set."."""
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
        blockers.insert(0, "No active CD Cost Catalogue — publish one before scheduling.")
    return {
        "catalogueId": catalogue.id if catalogue else None,
        "catalogueVersion": catalogue.version if catalogue else None,
        "currency": "UGX",
        "amount": int(cost.amount),
        "lines": [_serialize_line(l) for l in cost.lines],
        "costMissing": cost.cost_missing or catalogue is None,
        "missingItems": missing,
        "blockers": blockers,
        "canSchedule": (not cost.cost_missing) and catalogue is not None,
    }


def assert_schedulable(input: dict) -> None:
    """Raise BadRequest if the activity cannot be costed (missing rate / no
    catalogue / invalid participants). Called by every scheduling path BEFORE
    persisting, so no activity is ever created with a fake or missing cost."""
    # Check scheduled date is present
    scheduled_date_raw = input.get("scheduledDate")
    if not scheduled_date_raw:
        raise BadRequest("Scheduled date is required.")

    # Check fiscal year can be calculated
    from apps.core.fy import get_operational_fy
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(scheduled_date_raw).replace("Z", "+00:00"))
        fy = get_operational_fy(dt)
        if not fy:
            raise ValueError()
    except Exception as exc:
        raise BadRequest("Fiscal year cannot be calculated from scheduled date.") from exc

    activity_type = input.get("activityType", "")
    is_training = activity_type in {
        "training", "school_improvement_training", "cluster_training", "core_training",
    }
    is_cluster_meeting = activity_type == "cluster_meeting"
    is_training_like = is_training or is_cluster_meeting

    if is_training_like:
        expected = input.get("expectedParticipants")
        if expected is None:
            raise BadRequest("Participant count is required.")
        try:
            expected_int = int(expected)
            if expected_int <= 0:
                raise ValueError()
        except ValueError:
            raise BadRequest("Participant count must be greater than zero.")

    result = preview(input)
    if result["blockers"]:
        raise BadRequest(" · ".join(result["blockers"]))


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
def apply_to_activity(activity: Activity, input: dict, responsible_user_id: str | None = None) -> ActivityCost:
    """Price the activity from the active catalogue and PERSIST its budget lines.

    Clears any prior ActivityScheduleCostLine rows, then writes one row per cost
    item — each stamped with catalogue_id + catalogue_version + line_item_type +
    currency. Sets activity.est_cost_cents + cost_missing. Idempotent: safe on
    create, reschedule, and partner self-schedule (re-prices every time).

    `responsible_user_id` (the scheduler/owner) is forwarded to the auto-created
    advance requests so the right user confirms funding. Falls back to the
    activity's responsible_staff_id.

    Returns the ActivityCost (amount + lines) so callers can return a preview in
    the same response as the schedule."""
    fy = input.get("fy") or activity.fy
    catalogue = active_catalogue(fy)
    rates, settings_by_key = _rate_card(catalogue)
    cost = cost_for_activity(input, rates)

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
        planned_date = scheduled_date.date()
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

    ActivityScheduleCostLine.objects.filter(activity=activity).delete()
    
    # Tag Core activity budget lines
    tag = None
    if activity.activity_type == "core_visit":
        tag = "Core Partner Activity" if activity.delivery_type == "partner" else "Core Visit"
    elif activity.activity_type == "core_training":
        tag = "Core Partner Activity" if activity.delivery_type == "partner" else "Core Training"
        
    ActivityScheduleCostLine.objects.bulk_create([
        ActivityScheduleCostLine(
            activity=activity,
            cost_setting_key=line.key,
            label=line.label,
            unit_cost=0 if line.unit is None else int(line.unit),
            quantity=int(line.qty),
            amount=int(line.amount),
            cost_setting_version=(settings_by_key[line.key].version if line.key in settings_by_key else 1),
            catalogue_id=catalogue_id,
            catalogue_version=catalogue_version,
            line_item_type=_line_item_type(line.key),
            currency="UGX",
            description=f"[{tag}] {line.label}" if tag else line.label,
            total_cost=int(line.amount),
            planned_date=planned_date,
            week_start_date=week_start,
            week_end_date=week_end,
            month=month,
            quarter=quarter,
            fiscal_year=fiscal_year,
            responsible_user=responsible_user_id or activity.responsible_staff_id,
            responsible_role=None,
            school=activity.school,
            cluster=activity.cluster,
            partner_id=activity.assigned_partner_id,
            project_id=activity.project_id,
        )
        for line in cost.lines
    ])
    activity.est_cost_cents = int(cost.amount)
    activity.cost_missing = cost.cost_missing or catalogue is None
    activity.save(update_fields=[
        "est_cost_cents", "cost_missing", "planned_date", "week_start_date",
        "week_end_date", "fiscal_year", "month", "quarter", "fy", "updated_at"
    ])

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
    "assert_schedulable",
    "apply_to_activity",
]
