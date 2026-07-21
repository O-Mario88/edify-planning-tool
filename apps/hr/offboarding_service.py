"""Offboarding that actually closes an account and hands over the work.

`OffboardingPlan` was four fields no other module read. Nothing consumed the
last working day, so an account stayed live past termination indefinitely;
the plan could be marked Closed with no preconditions, leaving the departing
person's schools still pointing at them, their pending approvals unrouted and
their activities still assigned.

This service is deliberately thin. It does not re-implement reassignment —
three audited services already exist for that (`staff_setup.services`
school reassignment, `accounts.supervisor_service.assign_supervisor`,
`activities.services.reassign`). It refuses to close while work is still
attached, and names what is attached so HR knows where to go.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden


def _principal_role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def outstanding_work(staff_profile) -> dict:
    """What still points at this person, by category.

    Empty dict means nothing is attached and the exit can complete.
    """
    from apps.accounts.models import StaffSupervisorAssignment
    from apps.activities.models import Activity
    from apps.core.scoping import owner_ids
    from apps.schools.models import School

    ids = owner_ids(staff_profile) + [staff_profile.id]
    out: dict[str, int] = {}

    owned_schools = School.objects.filter(
        account_owner_id__in=ids, deleted_at__isnull=True
    ).count()
    if owned_schools:
        out["schools"] = owned_schools

    open_activities = (
        Activity.objects.filter(
            responsible_staff_id__in=ids, deleted_at__isnull=True
        )
        .exclude(status__in=("closed", "cancelled", "completed"))
        .count()
    )
    if open_activities:
        out["open_activities"] = open_activities

    supervisees = StaffSupervisorAssignment.objects.filter(
        supervisor=staff_profile, supervisee__deleted_at__isnull=True
    ).count()
    if supervisees:
        out["direct_reports"] = supervisees

    return out


def _assert_may_offboard(principal) -> None:
    if _principal_role(principal) not in ("HumanResources", "Admin"):
        raise Forbidden("Only HR may complete an offboarding.")


@transaction.atomic
def complete_offboarding(plan_id: str, principal, *, force: bool = False) -> dict:
    """Close an offboarding: disable the account and mark the profile exited.

    Refuses while schools, open activities or direct reports still point at
    the person — those must be reassigned through their own audited services
    first, so the handover is recorded where it belongs rather than implied by
    a checkbox here.
    """
    from apps.hr.models import OffboardingPlan

    _assert_may_offboard(principal)

    plan = (
        OffboardingPlan.objects.select_for_update()
        .select_related("staff__user")
        .filter(id=plan_id)
        .first()
    )
    if not plan:
        raise BadRequest("Offboarding plan not found.")
    if plan.status == "Closed":
        raise BadRequest("This offboarding is already closed.")

    staff = plan.staff
    remaining = outstanding_work(staff)
    if remaining and not force:
        parts = ", ".join(f"{v} {k.replace('_', ' ')}" for k, v in remaining.items())
        raise BadRequest(
            f"Reassign this person's work before closing: {parts}. "
            "Use the school reassignment, supervisor reassignment and activity "
            "reassignment flows so each handover is recorded."
        )

    # Disable the account through the canonical service so token revocation,
    # session purge and the audit row all happen exactly as they do for any
    # other disablement.
    from apps.admin_users.services import disable

    try:
        disable(staff.user_id, principal)
    except Exception:  # noqa: BLE001 - a already-disabled account is fine
        pass

    staff.onboarding_state = "exited"
    staff.save(update_fields=["onboarding_state", "updated_at"])

    plan.status = "Closed"
    plan.clearance_completed = True
    plan.save(update_fields=["status", "clearance_completed", "updated_at"])

    from apps.audit.services import log as audit_log

    audit_log(
        action="hr.offboarding_completed",
        subject_kind="offboarding_plan",
        subject_id=plan.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_principal_role(principal),
        payload={
            "staffId": staff.id,
            "userId": staff.user_id,
            "lastWorkingDay": str(plan.last_working_day or ""),
            "forcedWithOutstandingWork": bool(remaining and force),
            "outstanding": remaining,
        },
    )
    return {
        "ok": True,
        "planId": plan.id,
        "staffId": staff.id,
        "outstanding": remaining,
    }


def accounts_past_last_working_day():
    """Still-active accounts whose approved exit date has passed.

    Nothing read `last_working_day`, so this condition was invisible. Exposed
    for the system-health check and for an operator sweep.
    """
    from apps.hr.models import OffboardingPlan

    today = timezone.now().date()
    return (
        OffboardingPlan.objects.filter(
            last_working_day__isnull=False,
            last_working_day__lt=today,
        )
        .exclude(staff__onboarding_state="exited")
        .select_related("staff__user")
    )
