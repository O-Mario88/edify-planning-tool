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
        Activity.objects.filter(responsible_staff_id__in=ids, deleted_at__isnull=True)
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


@transaction.atomic
def open_offboarding(
    staff_profile,
    principal,
    *,
    last_working_day,
    exit_reason: str,
    handover_owner=None,
    note: str = "",
):
    """Start an exit: record the last working day, why, and who takes over.

    Nothing created an offboarding plan except a probation decision to end
    employment, so a resignation had nowhere to be recorded and turnover could
    not be counted (HR audit, 2026-09-12). Closing still goes through
    `complete_offboarding`, which refuses while work is attached.
    """
    from apps.hr.models import ExitReason, OffboardingPlan
    from apps.hr.reach import people_reach

    _assert_may_offboard(principal)
    if staff_profile is None:
        raise BadRequest("Choose the employee who is leaving.")
    if not people_reach(principal).allows_country(staff_profile.country):
        raise Forbidden("You may only offboard staff in the countries you oversee.")
    if staff_profile.user_id and staff_profile.user_id == getattr(
        principal, "user_id", None
    ):
        raise Forbidden("You cannot start your own offboarding.")
    if not last_working_day:
        raise BadRequest("Record the last working day.")
    if exit_reason not in ExitReason.values:
        raise BadRequest("Choose why the employee is leaving.")
    if handover_owner is not None and handover_owner.id == staff_profile.id:
        raise BadRequest("The handover owner must be someone else.")

    plan = (
        OffboardingPlan.objects.select_for_update().filter(staff=staff_profile).first()
    )
    if plan is not None and plan.status == "Closed":
        raise BadRequest("This employee has already been offboarded.")
    if plan is None:
        plan = OffboardingPlan(staff=staff_profile, status="Initiated")
    plan.last_working_day = last_working_day
    plan.exit_reason = exit_reason
    plan.exit_note = note or ""
    plan.handover_owner = handover_owner
    plan.save()

    from apps.audit.services import log as audit_log

    audit_log(
        action="hr.offboarding_opened",
        subject_kind="offboarding_plan",
        subject_id=plan.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_principal_role(principal),
        payload={
            "staffId": staff_profile.id,
            "lastWorkingDay": str(last_working_day),
            "exitReason": exit_reason,
            "handoverOwnerId": getattr(handover_owner, "id", None),
        },
    )
    return plan


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
