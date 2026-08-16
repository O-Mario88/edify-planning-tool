"""Uganda Master Priority Plan — the one controlled target cascade.

Uganda master milestone (CD confirms, publishes, locks)
    → IA distributes annual targets to Program Leads (team allocations)
    → PLs distribute once among themselves and supervised CCEOs
    → quarterly spread approved (IA approves PL's, PL approves CCEO's)
    → months phased by real capacity (working days − holidays − leave)
    → scheduled activities raise planned output; verified actuals credit
    → monthly/quarterly/annual achievement classified.

Four figures are kept separate throughout (§8 of the proposal): the assigned
target, the capacity-phased monthly target, the planned output of scheduled
activities, and the verified actual. Insufficient planning never lowers an
assigned target — it widens a gap this module reports.

Rates never sum. A percentage milestone (SSA coverage 90%) cascades as a level
commitment — every holder carries the percentage against their own portfolio —
so allocations and period targets hold the rate itself and reconciliation
checks alignment, not addition. Only counts and currency reconcile by sum.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BadRequest
from apps.core.rbac import EdifyRole
from apps.targets.fy_calendar import FinancialYearCalendarService as Cal

from .models import (
    MilestoneAllocation,
    MilestoneAllocationAmendment,
    MilestoneAllocationMethod,
    MilestonePeriodTarget,
    PriorityMilestone,
    StrategicPriority,
    StrategicPriorityStatus,
)

QUARTERS = ("Q1", "Q2", "Q3", "Q4")

# The platform's two school families (see planning/services.py and
# schools/services.py): champions are Core-family, core_trained are
# Client-family. A "Core" target reaches both members of its family.
CORE_FAMILY = ("core", "champion")
CLIENT_FAMILY = ("client", "core_trained")

# Measurement types whose targets add up across people and periods. Everything
# else (percentage, ratio, score, date, boolean, manual) is a level or
# qualitative commitment and is never summed.
SUMMABLE_MEASUREMENTS = {"count", "currency"}

# Live pre-verification work: what a schedule promises but has not yet proven.
# Returned work stays planned (it is still expected to be fixed and delivered);
# cancelled/rejected/deferred work returns its output to the planning gap by
# leaving this set. Verified work leaves it for QUALIFYING_STATES.
PLANNED_OUTPUT_STATUSES = (
    "planned",
    "scheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "submitted_to_pl",
    "returned_by_pl",
    "returned_by_ia",
    "awaiting_ia_verification",
    "rescheduled",
)

DISTRIBUTION_APPROVER_ROLES = (
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.ADMIN.value,
)

_CENT = Decimal("0.01")

# Annual cascade recommendations deliberately combine demand and delivery
# capacity.  Portfolio remains the dominant signal, while team size,
# availability and already-held priorities prevent a mechanically equal split
# from overloading a small team.  The weights describe the model, never a
# priority: every target and holder still comes from the governed database.
TEAM_RECOMMENDATION_FACTORS = (
    ("eligibleSchools", 0.60),
    ("memberCount", 0.20),
    ("availableDays", 0.15),
    ("workloadHeadroom", 0.05),
)
MEMBER_RECOMMENDATION_FACTORS = (
    ("eligibleSchools", 0.75),
    ("availableDays", 0.15),
    ("workloadHeadroom", 0.10),
)


@dataclass(frozen=True)
class _CapacityUser:
    """Shim handing a StaffProfile id to Cal.working_days' user parameter."""

    staff_profile_id: str


def _q2(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(_CENT)


def is_summable(milestone: PriorityMilestone) -> bool:
    return milestone.measurement_type in SUMMABLE_MEASUREMENTS


# ─── Achievement classification (§11) ────────────────────────────────────────


def classify_achievement(pct, *, cap_at_100: bool = False) -> dict:
    """Classify an achievement percentage into the five official bands.

    Percentage metrics that logically cannot exceed 100% (coverage) are capped
    at 100 and classified Achieved — 104% SSA coverage is a data problem, not
    an over-delivery.
    """

    if pct is None:
        return {
            "key": "not_started",
            "label": "Not started",
            "tone": "neutral",
            "pct": None,
        }
    value = float(pct)
    if cap_at_100:
        value = min(value, 100.0)
    if value < 80:
        key, label, tone = "behind", "Behind target", "danger"
    elif value < 100:
        key, label, tone = "near", "Near target", "warning"
    elif value == 100:
        key, label, tone = "achieved", "Achieved target", "success"
    elif value < 150:
        key, label, tone = "exceeded", "Exceeded target", "success"
    else:
        key, label, tone = "far_exceeded", "Far exceeded target", "info"
    return {"key": key, "label": label, "tone": tone, "pct": round(value, 1)}


# ─── Splitting primitives ────────────────────────────────────────────────────


def weighted_split(total: Decimal, weights: list[int | float]) -> list[Decimal]:
    """Largest-remainder split of ``total`` proportional to ``weights``.

    Preserves the exact total to the cent. All-zero weights fall back to an
    equal split so a fully blocked window still carries its commitment (§7:
    the target is warned about, never silently reduced).
    """

    total = _q2(total)
    if not weights:
        return []
    weight_sum = sum(weights)
    if weight_sum <= 0:
        weights = [1] * len(weights)
        weight_sum = len(weights)
    cents = int(total * 100)
    shares = [cents * w / weight_sum for w in weights]
    floors = [int(share) for share in shares]
    remainder = cents - sum(floors)
    # Distribute leftover cents to the largest fractional parts, first-come on
    # ties so the result is deterministic.
    order = sorted(
        range(len(shares)), key=lambda i: (shares[i] - floors[i]), reverse=True
    )
    for i in order[:remainder]:
        floors[i] += 1
    return [Decimal(f) / 100 for f in floors]


# ─── Portfolio-aware recommendations (§4/§5) ─────────────────────────────────


def _portfolio_counts(staff_ids: list[str]) -> dict[str, dict[str, int]]:
    """Operationally active portfolio per staff id, split Core/Client.

    Reads StaffSchoolAssignment — the same source UserScope builds a person's
    own_school_ids from — so the recommendation and the person's real
    portfolio can never disagree.
    """

    from apps.accounts.models import StaffSchoolAssignment
    from apps.schools.models import School

    assignments = StaffSchoolAssignment.objects.filter(
        staff_id__in=staff_ids
    ).values_list("staff_id", "school_id")
    school_to_staff: dict[str, list[str]] = {}
    for staff_id, school_id in assignments:
        school_to_staff.setdefault(str(school_id), []).append(str(staff_id))
    counts = {
        str(staff_id): {"total": 0, "core": 0, "client": 0} for staff_id in staff_ids
    }
    if not school_to_staff:
        return counts
    schools = School.objects.filter(
        id__in=list(school_to_staff),
        deleted_at__isnull=True,
        operational_status__in=("active", "reopened"),
    ).values_list("id", "school_type")
    for school_id, school_type in schools:
        for staff_id in school_to_staff.get(str(school_id), []):
            row = counts.get(staff_id)
            if row is None:
                continue
            row["total"] += 1
            if school_type in CORE_FAMILY:
                row["core"] += 1
            elif school_type in CLIENT_FAMILY:
                row["client"] += 1
    return counts


def program_lead_teams() -> list[dict]:
    """Active Program Leads and every delivery holder in their team.

    The PL is a working portfolio owner, not only an administrative container,
    so the team portfolio and capacity include the lead alongside supervised
    CCEOs.  ``cceo_staff_ids`` remains separate for transparent team-size
    reporting.
    """

    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    leads = list(
        StaffProfile.objects.select_related("user")
        .filter(
            deleted_at__isnull=True,
            user__status="active",
            user__roles__contains=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
        )
        .order_by("user__name")
    )
    supervisees = StaffSupervisorAssignment.objects.filter(
        supervisor_id__in=[lead.id for lead in leads],
        supervisee__deleted_at__isnull=True,
        supervisee__user__status="active",
    ).values_list("supervisor_id", "supervisee_id")
    by_lead: dict[str, list[str]] = {}
    for supervisor_id, supervisee_id in supervisees:
        by_lead.setdefault(str(supervisor_id), []).append(str(supervisee_id))
    return [
        {
            "staff": lead,
            "cceo_staff_ids": by_lead.get(str(lead.id), []),
            "member_staff_ids": [
                str(lead.id),
                *by_lead.get(str(lead.id), []),
            ],
        }
        for lead in leads
    ]


def _eligible_weight(counts: dict[str, int], milestone: PriorityMilestone) -> int:
    """Portfolio size relevant to this milestone's Core/Client composition."""

    has_core = milestone.core_target is not None
    has_client = milestone.client_target is not None
    if has_core and not has_client:
        return counts["core"]
    if has_client and not has_core:
        return counts["client"]
    return counts["total"]


def _staff_recommendation_context(
    staff_ids: list[str],
    fy: str,
    *,
    portfolio: dict[str, dict[str, int]] | None = None,
) -> dict:
    """Bulk inputs shared by every recommendation rendered in one request.

    Availability includes public holidays, organisation calendar blocks and
    approved leave through the canonical FY calendar.  Workload is counted as
    distinct live annual priority assignments; target units are intentionally
    not summed because schools, visits, participants and percentages are not
    comparable quantities.
    """

    staff_ids = list(dict.fromkeys(str(staff_id) for staff_id in staff_ids))
    portfolio = portfolio if portfolio is not None else _portfolio_counts(staff_ids)
    start, end = Cal.fy_range(fy)
    available_days = {
        staff_id: Cal.working_days(start, end, _CapacityUser(staff_profile_id=staff_id))
        for staff_id in staff_ids
    }
    live_milestones: dict[str, set[str]] = {staff_id: set() for staff_id in staff_ids}
    allocation_pairs = (
        MilestoneAllocation.objects.filter(
            allocated_to_type="employee",
            employee_id__in=staff_ids,
            milestone__priority__fy=fy,
        )
        .exclude(status__in=("rejected", "superseded"))
        .values_list("employee_id", "milestone_id")
    )
    for staff_id, milestone_id in allocation_pairs:
        live_milestones.setdefault(str(staff_id), set()).add(str(milestone_id))
    return {
        "portfolio": portfolio,
        "availableDays": available_days,
        "liveMilestones": live_milestones,
    }


def _team_live_milestones(team_ids: list[str], fy: str) -> dict[str, set[str]]:
    team_ids = list(dict.fromkeys(str(team_id) for team_id in team_ids))
    result: dict[str, set[str]] = {team_id: set() for team_id in team_ids}
    pairs = (
        MilestoneAllocation.objects.filter(
            allocated_to_type="team",
            parent__isnull=True,
            team_id__in=team_ids,
            milestone__priority__fy=fy,
        )
        .exclude(status__in=("rejected", "superseded"))
        .values_list("team_id", "milestone_id")
    )
    for team_id, milestone_id in pairs:
        result.setdefault(str(team_id), set()).add(str(milestone_id))
    return result


def _workload_count(context: dict, staff_id: str, milestone_id: str) -> int:
    held = context["liveMilestones"].get(str(staff_id), set())
    return len(held - {str(milestone_id)})


def _normalized_factor_scores(rows: list[dict], factors) -> list[float]:
    """Blend normalized factor shares into deterministic holder weights.

    A factor with no data for any holder is omitted and the remaining model
    weights are renormalized.  This avoids pretending that missing portfolio
    data is evidence while still producing an exact, explainable split.
    """

    if not rows:
        return []
    active = []
    for key, model_weight in factors:
        values = [max(0.0, float(row.get(key) or 0)) for row in rows]
        total = sum(values)
        if total > 0:
            active.append((key, model_weight, values, total))
    if not active:
        for row in rows:
            row["balanceScore"] = round(100 / len(rows), 1)
            row["activeFactors"] = []
        return [1.0] * len(rows)
    active_weight_total = sum(item[1] for item in active)
    scores = [0.0] * len(rows)
    active_labels = [item[0] for item in active]
    for _key, model_weight, values, total in active:
        effective_weight = model_weight / active_weight_total
        for index, value in enumerate(values):
            scores[index] += effective_weight * (value / total)
    score_total = sum(scores)
    if score_total <= 0:
        scores = [1.0] * len(rows)
        score_total = float(len(rows))
    for row, score in zip(rows, scores):
        row["balanceScore"] = round(score / score_total * 100, 1)
        row["activeFactors"] = active_labels
    return scores


def _portfolio_key_for(milestone: PriorityMilestone) -> str:
    has_core = milestone.core_target is not None
    has_client = milestone.client_target is not None
    if has_core and not has_client:
        return "core"
    if has_client and not has_core:
        return "client"
    return "total"


def _recommendation_scores(rows, milestone, factors, *, portfolio_key=None):
    portfolio_key = portfolio_key or _portfolio_key_for(milestone)
    for row in rows:
        row["eligibleSchools"] = row["portfolio"].get(portfolio_key, 0)
    return _normalized_factor_scores(rows, factors)


def _build_team_recommendation_rows(milestone, teams, context) -> list[dict]:
    current_id = str(milestone.id)
    team_loads = _team_live_milestones(
        [str(team["staff"].id) for team in teams], milestone.priority.fy
    )
    rows = []
    for team in teams:
        member_ids = [str(member_id) for member_id in team["member_staff_ids"]]
        totals = {"total": 0, "core": 0, "client": 0}
        for member_id in member_ids:
            member = context["portfolio"].get(
                member_id, {"total": 0, "core": 0, "client": 0}
            )
            for key in totals:
                totals[key] += member[key]
        active_priorities = sum(
            _workload_count(context, member_id, current_id) for member_id in member_ids
        ) + len(team_loads.get(str(team["staff"].id), set()) - {current_id})
        member_count = len(member_ids)
        cceo_count = len(team.get("cceo_staff_ids", []))
        rows.append(
            {
                **team,
                "portfolio": totals,
                "memberCount": member_count,
                "cceoCount": cceo_count,
                "availableDays": sum(
                    context["availableDays"].get(member_id, 0)
                    for member_id in member_ids
                ),
                "activePriorities": active_priorities,
                "workloadHeadroom": (
                    member_count / (member_count + active_priorities)
                    if member_count
                    else 0
                ),
            }
        )
    return rows


def _build_member_recommendation_rows(
    team_allocation, members, context, supervisee_ids
) -> list[dict]:
    milestone = team_allocation.milestone
    rows = []
    for staff_id in supervisee_ids:
        staff_id = str(staff_id)
        member = members.get(staff_id)
        if member is None:
            continue
        active_priorities = _workload_count(context, staff_id, str(milestone.id))
        rows.append(
            {
                "staff": member,
                "isLead": staff_id == str(team_allocation.team_id),
                "portfolio": context["portfolio"].get(
                    staff_id, {"total": 0, "core": 0, "client": 0}
                ),
                "memberCount": 1,
                "availableDays": context["availableDays"].get(staff_id, 0),
                "activePriorities": active_priorities,
                "workloadHeadroom": 1 / (1 + active_priorities),
            }
        )
    return rows


def recommend_team_allocations(milestone: PriorityMilestone) -> list[dict]:
    """IA starting point using portfolio demand and real team capacity."""

    teams = program_lead_teams()
    if not teams:
        return []
    member_ids = [m for team in teams for m in team["member_staff_ids"]]
    context = _staff_recommendation_context(member_ids, milestone.priority.fy)
    team_rows = _build_team_recommendation_rows(milestone, teams, context)

    target = _q2(milestone.target_value)
    weights = _recommendation_scores(team_rows, milestone, TEAM_RECOMMENDATION_FACTORS)
    if not is_summable(milestone):
        # Level commitment: every team carries the country rate.
        for row in team_rows:
            row["recommended"] = target
            row["recommended_core"] = (
                _q2(milestone.core_target)
                if milestone.core_target is not None
                else None
            )
            row["recommended_client"] = (
                _q2(milestone.client_target)
                if milestone.client_target is not None
                else None
            )
        return team_rows

    shares = weighted_split(target, weights)
    core_shares = (
        weighted_split(
            _q2(milestone.core_target),
            _recommendation_scores(
                team_rows,
                milestone,
                TEAM_RECOMMENDATION_FACTORS,
                portfolio_key="core",
            ),
        )
        if milestone.core_target is not None
        else [None] * len(team_rows)
    )
    client_shares = (
        weighted_split(
            _q2(milestone.client_target),
            _recommendation_scores(
                team_rows,
                milestone,
                TEAM_RECOMMENDATION_FACTORS,
                portfolio_key="client",
            ),
        )
        if milestone.client_target is not None
        else [None] * len(team_rows)
    )
    for row, share, core, client in zip(team_rows, shares, core_shares, client_shares):
        row["eligibleSchools"] = _eligible_weight(row["portfolio"], milestone)
        row["recommended"] = share
        row["recommended_core"] = core
        row["recommended_client"] = client
    return team_rows


def recommend_employee_allocations(team_allocation: MilestoneAllocation) -> list[dict]:
    """PL starting point using school demand, availability and current load."""

    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    milestone = team_allocation.milestone
    supervisee_ids = list(
        StaffSupervisorAssignment.objects.filter(
            supervisor_id=team_allocation.team_id
        ).values_list("supervisee_id", flat=True)
    )
    member_ids = [str(team_allocation.team_id), *map(str, supervisee_ids)]
    members = list(
        StaffProfile.objects.select_related("user")
        .filter(
            deleted_at__isnull=True,
            user__status="active",
            id__in=member_ids,
        )
        .order_by("user__name")
    )
    if not members:
        return []
    member_ids = [str(member.id) for member in members]
    context = _staff_recommendation_context(member_ids, milestone.priority.fy)
    member_map = {str(member.id): member for member in members}
    rows = _build_member_recommendation_rows(
        team_allocation, member_map, context, member_ids
    )
    target = _q2(team_allocation.allocated_target)
    weights = _recommendation_scores(rows, milestone, MEMBER_RECOMMENDATION_FACTORS)
    if not is_summable(milestone):
        for row in rows:
            row["recommended"] = target
            row["recommended_core"] = (
                _q2(team_allocation.core_target)
                if team_allocation.core_target is not None
                else None
            )
            row["recommended_client"] = (
                _q2(team_allocation.client_target)
                if team_allocation.client_target is not None
                else None
            )
        return rows
    shares = weighted_split(
        target,
        weights,
    )
    core_shares = (
        weighted_split(
            _q2(team_allocation.core_target),
            _recommendation_scores(
                rows,
                milestone,
                MEMBER_RECOMMENDATION_FACTORS,
                portfolio_key="core",
            ),
        )
        if team_allocation.core_target is not None
        else [None] * len(rows)
    )
    client_shares = (
        weighted_split(
            _q2(team_allocation.client_target),
            _recommendation_scores(
                rows,
                milestone,
                MEMBER_RECOMMENDATION_FACTORS,
                portfolio_key="client",
            ),
        )
        if team_allocation.client_target is not None
        else [None] * len(rows)
    )
    for row, share, core, client in zip(rows, shares, core_shares, client_shares):
        row["eligibleSchools"] = _eligible_weight(row["portfolio"], milestone)
        row["recommended"] = share
        row["recommended_core"] = core
        row["recommended_client"] = client
    return rows


# ─── Reconciliation (§4) ─────────────────────────────────────────────────────


def _live_allocations(milestone: PriorityMilestone):
    return milestone.allocations.exclude(status__in=("rejected", "superseded"))


def reconcile_team_level(milestone: PriorityMilestone) -> dict:
    """Sum of PL team targets = Uganda distributable target (and per-column
    Core/Client), for summable measures. Rates check alignment instead."""

    rows = list(
        _live_allocations(milestone)
        .filter(allocated_to_type="team", parent__isnull=True)
        .select_related("employee__user")
    )
    return _reconcile_rows(
        milestone,
        rows,
        expected=_q2(milestone.target_value),
        expected_core=(
            _q2(milestone.core_target) if milestone.core_target is not None else None
        ),
        expected_client=(
            _q2(milestone.client_target)
            if milestone.client_target is not None
            else None
        ),
        level_label="Program Lead",
    )


def reconcile_employee_level(team_allocation: MilestoneAllocation) -> dict:
    """Sum of PL + CCEO targets = the PL's approved IA team target."""

    rows = list(
        team_allocation.children.exclude(
            status__in=("rejected", "superseded")
        ).select_related("employee__user")
    )
    return _reconcile_rows(
        team_allocation.milestone,
        rows,
        expected=_q2(team_allocation.allocated_target),
        expected_core=(
            _q2(team_allocation.core_target)
            if team_allocation.core_target is not None
            else None
        ),
        expected_client=(
            _q2(team_allocation.client_target)
            if team_allocation.client_target is not None
            else None
        ),
        level_label="team member",
    )


def _reconcile_rows(
    milestone, rows, *, expected, expected_core, expected_client, level_label
) -> dict:
    summable = is_summable(milestone)
    errors: list[str] = []
    unallocated_core = None
    unallocated_client = None
    if summable:
        allocated = sum((_q2(row.allocated_target) for row in rows), Decimal("0"))
        unallocated = expected - allocated
        if unallocated > 0:
            errors.append(
                f"{unallocated} of the {level_label} balance is not yet allocated."
            )
        elif unallocated < 0:
            errors.append(
                f"Over-allocated by {-unallocated} against the approved total."
            )
        column_remaining = {}
        for label, column_expected, attribute in (
            ("Core", expected_core, "core_target"),
            ("Client", expected_client, "client_target"),
        ):
            if column_expected is None:
                continue
            column_allocated = sum(
                (_q2(getattr(row, attribute)) for row in rows), Decimal("0")
            )
            # Server truth for the workspace's live balance display — the
            # remaining column figures are never recomputed client-side.
            column_remaining[label] = column_expected - column_allocated
            if column_allocated != column_expected:
                errors.append(
                    f"{label} allocations total {column_allocated}, "
                    f"expected {column_expected}."
                )
        unallocated_core = column_remaining.get("Core")
        unallocated_client = column_remaining.get("Client")
    else:
        allocated = None
        unallocated = None
        for row in rows:
            if _q2(row.allocated_target) != expected:
                errors.append(
                    f"{_display_name(row)} carries {_q2(row.allocated_target)}% "
                    f"against the {expected}% commitment — rates cascade as the "
                    "same level, they are never summed."
                )
    return {
        "rows": rows,
        "expected": expected,
        "expected_core": expected_core,
        "expected_client": expected_client,
        "allocated": allocated,
        "unallocated": unallocated,
        "unallocated_core": unallocated_core,
        "unallocated_client": unallocated_client,
        "summable": summable,
        "errors": errors,
        "balanced": not errors and bool(rows),
    }


def _display_name(allocation: MilestoneAllocation) -> str:
    if allocation.employee_id and getattr(allocation.employee, "user", None):
        return allocation.employee.user.name
    if allocation.allocated_to_type == "team" and allocation.team_id:
        from apps.accounts.models import StaffProfile

        lead = (
            StaffProfile.objects.select_related("user")
            .filter(id=allocation.team_id)
            .first()
        )
        if lead and lead.user:
            return f"{lead.user.name} (team)"
    if allocation.project_id:
        return f"Project {allocation.project_id}"
    return allocation.allocated_to_type


# ─── Quarterly spread + monthly phasing (§6, §7) ─────────────────────────────


def _phasing_user(allocation: MilestoneAllocation) -> _CapacityUser | None:
    if allocation.allocated_to_type == "employee" and allocation.employee_id:
        return _CapacityUser(staff_profile_id=str(allocation.employee_id))
    return None


def recommend_quarters(allocation: MilestoneAllocation) -> dict[str, Decimal]:
    """Working-day-proportional quarterly spread of the annual target.

    Uses the same capacity source as monthly phasing (weekdays minus public
    holidays minus the holder's approved leave), so terms, holidays and known
    leave shape the recommendation. Rates carry the level in every quarter.
    """

    milestone = allocation.milestone
    fy = milestone.priority.fy
    target = _q2(allocation.allocated_target)
    if not is_summable(milestone):
        return {quarter: target for quarter in QUARTERS}
    user = _phasing_user(allocation)
    weights = []
    for quarter in QUARTERS:
        start, end = Cal.quarter_range(fy, quarter)
        weights.append(Cal.working_days(start, end, user))
    shares = weighted_split(target, weights)
    return dict(zip(QUARTERS, shares))


def rephase_staff_allocations(staff_id: str, fys: list[str]) -> int:
    """§7 automatic adjustment: re-phase a person's future monthly targets
    when their delivery capacity changes (approved leave, blocked days).

    Elapsed months and verified achievements never move; quarter and annual
    totals are preserved — only the remaining months redistribute. Returns the
    number of allocations re-phased.
    """

    allocations = list(
        MilestoneAllocation.objects.filter(
            allocated_to_type="employee",
            employee_id=staff_id,
            status="approved",
            milestone__priority__fy__in=fys,
        ).select_related("milestone__priority", "milestone__metric_definition")
    )
    for allocation in allocations:
        phase_allocation_periods(allocation)
    return len(allocations)


def quarter_prefill(allocation: MilestoneAllocation) -> dict[str, str]:
    """The quarterly-spread form's starting values: the approved/entered
    distribution where one exists, the working-day recommendation otherwise."""

    entered = allocation.quarter_distribution or {}
    recommended = recommend_quarters(allocation)
    return {
        quarter: str(entered.get(quarter) or recommended[quarter])
        for quarter in QUARTERS
    }


def validate_quarters(
    allocation: MilestoneAllocation, quarters: dict
) -> dict[str, Decimal]:
    parsed: dict[str, Decimal] = {}
    for quarter in QUARTERS:
        raw = quarters.get(quarter)
        if raw in (None, ""):
            raise BadRequest(f"{quarter} is required — all four quarters are set.")
        try:
            value = _q2(raw)
        except Exception as exc:  # noqa: BLE001 — surface as one input error
            raise BadRequest(f"{quarter} must be numeric.") from exc
        if value < 0:
            raise BadRequest(f"{quarter} cannot be negative.")
        parsed[quarter] = value
    if is_summable(allocation.milestone):
        total = sum(parsed.values(), Decimal("0"))
        expected = _q2(allocation.allocated_target)
        if total != expected:
            raise BadRequest(
                f"Q1+Q2+Q3+Q4 must equal the annual target: entered {total}, "
                f"annual is {expected}."
            )
    return parsed


def phase_allocation_periods(
    allocation: MilestoneAllocation,
    quarters: dict[str, Decimal] | None = None,
    *,
    preserve_elapsed: bool = True,
    today: date | None = None,
) -> list[str]:
    """Write the quarter and month period-target rows for an allocation.

    Months inside each quarter are split by the holder's real working-day
    capacity. Elapsed months keep their committed value (verified history
    never moves); only remaining months absorb changes, and the quarter total
    is preserved. Returns capacity warnings — a target that cannot fit in the
    remaining capacity is warned about, never reduced (§7).
    """

    milestone = allocation.milestone
    fy = milestone.priority.fy
    today = today or Cal.current()["today"]
    summable = is_summable(milestone)
    quarters = quarters or (
        {
            quarter: _q2(value)
            for quarter, value in (allocation.quarter_distribution or {}).items()
        }
        if (allocation.quarter_distribution or {})
        else recommend_quarters(allocation)
    )
    user = _phasing_user(allocation)
    warnings: list[str] = []
    existing = {
        (row.period_type, row.period_start): row
        for row in allocation.period_targets.all()
    }

    def _write(period_type, start, end_exclusive, planned):
        MilestonePeriodTarget.objects.update_or_create(
            milestone=milestone,
            allocation=allocation,
            period_type=period_type,
            period_start=start,
            defaults={
                "scope": allocation.allocated_to_type,
                "country_id": allocation.country_id,
                "team_id": allocation.team_id,
                "employee": allocation.employee,
                "period_end": end_exclusive - timedelta(days=1),
                "planned_value": planned,
                "actual_source": (
                    milestone.metric_definition.canonical_service
                    if milestone.metric_definition_id
                    else ""
                ),
            },
        )

    for quarter in QUARTERS:
        quarter_target = _q2(quarters.get(quarter, 0))
        q_start, q_end = Cal.quarter_range(fy, quarter)
        _write("quarter", q_start, q_end, quarter_target)
        months = Cal.months_of_quarter(quarter)
        month_ranges = [Cal.month_range(fy, month) for month in months]
        if not summable:
            for start, end in month_ranges:
                _write("month", start, end, quarter_target)
            continue
        locked: dict[int, Decimal] = {}
        if preserve_elapsed:
            for index, (start, end) in enumerate(month_ranges):
                row = existing.get(("month", start))
                if row is not None and end <= today:
                    locked[index] = _q2(row.planned_value)
        remaining_target = quarter_target - sum(locked.values(), Decimal("0"))
        open_indexes = [i for i in range(len(months)) if i not in locked]
        if remaining_target < 0:
            warnings.append(
                f"{quarter}: elapsed months already carry "
                f"{sum(locked.values(), Decimal('0'))} against a quarter target "
                f"of {quarter_target}; remaining months hold 0."
            )
            remaining_target = Decimal("0")
        if open_indexes:
            weights = [
                Cal.working_days(month_ranges[i][0], month_ranges[i][1], user)
                for i in open_indexes
            ]
            if remaining_target > 0 and sum(weights) == 0:
                warnings.append(
                    f"{quarter}: {remaining_target} cannot fit in the remaining "
                    "capacity (no available working days) — the commitment is "
                    "unchanged; plan recovery or reforecast."
                )
            shares = weighted_split(remaining_target, weights)
            planned_by_index = dict(zip(open_indexes, shares))
        else:
            planned_by_index = {}
            if remaining_target > 0:
                warnings.append(
                    f"{quarter}: {remaining_target} remains but every month has "
                    "elapsed — the commitment is unchanged; recovery planning "
                    "or a reforecast is required."
                )
        for index, (start, end) in enumerate(month_ranges):
            planned = locked.get(index, planned_by_index.get(index, Decimal("0")))
            _write("month", start, end, planned)
    return warnings


@transaction.atomic
def approve_quarters(
    allocation: MilestoneAllocation, *, quarters: dict, principal
) -> list[str]:
    """Approve the quarterly spread (§6). IA (or CD/Admin) approves a PL team
    spread; the supervising PL (or CD/IA/Admin) approves a CCEO spread."""

    allocation = MilestoneAllocation.objects.select_for_update(of=("self",)).get(
        pk=allocation.pk
    )
    if allocation.status != "approved":
        raise BadRequest("Approve the annual allocation before its quarterly spread.")
    _assert_may_approve_spread(allocation, principal)
    parsed = validate_quarters(allocation, quarters)
    allocation.quarter_distribution = {
        quarter: str(value) for quarter, value in parsed.items()
    }
    allocation.quarter_status = "approved"
    allocation.quarter_approved_by = _actor_id(principal)
    allocation.quarter_approved_at = timezone.now()
    allocation.save(
        update_fields=[
            "quarter_distribution",
            "quarter_status",
            "quarter_approved_by",
            "quarter_approved_at",
            "updated_at",
        ]
    )
    warnings = phase_allocation_periods(allocation, parsed)
    from .milestone_progress import refresh_period_targets

    refresh_period_targets(allocation.milestone_id)
    # The spread is the figure the holder plans against — they hear about
    # its approval like they hear about the annual one (audit finding: the
    # annual approval notified, this didn't).
    holder = allocation.employee_id or allocation.team_id
    if holder:
        _notify_allocation_holders(
            allocation.milestone,
            [str(holder)],
            body=(
                f"Your FY{allocation.milestone.priority.fy} quarterly spread "
                f"for “{allocation.milestone.title}” is approved — monthly "
                "targets are phased to your calendar."
            ),
        )
    _audit(
        "hr.milestone_allocation_quarters_approved",
        allocation,
        principal,
        {"quarters": allocation.quarter_distribution, "warnings": warnings},
    )
    return warnings


def _assert_may_approve_spread(allocation: MilestoneAllocation, principal) -> None:
    role = getattr(principal, "active_role", "")
    if allocation.allocated_to_type == "team":
        if role not in DISTRIBUTION_APPROVER_ROLES:
            raise BadRequest(
                "The Program Lead quarterly spread is approved by Impact "
                "Assessment or the Country Director."
            )
        return
    if allocation.allocated_to_type == "employee":
        if role in DISTRIBUTION_APPROVER_ROLES:
            return
        if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            parent_team = allocation.parent.team_id if allocation.parent_id else None
            if parent_team and str(parent_team) == str(
                getattr(principal, "staff_profile_id", "")
            ):
                return
            from apps.accounts.models import StaffSupervisorAssignment

            if StaffSupervisorAssignment.objects.filter(
                supervisor_id=getattr(principal, "staff_profile_id", None),
                supervisee_id=allocation.employee_id,
            ).exists():
                return
        raise BadRequest(
            "A CCEO quarterly spread is approved by their supervising " "Program Lead."
        )


# ─── Amendments and reforecasts (§4, §6, §14) ────────────────────────────────


@transaction.atomic
def request_amendment(
    allocation: MilestoneAllocation,
    *,
    kind: str,
    reason: str,
    new_target=None,
    new_quarters: dict | None = None,
    principal,
) -> MilestoneAllocationAmendment:
    reason = (reason or "").strip()
    if not reason:
        raise BadRequest(
            "An amendment requires a reason — silent edits are the "
            "thing this workflow exists to prevent."
        )
    if allocation.status != "approved":
        raise BadRequest(
            "Only an approved (locked) allocation is amended; a "
            "draft is simply edited before approval."
        )
    if kind == MilestoneAllocationAmendment.KIND_AMENDMENT:
        try:
            new_value = _q2(new_target)
        except Exception as exc:  # noqa: BLE001
            raise BadRequest("The new annual target must be numeric.") from exc
        if new_value <= 0:
            raise BadRequest("The new annual target must be greater than zero.")
        return MilestoneAllocationAmendment.objects.create(
            allocation=allocation,
            kind=kind,
            reason=reason,
            previous_target=allocation.allocated_target,
            new_target=new_value,
            previous_quarters=allocation.quarter_distribution or {},
            requested_by=_actor_id(principal),
        )
    if kind == MilestoneAllocationAmendment.KIND_REFORECAST:
        parsed = validate_quarters(allocation, new_quarters or {})
        _assert_reforecast_moves_future_only(allocation, parsed)
        return MilestoneAllocationAmendment.objects.create(
            allocation=allocation,
            kind=kind,
            reason=reason,
            previous_target=allocation.allocated_target,
            new_target=allocation.allocated_target,
            previous_quarters=allocation.quarter_distribution or {},
            new_quarters={q: str(v) for q, v in parsed.items()},
            requested_by=_actor_id(principal),
        )
    raise BadRequest("Unknown amendment kind.")


def _assert_reforecast_moves_future_only(allocation, parsed) -> None:
    """A reforecast moves remaining targets; delivered quarters stay put."""

    fy = allocation.milestone.priority.fy
    today = Cal.current()["today"]
    current = allocation.quarter_distribution or {}
    for quarter in QUARTERS:
        _, q_end = Cal.quarter_range(fy, quarter)
        if q_end <= today and quarter in current:
            if parsed[quarter] != _q2(current[quarter]):
                raise BadRequest(
                    f"{quarter} has already closed — a reforecast may only move "
                    "targets between remaining quarters."
                )


@transaction.atomic
def approve_amendment(
    amendment: MilestoneAllocationAmendment, *, principal
) -> MilestoneAllocationAmendment:
    amendment = MilestoneAllocationAmendment.objects.select_for_update().get(
        pk=amendment.pk
    )
    if amendment.status != "requested":
        return amendment
    allocation = MilestoneAllocation.objects.select_for_update(of=("self",)).get(
        pk=amendment.allocation_id
    )
    _assert_may_approve_spread(allocation, principal)
    if amendment.kind == MilestoneAllocationAmendment.KIND_AMENDMENT:
        allocation.allocated_target = amendment.new_target
        allocation.version += 1
        # The old quarterly spread reconciled against the old annual figure;
        # it goes back through quarterly approval against the new one.
        allocation.quarter_status = "draft"
        allocation.save(
            update_fields=[
                "allocated_target",
                "version",
                "quarter_status",
                "updated_at",
            ]
        )
        warnings = phase_allocation_periods(allocation, None)
    else:
        parsed = {q: _q2(v) for q, v in (amendment.new_quarters or {}).items()}
        _assert_reforecast_moves_future_only(allocation, parsed)
        allocation.quarter_distribution = {q: str(v) for q, v in parsed.items()}
        allocation.version += 1
        allocation.save(update_fields=["quarter_distribution", "version", "updated_at"])
        warnings = phase_allocation_periods(allocation, parsed)
    amendment.status = "approved"
    amendment.approved_by = _actor_id(principal)
    amendment.approved_at = timezone.now()
    amendment.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    from .milestone_progress import refresh_period_targets

    refresh_period_targets(allocation.milestone_id)
    _audit(
        "hr.milestone_allocation_amended",
        allocation,
        principal,
        {
            "kind": amendment.kind,
            "previousTarget": str(amendment.previous_target),
            "newTarget": str(amendment.new_target),
            "warnings": warnings,
        },
    )
    return amendment


# ─── Planned output (§8) ─────────────────────────────────────────────────────


def school_type_family(value: str) -> tuple[str, ...]:
    """Expand a rule's school-type constraint to its platform family."""

    if value == "core":
        return CORE_FAMILY
    if value == "client":
        return CLIENT_FAMILY
    return (value,)


def _rule_activity_query(rule) -> Q:
    query = Q(catalogue_item_id=rule.catalogue_item_id)
    if rule.project_id:
        query &= Q(project_id=rule.project_id)
    if rule.required_executor_type:
        query &= Q(delivery_type=rule.required_executor_type)
    if rule.required_delivery_method:
        query &= Q(delivery_method_snapshot=rule.required_delivery_method)
    if rule.school_type:
        query &= Q(school__school_type__in=school_type_family(rule.school_type))
    if rule.target_intervention:
        query &= Q(focus_intervention=rule.target_intervention)
    return query


def planned_output(
    allocation: MilestoneAllocation,
    *,
    start: date | None = None,
    end: date | None = None,
) -> Decimal:
    """Expected delivery from live scheduled activities — the third of the
    four figures. Rises when an activity is scheduled, returns to the planning
    gap when it is cancelled, moves with a reschedule. Never touches the
    assigned target."""

    from apps.activities.models import Activity

    milestone = allocation.milestone
    rules = [rule for rule in milestone.activity_rules.all() if rule.active]
    if not rules:
        return Decimal("0")
    rule_query = Q()
    for rule in rules:
        rule_query |= _rule_activity_query(rule)
    activities = Activity.objects.filter(
        rule_query,
        status__in=PLANNED_OUTPUT_STATUSES,
        fy=milestone.priority.fy,
    )
    if start is not None:
        activities = activities.filter(planned_date__gte=start)
    if end is not None:
        activities = activities.filter(planned_date__lte=end)
    activities = _scope_activities(activities, allocation)
    bases = {rule.counting_basis for rule in rules}
    if bases & {
        "UNIQUE_SCHOOLS_SUPPORTED",
        "UNIQUE_SCHOOLS_TRAINED",
        "PERCENT_OF_ELIGIBLE_SCHOOLS",
    }:
        value = (
            activities.exclude(school__isnull=True)
            .values("school_id")
            .distinct()
            .count()
        )
    elif bases & {"UNIQUE_PARTICIPANTS", "TEACHERS_TRAINED", "SCHOOL_LEADERS_TRAINED"}:
        value = sum(
            expected or 0
            for expected in activities.values_list("expected_participants", flat=True)
        )
    else:
        value = activities.count()
    return Decimal(value or 0)


def _scope_activities(activities, allocation: MilestoneAllocation):
    if allocation.allocated_to_type == "employee" and allocation.employee_id:
        owner_ids = {
            str(allocation.employee_id),
            str(getattr(allocation.employee, "user_id", "") or ""),
        } - {""}
        return activities.filter(
            Q(responsible_staff_id__in=owner_ids)
            | Q(monitored_by_staff_id__in=owner_ids)
        )
    if allocation.allocated_to_type == "team" and allocation.team_id:
        from apps.accounts.models import StaffSupervisorAssignment

        member_ids = list(
            StaffSupervisorAssignment.objects.filter(
                supervisor_id=allocation.team_id
            ).values_list("supervisee_id", flat=True)
        )
        return activities.filter(
            Q(responsible_staff_id__in=member_ids)
            | Q(monitored_by_staff_id__in=member_ids)
        )
    if allocation.allocated_to_type == "project" and allocation.project_id:
        return activities.filter(project_id=allocation.project_id)
    return activities


def participant_guidance_for(catalogue_item_id: str) -> int | None:
    """Participants-per-school guidance for an activity, from the published
    Uganda master (§9). None when no published, active milestone carries one —
    callers keep their own defaults."""

    from apps.core.request_cache import memoize

    def _compute() -> int | None:
        value = (
            PriorityMilestone.objects.filter(
                activity_rules__catalogue_item_id=catalogue_item_id,
                activity_rules__active=True,
                active=True,
                participants_per_school__isnull=False,
                priority__status=StrategicPriorityStatus.PUBLISHED,
                priority__level="country",
            )
            .order_by("-participants_per_school")
            .values_list("participants_per_school", flat=True)
            .first()
        )
        return int(value) if value else None

    return memoize(("uganda_pps", str(catalogue_item_id)), _compute)


# ─── The Uganda master (§2, §14) ─────────────────────────────────────────────


def uganda_master_priorities(fy: str, *, country_id: str = "Uganda"):
    return (
        StrategicPriority.objects.filter(
            fy=fy,
            level="country",
            country_id=country_id,
            cycle__isnull=False,
        )
        .prefetch_related(
            "milestones__metric_definition",
            "milestones__activity_rules__catalogue_item",
        )
        .order_by("sequence", "title")
    )


@transaction.atomic
def confirm_milestone(milestone: PriorityMilestone, *, data: dict, principal):
    """CD confirms one source figure: adjusts the number, the Core/Client
    split, the participants guidance or the allocation method, and clears the
    needs-confirmation flag. Blocked once the master is published — after
    that, changes are amendments."""

    _assert_master_author(principal)
    milestone = PriorityMilestone.objects.select_for_update().get(pk=milestone.pk)
    if milestone.priority.status == StrategicPriorityStatus.PUBLISHED:
        raise BadRequest(
            "This master is published and locked — changes go through a formal "
            "amendment."
        )

    def _decimal_or_none(key):
        raw = data.get(key)
        if raw in (None, ""):
            return None
        try:
            return _q2(raw)
        except Exception as exc:  # noqa: BLE001
            raise BadRequest(f"{key} must be numeric.") from exc

    if "targetValue" in data:
        milestone.target_value = _decimal_or_none("targetValue")
    if "coreTarget" in data:
        milestone.core_target = _decimal_or_none("coreTarget")
    if "clientTarget" in data:
        milestone.client_target = _decimal_or_none("clientTarget")
    if "participantsPerSchool" in data:
        raw = data.get("participantsPerSchool")
        milestone.participants_per_school = int(raw) if raw not in (None, "") else None
    if data.get("allocationMethod"):
        method = data["allocationMethod"]
        if method not in MilestoneAllocationMethod.values:
            raise BadRequest("Unknown allocation method.")
        milestone.allocation_method = method
    if "confirmationNote" in data:
        milestone.confirmation_note = (data.get("confirmationNote") or "").strip()
    milestone.needs_confirmation = False
    scoreable = milestone.allocation_method != MilestoneAllocationMethod.NON_SCOREABLE
    if scoreable and milestone.target_value is None:
        raise BadRequest(
            "A scoreable milestone needs a confirmed target — or mark it "
            "non-scoreable to preserve it without scoring."
        )
    milestone.version += 1
    milestone.save()
    _audit(
        "hr.uganda_master_milestone_confirmed",
        milestone,
        principal,
        {
            "target": str(milestone.target_value),
            "method": milestone.allocation_method,
        },
    )
    return milestone


@transaction.atomic
def publish_uganda_master(fy: str, *, principal, country_id: str = "Uganda"):
    """CD approves and locks the Uganda master (§14 steps 4–5).

    Requires every scoreable milestone to be confirmed. Publication activates
    the scoreable milestones (they become allocatable) and publishes the
    country priorities; from then on figures change only by amendment.
    """

    _assert_master_author(principal)
    priorities = list(
        StrategicPriority.objects.select_for_update().filter(
            fy=fy, level="country", country_id=country_id, cycle__isnull=False
        )
    )
    if not priorities:
        raise BadRequest("There is no Uganda master to publish for this year.")
    milestones = PriorityMilestone.objects.select_for_update().filter(
        priority__in=priorities
    )
    unconfirmed = [
        milestone.title
        for milestone in milestones
        if milestone.needs_confirmation
        and milestone.allocation_method != MilestoneAllocationMethod.NON_SCOREABLE
    ]
    if unconfirmed:
        raise BadRequest(
            "Confirm these source figures before publishing: "
            + "; ".join(sorted(unconfirmed)[:8])
            + ("…" if len(unconfirmed) > 8 else "")
        )
    now = timezone.now()
    activated = 0
    for milestone in milestones:
        scoreable = (
            milestone.allocation_method != MilestoneAllocationMethod.NON_SCOREABLE
            and milestone.target_value is not None
            and milestone.metric_definition_id is not None
        )
        if scoreable:
            milestone.requires_definition = False
            milestone.definition_status = "approved"
            milestone.active = True
        else:
            milestone.active = False
        milestone.save(
            update_fields=[
                "requires_definition",
                "definition_status",
                "active",
                "updated_at",
            ]
        )
        activated += int(scoreable)
    for priority in priorities:
        priority.status = StrategicPriorityStatus.PUBLISHED
        priority.published_at = now
        priority.published_by_id = getattr(principal, "id", None)
        priority.save(
            update_fields=["status", "published_at", "published_by", "updated_at"]
        )
    _audit(
        "hr.uganda_master_published",
        priorities[0],
        principal,
        {"fy": fy, "activatedMilestones": activated},
    )
    return activated


def _assert_master_author(principal) -> None:
    role = getattr(principal, "active_role", "")
    if role not in (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.ADMIN.value,
    ):
        raise BadRequest(
            "The Uganda master is owned and confirmed by the Country Director."
        )


# ─── Distribution approval (§4: reconciled, then locked) ─────────────────────


@transaction.atomic
def approve_team_distribution(milestone: PriorityMilestone, *, principal) -> int:
    """IA completes the annual IA→PL distribution for one milestone. Refuses
    while the balance is missing or over-allocated; approval locks every row
    at once — one annual distribution, not a rolling edit."""

    role = getattr(principal, "active_role", "")
    if role not in DISTRIBUTION_APPROVER_ROLES:
        raise BadRequest("Impact Assessment distributes the Uganda annual targets.")
    if milestone.needs_confirmation:
        raise BadRequest("This figure is awaiting CD confirmation.")
    state = reconcile_team_level(milestone)
    if not state["rows"]:
        raise BadRequest("Nothing to approve — no Program Lead allocations yet.")
    if state["errors"]:
        raise BadRequest("Reconciliation failed: " + " ".join(state["errors"]))
    from .milestone_allocations import approve_allocation

    approved = 0
    for allocation in state["rows"]:
        if allocation.status != "approved":
            approve_allocation(allocation, principal=principal)
            approved += 1
    _notify_allocation_holders(
        milestone,
        [str(row.team_id) for row in state["rows"] if row.team_id],
        body=(
            f"Your team's FY{milestone.priority.fy} annual target for "
            f"“{milestone.title}” is approved. Distribute only this received "
            "figure once across yourself and your supervised CCEOs."
        ),
    )
    _audit(
        "hr.uganda_master_team_distribution_approved",
        milestone,
        principal,
        {"allocations": len(state["rows"]), "newlyApproved": approved},
    )
    return approved


@transaction.atomic
def approve_employee_distribution(
    team_allocation: MilestoneAllocation, *, principal
) -> int:
    """The PL allocates their received target within their delivery team."""

    role = getattr(principal, "active_role", "")
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        if str(team_allocation.team_id) != str(
            getattr(principal, "staff_profile_id", "")
        ):
            raise BadRequest("Program Leads distribute only their own team target.")
    elif role not in DISTRIBUTION_APPROVER_ROLES:
        raise BadRequest("Only the team's Program Lead completes this distribution.")
    if team_allocation.status != "approved":
        raise BadRequest("The IA→PL allocation must be approved first.")
    state = reconcile_employee_level(team_allocation)
    if not state["rows"]:
        raise BadRequest("Nothing to approve — no team-member allocations yet.")
    if state["errors"]:
        raise BadRequest("Reconciliation failed: " + " ".join(state["errors"]))
    from .milestone_allocations import approve_allocation

    approved = 0
    for allocation in state["rows"]:
        if allocation.status != "approved":
            approve_allocation(allocation, principal=principal)
            approved += 1
    milestone = team_allocation.milestone
    _notify_allocation_holders(
        milestone,
        [str(row.employee_id) for row in state["rows"] if row.employee_id],
        body=(
            f"Your FY{milestone.priority.fy} target for “{milestone.title}” is "
            "approved and now appears under My Priorities. Plan activities "
            "against your monthly and quarterly targets."
        ),
    )
    _audit(
        "hr.uganda_master_employee_distribution_approved",
        team_allocation,
        principal,
        {"allocations": len(state["rows"]), "newlyApproved": approved},
    )
    return approved


def _notify_allocation_holders(milestone, staff_ids: list[str], *, body: str) -> None:
    """One workflow notification per new target-holder; idempotent by design
    (the notification service re-fires in place rather than stacking)."""

    if not staff_ids:
        return
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type="target_allocation.approved",
            category="performance",
            priority="high",
            title="Annual target allocated",
            body=body,
            context_type="PriorityMilestone",
            context_id=str(milestone.id),
            recipients=staff_ids,
        )
    except Exception:  # noqa: BLE001 — notification must never break approval
        pass


# ─── Workspace payloads (§12, §13) ───────────────────────────────────────────


def _milestone_progress(milestone: PriorityMilestone, approved_rows) -> dict | None:
    """Country monitoring rollup from approved allocations' period rows.

    Counts sum; rates are tracked per holder (their coverage denominators
    differ), so a rate milestone reports holder count instead of a fabricated
    country percentage.
    """

    if not approved_rows:
        return None
    if not is_summable(milestone):
        achieved = sum(
            1
            for allocation in approved_rows
            for row in allocation.period_targets.all()
            if row.period_type == "quarter" and row.achievement_percentage >= 100
        )
        return {
            "summable": False,
            "holders": len(approved_rows),
            "quartersAchieved": achieved,
        }
    plan = Decimal("0")
    actual = Decimal("0")
    for allocation in approved_rows:
        for row in allocation.period_targets.all():
            if row.period_type == "month":
                plan += row.planned_value
                actual += row.actual_value
    pct = round(float(actual / plan * 100), 1) if plan else None
    return {
        "summable": True,
        "plan": plan,
        "actual": actual,
        "pct": pct,
        "classification": classify_achievement(pct, cap_at_100=milestone.cap_at_100),
    }


def country_distribution_workspace(fy: str, *, country_id: str = "Uganda") -> dict:
    """Everything the IA Uganda Target Distribution workspace shows (§12)."""

    priorities = list(uganda_master_priorities(fy, country_id=country_id))
    teams = program_lead_teams()
    member_ids = [m for team in teams for m in team["member_staff_ids"]]
    portfolio = _portfolio_counts(member_ids) if member_ids else {}
    milestone_ids = [
        milestone.id
        for priority in priorities
        for milestone in priority.milestones.all()
    ]
    allocations_by_milestone: dict[str, list[MilestoneAllocation]] = {}
    for allocation in (
        MilestoneAllocation.objects.filter(milestone_id__in=milestone_ids)
        .exclude(status__in=("rejected", "superseded"))
        .select_related("employee__user", "project")
        .prefetch_related("period_targets", "amendments")
    ):
        allocations_by_milestone.setdefault(str(allocation.milestone_id), []).append(
            allocation
        )
    groups = []
    latest_updated = max(
        (priority.updated_at for priority in priorities),
        default=None,
    )
    kpis = {
        "milestones": 0,
        "priorityGroups": len(priorities),
        "needsConfirmation": 0,
        "fieldCascade": 0,
        "balanced": 0,
        "locked": 0,
        "reconciliationErrors": 0,
        "quartersPending": 0,
        # These portfolio totals intentionally include only additive measures.
        # Percentages, dates and qualitative commitments cannot be summed
        # without fabricating a country number.
        "totalTarget": Decimal("0"),
        "distributableTarget": Decimal("0"),
        "countryProjectTarget": Decimal("0"),
        "coreTarget": Decimal("0"),
        "clientTarget": Decimal("0"),
        "allocatedTarget": Decimal("0"),
        "remainingTarget": Decimal("0"),
        "openFieldMilestones": 0,
    }
    for priority in priorities:
        rows = []
        for milestone in priority.milestones.all():
            if latest_updated is None or milestone.updated_at > latest_updated:
                latest_updated = milestone.updated_at
            milestone_allocations = allocations_by_milestone.get(str(milestone.id), [])
            team_rows = [
                allocation
                for allocation in milestone_allocations
                if allocation.allocated_to_type == "team"
                and allocation.parent_id is None
            ]
            other_rows = [
                allocation
                for allocation in milestone_allocations
                if allocation.allocated_to_type in ("project", "country")
            ]
            state = None
            recommendations = []
            method = milestone.allocation_method
            if method == MilestoneAllocationMethod.FIELD_CASCADE:
                state = _reconcile_rows(
                    milestone,
                    team_rows,
                    expected=_q2(milestone.target_value),
                    expected_core=(
                        _q2(milestone.core_target)
                        if milestone.core_target is not None
                        else None
                    ),
                    expected_client=(
                        _q2(milestone.client_target)
                        if milestone.client_target is not None
                        else None
                    ),
                    level_label="Program Lead",
                )
                recommendations = _team_recommendation_rows(
                    milestone, teams, portfolio, team_rows
                )
            catalogue_names = []
            for rule in milestone.activity_rules.all():
                item = getattr(rule, "catalogue_item", None)
                name = getattr(item, "display_name", "") if item else ""
                if name and name not in catalogue_names:
                    catalogue_names.append(name)
            activity_display = ", ".join(catalogue_names) or milestone.title
            kpis["milestones"] += 1
            if milestone.needs_confirmation:
                kpis["needsConfirmation"] += 1
            if method == MilestoneAllocationMethod.FIELD_CASCADE:
                kpis["fieldCascade"] += 1
                if state and state["balanced"]:
                    kpis["balanced"] += 1
                else:
                    kpis["openFieldMilestones"] += 1
                if state:
                    kpis["reconciliationErrors"] += len(state["errors"])
            if is_summable(milestone) and milestone.target_value is not None:
                target = _q2(milestone.target_value)
                kpis["totalTarget"] += target
                kpis["coreTarget"] += _q2(milestone.core_target)
                kpis["clientTarget"] += _q2(milestone.client_target)
                if method == MilestoneAllocationMethod.FIELD_CASCADE:
                    allocated = state["allocated"] if state else Decimal("0")
                    kpis["distributableTarget"] += target
                    kpis["allocatedTarget"] += allocated or Decimal("0")
                    kpis["remainingTarget"] += target - (allocated or Decimal("0"))
                elif method in (
                    MilestoneAllocationMethod.SPECIALIST,
                    MilestoneAllocationMethod.COUNTRY_OWNED,
                ):
                    kpis["countryProjectTarget"] += target
            quarters_pending = sum(
                1
                for allocation in milestone_allocations
                if allocation.status == "approved"
                and allocation.quarter_status != "approved"
            )
            kpis["quartersPending"] += quarters_pending
            approved_rows = [
                allocation
                for allocation in milestone_allocations
                if allocation.status == "approved"
            ]
            for allocation in approved_rows:
                # Template prefill for the quarterly-spread form, merged in
                # Python: `|default:` resolves a dotted argument eagerly and
                # 500s when the path is missing, so templates get one flat
                # dict, never a fallback chain.
                allocation.quarter_prefill = quarter_prefill(allocation)
                allocation.display_name = _display_name(allocation)
            rows.append(
                {
                    "milestone": milestone,
                    "activityDisplay": activity_display,
                    "state": state,
                    "recommendations": recommendations,
                    "otherAllocations": other_rows,
                    "teamAllocations": team_rows,
                    "quartersPending": quarters_pending,
                    "progress": _milestone_progress(milestone, approved_rows),
                    "amendments": [
                        amendment
                        for allocation in milestone_allocations
                        for amendment in allocation.amendments.all()
                    ],
                }
            )
        groups.append({"priority": priority, "milestones": rows})
    published = bool(priorities) and all(
        priority.status == StrategicPriorityStatus.PUBLISHED for priority in priorities
    )
    for group in groups:
        for row in group["milestones"]:
            milestone = row["milestone"]
            state = row["state"]
            if milestone.needs_confirmation:
                label, tone = "Needs confirmation", "warning"
            elif not published:
                label, tone = "Draft", "neutral"
            elif milestone.allocation_method == MilestoneAllocationMethod.FIELD_CASCADE:
                if (
                    state
                    and state["balanced"]
                    and all(
                        allocation.status == "approved" for allocation in state["rows"]
                    )
                ):
                    label, tone = "Distributed", "success"
                    kpis["locked"] += 1
                elif state and state["balanced"]:
                    label, tone = "Ready to approve", "info"
                elif state and state["rows"]:
                    label, tone = "Balance open", "warning"
                else:
                    label, tone = "Published", "info"
            elif milestone.allocation_method == MilestoneAllocationMethod.NON_SCOREABLE:
                label, tone = "Non-scoreable", "neutral"
            else:
                label, tone = "Published", "success"
            row["displayStatus"] = label
            row["statusTone"] = tone
            row["remaining"] = (
                state["unallocated"] if state and state["summable"] else None
            )
    distributable = kpis["distributableTarget"]
    raw_distribution_pct = (
        round(float(kpis["allocatedTarget"] / distributable * 100), 1)
        if distributable
        else 0
    )
    # Keep the progress bar visually bounded even while a bad draft is
    # deliberately shown as over-allocated by the reconciliation balance.
    kpis["distributionPct"] = max(0, min(100, raw_distribution_pct))
    kpis["lockedPct"] = (
        round(kpis["locked"] / kpis["fieldCascade"] * 100)
        if kpis["fieldCascade"]
        else 0
    )
    portfolio_total = kpis["coreTarget"] + kpis["clientTarget"]
    kpis["corePct"] = (
        round(float(kpis["coreTarget"] / portfolio_total * 100), 1)
        if portfolio_total
        else 0
    )
    kpis["clientPct"] = round(100 - kpis["corePct"], 1) if portfolio_total else 0
    kpis["actionableMilestones"] = max(0, kpis["fieldCascade"] - kpis["locked"])
    kpis["distributionComplete"] = (
        kpis["fieldCascade"] > 0 and kpis["locked"] == kpis["fieldCascade"]
    )
    return {
        "fy": fy,
        "groups": groups,
        "kpis": kpis,
        "teams": teams,
        "latestUpdated": latest_updated,
        "published": published,
        "canPublish": bool(priorities) and kpis["needsConfirmation"] == 0,
        "hasMaster": bool(priorities),
    }


def country_milestone_distribution_context(
    milestone: PriorityMilestone,
) -> dict:
    """Focused IA form payload for one database-backed master milestone.

    The master page deliberately renders only the master table. Program Lead
    rows are fetched when the IA opens the distribution form, keeping a 74-row
    page light while ensuring the form and the table read the same records.
    """

    milestone = (
        PriorityMilestone.objects.select_related("priority", "metric_definition")
        .prefetch_related("activity_rules__catalogue_item")
        .get(pk=milestone.pk)
    )
    if milestone.allocation_method != MilestoneAllocationMethod.FIELD_CASCADE:
        raise BadRequest("Only field-cascade milestones distribute to Program Leads.")
    teams = program_lead_teams()
    member_ids = [member for team in teams for member in team["member_staff_ids"]]
    portfolio = _portfolio_counts(member_ids) if member_ids else {}
    allocations = list(
        _live_allocations(milestone)
        .filter(allocated_to_type="team", parent__isnull=True)
        .select_related("employee__user")
    )
    state = _reconcile_rows(
        milestone,
        allocations,
        expected=_q2(milestone.target_value),
        expected_core=(
            _q2(milestone.core_target) if milestone.core_target is not None else None
        ),
        expected_client=(
            _q2(milestone.client_target)
            if milestone.client_target is not None
            else None
        ),
        level_label="Program Lead",
    )
    activity_names = []
    for rule in milestone.activity_rules.all():
        name = rule.catalogue_item.display_name
        if name and name not in activity_names:
            activity_names.append(name)
    recommendations = _team_recommendation_rows(
        milestone, teams, portfolio, allocations
    )
    return {
        "milestone": milestone,
        "state": state,
        "recommendations": recommendations,
        "proposal": _proposal_balance(state, recommendations),
        "activityDisplay": ", ".join(activity_names) or milestone.title,
        "allLocked": bool(allocations)
        and all(allocation.status == "approved" for allocation in allocations),
    }


def _proposal_balance(state: dict, recommendations: list[dict]) -> dict:
    """Balance of the values actually prefilled in the recommendation form."""

    if not state["summable"]:
        return {"remaining": None, "coreRemaining": None, "clientRemaining": None}

    def proposed_value(row, allocation_field, recommendation_field):
        allocation = row.get("allocation")
        if allocation is not None:
            value = getattr(allocation, allocation_field)
            if value is not None:
                return _q2(value)
        return _q2(row.get(recommendation_field))

    total = sum(
        (
            proposed_value(row, "allocated_target", "recommended")
            for row in recommendations
        ),
        Decimal("0"),
    )
    core = sum(
        (
            proposed_value(row, "core_target", "recommendedCore")
            for row in recommendations
        ),
        Decimal("0"),
    )
    client = sum(
        (
            proposed_value(row, "client_target", "recommendedClient")
            for row in recommendations
        ),
        Decimal("0"),
    )
    return {
        "remaining": state["expected"] - total,
        "coreRemaining": (
            state["expected_core"] - core
            if state["expected_core"] is not None
            else None
        ),
        "clientRemaining": (
            state["expected_client"] - client
            if state["expected_client"] is not None
            else None
        ),
    }


def _team_recommendation_rows(milestone, teams, portfolio, existing_rows) -> list[dict]:
    existing_by_team = {str(row.team_id): row for row in existing_rows}
    rows = []
    member_ids = [member for team in teams for member in team["member_staff_ids"]]
    context = _staff_recommendation_context(
        member_ids, milestone.priority.fy, portfolio=portfolio
    )
    team_rows = _build_team_recommendation_rows(milestone, teams, context)
    if not team_rows:
        return []
    target = _q2(milestone.target_value)
    weights = _recommendation_scores(team_rows, milestone, TEAM_RECOMMENDATION_FACTORS)
    if is_summable(milestone):
        shares = weighted_split(
            target,
            weights,
        )
        core_shares = (
            weighted_split(
                _q2(milestone.core_target),
                _recommendation_scores(
                    team_rows,
                    milestone,
                    TEAM_RECOMMENDATION_FACTORS,
                    portfolio_key="core",
                ),
            )
            if milestone.core_target is not None
            else [None] * len(team_rows)
        )
        client_shares = (
            weighted_split(
                _q2(milestone.client_target),
                _recommendation_scores(
                    team_rows,
                    milestone,
                    TEAM_RECOMMENDATION_FACTORS,
                    portfolio_key="client",
                ),
            )
            if milestone.client_target is not None
            else [None] * len(team_rows)
        )
    else:
        shares = [target] * len(team_rows)
        core_shares = [None] * len(team_rows)
        client_shares = [None] * len(team_rows)
    for team, share, core, client in zip(team_rows, shares, core_shares, client_shares):
        existing = existing_by_team.get(str(team["staff"].id))
        team["eligibleSchools"] = _eligible_weight(team["portfolio"], milestone)
        rows.append(
            {
                "staff": team["staff"],
                "portfolio": team["portfolio"],
                "eligibleSchools": team["eligibleSchools"],
                "memberCount": team["memberCount"],
                "cceoCount": team["cceoCount"],
                "availableDays": team["availableDays"],
                "activePriorities": team["activePriorities"],
                "balanceScore": team["balanceScore"],
                "activeFactors": team["activeFactors"],
                "recommended": share,
                "recommendedCore": core,
                "recommendedClient": client,
                "allocation": existing,
            }
        )
    return rows


def team_distribution_workspace(fy: str, *, principal) -> dict:
    """Everything the PL Team Target Distribution workspace shows (§13)."""

    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    role = getattr(principal, "active_role", "")
    lead_id = getattr(principal, "staff_profile_id", None)
    if role == EdifyRole.ADMIN.value and not lead_id:
        lead_id = None
    query = MilestoneAllocation.objects.filter(
        allocated_to_type="team",
        milestone__priority__fy=fy,
        status="approved",
    ).exclude(status__in=("rejected", "superseded"))
    if role != EdifyRole.ADMIN.value:
        query = query.filter(team_id=lead_id)
    team_allocations = list(
        query.select_related(
            "milestone__priority", "milestone__metric_definition"
        ).prefetch_related(
            "milestone__activity_rules",
            "period_targets",
            "children__employee__user",
            "children__period_targets",
        )
    )
    # Fetch the complete PL → team ownership graph once. The team workspace can
    # contain many milestones for the same lead, so querying assignments per
    # allocation would turn the page into an avoidable N+1 workload.
    team_ids = {str(allocation.team_id) for allocation in team_allocations}
    # A Program Lead is also an allocation holder in their own team. Start
    # every roster with the PL, then append active supervised CCEOs.
    member_ids_by_team: dict[str, list[str]] = {
        team_id: [team_id] for team_id in team_ids
    }
    supervised_cceo_ids: set[str] = set()
    for supervisor_id, supervisee_id in StaffSupervisorAssignment.objects.filter(
        supervisor_id__in=team_ids
    ).values_list("supervisor_id", "supervisee_id"):
        supervisor_id = str(supervisor_id)
        supervisee_id = str(supervisee_id)
        supervised_cceo_ids.add(supervisee_id)
        if supervisee_id not in member_ids_by_team.setdefault(supervisor_id, []):
            member_ids_by_team[supervisor_id].append(supervisee_id)
    member_ids = {
        member_id
        for supervisee_ids in member_ids_by_team.values()
        for member_id in supervisee_ids
    }
    members = {
        str(member.id): member
        for member in StaffProfile.objects.select_related("user").filter(
            id__in=member_ids, deleted_at__isnull=True, user__status="active"
        )
    }
    portfolio = _portfolio_counts(list(members)) if members else {}
    recommendation_context = _staff_recommendation_context(
        list(members), fy, portfolio=portfolio
    )
    current = Cal.current()
    rows = []
    pending_spreads = 0
    unbalanced = 0
    locked_targets = 0
    total_team_target = Decimal("0")
    allocated_to_cceos = Decimal("0")
    latest_updated = max(
        (allocation.updated_at for allocation in team_allocations), default=None
    )
    for allocation in team_allocations:
        state = reconcile_employee_level(allocation)
        if not state["balanced"]:
            unbalanced += 1
        all_locked = (
            bool(state["rows"])
            and state["balanced"]
            and all(child.status == "approved" for child in state["rows"])
        )
        if all_locked:
            locked_targets += 1
        if state["summable"]:
            total_team_target += _q2(allocation.allocated_target)
            allocated_to_cceos += state["allocated"] or Decimal("0")
        recommendations = _member_recommendation_rows(
            allocation,
            members,
            portfolio,
            state["rows"],
            supervisee_ids=member_ids_by_team.get(str(allocation.team_id), []),
            recommendation_context=recommendation_context,
        )
        proposal = _proposal_balance(state, recommendations)
        member_rows = []
        for child in state["rows"]:
            spread_pending = (
                child.status == "approved" and child.quarter_status != "approved"
            )
            if spread_pending:
                pending_spreads += 1
            child_planned = planned_output(child)
            child_verified = sum(
                (
                    row.actual_value
                    for row in child.period_targets.all()
                    if row.period_type == "month"
                ),
                Decimal("0"),
            )
            child_target = _q2(child.allocated_target)
            member_rows.append(
                {
                    "allocation": child,
                    "spreadPending": spread_pending,
                    # Merged in Python — templates never chain dotted
                    # |default: fallbacks (the filter resolves its argument
                    # eagerly and 500s on a missing path).
                    "quarterPrefill": (
                        quarter_prefill(child) if child.status == "approved" else None
                    ),
                    "plannedOutput": child_planned,
                    "verified": child_verified,
                    # §8: the unplanned gap is target minus what schedules
                    # promise — it widens when planning is insufficient and
                    # never lowers the assigned target.
                    "unplannedGap": max(
                        Decimal("0"), child_target - child_planned - child_verified
                    ),
                }
            )
        rows.append(
            {
                "allocation": allocation,
                "milestone": allocation.milestone,
                "state": state,
                "recommendations": recommendations,
                "proposal": proposal,
                "memberRows": member_rows,
                "quarterStatus": allocation.quarter_status,
                "recommendedQuarters": recommend_quarters(allocation),
                "allLocked": all_locked,
                "displayStatus": (
                    "Distributed & locked"
                    if all_locked
                    else "Ready to approve"
                    if state["balanced"]
                    else "Balance open"
                    if state["rows"]
                    else "Not distributed"
                ),
                "statusTone": (
                    "success"
                    if all_locked
                    else "info"
                    if state["balanced"]
                    else "warning"
                    if state["rows"]
                    else "neutral"
                ),
                "actionLabel": (
                    "Review allocation"
                    if all_locked
                    else "Review & approve"
                    if state["balanced"]
                    else "Continue distribution"
                    if state["rows"]
                    else "Distribute within team"
                ),
            }
        )
    raw_distribution_pct = (
        round(float(allocated_to_cceos / total_team_target * 100), 1)
        if total_team_target
        else 0
    )
    return {
        "fy": fy,
        "rows": rows,
        "members": sorted(members.values(), key=lambda member: member.user.name or ""),
        "current": current,
        "latestUpdated": latest_updated,
        "kpis": {
            "teamTargets": len(team_allocations),
            "unbalanced": unbalanced,
            "pendingSpreads": pending_spreads,
            "lockedTargets": locked_targets,
            "openActions": max(0, len(team_allocations) - locked_targets),
            "totalTeamTarget": total_team_target,
            "allocatedWithinTeam": allocated_to_cceos,
            # Compatibility alias for any existing template integration.
            "allocatedToCceos": allocated_to_cceos,
            "remainingTarget": total_team_target - allocated_to_cceos,
            "distributionPct": max(0, min(100, raw_distribution_pct)),
            "cceos": len(supervised_cceo_ids & set(members)),
            "allocationHolders": len(members),
            "distributionComplete": bool(team_allocations)
            and locked_targets == len(team_allocations),
        },
    }


def _member_recommendation_rows(
    team_allocation,
    members,
    portfolio,
    existing_rows,
    *,
    supervisee_ids,
    recommendation_context,
) -> list[dict]:
    milestone = team_allocation.milestone
    existing_by_member = {str(row.employee_id): row for row in existing_rows}
    supervisee_ids = [
        str(supervisee_id)
        for supervisee_id in supervisee_ids
        if str(supervisee_id) in members
    ]
    if not supervisee_ids:
        return []
    member_rows = _build_member_recommendation_rows(
        team_allocation, members, recommendation_context, supervisee_ids
    )
    target = _q2(team_allocation.allocated_target)
    weights = _recommendation_scores(
        member_rows, milestone, MEMBER_RECOMMENDATION_FACTORS
    )
    if is_summable(milestone):
        shares = weighted_split(
            target,
            weights,
        )
        core_shares = (
            weighted_split(
                _q2(team_allocation.core_target),
                _recommendation_scores(
                    member_rows,
                    milestone,
                    MEMBER_RECOMMENDATION_FACTORS,
                    portfolio_key="core",
                ),
            )
            if team_allocation.core_target is not None
            else [None] * len(member_rows)
        )
        client_shares = (
            weighted_split(
                _q2(team_allocation.client_target),
                _recommendation_scores(
                    member_rows,
                    milestone,
                    MEMBER_RECOMMENDATION_FACTORS,
                    portfolio_key="client",
                ),
            )
            if team_allocation.client_target is not None
            else [None] * len(member_rows)
        )
    else:
        shares = [target] * len(member_rows)
        core_shares = [None] * len(member_rows)
        client_shares = [None] * len(member_rows)
    rows = []
    for member, share, core, client in zip(
        member_rows, shares, core_shares, client_shares
    ):
        member["eligibleSchools"] = _eligible_weight(member["portfolio"], milestone)
        rows.append(
            {
                "staff": member["staff"],
                "isLead": member["isLead"],
                "portfolio": member["portfolio"],
                "eligibleSchools": member["eligibleSchools"],
                "availableDays": member["availableDays"],
                "activePriorities": member["activePriorities"],
                "balanceScore": member["balanceScore"],
                "activeFactors": member["activeFactors"],
                "recommended": share,
                "recommendedCore": core,
                "recommendedClient": client,
                "allocation": existing_by_member.get(str(member["staff"].id)),
            }
        )
    return rows


# ─── Utilities ───────────────────────────────────────────────────────────────


def _actor_id(principal) -> str:
    return str(getattr(principal, "user_id", None) or getattr(principal, "id", ""))


def _audit(action: str, subject, principal, payload: dict) -> None:
    try:
        from apps.audit.services import log

        log(
            action=action,
            subject_kind=type(subject).__name__,
            subject_id=str(getattr(subject, "id", "")),
            actor_id=_actor_id(principal),
            actor_role=getattr(principal, "active_role", ""),
            payload=payload,
        )
    except Exception:  # noqa: BLE001 — audit must never break the workflow
        pass
