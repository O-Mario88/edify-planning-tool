"""Which activities a bulk upload may complete, and where each one stands.

Everything here reads the platform's own vocabularies (apps.core
.activity_types, apps.activities.services) so "already completed" means here
exactly what it means on My Plan, the calendar and the monitors.
"""

from __future__ import annotations

from apps.core.activity_types import (
    COMPLETED_WORK_STATUSES,
    NOT_IN_PLAN_ACTIVITY_STATUSES,
    TRAINING_TYPES,
    VISIT_TYPES,
)

from .models import BulkKind

#: The activity types each upload completes.
KIND_TYPES: dict[str, tuple[str, ...]] = {
    BulkKind.VISIT: tuple(VISIT_TYPES),
    BulkKind.TRAINING: tuple(TRAINING_TYPES),
}

#: Staff work handed in with its ID is marked completed at once and counted
#: once its reviewer approves it (owner, 2026-10-15). Partner work waiting for
#: Impact Assessment is the exception: the partner has uploaded its form, and
#: IA's confirmation with the Salesforce ID is what completes it.
HANDED_IN_STATUSES = ("submitted_to_pl", "awaiting_ia_verification")

CALLED_OFF_STATUSES = (*NOT_IN_PLAN_ACTIVITY_STATUSES, "awaiting_owner_approval")


def is_partner(activity) -> bool:
    return getattr(activity, "delivery_type", "") == "partner"


def is_done(activity) -> bool:
    """The work is completed: handed in, verified or closed."""
    status = activity.status
    if status in COMPLETED_WORK_STATUSES:
        return True
    if status in HANDED_IN_STATUSES:
        return not (is_partner(activity) and status == "awaiting_ia_verification")
    return activity.ia_verification_status == "confirmed"


def is_called_off(activity) -> bool:
    return activity.deleted_at is not None or activity.status in CALLED_OFF_STATUSES


def is_open(activity) -> bool:
    """Scheduled, under way or returned for correction: completable."""
    from apps.activities.services import STARTABLE_STATUSES, SUBMITTABLE_STATUSES

    if is_partner(activity):
        return activity.status == "awaiting_ia_verification"
    return activity.status in (*STARTABLE_STATUSES, *SUBMITTABLE_STATUSES)


def activities_in_reach(principal):
    """The live activities this uploader's country lens holds.

    Completion itself asks the full question again for every row
    (apps.activities.services._get_for_execution); this keeps the matching
    and the prefilled template inside the uploader's country.
    """
    from apps.activities.models import Activity
    from apps.core.scoping import activity_country_q, resolve_user_scope

    scope = resolve_user_scope(principal)
    return Activity.objects.filter(deleted_at__isnull=True).filter(
        activity_country_q(scope)
    )


def schools_in_reach(principal, school_codes):
    """({code: School} inside the uploader's country, {code: School} outside).

    The SSA import's rule, shared: a School ID elsewhere in the deployment is
    refused, never written onto another country's school.
    """
    from apps.ssa.upload_service import _schools_in_reach

    return _schools_in_reach(principal, school_codes)


def may_bulk_complete(principal) -> bool:
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission

    return has_permission(principal, Permission.ACTIVITY_BULK_COMPLETE.value)
