"""Visits into somebody else's portfolio wait for that owner's yes.

Planning follows direct ownership (§10): a school belongs to the CCEO or
Programme Lead who owns it, and the country roles that hold no portfolio — the
Country Director, Impact Assessment and the Accountant — do not plan into it.
They still need to be at schools: a director's monitoring visit, an assessor's
verification, an accountant's spot check. The rule for that is one step, not
an exception to the rule:

1. The requester schedules the visit exactly as anyone else would, and says
   *why they need to be at this school* on top of the ordinary purpose.
2. The activity is created against the requester — they are the one going —
   in ``awaiting_owner_approval``, addressed to the school's owner.
3. The owner approves or declines from their Visit Requests queue. Approved,
   it becomes an ordinary scheduled activity: it lands on the requester's My
   Plan and calendar and enters funding from that moment. Declined, it is
   rejected with the owner's reason, and the requester is told.

Cluster meetings and trainings are the cluster owner's programme; these three
roles never plan them, owned or not. A school that nobody owns has nobody to
ask, so a visit there is simply scheduled — for all three roles alike
(owner, 2026-09-02: "they can only schedule visits, and to any school").

State lives on the Activity — status plus the ``visit_justification`` /
``approval_owner_id`` / ``owner_decided_*`` columns — the same shape as the
PL review handoff, so every surface that already reads status keeps working
and nothing needs a second table to reconcile.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.activities.models import Activity
from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.scoping import VISIT_REQUEST_ROLES, owner_ids

AWAITING = "awaiting_owner_approval"

EVENT_REQUESTED = "school_visit_requested"
EVENT_APPROVED = "school_visit_approved"
EVENT_DECLINED = "school_visit_declined"

QUEUE_URL = "/planning/visit-requests"

JUSTIFICATION_REQUIRED = (
    "Explain why you need to visit this school. The request goes to the "
    "school's owner, who decides on it."
)


def is_requester(principal) -> bool:
    return getattr(principal, "active_role", None) in VISIT_REQUEST_ROLES


def approval_owner_for(school, principal) -> str | None:
    """The StaffProfile id whose approval a visit by `principal` needs.

    None when the request path does not apply: the principal is not a
    request-only role, the school has no owner to ask, or the principal owns
    it themselves.
    """
    if school is None or not is_requester(principal):
        return None
    from apps.clusters.eligibility import portfolio_owner_profile_id, school_owner_ids

    if school_owner_ids(school) & set(owner_ids(principal)):
        return None
    return portfolio_owner_profile_id(school) or None


CLUSTER_REFUSED = (
    "Cluster meetings and trainings are planned by the CCEO or Program Lead "
    "responsible for the cluster. Your role schedules school visits only."
)


def refuse_cluster(cluster_id: str | None, principal) -> None:
    """A request-only role never plans cluster work, whoever holds the cluster."""
    if cluster_id and is_requester(principal):
        raise Forbidden(CLUSTER_REFUSED)


# ── The owner's queue ────────────────────────────────────────────────────────


def pending_for_owner(principal):
    """Requests waiting on THIS owner, oldest first."""
    mine = owner_ids(principal)
    if not mine:
        return Activity.objects.none()
    return (
        Activity.objects.filter(
            deleted_at__isnull=True, status=AWAITING, approval_owner_id__in=mine
        )
        .select_related("school", "school__district")
        .order_by("planned_date", "created_at")
    )


def requests_by(principal, *, limit: int = 50):
    """Every request this person has made, newest first, whatever became of it."""
    mine = owner_ids(principal)
    if not mine:
        return Activity.objects.none()
    return (
        Activity.objects.filter(
            deleted_at__isnull=True,
            responsible_staff_id__in=mine,
        )
        .exclude(approval_owner_id="")
        .select_related("school", "school__district")
        .order_by("-created_at")[:limit]
    )


def _decidable(activity_id: str, principal) -> Activity:
    a = (
        Activity.objects.select_for_update()
        .filter(id=activity_id, deleted_at__isnull=True)
        .first()
    )
    if a is None:
        raise NotFoundError("Visit request not found.")
    if a.status != AWAITING:
        raise BadRequest("This visit request has already been decided.")
    if a.approval_owner_id not in owner_ids(principal):
        raise Forbidden("Only the owner of this school decides on visits to it.")
    return a


def approve(activity_id: str, principal, note: str = "") -> Activity:
    """The owner says yes: the request becomes an ordinary scheduled activity."""
    with transaction.atomic():
        a = _decidable(activity_id, principal)
        a.status = "scheduled" if a.scheduled_date else "planned"
        a.owner_decided_at = timezone.now()
        a.owner_decided_by = getattr(principal, "user_id", None) or principal.id
        a.owner_decision_note = (note or "").strip()[:512]
        a.save(
            update_fields=[
                "status",
                "owner_decided_at",
                "owner_decided_by",
                "owner_decision_note",
                "updated_at",
            ]
        )
        _price(a)
    _audit("visit_request_approve", a, principal, reason=a.owner_decision_note)
    _close_request_notice(a)
    _notify(
        a,
        EVENT_APPROVED,
        "Your visit was approved",
        f"{_person(principal)} approved your visit to {_where(a)}"
        f"{_on(a)}. It is now on your plan.",
        [a.responsible_staff_id],
    )
    return a


def decline(activity_id: str, principal, reason: str) -> Activity:
    """The owner says no, and says why. The reason travels to the requester."""
    reason = (reason or "").strip()
    if not reason:
        raise BadRequest("Give the requester a reason for declining.")
    with transaction.atomic():
        a = _decidable(activity_id, principal)
        a.status = "rejected"
        a.owner_decided_at = timezone.now()
        a.owner_decided_by = getattr(principal, "user_id", None) or principal.id
        a.owner_decision_note = reason[:512]
        a.last_reason = reason[:512]
        a.save(
            update_fields=[
                "status",
                "owner_decided_at",
                "owner_decided_by",
                "owner_decision_note",
                "last_reason",
                "updated_at",
            ]
        )
    _audit("visit_request_decline", a, principal, reason=reason)
    _release_core_slot(a)
    _close_request_notice(a)
    _notify(
        a,
        EVENT_DECLINED,
        "Your visit was declined",
        f"{_person(principal)} declined your visit to {_where(a)}{_on(a)}: "
        f"{reason}",
        [a.responsible_staff_id],
        priority="high",
    )
    return a


# ── The request itself ───────────────────────────────────────────────────────


def notify_requested(activity: Activity, principal) -> None:
    """Tell the owner a request has arrived. Called once, by `create`."""
    audit_log(
        action="visit_request_submitted",
        subject_kind="Activity",
        subject_id=activity.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        reason=activity.visit_justification,
        payload={
            "schoolId": activity.school_id,
            "activityType": activity.activity_type,
            "approvalOwnerId": activity.approval_owner_id,
        },
    )
    _notify(
        activity,
        EVENT_REQUESTED,
        "Visit request for your school",
        f"{_person(principal)} asks to visit {_where(activity)}{_on(activity)}: "
        f"{activity.visit_justification}",
        [activity.approval_owner_id],
    )


def owner_name(activity: Activity) -> str:
    from apps.accounts.models import StaffProfile

    owner = (
        StaffProfile.objects.filter(id=activity.approval_owner_id)
        .select_related("user")
        .first()
    )
    return (owner.user.name if owner and owner.user else "") or "the school's owner"


def staff_name(staff_id: str | None) -> str:
    """A StaffProfile id, as the person's name (empty when unresolvable)."""
    if not staff_id:
        return ""
    from apps.accounts.models import StaffProfile

    owner = StaffProfile.objects.filter(id=staff_id).select_related("user").first()
    return (owner.user.name if owner and owner.user else "") or ""


def requester_name(activity: Activity) -> str:
    from apps.core.calendar_policy import resolve_scheduling_user

    user = resolve_scheduling_user(activity.responsible_staff_id)
    return (getattr(user, "name", "") or "") or "A staff member"


# ── helpers ──────────────────────────────────────────────────────────────────


def _person(principal) -> str:
    return getattr(principal, "name", None) or "A staff member"


def _where(a: Activity) -> str:
    return a.school.name if a.school_id and a.school else "the school"


def _on(a: Activity) -> str:
    return f" on {a.planned_date:%-d %b %Y}" if a.planned_date else ""


def _audit(action: str, a: Activity, principal, reason: str | None = None) -> None:
    audit_log(
        action=action,
        subject_kind="Activity",
        subject_id=a.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        reason=reason or None,
        payload={
            "schoolId": a.school_id,
            "activityType": a.activity_type,
            "responsibleStaffId": a.responsible_staff_id,
            "approvalOwnerId": a.approval_owner_id,
            "status": a.status,
        },
    )


def _price(a: Activity) -> None:
    """Approved work is a plan from now on, and a plan is priced.

    `create` deliberately skipped the cost snapshot while the request waited:
    a pending visit must draw no money and must not dilute the day pool of
    the owner's own visits. The same single cost writer runs here instead —
    it pools the visit into that day's batch, writes its cost lines and
    rebuilds the requester's weekly and monthly drafts, exactly as if the
    visit had been scheduled outright at this moment. Inside the approval
    transaction on purpose: an approval whose pricing failed would be a
    scheduled visit with no budget lines, the state the snapshot's own
    atomicity exists to prevent.
    """
    if not a.scheduled_date:
        return
    from apps.activities.services import _apply_schedule_cost_snapshot

    _apply_schedule_cost_snapshot(a, {}, principal=None)


def _release_core_slot(a: Activity) -> None:
    """A declined core visit hands its package slot back.

    Core work is scheduled into one of the school's 4 + 4 slots, and the slot
    was marked Scheduled against the request when it was made. Declined, the
    request is rejected, and the slot must be free for the owner to fill —
    otherwise a "no" would quietly consume one of the school's four visits.
    """
    try:
        from apps.core_schools.models import CoreActivitySlot
    except Exception:  # noqa: BLE001 - core schools app not installed
        return
    CoreActivitySlot.objects.filter(activity_id=a.id).update(
        status="Planned",
        activity_id=None,
        scheduled_for=None,
        scheduled_month=None,
        scheduled_week=None,
        assigned_staff_id=None,
        assigned_staff_name=None,
        owner="unassigned",
    )


def _close_request_notice(a: Activity) -> None:
    """The owner's queue no longer holds this request; close their notice."""
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition(EVENT_REQUESTED, "Activity", a.id)
    except Exception:  # noqa: BLE001 - bookkeeping never fails a decision
        pass


def _notify(a, event_type, title, body, recipients, priority="normal") -> None:
    """Best-effort — a notification failure must not undo the decision."""
    recipients = [r for r in (recipients or []) if r]
    if not recipients:
        return
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event_type,
            category="activity",
            priority=priority,
            title=title,
            body=body,
            context_type="Activity",
            context_id=a.id,
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001
        pass
