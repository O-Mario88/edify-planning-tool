"""A visit at a Core School is core package work, wherever it was scheduled.

The Core Schools page has always treated it that way: every purpose its visit
drawer offers creates a ``core_visit`` priced against the Core Visit costing
and locks one of the package's visit slots.

The Planning page's Core tab and the Cluster schools table open the SAME
drawer -- both point at ``/planning/schedule-modal`` -- and that drawer went
through ``schedule_school_visit``, which created a plain ``school_visit`` with
no slot. So a visit planned from either surface was invisible on the Core
School Visit page, counted toward no package, was priced as client work, and
was not seen by the visit gate's core caps (``is_gated_visit`` matches on
``activity_type == "core_visit"``). Three surfaces, two answers to "what is a
visit at a core school".

The rule lives here, not in either view, because both of those surfaces share
one POST handler and the Core Schools page has its own: what a core school's
visit IS belongs to the core package, not to whichever page is open.

Trainings are deliberately not routed here. Cluster sessions already credit
core training slots through :mod:`apps.core_schools.cluster_credit`, and an
in-school training pair is a different workflow with its own entry point.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.exceptions import BadRequest
from apps.planning.visit_gate import CORE_RULE_SCHOOL_TYPES

#: The activity type every core package visit carries, whatever its purpose.
CORE_VISIT_TYPE = "core_visit"


def resolve_school(school_ref):
    """The School a payload's ``schoolId`` names, or None.

    ``CorePlan.school_id`` holds the BUSINESS school id while some callers
    hold a primary key, so both are accepted and the business id is what is
    read back off the returned row.
    """
    if not school_ref:
        return None
    from django.db.models import Q

    from apps.schools.models import School

    return School.objects.filter(Q(id=school_ref) | Q(school_id=school_ref)).first()


def core_plan_for_visit(school, *, scheduled_date=None):
    """The live Core package a visit at this school would belong to.

    None when the school is not on the core rule, or carries no package for
    the fiscal year the visit falls in. Both are ordinary cases: the visit is
    then scheduled exactly as it was before, so a school without a package
    never becomes unschedulable because of this routing.
    """
    if school is None or school.school_type not in CORE_RULE_SCHOOL_TYPES:
        return None

    from apps.core.fy import get_operational_fy
    from apps.core_schools.services import get_live_core_plan

    fy = get_operational_fy(scheduled_date) if scheduled_date else get_operational_fy()
    plan = get_live_core_plan(school.school_id, fy)
    if plan is None and scheduled_date is not None:
        # Planned into a year the school has no package for yet. The package
        # it does have is the one this work belongs to -- the FY restriction
        # on core scheduling was lifted on 2026-09-17, so a package's work is
        # allowed to land outside its own year.
        plan = get_live_core_plan(school.school_id, get_operational_fy())
    return plan


def _parse_date(value):
    if not value:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def core_visit_catalogue_item(on_date=None):
    """The Catalogue item that prices a Core School visit."""
    from apps.activity_catalogue.services import resolve_item_for_workflow_kind

    item = resolve_item_for_workflow_kind(CORE_VISIT_TYPE, on_date=on_date)
    if item is None:
        raise BadRequest(
            "No approved Catalogue Activity costs a Core School visit. "
            "Ask the Country Director to configure one."
        )
    return item


def next_visit_sequence(plan) -> int:
    """The visit slot this work should take.

    The Core Schools drawer asks the planner which slot; the Planning and
    Cluster drawers have no such field, so the next open one answers. The
    sequence is a hint either way -- ``_free_slot`` takes the next free slot
    when this one is gone, and creates one when the package has run out, so
    this never becomes a refusal.
    """
    from apps.core_schools.core_planning_services import CorePackageSchedulingService

    available = CorePackageSchedulingService.available_sequences(plan, "visit")
    return available[0] if available else 1


@transaction.atomic
def schedule_as_core_visit(data: dict, principal) -> dict | None:
    """Schedule this visit as core package work, or None if it is not core.

    Returns what ``apps.activities.services.create`` returns, so a caller can
    hand the result straight back. None means "not a core school visit" and
    the caller schedules it in the ordinary way.
    """
    from apps.activities.services import create as create_activity
    from apps.core_schools.core_planning_services import CorePackageSchedulingService

    if data.get("projectId"):
        # Project work is the project's, not the package's. It is funded from
        # the project's own approved activity list -- the caller has already
        # validated the Catalogue item as eligible for every school in the
        # batch -- so routing it here would re-cost it against the Core Visit
        # item and count somebody else's delivery as core package support.
        return None

    school = resolve_school(data.get("schoolId"))
    scheduled_date = _parse_date(data.get("scheduledDate"))
    plan = core_plan_for_visit(school, scheduled_date=scheduled_date)
    if plan is None:
        return None

    item = core_visit_catalogue_item(on_date=scheduled_date)
    partner_id = str(data.get("assignedPartnerId") or "").strip() or None
    is_partner_delivery = bool(partner_id) or data.get("deliveryType") == "partner"

    # Locks the slot and applies the two caps the package exists to protect:
    # staff deliver at most two of its visits, the partner at most two.
    slot = CorePackageSchedulingService.assert_can_schedule(
        plan=plan,
        school=school,
        activity_type="visit",
        sequence_number=next_visit_sequence(plan),
        scheduled_for=scheduled_date,
        is_partner_delivery=is_partner_delivery,
    )

    payload = {
        **data,
        "activityType": CORE_VISIT_TYPE,
        "catalogueItemId": item.id,
        "requireCatalogue": True,
    }
    # `create` refuses a core type without this, which is what stops a raw
    # POST from making core work with no slot behind it. It is set here
    # because a slot was locked immediately above.
    created = create_activity(payload, principal, core_slot_verified=True)

    CorePackageSchedulingService.commit_schedule(
        slot,
        activity_id=created["id"],
        scheduled_for=scheduled_date,
        scheduled_month=str(payload.get("plannedMonth") or ""),
        scheduled_week=payload.get("plannedWeek"),
        assigned_staff_id=str(data.get("responsibleStaffId") or ""),
        partner_id=partner_id,
    )
    return created
