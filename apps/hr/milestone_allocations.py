from datetime import date
from decimal import Decimal
import re

from django.db import transaction
from django.db.models import Count, Q

from apps.core.exceptions import BadRequest

from .models import (
    ActivityPriorityLink,
    MilestoneAllocation,
    MilestoneProgressCredit,
    PriorityMilestone,
    StrategicPriority,
)


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
    # 2026-08-20 audit G8: a count target is whole schools/visits/people —
    # fractional staff targets are not allocatable.
    if milestone.measurement_type == "count" and target != target.to_integral_value():
        raise BadRequest("Count targets must be whole numbers.")
    employee_id = data.get("employeeId") if allocated_to_type == "employee" else None
    project_id = data.get("projectId") if allocated_to_type == "project" else None
    team_id = data.get("teamId") if allocated_to_type == "team" else None
    country_id = data.get("countryId") if allocated_to_type == "country" else None
    effective_date = data.get("effectiveDate")
    allocation_reason = (data.get("allocationReason") or "").strip()
    parent = None
    if data.get("parentId"):
        parent = MilestoneAllocation.objects.filter(id=data["parentId"]).first()
        if parent is None or parent.milestone_id != milestone.id:
            raise BadRequest("The parent allocation must belong to this milestone.")
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
        from apps.core.rbac import EdifyRole as _Role

        employee = (
            StaffProfile.objects.select_related("user").filter(id=employee_id).first()
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
        principal_staff_id = getattr(principal, "staff_profile_id", None)
        has_own_approved_team_parent = (
            getattr(principal, "active_role", "") == _Role.COUNTRY_PROGRAM_LEAD.value
            and parent is not None
            and parent.allocated_to_type == "team"
            and str(parent.team_id) == str(principal_staff_id)
            and parent.status == "approved"
        )
        is_pl_self_allocation = has_own_approved_team_parent and str(
            employee.id
        ) == str(principal_staff_id)
        if (
            applicable
            and "all" not in applicable
            and not (applicable & employee_roles)
            and not is_pl_self_allocation
        ):
            raise BadRequest(
                "This milestone is not applicable to the selected employee's role."
            )
        # The real role string is "Program Lead" (EdifyRole). The previous
        # comparison against "CountryProgramLead" — the enum NAME — matched no
        # live principal, so this guard never fired.
        if getattr(principal, "active_role", "") == _Role.COUNTRY_PROGRAM_LEAD.value:
            from apps.accounts.models import StaffSupervisorAssignment

            if not has_own_approved_team_parent:
                raise BadRequest(
                    "Program Leads may allocate only from their own approved "
                    "team target."
                )
            is_self = str(employee.id) == str(principal_staff_id)
            is_supervised = StaffSupervisorAssignment.objects.filter(
                supervisor_id=principal_staff_id, supervisee_id=employee.id
            ).exists()
            if not (is_self or is_supervised):
                raise BadRequest(
                    "Program Leads may allocate only to themselves or their "
                    "supervised team."
                )
            if is_self and not is_pl_self_allocation:
                raise BadRequest(
                    "A Program Lead may allocate to themselves only from their "
                    "own approved team target."
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
            raise BadRequest(
                "This milestone is not applicable to the selected Project."
            )
    elif allocated_to_type == "team" and not team_id:
        raise BadRequest("Choose a valid team.")
    elif allocated_to_type == "country" and not country_id:
        raise BadRequest("Choose a valid country.")
    if allocated_to_type == "team":
        from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
        from apps.core.rbac import EdifyRole as _Role

        if not StaffProfile.objects.filter(id=team_id).exists() or not (
            StaffSupervisorAssignment.objects.filter(supervisor_id=team_id).exists()
        ):
            raise BadRequest("Choose a valid supervised team.")
        if getattr(
            principal, "active_role", ""
        ) == _Role.COUNTRY_PROGRAM_LEAD.value and str(team_id) != str(
            getattr(principal, "staff_profile_id", "")
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

    def _column(key):
        if data.get(key) in (None, ""):
            return None
        try:
            return Decimal(str(data[key]))
        except Exception as exc:  # noqa: BLE001
            raise BadRequest("Core and Client targets must be numeric.") from exc

    core_target = _column("coreTarget")
    client_target = _column("clientTarget")

    # One annual distribution (§4): a target-holder gets ONE live allocation
    # per milestone for the year. Changing it afterwards is an amendment with
    # a reason and audit history, never a second row.
    live = milestone.allocations.exclude(status__in=("rejected", "superseded"))
    duplicate = None
    if allocated_to_type == "employee":
        duplicate = live.filter(employee_id=employee_id).first()
    elif allocated_to_type == "team":
        duplicate = live.filter(allocated_to_type="team", team_id=team_id).first()
    if duplicate is not None:
        raise BadRequest(
            "This target is already allocated for the year — targets are "
            "distributed once; use a formal amendment to change the figure."
        )
    allocation = MilestoneAllocation.objects.create(
        milestone=milestone,
        parent=parent,
        allocated_to_type=allocated_to_type,
        country_id=country_id,
        team_id=team_id,
        employee_id=employee_id,
        project_id=project_id,
        allocated_target=target,
        core_target=core_target,
        client_target=client_target,
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
    # 2026-08-20 priorities audit G1: approval LOCKS a figure into somebody's
    # My Targets, so it carries the same authority and arithmetic rules as
    # the distribution workspace — previously this had neither, and the
    # strategic-priorities page auto-approved any amount for any holder,
    # bypassing reconcile-to-zero entirely.
    from apps.core.exceptions import Forbidden as _Forbidden

    from .target_distribution import (
        DISTRIBUTION_APPROVER_ROLES,
        is_summable,
        reconcile_employee_level,
        reconcile_team_level,
    )

    _role = getattr(principal, "active_role", "")
    if allocation.allocated_to_type == "employee" and allocation.parent_id:
        # Employee rows under a team parent are approved by the supervising
        # flow (approve_employee_distribution) — that path reconciles.
        from .target_distribution import _assert_may_approve_spread

        _assert_may_approve_spread(allocation, principal)
    elif _role not in DISTRIBUTION_APPROVER_ROLES:
        raise _Forbidden(
            "Only the distribution approver may lock an annual allocation."
        )
    if is_summable(allocation.milestone):
        milestone = allocation.milestone
        if allocation.allocated_to_type == "team":
            errors = reconcile_team_level(milestone).get("errors") or []
        elif allocation.parent_id:
            errors = reconcile_employee_level(allocation.parent).get("errors") or []
        else:
            # A single-holder (specialist / country-owned) allocation IS the
            # whole distribution: it must equal the milestone target exactly.
            errors = (
                []
                if milestone.target_value is not None
                and allocation.allocated_target == milestone.target_value
                else [
                    "A single-holder allocation must equal the milestone "
                    f"target exactly ({milestone.target_value} — got "
                    f"{allocation.allocated_target})."
                ]
            )
        if errors:
            raise BadRequest(
                "Approval blocked — the distribution does not reconcile to "
                "zero: " + " · ".join(str(e) for e in errors[:3])
            )
    # Approval locks the annual figure and writes the quarter rows plus the
    # capacity-aware month rows (working days − holidays − the holder's
    # approved leave). The quarterly spread starts from the working-day
    # recommendation and remains a draft until its own approval (§6).
    from django.utils import timezone as _tz

    from .target_distribution import phase_allocation_periods

    phase_allocation_periods(allocation)
    allocation.status = "approved"
    allocation.approved_by = getattr(principal, "user_id", None) or str(principal.id)
    allocation.locked_at = _tz.now()
    allocation.save(update_fields=["status", "approved_by", "locked_at", "updated_at"])
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
        allocation_filter &= Q(milestones__allocations__employee_id__in=staff_ids)
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
    """Count explicit planning links plus legacy credited work without N+1s."""

    allocation_rows = list(allocations)
    if not allocation_rows:
        return {}
    owner_to_staff: dict[str, set[str]] = {}
    milestone_ids = set()
    allocation_keys = {}
    for allocation in allocation_rows:
        if not allocation.employee_id:
            continue
        milestone_ids.add(allocation.milestone_id)
        allocation_keys[str(allocation.id)] = (
            str(allocation.milestone_id),
            str(allocation.employee_id),
        )
        owner_ids = {
            str(allocation.employee_id),
            str(getattr(allocation.employee, "user_id", "") or ""),
        }
        for owner_id in owner_ids - {""}:
            owner_to_staff.setdefault(owner_id, set()).add(str(allocation.employee_id))
    if not milestone_ids or not owner_to_staff:
        return {}
    owner_ids = list(owner_to_staff)
    linked: dict[tuple[str, str], set[str]] = {}
    explicit_links = ActivityPriorityLink.objects.filter(
        allocation_id__in=allocation_keys
    ).values("allocation_id", "activity_id")
    for row in explicit_links:
        key = allocation_keys.get(str(row["allocation_id"]))
        if key:
            linked.setdefault(key, set()).add(str(row["activity_id"]))

    credits = (
        MilestoneProgressCredit.objects.filter(
            rule__milestone_id__in=milestone_ids,
            reversed_at__isnull=True,
        )
        .filter(
            Q(activity__responsible_staff_id__in=owner_ids)
            | Q(activity__monitored_by_staff_id__in=owner_ids)
        )
        .values(
            "rule__milestone_id",
            "activity_id",
            "activity__responsible_staff_id",
            "activity__monitored_by_staff_id",
        )
    )
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
            linked.setdefault((str(credit["rule__milestone_id"]), staff_id), set()).add(
                str(credit["activity_id"])
            )
    return {key: len(activity_ids) for key, activity_ids in linked.items()}


def _allocation_projection(
    allocation,
    *,
    month_of_fy: int,
    linked_activity_count: int,
) -> dict:
    from .target_distribution import classify_achievement

    milestone = allocation.milestone
    summable = milestone.measurement_type in {"count", "currency"}
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
    if summable:
        # The annual allocation remains authoritative before quarterly/monthly
        # phasing is generated. Showing 0 / 0 during that interval hides a
        # real approved commitment and makes its Planning entry point look
        # complete before any work exists.
        fy_plan = (
            sum((target.planned_value for target in periods), Decimal("0"))
            if periods
            else allocation.allocated_target or Decimal("0")
        )
        fy_actual = sum((target.actual_value for target in periods), Decimal("0"))
        quarter_plan = sum((target.planned_value for target in quarter), Decimal("0"))
        quarter_actual = sum((target.actual_value for target in quarter), Decimal("0"))
    else:
        # Rates never sum: a 90% coverage commitment is 90% in every period,
        # and adding three months of it is not 270%. The FY view of a rate is
        # the rate itself, and actuals genuinely ride the period rows'
        # achievement math now — `actual_value` on a rate period holds RAW
        # UNITS (schools reached), so reading it as the achieved rate scored
        # units against a percentage. The achieved rate is achievement × the
        # committed rate.
        fy_plan = allocation.allocated_target or Decimal("0")

        def _achieved_rate(rows):
            best = max(
                (target.achievement_percentage for target in rows),
                default=Decimal("0"),
            )
            return (best * fy_plan / 100).quantize(Decimal("0.01"))

        fy_actual = _achieved_rate(periods)
        quarter_plan = fy_plan
        quarter_actual = _achieved_rate(quarter)
    remaining = max(Decimal("0"), fy_plan - fy_actual)
    month_plan = current.planned_value if current else Decimal("0")
    if summable:
        month_actual = current.actual_value if current else Decimal("0")
    else:
        month_actual = (
            (current.achievement_percentage * fy_plan / 100).quantize(Decimal("0.01"))
            if current
            else Decimal("0")
        )
    progress = round(float(fy_actual / fy_plan * 100), 1) if fy_plan else 0
    # One vocabulary. This block used to compute its own "Achieved / In
    # Progress / Not Started" and "On track / Watch / Needs attention" beside
    # the canonical classification, so the same allocation could be described
    # three different ways on three different surfaces.
    from .target_distribution import rate_achievement_ceiling

    classification = classify_achievement(
        progress if fy_plan else None,
        cap_at_100=milestone.cap_at_100,
        ceiling=None if summable else rate_achievement_ceiling(fy_plan),
        target=fy_plan,
    )
    status = classification["label"]
    # Pace is a different question from achievement — "am I keeping up this
    # month?" rather than "did I hit the annual number?" — so it keeps its own
    # reading, but only ever against the month's own plan.
    if not classification["is_scoring"]:
        risk, risk_tone = classification["label"], classification["tone"]
    elif classification["key"] in ("met", "exceeded", "far_exceeded") or (
        month_plan and month_actual >= month_plan
    ):
        risk, risk_tone = "On track", "success"
    elif month_actual:
        risk, risk_tone = "Watch", "warning"
    else:
        risk, risk_tone = "Needs attention", "danger"
    return {
        "allocationId": allocation.id,
        "priority": milestone.priority.title,
        "milestone": milestone.title,
        "targetSource": "Approved Milestone Allocation",
        "dataSource": milestone.metric_definition.canonical_label,
        "allocatedTarget": allocation.allocated_target or fy_plan,
        "monthPlan": month_plan,
        "monthActual": month_actual,
        "quarterPlan": quarter_plan,
        "quarterActual": quarter_actual,
        "fyPlan": fy_plan,
        "fyActual": fy_actual,
        "remaining": remaining,
        "progress": progress,
        "classification": classification,
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
