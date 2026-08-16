"""Weekly schedule recommendation — autopilot slice 1 (roadmap Phase 4).

The generator turns "which of my schools most need a visit next week, and
on which days can I actually work?" into a reviewable draft: portfolio
schools without recent support, SSA-outstanding first, grouped by
sub-county into route-coherent days that pass the calendar-policy gate.
The staff member's decision is Accept Week (or dismiss) — not school-by-
school construction. Acceptance runs every item through the canonical
create() funnel, so a machine draft can never bypass a gate a human plan
would face.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest

from .models import ProposedActivity, ProposedPlan, ProposedPlanStatus

logger = logging.getLogger("edify.autopilot")

MAX_SCHOOLS_PER_DAY = 3
WORKABLE_WEEKDAYS = 6  # Mon–Sat; Sunday is always blocked by policy.

VISIT_STABLE_CODE = "STANDARD_SCHOOL_VISIT"
VISIT_ACTIVITY_TYPE = "school_visit"


def _next_week_start(today: date | None = None) -> date:
    today = today or timezone.localdate()
    return today + timedelta(days=(7 - today.weekday()))


def _workable_days(staff, week_start: date) -> list[date]:
    """Next week's days this person can actually work, by the same gate that
    governs manual scheduling (REG-02): holidays, blackouts, org events and
    the person's approved leave all block here too."""

    from apps.core.calendar_policy import SchedulingPolicyService

    user = getattr(staff, "user", None)
    days = []
    for offset in range(WORKABLE_WEEKDAYS):
        candidate = week_start + timedelta(days=offset)
        verdict = SchedulingPolicyService.check(user, candidate)
        if verdict.get("status") != "blocked":
            days.append(candidate)
    return days


def _candidate_schools(staff, *, limit: int = 30) -> list[dict]:
    """Portfolio schools most in need of support: no live activity this
    month, SSA-outstanding first. Reads the same assignment source scope
    builds from, so the proposal can never reach outside the portfolio."""

    from apps.accounts.models import StaffSchoolAssignment
    from apps.activities.models import Activity
    from apps.schools.models import School

    school_ids = list(
        StaffSchoolAssignment.objects.filter(staff_id=staff.id).values_list(
            "school_id", flat=True
        )
    )
    if not school_ids:
        return []
    from apps.core.fy import get_operational_fy

    month_start = timezone.localdate().replace(day=1)
    covered = set(
        Activity.objects.filter(
            school_id__in=school_ids,
            planned_date__gte=month_start,
            deleted_at__isnull=True,
        )
        .exclude(status__in=("cancelled", "rejected"))
        .values_list("school_id", flat=True)
    )
    # Client-family schools carry a ONE-visit-per-FY entitlement
    # (activities.services._assert_schedule_entitlement). Proposing a school
    # whose entitlement is already consumed guarantees a refusal at
    # acceptance, so the generator applies the same rule up front.
    fy = get_operational_fy(timezone.now())
    fy_visited = set(
        Activity.objects.filter(
            school_id__in=school_ids,
            fy=fy,
            activity_type=VISIT_ACTIVITY_TYPE,
            deleted_at__isnull=True,
        )
        .exclude(status__in=("cancelled", "rejected"))
        .values_list("school_id", flat=True)
    )
    schools = (
        School.objects.filter(
            id__in=school_ids,
            deleted_at__isnull=True,
            operational_status__in=("active", "reopened"),
        )
        .exclude(id__in=covered)
        .exclude(
            id__in=fy_visited,
            school_type__in=("client", "core_trained"),
        )
        .select_related("sub_county")
        .order_by("name")[: limit * 2]
    )
    rows = []
    for school in schools:
        ssa_outstanding = school.current_fy_ssa_status != "done"
        rows.append(
            {
                "school": school,
                "area": school.sub_county.name if school.sub_county_id else "",
                "ssa_outstanding": ssa_outstanding,
                "reason": (
                    "SSA outstanding this FY"
                    if ssa_outstanding
                    else "No support activity this month"
                ),
            }
        )
    rows.sort(key=lambda row: (not row["ssa_outstanding"], row["school"].name))
    return rows[:limit]


@transaction.atomic
def generate_week_proposal(staff, *, week_start: date | None = None) -> ProposedPlan:
    """Draft next week for one staff member. Regeneration supersedes the
    previous live draft (dismissed, never stacked); an accepted week is
    final — the work is real now and a new draft would shadow it."""

    week_start = week_start or _next_week_start()
    existing = ProposedPlan.objects.filter(staff=staff, week_start=week_start).first()
    if existing and existing.status == ProposedPlanStatus.ACCEPTED:
        raise BadRequest(
            "This week is already accepted — its activities are real planned "
            "work now. Adjust them in My Plan."
        )
    if existing and existing.status == ProposedPlanStatus.PROPOSED:
        existing.status = ProposedPlanStatus.DISMISSED
        existing.save(update_fields=["status", "updated_at"])
    days = _workable_days(staff, week_start)
    candidates = _candidate_schools(
        staff, limit=MAX_SCHOOLS_PER_DAY * max(len(days), 1)
    )
    plan = ProposedPlan.objects.create(
        staff=staff,
        week_start=week_start,
        rationale={
            "workableDays": [day.isoformat() for day in days],
            "candidatesConsidered": len(candidates),
            "ordering": "SSA-outstanding first, then coverage gaps",
            "grouping": "sub-county route days",
            "maxSchoolsPerDay": MAX_SCHOOLS_PER_DAY,
        },
    )
    # Route-coherent days: one sub-county per day where possible.
    by_area: dict[str, list[dict]] = {}
    for row in candidates:
        by_area.setdefault(row["area"] or "Unlocated", []).append(row)
    areas = sorted(by_area.items(), key=lambda pair: len(pair[1]), reverse=True)
    day_index = 0
    for area, rows in areas:
        for chunk_start in range(0, len(rows), MAX_SCHOOLS_PER_DAY):
            if day_index >= len(days):
                break
            for row in rows[chunk_start : chunk_start + MAX_SCHOOLS_PER_DAY]:
                ProposedActivity.objects.create(
                    plan=plan,
                    school_id=row["school"].id,
                    school_name=row["school"].name,
                    area=area,
                    proposed_date=days[day_index],
                    activity_type=VISIT_ACTIVITY_TYPE,
                    catalogue_stable_code=VISIT_STABLE_CODE,
                    reason=row["reason"],
                )
            day_index += 1
        if day_index >= len(days):
            break
    return plan


@transaction.atomic
def accept_plan(plan: ProposedPlan, *, principal) -> dict:
    """Accept Week: every item goes through the canonical create() funnel —
    catalogue eligibility, scheduling policy, duplicate prevention and
    costing all apply exactly as they would to a hand-built plan. Items the
    funnel refuses are reported, never forced."""

    plan = ProposedPlan.objects.select_for_update().get(pk=plan.pk)
    if plan.status != ProposedPlanStatus.PROPOSED:
        raise BadRequest("Only a live proposal can be accepted.")
    actor_staff_id = str(getattr(principal, "staff_profile_id", "") or "")
    if actor_staff_id != str(plan.staff_id) and (
        getattr(principal, "active_role", "") != "Admin"
    ):
        raise BadRequest("A proposed week is accepted by its owner.")
    from apps.activities import services as activity_services
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.core.fy import get_operational_fy

    from apps.schools.models import School

    # ProposedActivity.school_id holds the School PK (the assignment-table
    # convention); create() expects the BUSINESS code (School.school_id) —
    # two identifier spaces that silently diverged and refused every item.
    business_codes = dict(
        School.objects.filter(
            id__in=[item.school_id for item in plan.items.all()]
        ).values_list("id", "school_id")
    )
    created, refused = [], []
    for item in plan.items.all():
        catalogue_item = ActivityCatalogueItem.objects.filter(
            stable_code=item.catalogue_stable_code
        ).first()
        catalogue_ref = {"catalogueItemId": catalogue_item.id} if catalogue_item else {}
        try:
            result = activity_services.create(
                {
                    "activityType": item.activity_type,
                    "schoolId": business_codes.get(item.school_id, item.school_id),
                    "responsibleStaffId": str(plan.staff_id),
                    "fy": get_operational_fy(item.proposed_date),
                    "scheduledDate": item.proposed_date.isoformat(),
                    "activityPurposeText": (f"Accepted weekly plan — {item.reason}"),
                    "purposeType": "weekly_plan",
                    **catalogue_ref,
                },
                principal=principal,
            )
        except Exception as exc:  # noqa: BLE001 — surfaced per item, never hidden
            refused.append({"school": item.school_name, "error": str(exc)})
            continue
        item.created_activity_id = (
            result.get("id", "") if isinstance(result, dict) else ""
        )
        item.save(update_fields=["created_activity_id", "updated_at"])
        created.append(item.created_activity_id)
    plan.status = ProposedPlanStatus.ACCEPTED
    plan.accepted_by = str(getattr(principal, "id", ""))
    plan.accepted_at = timezone.now()
    # Durable acceptance record (audit finding: refusals lived only in a
    # flash message and vanished on refresh). The rationale carries what
    # the funnel decided, per item, forever.
    plan.rationale = {
        **(plan.rationale or {}),
        "acceptance": {"created": created, "refused": refused},
    }
    plan.save(
        update_fields=[
            "status",
            "accepted_by",
            "accepted_at",
            "rationale",
            "updated_at",
        ]
    )
    return {"created": created, "refused": refused}


def dismiss_plan(plan: ProposedPlan, *, principal) -> None:
    if plan.status != ProposedPlanStatus.PROPOSED:
        raise BadRequest("Only a live proposal can be dismissed.")
    plan.status = ProposedPlanStatus.DISMISSED
    plan.save(update_fields=["status", "updated_at"])


def generate_weekly_proposals_for_all() -> int:
    """The autopilot's automatic producer (audit finding: preparation itself
    cost the staff member a click). Every Friday, draft next week for every
    active CCEO with a portfolio; accepted weeks are left alone, stale drafts
    supersede. One failure never blocks the rest of the roster."""

    from apps.accounts.models import StaffProfile

    staff_ids = (
        StaffProfile.objects.filter(
            deleted_at__isnull=True,
            user__status="active",
            user__roles__contains=["CCEO"],
            school_links__isnull=False,
        )
        .distinct()
        .values_list("id", flat=True)
    )
    generated = 0
    week_start = _next_week_start()
    for staff_id in staff_ids:
        staff = StaffProfile.objects.select_related("user").get(id=staff_id)
        try:
            generate_week_proposal(staff, week_start=week_start)
            generated += 1
        except BadRequest:
            continue  # accepted week — final, never regenerated over
        except Exception:  # noqa: BLE001 — one person never blocks the roster
            logger.warning(
                "weekly proposal generation failed for staff %s",
                staff_id,
                exc_info=True,
            )
    return generated


def live_proposal_for(staff) -> ProposedPlan | None:
    if staff is None:
        return None
    return (
        ProposedPlan.objects.filter(
            staff_id=staff if isinstance(staff, str) else staff.id,
            status=ProposedPlanStatus.PROPOSED,
        )
        .prefetch_related("items")
        .order_by("-week_start")
        .first()
    )
