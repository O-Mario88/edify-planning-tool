"""Onboarding and probation — with due dates, so "overdue" can exist.

`OnboardingPlan` had no writer, no target date and no owner per task, so the
view's "Overdue" metric filtered on a status nothing could ever set and
neither HR nor a manager could see a late task anywhere. `OnboardingTask`
carried a name and a completion flag and nothing else.

Closing an onboarding is what finally flips `StaffProfile.onboarding_state`
to active — the state that, until now, nothing outside the demo seeder ever
wrote, which is why nobody on a live deployment could be nominated to cover
anyone's leave.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.hr.models import (
    OnboardingPlan,
    OnboardingStatus,
    OnboardingTask,
    PerformanceReview,
    ReviewStage,
    ReviewType,
)

_HR_ROLES = {"HumanResources", "Admin"}

#: The starting checklist. Owner-role matters: an employee cannot complete
#: the account-provisioning task, and Admin cannot sign the policies.
DEFAULT_TASKS = [
    ("Welcome pack and role expectations shared", "orientation", "hr", 3),
    ("System accounts and access provisioned", "systems", "admin", 3),
    ("Required policies read and acknowledged", "policy", "employee", 7),
    ("Employment documents submitted", "documents", "employee", 7),
    ("Equipment issued", "equipment", "admin", 7),
    ("Supervisor introduction and first-week plan agreed", "orientation", "manager", 7),
    ("Role training started", "training", "manager", 30),
    ("30-day check-in held", "milestone", "manager", 30),
    ("60-day check-in held", "milestone", "manager", 60),
    ("90-day review scheduled", "milestone", "manager", 90),
]


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def _assert_hr(principal) -> None:
    if _role(principal) not in _HR_ROLES:
        raise Forbidden("Only HR may manage onboarding.")


def _audit(action: str, plan, principal, payload=None) -> None:
    from apps.audit.services import log as audit_log

    audit_log(
        action=action,
        subject_kind="onboarding_plan",
        subject_id=plan.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_role(principal),
        payload={"staffId": plan.staff_id, **(payload or {})},
    )


@transaction.atomic
def open_onboarding(staff_profile, principal, *, application=None, start_date=None):
    """Create the plan and its checklist for a new employee."""
    _assert_hr(principal)
    existing = OnboardingPlan.objects.filter(staff=staff_profile).first()
    if existing:
        return existing

    start = start_date or timezone.now().date()
    plan = OnboardingPlan.objects.create(
        staff=staff_profile,
        status=OnboardingStatus.IN_PROGRESS,
        start_date=start,
        # Every task has a due date, and the plan has one, because a plan
        # that cannot be late cannot be chased.
        target_completion_date=start + timedelta(days=90),
        probation_review_date=start + timedelta(days=90),
        source_application=application,
    )
    OnboardingTask.objects.bulk_create(
        [
            OnboardingTask(
                plan=plan,
                name=name,
                category=category,
                owner_role=owner,
                due_date=start + timedelta(days=offset),
            )
            for name, category, owner, offset in DEFAULT_TASKS
        ]
    )
    _audit("hr.onboarding_opened", plan, principal, {"taskCount": len(DEFAULT_TASKS)})
    return plan


@transaction.atomic
def complete_task(task_id: str, principal) -> OnboardingTask:
    """Mark one checklist item done. The owner or HR may do it."""
    task = (
        OnboardingTask.objects.select_for_update()
        .select_related("plan__staff")
        .filter(id=task_id)
        .first()
    )
    if not task:
        raise BadRequest("Onboarding task not found.")
    is_hr = _role(principal) in _HR_ROLES
    is_owner = task.plan.staff.user_id == getattr(principal, "user_id", None)
    if not (is_hr or is_owner):
        raise Forbidden("Only HR or the employee may complete this task.")
    if task.is_completed:
        return task
    task.is_completed = True
    task.completed_at = timezone.now()
    task.completed_by_id = getattr(principal, "user_id", None)
    task.save(
        update_fields=["is_completed", "completed_at", "completed_by", "updated_at"]
    )
    return task


@transaction.atomic
def confirm_readiness(plan_id: str, principal) -> OnboardingPlan:
    """The supervisor confirms the person is ready to be activated."""
    plan = (
        OnboardingPlan.objects.select_for_update()
        .select_related("staff")
        .filter(id=plan_id)
        .first()
    )
    if not plan:
        raise BadRequest("Onboarding plan not found.")

    from apps.accounts.models import StaffSupervisorAssignment

    is_supervisor = StaffSupervisorAssignment.objects.filter(
        supervisee=plan.staff,
        supervisor__user_id=getattr(principal, "user_id", None),
    ).exists()
    if not (is_supervisor or _role(principal) in _HR_ROLES):
        raise Forbidden("Only this employee's supervisor or HR may confirm readiness.")

    plan.supervisor_confirmed_at = timezone.now()
    plan.status = OnboardingStatus.READY_FOR_ACTIVATION
    plan.save(update_fields=["supervisor_confirmed_at", "status", "updated_at"])
    _audit("hr.onboarding_readiness_confirmed", plan, principal)
    return plan


@transaction.atomic
def close_onboarding(plan_id: str, principal, *, force: bool = False):
    """Close onboarding, activate the profile, and open probation.

    This is the writer `StaffProfile.onboarding_state` never had. Until it
    existed, every real employee stayed "pending" forever while coverage
    eligibility filtered on "active" — so the leave-coverage picker returned
    an empty list for everyone on a live deployment.
    """
    _assert_hr(principal)
    plan = (
        OnboardingPlan.objects.select_for_update()
        .select_related("staff")
        .filter(id=plan_id)
        .first()
    )
    if not plan:
        raise BadRequest("Onboarding plan not found.")
    if plan.status == OnboardingStatus.CLOSED:
        raise BadRequest("This onboarding is already closed.")

    outstanding = list(
        plan.tasks.filter(is_completed=False).values_list("name", flat=True)
    )
    if outstanding and not force:
        raise BadRequest(
            f"{len(outstanding)} onboarding task(s) are still open: "
            + "; ".join(outstanding[:3])
            + ("…" if len(outstanding) > 3 else "")
        )

    plan.status = OnboardingStatus.CLOSED
    plan.closed_at = timezone.now()
    plan.save(update_fields=["status", "closed_at", "updated_at"])

    staff = plan.staff
    if staff.onboarding_state == "pending":
        staff.onboarding_state = "active"
        staff.save(update_fields=["onboarding_state", "updated_at"])

    review = start_probation(staff, principal, due_date=plan.probation_review_date)
    _audit(
        "hr.onboarding_closed",
        plan,
        principal,
        {
            "forcedWithOpenTasks": bool(outstanding and force),
            "probationReviewId": review.id,
        },
    )
    return plan


@transaction.atomic
def start_probation(staff_profile, principal, *, due_date=None) -> PerformanceReview:
    """Open the probation review. Probation had no representation at all —
    Confirm / Extend / End Employment existed nowhere in the schema."""
    due = due_date or (timezone.now().date() + timedelta(days=90))
    existing = PerformanceReview.objects.filter(
        staff=staff_profile, review_type=ReviewType.PROBATION
    ).first()
    if existing:
        return existing
    return PerformanceReview.objects.create(
        staff=staff_profile,
        period=f"Probation to {due}",
        review_type=ReviewType.PROBATION,
        stage=ReviewStage.PRIORITIES_AGREED,
        status="Probation in progress",
        due_date=due,
    )


@transaction.atomic
def decide_probation(
    review_id: str, principal, *, decision: str, reason: str, extend_days: int = 0
) -> PerformanceReview:
    """Confirm employment, extend probation, or end employment."""
    from apps.hr.models import ProbationDecision

    _assert_hr(principal)
    if decision not in ProbationDecision.values:
        raise BadRequest("Unknown probation decision.")
    if not (reason or "").strip():
        raise BadRequest("A reason is required for a probation decision.")

    review = (
        PerformanceReview.objects.select_for_update()
        .select_related("staff")
        .filter(id=review_id, review_type=ReviewType.PROBATION)
        .first()
    )
    if not review:
        raise BadRequest("Probation review not found.")
    if review.staff.user_id == getattr(principal, "user_id", None):
        raise Forbidden("You cannot decide your own probation.")

    if decision == ProbationDecision.EXTENDED:
        review.due_date = review.due_date + timedelta(days=extend_days or 30)
        review.status = "Probation extended"
    else:
        review.stage = ReviewStage.CLOSED
        review.closed_at = timezone.now()
        review.status = (
            "Confirmed" if decision == ProbationDecision.CONFIRMED else "Ended"
        )
    review.calibration_note = reason
    review.save()

    if decision == ProbationDecision.ENDED:
        # Ending employment is an exit; route it through the offboarding
        # service rather than disabling the account inline here.
        from apps.hr.models import OffboardingPlan

        OffboardingPlan.objects.get_or_create(
            staff=review.staff,
            defaults={
                "status": "Initiated",
                "last_working_day": timezone.now().date(),
            },
        )

    from apps.audit.services import log as audit_log

    audit_log(
        action=f"hr.probation_{decision}",
        subject_kind="performance_review",
        subject_id=review.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=_role(principal),
        payload={"staffId": review.staff_id, "reason": reason},
    )
    return review


def overdue_onboarding(scope_qs=None):
    """Plans past their target date, and open tasks past theirs."""
    today = timezone.now().date()
    plans = OnboardingPlan.objects.exclude(status=OnboardingStatus.CLOSED).filter(
        target_completion_date__lt=today
    )
    if scope_qs is not None:
        plans = plans.filter(staff_id__in=scope_qs)
    return plans


def overdue_tasks(scope_qs=None):
    today = timezone.now().date()
    tasks = OnboardingTask.objects.filter(
        is_completed=False, due_date__lt=today
    ).exclude(plan__status=OnboardingStatus.CLOSED)
    if scope_qs is not None:
        tasks = tasks.filter(plan__staff_id__in=scope_qs)
    return tasks
