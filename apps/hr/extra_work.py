"""Extra Assigned Work — the governed §18 module (built 2026-08-20).

The laws, stated once:
- Authority: the CD assigns to Program Leads and CCEOs; a Program Lead
  assigns only to CCEOs they currently supervise. Nobody assigns to
  themselves. Admin supports and views, but holds no assignment authority.
- Verification is independent: the reviewer (default: the assigner) confirms
  completion — the assignee never verifies their own work, enforced by a
  database constraint as well as here.
- Performance is separate and single-counted: verified extra work carries
  contribution points from the APPROVED scoring policy only. No approved
  policy → tracked but unscored, never invented. Extra work never touches
  distributed targets, milestone credits or the achievement ledger, so it
  can never double-count target achievement.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden

from .models import ExtraAssignment, ExtraWorkScoringPolicy

ASSIGNER_ROLES = {"CountryDirector", "Program Lead"}


def _actor(principal) -> str:
    return getattr(principal, "user_id", None) or str(principal.id)


def _notify(event_type, *, title, body, recipients, context_id, priority="normal"):
    try:
        from apps.notifications.services import WorkflowNotificationService

        recipients = [r for r in recipients if r]
        if recipients:
            WorkflowNotificationService.trigger(
                event_type=event_type,
                category="extra_work",
                priority=priority,
                title=title,
                body=body,
                context_type="extra_assignment",
                context_id=str(context_id),
                recipients=recipients,
            )
    except Exception:  # noqa: BLE001 — bookkeeping never blocks the workflow
        import logging

        logging.getLogger(__name__).warning(
            "extra-work notification failed", exc_info=True
        )


def _supervising_pl_user_id(assignee_user) -> str:
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    staff = StaffProfile.objects.filter(user=assignee_user).first()
    if staff is None:
        return ""
    return (
        StaffSupervisorAssignment.objects.filter(supervisee=staff)
        .values_list("supervisor__user_id", flat=True)
        .first()
        or ""
    )


@transaction.atomic
def create_assignment(principal, data: dict) -> ExtraAssignment:
    from django.contrib.auth import get_user_model

    role = getattr(principal, "active_role", "")
    if role not in ASSIGNER_ROLES:
        raise Forbidden(
            "Only the Country Director or a Program Lead may assign extra work."
        )

    User = get_user_model()
    assignee = User.objects.filter(id=data.get("assignee_id"), is_active=True).first()
    if assignee is None:
        raise BadRequest("Choose an active staff member to assign.")
    if str(assignee.id) == str(principal.id):
        raise BadRequest("You cannot assign extra work to yourself.")

    assignee_role = getattr(assignee, "active_role", "")
    if role == "CountryDirector":
        if assignee_role not in ("Program Lead", "CCEO"):
            raise BadRequest("The CD assigns extra work to Program Leads and CCEOs.")
    else:  # Program Lead
        if assignee_role != "CCEO":
            raise Forbidden("A Program Lead assigns extra work only to CCEOs.")
        from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

        pl_staff_id = getattr(principal, "staff_profile_id", None)
        assignee_staff = StaffProfile.objects.filter(user=assignee).first()
        if (
            assignee_staff is None
            or not StaffSupervisorAssignment.objects.filter(
                supervisor_id=pl_staff_id, supervisee=assignee_staff
            ).exists()
        ):
            raise Forbidden(
                "A Program Lead may assign extra work only to CCEOs they "
                "currently supervise."
            )

    title = (data.get("title") or "").strip()
    instruction = (data.get("instruction") or "").strip()
    due_date = data.get("due_date")
    if not title:
        raise BadRequest("Give the assignment a title.")
    if not instruction:
        raise BadRequest("Write the detailed instruction — the assignee acts on it.")
    if not due_date:
        raise BadRequest("Set a due date.")
    category = (data.get("category") or "").strip()
    if category not in {c[0] for c in ExtraAssignment.CATEGORIES}:
        raise BadRequest("Choose an assignment category.")

    reviewer_id = (data.get("reviewer_id") or "").strip() or _actor(principal)
    if str(reviewer_id) == str(assignee.id):
        raise BadRequest(
            "The reviewer cannot be the assignee — verification is independent."
        )

    from apps.core.fy import get_operational_fy

    fy = str(data.get("fy") or get_operational_fy())
    assignment = ExtraAssignment.objects.create(
        fy=fy,
        title=title,
        instruction=instruction,
        reason=(data.get("reason") or "").strip(),
        category=category,
        linked_priority_id=data.get("linked_priority_id") or None,
        linked_milestone_id=data.get("linked_milestone_id") or None,
        linked_activity_id=(data.get("linked_activity_id") or "").strip(),
        assigner_id=_actor(principal),
        assigner_role=role,
        assignee_id=str(assignee.id),
        assignee_role=assignee_role,
        supervising_pl_id=_supervising_pl_user_id(assignee),
        due_date=due_date,
        expected_output=(data.get("expected_output") or "").strip(),
        output_unit=(data.get("output_unit") or "").strip(),
        evidence_required=bool(data.get("evidence_required", True)),
        reviewer_id=str(reviewer_id),
        complexity=(data.get("complexity") or "medium"),
        urgency=(data.get("urgency") or "normal"),
        status="assigned",
    )
    _notify(
        "extra_work_assigned",
        title="Extra work assigned to you",
        body=f"{title} — due {assignment.due_date:%-d %b %Y}. Review and start it.",
        recipients=[assignment.assignee_id],
        context_id=assignment.id,
        priority="high" if assignment.urgency != "normal" else "normal",
    )
    # A CD assignment straight to a CCEO keeps the supervising PL informed —
    # they monitor it, they never own or alter it (§18.2).
    if (
        role == "CountryDirector"
        and assignee_role == "CCEO"
        and assignment.supervising_pl_id
    ):
        _notify(
            "extra_work_assigned_fyi",
            title="Extra work assigned on your team",
            body=(
                f"The Country Director assigned “{title}” to a CCEO you "
                "supervise. You can monitor it; the CD owns it."
            ),
            recipients=[assignment.supervising_pl_id],
            context_id=assignment.id,
        )
    _audit(assignment, principal, "extra_work.assigned", {"title": title})
    return assignment


def _audit(assignment, principal, action, payload):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="ExtraAssignment",
            subject_id=str(assignment.id),
            actor_id=_actor(principal),
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload=payload,
        )
    except Exception:  # noqa: BLE001
        pass


def _get_for(principal, assignment_id, *, as_role: str) -> ExtraAssignment:
    assignment = (
        ExtraAssignment.objects.select_for_update().filter(id=assignment_id).first()
    )
    if assignment is None:
        raise BadRequest("Assignment not found.")
    uid = str(principal.id)
    if as_role == "assignee" and assignment.assignee_id != uid:
        raise Forbidden("This assignment is not yours.")
    if as_role == "reviewer" and assignment.reviewer_id != uid:
        raise Forbidden("You are not the reviewer of this assignment.")
    if as_role == "assigner" and assignment.assigner_id != uid:
        raise Forbidden("You did not assign this work.")
    return assignment


@transaction.atomic
def acknowledge(principal, assignment_id) -> ExtraAssignment:
    a = _get_for(principal, assignment_id, as_role="assignee")
    if a.status != "assigned":
        raise BadRequest("Only a newly assigned task can be acknowledged.")
    a.status = "acknowledged"
    a.acknowledged_at = timezone.now()
    a.save(update_fields=["status", "acknowledged_at", "updated_at"])
    return a


@transaction.atomic
def start(principal, assignment_id) -> ExtraAssignment:
    a = _get_for(principal, assignment_id, as_role="assignee")
    if a.status not in ("assigned", "acknowledged", "returned"):
        raise BadRequest("This assignment cannot be started from its current state.")
    a.status = "in_progress"
    a.started_at = a.started_at or timezone.now()
    if not a.start_date:
        a.start_date = timezone.localdate()
    a.save(update_fields=["status", "started_at", "start_date", "updated_at"])
    return a


@transaction.atomic
def submit(principal, assignment_id, data: dict) -> ExtraAssignment:
    a = _get_for(principal, assignment_id, as_role="assignee")
    if a.status not in ("assigned", "acknowledged", "in_progress", "returned"):
        raise BadRequest("This assignment cannot be submitted from its current state.")
    outcome = (data.get("outcome") or "").strip()
    if not outcome:
        raise BadRequest("Describe the outcome — what was actually delivered.")
    evidence_note = (data.get("evidence_note") or "").strip()
    evidence_uri = (data.get("evidence_uri") or "").strip()
    if a.evidence_required and not (evidence_note or evidence_uri):
        raise BadRequest(
            "This assignment requires evidence — add the evidence note or link."
        )
    a.outcome = outcome
    a.evidence_note = evidence_note
    a.evidence_uri = evidence_uri
    a.status = "submitted"
    a.submitted_at = timezone.now()
    a.save(
        update_fields=[
            "outcome",
            "evidence_note",
            "evidence_uri",
            "status",
            "submitted_at",
            "updated_at",
        ]
    )
    _notify(
        "extra_work_submitted",
        title="Extra work submitted for review",
        body=f"“{a.title}” was submitted — review and verify or return it.",
        recipients=[a.reviewer_id],
        context_id=a.id,
        priority="high",
    )
    _audit(a, principal, "extra_work.submitted", {"outcome": outcome[:200]})
    return a


@transaction.atomic
def return_work(principal, assignment_id, reason: str) -> ExtraAssignment:
    a = _get_for(principal, assignment_id, as_role="reviewer")
    if a.status != "submitted":
        raise BadRequest("Only submitted work can be returned.")
    reason = (reason or "").strip()
    if not reason:
        raise BadRequest("Say what must be corrected.")
    a.status = "returned"
    a.return_reason = reason
    a.return_count += 1
    a.save(update_fields=["status", "return_reason", "return_count", "updated_at"])
    _notify(
        "extra_work_returned",
        title="Extra work returned for correction",
        body=f"“{a.title}”: {reason[:180]}",
        recipients=[a.assignee_id],
        context_id=a.id,
        priority="high",
    )
    _audit(a, principal, "extra_work.returned", {"reason": reason[:200]})
    return a


@transaction.atomic
def verify(principal, assignment_id, note: str = "") -> ExtraAssignment:
    a = _get_for(principal, assignment_id, as_role="reviewer")
    if str(principal.id) == a.assignee_id:
        raise Forbidden("The assignee can never verify their own extra work.")
    if a.status != "submitted":
        raise BadRequest("Only submitted work can be verified.")
    a.status = "verified"
    a.verified_at = timezone.now()
    a.verified_by = _actor(principal)
    a.completion_date = timezone.localdate()
    # Contribution enters performance ONCE, from the APPROVED policy only.
    policy = ExtraWorkScoringPolicy.objects.filter(fy=a.fy, status="approved").first()
    if policy is not None:
        from decimal import Decimal

        weights = policy.complexity_weights or {}
        points = Decimal(str(weights.get(a.complexity, 0)))
        if a.due_date and a.completion_date > a.due_date:
            points = (points * policy.overdue_multiplier).quantize(Decimal("0.01"))
        a.contribution_points = min(points, policy.max_contribution_points)
        a.scoring_policy = policy
    a.save(
        update_fields=[
            "status",
            "verified_at",
            "verified_by",
            "completion_date",
            "contribution_points",
            "scoring_policy",
            "updated_at",
        ]
    )
    _notify(
        "extra_work_verified",
        title="Extra work verified",
        body=(
            f"“{a.title}” is verified"
            + (
                f" — {a.contribution_points} performance point(s)."
                if a.contribution_points is not None
                else " — it is tracked; scoring awaits the approved policy."
            )
        ),
        recipients=[a.assignee_id, a.supervising_pl_id],
        context_id=a.id,
    )
    _audit(
        a,
        principal,
        "extra_work.verified",
        {"points": str(a.contribution_points), "note": (note or "")[:200]},
    )
    return a


@transaction.atomic
def cancel(principal, assignment_id, reason: str) -> ExtraAssignment:
    a = _get_for(principal, assignment_id, as_role="assigner")
    if a.status in ("verified", "cancelled"):
        raise BadRequest("Finished work cannot be cancelled.")
    a.status = "cancelled"
    a.cancelled_at = timezone.now()
    a.cancel_reason = (reason or "").strip()
    a.save(update_fields=["status", "cancelled_at", "cancel_reason", "updated_at"])
    _notify(
        "extra_work_cancelled",
        title="Extra work cancelled",
        body=f"“{a.title}” was cancelled by the assigner.",
        recipients=[a.assignee_id],
        context_id=a.id,
    )
    _audit(a, principal, "extra_work.cancelled", {"reason": (reason or "")[:200]})
    return a


def performance_summary(user_id: str, fy: str) -> dict:
    """The separate §18.8 performance lane: counted once, never mixed into
    target achievement."""
    from django.db.models import Sum

    rows = ExtraAssignment.objects.filter(assignee_id=str(user_id), fy=fy)
    today = timezone.localdate()
    verified = rows.filter(status="verified")
    policy = ExtraWorkScoringPolicy.objects.filter(fy=fy, status="approved").first()
    return {
        "total": rows.exclude(status="cancelled").count(),
        "verified": verified.count(),
        "open": rows.filter(status__in=ExtraAssignment.OPEN_STATUSES).count(),
        "submitted": rows.filter(status="submitted").count(),
        "overdue": rows.filter(
            status__in=ExtraAssignment.OPEN_STATUSES, due_date__lt=today
        ).count(),
        "points": verified.aggregate(s=Sum("contribution_points"))["s"],
        "policy_approved": policy is not None,
    }
