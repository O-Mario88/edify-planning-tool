"""Closing a school, reopening it, and the one definition of "active".

`active_schools()` is the point of this module. Thirty-two places in the
codebase answered "which schools count" with `deleted_at__isnull=True`, which
was correct while the only way a school left the programme was being deleted.
Once a school can close, every one of those places is wrong in the same way —
each still counts a school that stopped operating — and thirty-two
independently-fixed definitions would drift again within a release.

So there is one function, and the health check finds callers that are not
using it.

The closure itself is a state transition. Nothing is deleted: the enrolment a
school once had, the visits it received and the money spent on it are facts
about periods that have already been reported, and a closure that rewrote them
would change history to tidy the present.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.schools.lifecycle_models import (
    DATA_QUALITY_REASONS,
    OPERATING_STATUSES,
    ClosureReason,
    ClosureType,
    SchoolClosure,
    SchoolOperationalStatus,
)
from apps.schools.models import School

REASON_MIN_LENGTH = 20
REASON_MAX_LENGTH = 600


# ── The one definition ───────────────────────────────────────────────────────
def active_schools(base=None):
    """Schools that count toward anything current.

    Active means: the row exists (not deleted) AND the school is operating.
    Both halves are needed and they mean different things — deleted is "this
    should never have existed", closed is "this was real and has ended".

    Use this for directory listings, planning eligibility, active counts,
    enrolment totals, cluster membership and coverage denominators. Do NOT use
    it for history: a report about last quarter must still see a school that
    closed this quarter, because it was open then.
    """
    qs = base if base is not None else School.objects.all()
    return qs.filter(deleted_at__isnull=True, operational_status__in=OPERATING_STATUSES)


def closed_schools(base=None):
    """The archive: schools that operated and have stopped.

    Excludes deleted rows, which are not closures — a duplicate that was
    removed never closed, and showing it here would report a school loss that
    did not happen.
    """
    from apps.schools.lifecycle_models import CLOSED_STATUSES

    qs = base if base is not None else School.objects.all()
    return qs.filter(deleted_at__isnull=True, operational_status__in=CLOSED_STATUSES)


def active_enrollment(base=None) -> dict:
    """Learners currently reached, and an honest account of what is unknown.

    Returns the total alongside how many schools have no figure, because a
    sum that silently treats missing as zero reports a smaller programme with
    the same confidence as a real one. The caller decides how to present the
    gap; it must not be able to avoid knowing it exists.

    Uses the actual School Enrolment Count. Never the SSA Enrolment Score —
    that is a 1–10 assessment band, and summing it would report a country
    reaching a few thousand learners.
    """
    from django.db.models import Count, Q, Sum

    qs = active_schools(base)
    agg = qs.aggregate(
        total=Sum("enrollment", filter=Q(enrollment__gt=0)),
        counted=Count("id", filter=Q(enrollment__gt=0)),
        missing=Count("id", filter=Q(enrollment__isnull=True) | Q(enrollment__lte=0)),
    )
    return {
        "total": int(agg["total"] or 0),
        "schools_counted": agg["counted"] or 0,
        "schools_missing_enrollment": agg["missing"] or 0,
        "schools_active": (agg["counted"] or 0) + (agg["missing"] or 0),
    }


# ── Authority ────────────────────────────────────────────────────────────────
def assert_may_close(principal, school) -> str:
    """Who may close this school. Returns the acting role.

    The rule worth stating: a Program Lead may close a school assigned to them
    directly, but NOT one belonging to a CCEO they supervise. Supervision is
    the right to ask, and closing somebody's school out from under them —
    cancelling their planned work, changing their portfolio size and their
    target denominator — is not asking. The PL sends a closure review instead.
    """
    from apps.core.permissions import has_permission
    from apps.core.rbac import EdifyRole, Permission
    from apps.core.scoping import owner_ids

    role = getattr(principal, "active_role", "") or ""
    if getattr(principal, "is_superuser", False) or role == EdifyRole.ADMIN.value:
        return role

    if not has_permission(principal, Permission.SCHOOL_CLOSE.value):
        raise Forbidden("Your role cannot close schools.")

    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        return role

    from apps.planning.oversight_service import _both_id_spaces

    own = _both_id_spaces(set(owner_ids(principal)))
    owner = (school.account_owner_id or "").strip()
    if not owner or owner not in own:
        if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
            raise Forbidden(
                "This school belongs to a CCEO you supervise. Send them a "
                "closure review rather than closing it yourself — the work "
                "and targets it carries are theirs."
            )
        raise Forbidden("This school is not yours to close.")
    return role


# ── Validation ───────────────────────────────────────────────────────────────
def _validate(data: dict) -> tuple[str, str, str, object]:
    closure_type = ((data or {}).get("closure_type") or "").strip()
    if closure_type not in ClosureType.values:
        raise BadRequest("Choose whether this closure is temporary or permanent.")

    reason_category = ((data or {}).get("reason_category") or "").strip()
    if reason_category not in ClosureReason.values:
        raise BadRequest("Choose a closure reason.")

    reason = ((data or {}).get("reason") or "").strip()
    if len(reason) < REASON_MIN_LENGTH:
        raise BadRequest(
            "Explain briefly why the school is closing, when it stopped "
            f"operating, and any follow-up required (at least "
            f"{REASON_MIN_LENGTH} characters)."
        )
    if len(reason) > REASON_MAX_LENGTH:
        raise BadRequest(f"Keep the explanation under {REASON_MAX_LENGTH} characters.")

    effective_date = (data or {}).get("effective_date") or timezone.localdate()
    if isinstance(effective_date, str):
        from datetime import date as _date

        try:
            effective_date = _date.fromisoformat(effective_date)
        except ValueError as exc:
            raise BadRequest("Enter a valid closure date.") from exc

    return closure_type, reason_category, reason, effective_date


# ── Impact preview ───────────────────────────────────────────────────────────
def preview(school_id: str, *, effective_date=None) -> dict:
    """What closing this school would actually do, computed on the server.

    Read from the records rather than estimated, because the point of a
    preview is that nobody confirms a change to a country's active enrolment
    and somebody's target denominator without having seen the numbers.
    """
    school = _load(school_id)
    effective_date = effective_date or timezone.localdate()

    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment

    future = Activity.objects.filter(
        school_id=school.id,
        deleted_at__isnull=True,
        planned_date__gte=effective_date,
    ).exclude(status__in=("cancelled", "deferred", "rejected", "completed", "closed"))

    unlocked, locked, released = [], [], 0
    for activity in future:
        if _is_financially_locked(activity):
            locked.append(activity)
        else:
            unlocked.append(activity)
            released += _cost_of(activity)

    assignments = PartnerAssignment.objects.filter(school_id=school.id).exclude(
        status=PartnerAssignment.STATUS_RETURNED_TO_STAFF
    )

    return {
        "school_id": school.id,
        "school_ref": school.school_id,
        "name": school.name,
        "operational_status": school.operational_status,
        "already_closed": school.is_closed,
        "owner": school.account_owner_name_raw or "",
        "cluster_id": school.cluster_id or "",
        "district": getattr(school.district, "name", "") or "",
        "school_type": school.school_type or "",
        "effective_date": effective_date,
        # The actual enrolment count, never an SSA score.
        "enrollment": school.enrollment,
        "enrollment_record_date": school.last_enrollment_date,
        "enrollment_missing": not school.enrollment or school.enrollment <= 0,
        "future_activities": len(unlocked) + len(locked),
        "activities_to_cancel": len(unlocked),
        "activities_needing_review": len(locked),
        "budget_released": released,
        "partner_assignments": assignments.count(),
        # Stated plainly because these are the two numbers a leadership page
        # will move by, and somebody is accountable for both.
        "active_school_count_change": -1 if school.is_operating else 0,
        "active_enrollment_change": (
            -(school.enrollment or 0) if school.is_operating else 0
        ),
    }


def _load(school_id: str) -> School:
    school = (
        School.objects.select_related("district")
        .filter(deleted_at__isnull=True)
        .filter(models_Q_id_or_ref(school_id))
        .first()
    )
    if school is None:
        raise NotFoundError("School not found.")
    return school


def models_Q_id_or_ref(school_id: str):
    """Accept either identifier — routes carry the human school_id."""
    from django.db.models import Q

    return Q(id=school_id) | Q(school_id=school_id)


def _is_financially_locked(activity) -> bool:
    if (activity.payment_status or "none") not in ("none", "pending", "pending_ia"):
        return True
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES, AdvanceRequest

    return AdvanceRequest.objects.filter(
        activity_id=activity.id, status__in=MONEY_MOVED_ADVANCE_STATUSES
    ).exists()


def _cost_of(activity) -> int:
    from django.db.models import Sum

    from apps.activities.models import ActivityScheduleCostLine

    return int(
        ActivityScheduleCostLine.objects.filter(activity=activity).aggregate(
            t=Sum("amount")
        )["t"]
        or 0
    )


# ── The closure ──────────────────────────────────────────────────────────────
def close_school(school_id: str, data: dict, principal) -> SchoolClosure:
    """Stop a school receiving new work, and leave everything it did intact.

    One transaction. If any step fails the school stays active, no work is
    cancelled and nothing is announced — a half-closed school is one that has
    left the directory but still has a partner arriving on Tuesday.
    """
    closure_type, reason_category, reason, effective_date = _validate(data)

    with transaction.atomic():
        school = (
            School.objects.select_for_update(of=("self",))
            .filter(models_Q_id_or_ref(school_id), deleted_at__isnull=True)
            .first()
        )
        if school is None:
            raise NotFoundError("School not found.")

        open_closure = SchoolClosure.objects.filter(
            school=school, reopened_at__isnull=True
        ).first()
        if open_closure is not None:
            # Already closed. Reporting the existing decision beats recording
            # a second one that would double the enrolment removed.
            return open_closure

        acting_role = assert_may_close(principal, school)

        if reason_category in DATA_QUALITY_REASONS:
            raise BadRequest(
                "A duplicate or incorrect record is not a closure — the school "
                "never stopped operating, and recording it as one would report "
                "a school loss that did not happen. Resolve it through the "
                "duplicate workflow so the histories can be merged."
            )

        closure = SchoolClosure.objects.create(
            school=school,
            closure_type=closure_type,
            reason_category=reason_category,
            reason=reason,
            effective_date=effective_date,
            closed_by=getattr(principal, "id", "") or "",
            closed_by_role=acting_role,
            # Snapshots. Copied rather than read back later, because all three
            # change and the question this answers is what the programme lost
            # on the day.
            enrollment_at_closure=school.enrollment,
            enrollment_source="school.enrollment",
            enrollment_record_date=school.last_enrollment_date,
            cluster_at_closure=school.cluster_id,
            owner_at_closure=school.account_owner_id,
            owner_name_at_closure=school.account_owner_name_raw or "",
        )

        school.operational_status = (
            SchoolOperationalStatus.PERMANENTLY_CLOSED
            if closure_type == ClosureType.PERMANENT
            else SchoolOperationalStatus.TEMPORARILY_CLOSED
        )
        school.closed_at = timezone.now()
        school.closure_effective_date = effective_date
        school.save(
            update_fields=[
                "operational_status",
                "closed_at",
                "closure_effective_date",
                "updated_at",
            ]
        )

        stopped = _stop_future_work(school, closure, principal, effective_date)
        closure.activities_cancelled = stopped["cancelled"]
        closure.locked_activities_for_review = stopped["locked"]
        closure.budget_released = stopped["released"]
        closure.partner_assignments_withdrawn = stopped["assignments"]
        closure.save(
            update_fields=[
                "activities_cancelled",
                "locked_activities_for_review",
                "budget_released",
                "partner_assignments_withdrawn",
                "updated_at",
            ]
        )

    _announce_closure(closure, principal)
    return closure


def _stop_future_work(school, closure, principal, effective_date) -> dict:
    """Stop what has not happened; leave alone what has.

    The cut is the effective date, not today. A closure recorded late must not
    cancel a visit that genuinely took place last week — that work happened,
    the evidence exists, and somebody is owed for it.

    Financially locked activities are counted for review rather than cancelled.
    Money that has moved settles through accountability, never by a status
    flip performed on its behalf.
    """
    from apps.activities import services as activity_services
    from apps.activities.models import Activity
    from apps.partners import withdrawal_service
    from apps.partners.models import PartnerAssignment
    from apps.partners.withdrawal_models import (
        WithdrawalDisposition,
        WithdrawalReason,
    )

    result = {"cancelled": 0, "locked": 0, "released": 0, "assignments": 0}

    future = Activity.objects.filter(
        school_id=school.id,
        deleted_at__isnull=True,
        planned_date__gte=effective_date,
    ).exclude(status__in=("cancelled", "deferred", "rejected", "completed", "closed"))

    for activity in list(future):
        if _is_financially_locked(activity):
            # Left alone deliberately, and counted so it is chased rather than
            # lost. The health check reports a locked activity on a closed
            # school that nobody has reviewed.
            result["locked"] += 1
            continue
        cost = _cost_of(activity)
        activity_services.cancel(
            activity.id,
            {"reason": f"School closed — {closure.get_reason_category_display()}"},
            principal,
        )
        result["cancelled"] += 1
        result["released"] += cost

    # Partner work goes through the withdrawal service rather than a status
    # update, so the partner is told, the slot is released and the decision is
    # recorded with a reason like any other withdrawal.
    assignments = PartnerAssignment.objects.filter(school_id=school.id).exclude(
        status=PartnerAssignment.STATUS_RETURNED_TO_STAFF
    )
    for assignment in list(assignments):
        try:
            withdrawal_service.withdraw(
                assignment.id,
                {
                    "reason_category": WithdrawalReason.SCHOOL_UNAVAILABLE,
                    "partner_facing_reason": (
                        f"{school.name} has closed, so this assignment has been "
                        "withdrawn. Please stop any preparation for it."
                    ),
                    "internal_note": f"School closure {closure.id}.",
                    "disposition": WithdrawalDisposition.CANCEL_SUPPORT,
                },
                principal,
            )
            result["assignments"] += 1
        except Exception:  # noqa: BLE001
            # A partner assignment that cannot be withdrawn (already paid, in
            # review) must not abort the closure — the school has still shut.
            # The health check reports active partner work on a closed school.
            continue

    return result


def _announce_closure(closure, principal) -> None:
    """Record it, then tell the people whose work just changed."""
    from apps.audit.services import log as audit_log

    audit_log(
        action="school.closed",
        subject_kind="SchoolClosure",
        subject_id=closure.id,
        actor_id=closure.closed_by or "unknown",
        actor_role=closure.closed_by_role,
        success=True,
        payload={
            "school_id": closure.school_id,
            "closure_type": closure.closure_type,
            "reason_category": closure.reason_category,
            "effective_date": str(closure.effective_date),
            "enrollment_at_closure": closure.enrollment_at_closure,
            "cluster_at_closure": closure.cluster_at_closure,
            "activities_cancelled": closure.activities_cancelled,
            "locked_activities_for_review": closure.locked_activities_for_review,
            "budget_released": closure.budget_released,
            "partner_assignments_withdrawn": closure.partner_assignments_withdrawn,
        },
    )

    if closure.locked_activities_for_review:
        _notify_accountant(closure)


def _notify_accountant(closure) -> None:
    """Money already committed against a school that has shut.

    A queue nudge rather than a TeamAction: the accountant function is a
    queue, and naming one of them personally responsible for a school closure
    they did not make is the fabrication the withdrawal work established a
    rule against.
    """
    from apps.planning.action_service import ActionError, notify_role_queue

    try:
        notify_role_queue(
            sender=None,
            role="Accountant",
            subject=f"School closed with committed funds — {closure.school.name}",
            body=(
                f"{closure.school.name} closed on "
                f"{closure.effective_date:%-d %b %Y}. "
                f"{closure.locked_activities_for_review} activity(s) have "
                "committed or disbursed funds and need settling."
            ),
            context_type="SchoolClosure",
            context_id=closure.id,
            event_key="school_closure.locked_finance",
            route="/finance/accountability",
            action_label="Review committed funds",
            priority="high",
        )
    except ActionError:
        # No active accountant. The health check reports it; the closure is
        # still correct.
        pass


# ── Reopening ────────────────────────────────────────────────────────────────
def reopen_school(school_id: str, data: dict, principal) -> SchoolClosure:
    """Bring a school back, without resurrecting the work that was stopped.

    Reopening restores the school's place in current counts. It does NOT
    recreate cancelled activities, reactivate withdrawn partner assignments or
    treat a prior-year SSA as current — each of those was a decision somebody
    made, and undoing them silently would put work back on people's plans that
    nobody re-planned.
    """
    reason = ((data or {}).get("reason") or "").strip()
    if len(reason) < REASON_MIN_LENGTH:
        raise BadRequest(
            "Explain why the school is reopening and confirm it is operating "
            f"(at least {REASON_MIN_LENGTH} characters)."
        )

    enrollment = (data or {}).get("enrollment")
    if enrollment in (None, "", 0):
        raise BadRequest(
            "Record the school's current enrolment. Reopening with the old "
            "figure would restore a learner count nobody has confirmed."
        )
    try:
        enrollment = int(enrollment)
    except (TypeError, ValueError) as exc:
        raise BadRequest("Enter the current enrolment as a number.") from exc
    if enrollment <= 0:
        raise BadRequest("Enter the current enrolment as a positive number.")

    with transaction.atomic():
        school = (
            School.objects.select_for_update(of=("self",))
            .filter(models_Q_id_or_ref(school_id), deleted_at__isnull=True)
            .first()
        )
        if school is None:
            raise NotFoundError("School not found.")

        assert_may_close(principal, school)

        closure = SchoolClosure.objects.filter(
            school=school, reopened_at__isnull=True
        ).first()
        if closure is None:
            raise ConflictError("This school is not closed.")

        closure.reopened_at = timezone.now()
        closure.reopened_by = getattr(principal, "id", "") or ""
        closure.reopening_reason = reason
        closure.save(
            update_fields=[
                "reopened_at",
                "reopened_by",
                "reopening_reason",
                "updated_at",
            ]
        )

        school.operational_status = SchoolOperationalStatus.REOPENED
        school.reopened_at = timezone.now()
        school.closed_at = None
        school.closure_effective_date = None
        school.enrollment = enrollment
        school.last_enrollment_date = timezone.localdate()
        school.save(
            update_fields=[
                "operational_status",
                "reopened_at",
                "closed_at",
                "closure_effective_date",
                "enrollment",
                "last_enrollment_date",
                "updated_at",
            ]
        )

    from apps.audit.services import log as audit_log

    audit_log(
        action="school.reopened",
        subject_kind="SchoolClosure",
        subject_id=closure.id,
        actor_id=closure.reopened_by or "unknown",
        actor_role=getattr(principal, "active_role", "") or "",
        success=True,
        payload={
            "school_id": school.id,
            "enrollment": enrollment,
            "closed_on": str(closure.effective_date),
        },
    )
    return closure
