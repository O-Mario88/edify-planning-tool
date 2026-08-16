"""Guards and writes the explicit priority-allocation → Activity trace."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from apps.core.exceptions import BadRequest, Forbidden


def allocation_for_planning(*, allocation_id: str, principal):
    from apps.hr.models import MilestoneAllocation

    allocation = (
        MilestoneAllocation.objects.select_related(
            "employee__user", "milestone__priority"
        )
        .prefetch_related("milestone__activity_rules")
        .filter(id=allocation_id, status="approved")
        .first()
    )
    if allocation is None:
        raise BadRequest("Choose an approved personal priority allocation.")
    actor_staff_id = getattr(principal, "staff_profile_id", None)
    if not allocation.employee_id or str(allocation.employee_id) != str(actor_staff_id):
        raise Forbidden("You may plan work only against your own approved allocation.")
    return allocation


def link_activity(*, activity, allocation_id: str, principal, planned_contribution=None):
    from apps.hr.models import ActivityPriorityLink

    allocation = allocation_for_planning(
        allocation_id=allocation_id, principal=principal
    )
    if str(activity.fy) != str(allocation.milestone.priority.fy):
        raise BadRequest("The activity and priority allocation must use the same FY.")
    activity_owner_ids = {
        str(activity.responsible_staff_id or ""),
        str(activity.monitored_by_staff_id or ""),
    }
    if str(allocation.employee_id) not in activity_owner_ids:
        raise BadRequest(
            "The activity owner or partner-work monitor must be the priority allocation owner."
        )

    allowed_catalogue_ids = set(
        allocation.milestone.activity_rules.filter(active=True).values_list(
            "catalogue_item_id", flat=True
        )
    )
    if allowed_catalogue_ids and activity.catalogue_item_id not in allowed_catalogue_ids:
        raise BadRequest(
            "The selected Activity Catalogue item is not approved for this priority milestone."
        )
    contribution = None
    if planned_contribution not in (None, ""):
        try:
            contribution = Decimal(str(planned_contribution))
        except InvalidOperation as exc:
            raise BadRequest("Planned contribution must be numeric.") from exc
        if contribution <= 0:
            raise BadRequest("Planned contribution must be greater than zero.")

    link, _ = ActivityPriorityLink.objects.get_or_create(
        activity=activity,
        allocation=allocation,
        defaults={
            "is_primary": True,
            "planned_contribution": contribution,
            "linked_by": str(
                getattr(principal, "user_id", None) or getattr(principal, "id", "")
            ),
        },
    )
    return link
