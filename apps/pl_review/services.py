"""PL review queue — CCEO completions routed to the supervising PL.

Every function here previously ignored its `principal`: `queue()` returned every
`submitted_to_pl` activity in the country, and `confirm()`/`return_activity()`
performed the transition with no supervision check, no self-check and no audit
row. Because the API is gated on `planning.view` — a permission Partner roles
also hold — a partner user could confirm another team's completions, and a CCEO
could confirm their own.

The rule this module enforces: a completion is reviewable only by the person who
supervises the staff member who submitted it (or an Admin), and never by the
submitter.
"""

from __future__ import annotations

from django.utils import timezone

from apps.activities.models import Activity
from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole


def _reviewer_staff_ids(principal) -> set[str]:
    """The staff whose completions this principal may review, in BOTH id spaces.

    `supervised_staff_ids` holds StaffProfile ids, but
    `Activity.responsible_staff_id` may hold either a StaffProfile id or a User
    id depending on which path wrote it (see `scoping.owner_ids`). Matching
    only one space would refuse legitimate reviews.

    Reads from the shared scope service, so active temporary coverage confers
    review authority exactly as it does for leave and PD approvals.
    """
    from apps.accounts.models import StaffProfile
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(principal)
    staff_ids = set(scope.supervised_staff_ids or [])
    if not staff_ids:
        return staff_ids
    user_ids = StaffProfile.objects.filter(id__in=staff_ids).values_list(
        "user_id", flat=True
    )
    return staff_ids | {u for u in user_ids if u}


def _is_admin(principal) -> bool:
    return getattr(principal, "active_role", "") == EdifyRole.ADMIN.value


def _own_ids(principal) -> set[str]:
    """Both id spaces a completion may be attributed to for this principal.

    `Activity.responsible_staff_id` holds either a User id or a StaffProfile id
    depending on the writer, so a self-check must cover both.
    """
    return {
        i
        for i in (
            getattr(principal, "user_id", None),
            getattr(principal, "staff_profile_id", None),
        )
        if i
    }


def _owning_staff_id(activity) -> str | None:
    """Who this completion belongs to for review purposes.

    Partner-delivered activities carry `responsible_staff_id=None` and record
    the scheduling staff member on `monitored_by_staff_id` instead — that
    person submits the completion, so they are who the reviewer supervises.
    """
    return activity.responsible_staff_id or getattr(
        activity, "monitored_by_staff_id", None
    )


def queue(principal) -> list[dict]:
    """Activities awaiting THIS reviewer's confirmation."""
    from django.db.models import Q

    from apps.activities.services import _serialize

    qs = Activity.objects.filter(deleted_at__isnull=True, status="submitted_to_pl")
    if not _is_admin(principal):
        reviewable = _reviewer_staff_ids(principal)
        if not reviewable:
            return []
        mine = _own_ids(principal)
        # Staff-delivered work is attributed by responsible_staff_id; partner
        # work by the monitoring staff member. Never surface the reviewer's
        # own submission, whichever id space it was written in.
        qs = qs.filter(
            Q(responsible_staff_id__in=reviewable)
            | Q(
                responsible_staff_id__isnull=True,
                monitored_by_staff_id__in=reviewable,
            )
        ).exclude(
            Q(responsible_staff_id__in=mine)
            | Q(responsible_staff_id__isnull=True, monitored_by_staff_id__in=mine)
        )
    return [
        _serialize(a)
        for a in qs.select_related("school").order_by("-updated_at")
    ]


def _get_reviewable(activity_id: str, principal) -> Activity:
    a = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not a:
        raise NotFoundError("Activity not found.")
    if a.status != "submitted_to_pl":
        raise BadRequest("Activity is not awaiting PL review.")
    if _is_admin(principal):
        return a
    owner = _owning_staff_id(a)
    if owner and owner in _own_ids(principal):
        raise Forbidden("You cannot review your own completion.")
    if owner not in _reviewer_staff_ids(principal):
        raise Forbidden("This completion belongs to another Program Lead's team.")
    return a


def _audit(action: str, activity: Activity, principal, reason: str | None = None):
    audit_log(
        action=action,
        subject_kind="Activity",
        subject_id=activity.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        reason=reason,
        payload={
            "schoolId": activity.school_id,
            "activityType": activity.activity_type,
            "responsibleStaffId": activity.responsible_staff_id,
            "status": activity.status,
        },
    )


def _close_review_notice(activity) -> None:
    """The PL's review queue no longer holds this activity.

    `activity_submitted_for_review` is fired at the supervising PL when a
    completion arrives. Nothing closed it: once the PL confirmed or returned
    the work, the derived To-Do disappeared while the notification stayed
    unread and was later promoted to urgent by the staleness job.
    """
    try:
        from apps.notifications.services import resolve_condition

        resolve_condition("activity_submitted_for_review", "Activity", activity.id)
    except Exception:  # noqa: BLE001 - never fail a review over bookkeeping
        pass


def confirm(activity_id: str, principal) -> dict:
    """PL confirms a CCEO completion -> routes to IA verification."""
    from apps.activities.services import _serialize

    a = _get_reviewable(activity_id, principal)
    a.status = "awaiting_ia_verification"
    reviewed_at = timezone.now()
    a.pl_reviewed_at = reviewed_at
    a.submitted_to_ia_at = reviewed_at
    a.pl_reviewed_by = principal.user_id
    a.save(
        update_fields=[
            "status",
            "pl_reviewed_at",
            "pl_reviewed_by",
            "submitted_to_ia_at",
            "updated_at",
        ]
    )
    _audit("pl_review_confirm", a, principal)
    _close_review_notice(a)
    _notify_after_review(
        a,
        "activity_submitted_for_review",
        "Activity awaiting verification",
        f"{getattr(principal, 'name', 'A reviewer')} confirmed a completion.",
        _impact_assessment_ids(),
    )
    return _serialize(a)


def return_activity(activity_id: str, data: dict, principal) -> dict:
    """PL returns a completion to the CCEO for correction."""
    from apps.activities.services import _serialize

    a = _get_reviewable(activity_id, principal)
    reason = (data or {}).get("reason")
    a.status = "returned_by_pl"
    a.pl_review_note = reason
    a.pl_reviewed_at = timezone.now()
    a.pl_reviewed_by = principal.user_id
    a.save(
        update_fields=[
            "status",
            "pl_review_note",
            "pl_reviewed_at",
            "pl_reviewed_by",
            "updated_at",
        ]
    )
    _audit("pl_review_return", a, principal, reason=reason)
    _close_review_notice(a)
    # The submitter must be told, WITH the reason — returning work silently is
    # how a completion sat untouched until someone happened to reopen My Plan.
    owner = _owning_staff_id(a)
    _notify_after_review(
        a,
        "activity_returned_by_pl",
        "Your completion was returned",
        reason or "Your Program Lead returned this completion for correction.",
        [owner],
        priority="high",
    )
    return _serialize(a)


def _impact_assessment_ids() -> list[str]:
    from apps.accounts.models import User

    return list(
        User.objects.filter(
            roles__contains=["ImpactAssessment"], status="active"
        ).values_list("id", flat=True)
    )


def _notify_after_review(activity, event_type, title, body, recipients, priority="normal"):
    """Best-effort — a notification failure must not undo the review."""
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
            context_id=activity.id,
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001
        pass
