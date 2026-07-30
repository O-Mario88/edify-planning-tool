from datetime import date
from decimal import Decimal
import re

from django.db import transaction
from django.db.models import Count, Q

from apps.core.exceptions import BadRequest
from apps.targets.fy_calendar import FinancialYearCalendarService as FyCalendar

from .models import (
    MilestoneAllocation,
    MilestonePeriodTarget,
    MilestoneProgressCredit,
    PriorityMilestone,
    StrategicPriority,
)


def _split_decimal(total: Decimal, periods=12) -> list[Decimal]:
    """Largest-remainder split that preserves the exact approved total."""
    cents = int((total * 100).quantize(Decimal("1")))
    base, remainder = divmod(cents, periods)
    return [
        Decimal(base + (1 if index < remainder else 0)) / 100
        for index in range(periods)
    ]


def _assert_allocatable(milestone: PriorityMilestone) -> None:
    if (
        milestone.requires_definition
        or milestone.definition_status != "approved"
        or not milestone.active
        or milestone.metric_definition_id is None
    ):
        raise BadRequest(
            "This milestone is not approved and active. Define its metric, "
            "target, period, source and quality gate before allocation."
        )


def _normalized_role(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


@transaction.atomic
def create_allocation(*, milestone, data: dict, principal) -> MilestoneAllocation:
    _assert_allocatable(milestone)
    allocated_to_type = (data.get("allocatedToType") or "").strip()
    if allocated_to_type not in {"country", "team", "employee", "project"}:
        raise BadRequest("Allocation scope must be country, team, employee or project.")
    target = data.get("allocatedTarget")
    try:
        target = Decimal(str(target))
    except Exception as exc:
        raise BadRequest("Allocated target must be numeric.") from exc
    if target <= 0:
        raise BadRequest("Allocated target must be greater than zero.")
    employee_id = data.get("employeeId") if allocated_to_type == "employee" else None
    project_id = data.get("projectId") if allocated_to_type == "project" else None
    team_id = data.get("teamId") if allocated_to_type == "team" else None
    country_id = data.get("countryId") if allocated_to_type == "country" else None
    effective_date = data.get("effectiveDate")
    allocation_reason = (data.get("allocationReason") or "").strip()
    if not effective_date:
        raise BadRequest("Effective date is required.")
    if isinstance(effective_date, str):
        try:
            effective_date = date.fromisoformat(effective_date)
        except ValueError as exc:
            raise BadRequest("Effective date must be a valid ISO date.") from exc
    if not allocation_reason:
        raise BadRequest("Allocation reason is required.")
    if allocated_to_type == "employee":
        from apps.accounts.models import StaffProfile

        employee = (
            StaffProfile.objects.select_related("user")
            .filter(id=employee_id)
            .first()
            if employee_id
            else None
        )
        if employee is None:
            raise BadRequest("Choose a valid employee.")
        applicable = {
            _normalized_role(role) for role in (milestone.role_applicability or [])
        }
        employee_roles = {
            _normalized_role(employee.title),
            *{
                _normalized_role(role)
                for role in (getattr(employee.user, "roles", None) or [])
            },
        }
        if applicable and "all" not in applicable and not (
            applicable & employee_roles
        ):
            raise BadRequest(
                "This milestone is not applicable to the selected employee's role."
            )
        if getattr(principal, "active_role", "") == "CountryProgramLead":
            from apps.accounts.models import StaffSupervisorAssignment

            principal_staff_id = getattr(principal, "staff_profile_id", None)
            if not StaffSupervisorAssignment.objects.filter(
                supervisor_id=principal_staff_id,
                supervisee_id=employee.id,
            ).exists():
                raise BadRequest(
                    "Program Leads may allocate only to their supervised team."
                )
    elif allocated_to_type == "project":
        from apps.projects.scoping import get_scoped_project

        try:
            project = get_scoped_project(project_id, principal) if project_id else None
        except Exception as exc:
            raise BadRequest("Choose a valid in-scope project.") from exc
        if project is None:
            raise BadRequest("Choose a valid project.")
        applicable = set(milestone.project_applicability or [])
        if applicable and not ({project.id, project.code} & applicable):
            raise BadRequest("This milestone is not applicable to the selected Project.")
    elif allocated_to_type == "team" and not team_id:
        raise BadRequest("Choose a valid team.")
    elif allocated_to_type == "country" and not country_id:
        raise BadRequest("Choose a valid country.")
    if allocated_to_type == "team":
        from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

        if not StaffProfile.objects.filter(id=team_id).exists() or not (
            StaffSupervisorAssignment.objects.filter(supervisor_id=team_id).exists()
        ):
            raise BadRequest("Choose a valid supervised team.")
        if (
            getattr(principal, "active_role", "") == "CountryProgramLead"
            and str(team_id) != str(getattr(principal, "staff_profile_id", ""))
        ):
            raise BadRequest("Program Leads may allocate only their own team target.")
    if allocated_to_type == "country":
        applicable = set(milestone.country_applicability or [])
        if applicable and country_id not in applicable:
            raise BadRequest("This milestone is not applicable to that country.")
    try:
        denominator = (
            Decimal(str(data["denominator"]))
            if data.get("denominator") not in (None, "")
            else None
        )
        weight = Decimal(str(data.get("weight") or 0))
    except Exception as exc:
        raise BadRequest("Denominator and weight must be numeric.") from exc
    if denominator is not None and denominator <= 0:
        raise BadRequest("Denominator must be greater than zero.")
    if weight < 0 or weight > 100:
        raise BadRequest("Weight must be between 0 and 100.")
    allocation = MilestoneAllocation.objects.create(
        milestone=milestone,
        allocated_to_type=allocated_to_type,
        country_id=country_id,
        team_id=team_id,
        employee_id=employee_id,
        project_id=project_id,
        allocated_target=target,
        denominator=denominator,
        weight=weight,
        allocation_reason=allocation_reason,
        allocated_by=getattr(principal, "user_id", None) or str(principal.id),
        effective_date=effective_date,
        status="draft",
    )
    return allocation


@transaction.atomic
def approve_allocation(allocation, *, principal) -> MilestoneAllocation:
    allocation = (
        MilestoneAllocation.objects.select_for_update(of=("self",))
        .select_related("milestone__priority__cycle")
        .get(pk=allocation.pk)
    )
    _assert_allocatable(allocation.milestone)
    if allocation.status == "approved":
        return allocation
    fy = allocation.milestone.priority.fy
    monthly = _split_decimal(allocation.allocated_target or Decimal("0"))
    for month_of_fy, planned in enumerate(monthly, 1):
        start, end_exclusive = FyCalendar.month_range(fy, month_of_fy)
        from datetime import timedelta

        MilestonePeriodTarget.objects.update_or_create(
            milestone=allocation.milestone,
            allocation=allocation,
            period_type="month",
            period_start=start,
            defaults={
                "scope": allocation.allocated_to_type,
                "country_id": allocation.country_id,
                "team_id": allocation.team_id,
                "employee": allocation.employee,
                "period_end": end_exclusive - timedelta(days=1),
                "planned_value": planned,
                "actual_source": (
                    allocation.milestone.metric_definition.canonical_service
                ),
            },
        )
    allocation.status = "approved"
    allocation.approved_by = (
        getattr(principal, "user_id", None) or str(principal.id)
    )
    allocation.save(
        update_fields=["status", "approved_by", "updated_at"]
    )
    from .milestone_progress import refresh_period_targets

    refresh_period_targets(allocation.milestone_id)
    return allocation


def strategic_priority_overview(
    *,
    fy: str,
    staff_ids: list[str] | None = None,
) -> list[dict]:
    """Governed priority context for My/Team Targets.

    Priorities remain visible while their milestones are being defined, but
    only approved allocations are counted as targets. That distinction keeps
    unresolved source wording out of performance status and risk calculations.
    """

    allocation_filter = Q(milestones__allocations__status="approved")
    if staff_ids is not None:
        allocation_filter &= Q(
            milestones__allocations__employee_id__in=staff_ids
        )
    priorities = (
        StrategicPriority.objects.filter(fy=fy, cycle__isnull=False)
        .annotate(
            milestone_count=Count("milestones", distinct=True),
            ready_milestone_count=Count(
                "milestones",
                filter=Q(
                    milestones__active=True,
                    milestones__requires_definition=False,
                    milestones__definition_status="approved",
                    milestones__metric_definition__isnull=False,
                ),
                distinct=True,
            ),
            allocated_count=Count(
                "milestones__allocations",
                filter=allocation_filter,
                distinct=True,
            ),
        )
        .order_by("sequence", "title")
    )
    rows = []
    for priority in priorities:
        if priority.allocated_count:
            status, tone = "Allocated", "success"
        elif priority.ready_milestone_count:
            status, tone = "Ready for allocation", "info"
        else:
            status, tone = "Definition in progress", "neutral"
        rows.append(
            {
                "code": priority.code,
                "title": priority.title,
                "sequence": priority.sequence,
                "sourceDocument": priority.source_document,
                "milestoneCount": priority.milestone_count,
                "readyMilestoneCount": priority.ready_milestone_count,
                "allocatedCount": priority.allocated_count,
                "status": status,
                "tone": tone,
            }
        )
    return rows


def _linked_activity_counts(allocations) -> dict[tuple[str, str], int]:
    """Count unique credited Activities per milestone/employee without N+1s."""

    allocation_rows = list(allocations)
    if not allocation_rows:
        return {}
    owner_to_staff: dict[str, set[str]] = {}
    milestone_ids = set()
    for allocation in allocation_rows:
        if not allocation.employee_id:
            continue
        milestone_ids.add(allocation.milestone_id)
        owner_ids = {
            str(allocation.employee_id),
            str(getattr(allocation.employee, "user_id", "") or ""),
        }
        for owner_id in owner_ids - {""}:
            owner_to_staff.setdefault(owner_id, set()).add(
                str(allocation.employee_id)
            )
    if not milestone_ids or not owner_to_staff:
        return {}
    owner_ids = list(owner_to_staff)
    credits = MilestoneProgressCredit.objects.filter(
        rule__milestone_id__in=milestone_ids,
    ).filter(
        Q(activity__responsible_staff_id__in=owner_ids)
        | Q(activity__monitored_by_staff_id__in=owner_ids)
    ).values(
        "rule__milestone_id",
        "activity_id",
        "activity__responsible_staff_id",
        "activity__monitored_by_staff_id",
    )
    linked: dict[tuple[str, str], set[str]] = {}
    for credit in credits:
        matched_staff_ids = set()
        for owner_field in (
            "activity__responsible_staff_id",
            "activity__monitored_by_staff_id",
        ):
            matched_staff_ids.update(
                owner_to_staff.get(str(credit[owner_field] or ""), set())
            )
        for staff_id in matched_staff_ids:
            linked.setdefault(
                (str(credit["rule__milestone_id"]), staff_id), set()
            ).add(str(credit["activity_id"]))
    return {key: len(activity_ids) for key, activity_ids in linked.items()}


def _allocation_projection(
    allocation,
    *,
    month_of_fy: int,
    linked_activity_count: int,
) -> dict:
    periods = sorted(
        (
            target
            for target in allocation.period_targets.all()
            if target.period_type == "month"
        ),
        key=lambda target: target.period_start,
    )
    current = periods[month_of_fy - 1] if len(periods) >= month_of_fy else None
    quarter_start = ((month_of_fy - 1) // 3) * 3
    quarter = periods[quarter_start : quarter_start + 3]
    fy_plan = sum((target.planned_value for target in periods), Decimal("0"))
    fy_actual = sum((target.actual_value for target in periods), Decimal("0"))
    quarter_plan = sum(
        (target.planned_value for target in quarter), Decimal("0")
    )
    quarter_actual = sum(
        (target.actual_value for target in quarter), Decimal("0")
    )
    remaining = max(Decimal("0"), fy_plan - fy_actual)
    month_plan = current.planned_value if current else Decimal("0")
    month_actual = current.actual_value if current else Decimal("0")
    status = (
        "Achieved"
        if fy_plan and fy_actual >= fy_plan
        else "In Progress"
        if fy_actual
        else "Not Started"
    )
    if status == "Achieved" or (
        month_plan and month_actual >= month_plan
    ):
        risk, risk_tone = "On track", "success"
    elif month_actual:
        risk, risk_tone = "Watch", "warning"
    else:
        risk, risk_tone = "Needs attention", "danger"
    return {
        "allocationId": allocation.id,
        "priority": allocation.milestone.priority.title,
        "milestone": allocation.milestone.title,
        "targetSource": "Approved Milestone Allocation",
        "dataSource": allocation.milestone.metric_definition.canonical_label,
        "allocatedTarget": allocation.allocated_target or fy_plan,
        "monthPlan": month_plan,
        "monthActual": month_actual,
        "quarterPlan": quarter_plan,
        "quarterActual": quarter_actual,
        "fyPlan": fy_plan,
        "fyActual": fy_actual,
        "remaining": remaining,
        "progress": (
            round(float(fy_actual / fy_plan * 100), 1) if fy_plan else 0
        ),
        "status": status,
        "risk": risk,
        "riskTone": risk_tone,
        "linkedActivities": linked_activity_count,
    }


def _approved_employee_allocations(*, staff_ids, fy):
    return list(
        MilestoneAllocation.objects.filter(
            employee_id__in=staff_ids,
            status="approved",
            milestone__priority__fy=fy,
        )
        .select_related(
            "employee__user",
            "milestone__priority",
            "milestone__metric_definition",
        )
        .prefetch_related("period_targets")
        .order_by(
            "milestone__priority__sequence",
            "milestone__source_order",
            "employee__user__name",
        )
    )


def personal_milestone_targets(*, staff, fy: str, month_of_fy: int) -> list[dict]:
    """Strategic allocation projection for the existing My Targets page."""
    allocations = _approved_employee_allocations(
        staff_ids=[staff.id],
        fy=fy,
    )
    linked = _linked_activity_counts(allocations)
    return [
        _allocation_projection(
            allocation,
            month_of_fy=month_of_fy,
            linked_activity_count=linked.get(
                (str(allocation.milestone_id), str(staff.id)), 0
            ),
        )
        for allocation in allocations
    ]


def team_milestone_targets(*, users, fy: str, month_of_fy: int) -> list[dict]:
    users_by_staff_id = {
        str(user.staff_profile_id): user
        for user in users
        if getattr(user, "staff_profile_id", None)
    }
    allocations = _approved_employee_allocations(
        staff_ids=list(users_by_staff_id),
        fy=fy,
    )
    linked = _linked_activity_counts(allocations)
    rows = []
    for allocation in allocations:
        staff_id = str(allocation.employee_id)
        user = users_by_staff_id.get(staff_id)
        if user is None:
            continue
        target = _allocation_projection(
            allocation,
            month_of_fy=month_of_fy,
            linked_activity_count=linked.get(
                (str(allocation.milestone_id), staff_id), 0
            ),
        )
        rows.append(
            {
                **target,
                "teamMember": user.name,
                "teamMemberId": user.id,
            }
        )
    return rows
