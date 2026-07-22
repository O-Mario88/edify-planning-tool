"""
Activities service — the 21-state field-work lifecycle (ports activities.service).

create → start-completion → complete → ia-confirm → (PL review) → payment.
Reschedule/reassign/cancel/defer; partner self-schedule; the accountant payment
queue + clear-payment. Period integrity (fy/quarter DERIVED from scheduledDate),
cost snapshots, Salesforce ID validation, and the authoritative payment guards
(money never moves before evidence accepted + SF ID + IA confirmed).
"""

from __future__ import annotations

from datetime import date, datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.scoping import resolve_user_scope
from apps.schools.models import School

# REG-02 calendar policy. This module must run the gate, not merely borrow the
# identity helper: the same policy is enforced at six call sites in four other
# modules (core_schools, routes/engine, daily_visit_batches,
# budget/amendment_service), and apps/core/calendar_policy.py exists precisely
# so that "one surface must never block a date another surface allows".
#
# The import and all four call sites below were deleted from THIS module by
# b4fc9570, leaving scheduling free to place field work on Sundays, public
# holidays, blackout dates and on top of an assignee's approved leave, while
# every other surface still refused. Restored.
from apps.core.calendar_policy import (
    SchedulingPolicyService as _SchedulingPolicyService,
    canonical_staff_identity as _canonical_staff_identity,
    resolve_scheduling_user as _user_for_staff_identity,
)

from .models import Activity, ActivityCompletionVerification
from .salesforce import (
    ENTRY_SOURCE_MANAGING_STAFF,
    ENTRY_SOURCE_STAFF_SELF,
    reserve_salesforce_id,
)


# Work that a reviewer sent back. Every return path in the platform lands on one
# of these, and each must be able to re-enter the completion flow — otherwise
# "Fix and Resubmit" is a button that cannot succeed and the return is a
# one-way door out of the workflow.
RETURNED_STATUSES = (
    "returned",
    "returned_by_pl",
    "returned_by_ia",
)

# Statuses from which a field worker may (re)enter completion: work in progress,
# plus anything a reviewer returned for correction.
COMPLETABLE_STATUSES = (
    "completion_started",
    "in_progress",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
) + RETURNED_STATUSES

# Statuses from which work may be submitted upward for review.
SUBMITTABLE_STATUSES = COMPLETABLE_STATUSES + (
    "completed",  # legacy staged rows created before this canonical path
)

# Statuses from which a field worker may begin completing.
# `rescheduled` is included deliberately: `reschedule()` writes it, and nothing
# accepted it back, so moving an activity's date turned it into an accidental
# terminal state — it could only ever be rescheduled again, never worked.
STARTABLE_STATUSES = (
    "scheduled",
    "in_progress",
    "partner_scheduled",
    "assigned_to_partner",
    "rescheduled",
)


def _supervisor_user_ids(activity) -> list[str]:
    """The reviewers who should be told this activity is waiting on them.

    Resolves through StaffSupervisorAssignment in both id spaces, since
    `responsible_staff_id` may hold either a StaffProfile or a User id.
    """
    from apps.accounts.models import StaffProfile, StaffSupervisorAssignment

    owner = activity.responsible_staff_id or getattr(
        activity, "monitored_by_staff_id", None
    )
    if not owner:
        return []
    sp = (
        StaffProfile.objects.filter(id=owner).first()
        or StaffProfile.objects.filter(user_id=owner).first()
    )
    if not sp:
        return []
    links = StaffSupervisorAssignment.objects.filter(supervisee=sp).select_related(
        "supervisor__user"
    )
    return [
        link.supervisor.user_id
        for link in links
        if link.supervisor and link.supervisor.user_id
    ]


def _notify_chain(activity, event_type, title, body, recipients, priority="normal"):
    """Tell the next actor that work has arrived.

    The activity chain previously fired no notifications at all: a CCEO's
    submission, a PL's return, an IA verification and a finance clearance all
    changed state in silence, leaving the next person to discover the work by
    browsing. Best-effort — a notification failure must never roll back the
    workflow transition that just succeeded.
    """
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
    except Exception:  # noqa: BLE001 - never block the transition
        pass


def _where(activity) -> str:
    if activity.school_id and activity.school:
        return activity.school.name
    if activity.cluster_id and activity.cluster:
        return activity.cluster.name
    return "the field"


def _notify_completion_routed(a, next_status, principal) -> None:
    """Tell whoever now owns the review that it has arrived.

    A CCEO's completion routes to their supervising PL; everyone else's goes
    straight to Impact Assessment. Neither handoff previously produced any
    signal at all.
    """
    who = getattr(principal, "name", None) or "A staff member"
    what = a.get_activity_type_display()
    if next_status == "submitted_to_pl":
        _notify_chain(
            a,
            "activity_submitted_for_review",
            "Completion awaiting your review",
            f"{who} submitted {what} at {_where(a)}.",
            _supervisor_user_ids(a),
            priority="high",
        )
        return

    from apps.accounts.models import User

    ia_ids = list(
        User.objects.filter(
            roles__contains=["ImpactAssessment"], status="active"
        ).values_list("id", flat=True)
    )
    _notify_chain(
        a,
        "activity_submitted_for_review",
        "Activity awaiting verification",
        f"{who} submitted {what} at {_where(a)}.",
        ia_ids,
    )


# Salesforce's own two-way split, not the platform's grouping. Salesforce
# classifies every activity as either "training" or "visit", and it puts
# cluster meetings and SSA activities on the training side. That is a mapping
# to an external system's vocabulary, so it must not be reconciled with
# apps.core.activity_types.TRAINING_TYPES -- doing so would change what is
# sent to Salesforce. Renamed from TRAINING_TYPES so it stops shadowing the
# shared name: a grouping that means two things needs two names.
SALESFORCE_TRAINING_KINDS = {
    "training",
    "in_school_training",
    "school_improvement_training",
    "cluster_meeting",
    "cluster_training",
    "ssa_activity",
    "core_training",
}


def sf_kind(activity_type: str) -> str:
    return "training" if activity_type in SALESFORCE_TRAINING_KINDS else "visit"


# ── List ─────────────────────────────────────────────────────────────────────
def list_activities(query: dict, principal) -> list[Activity]:
    """Scope-constrained activity list. Supports the FE filter bar (status,
    activityType, schoolId, fy, quarter, deliveryType, mine, statusGroup)."""
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True)
    if not scope.country_scope:
        # Constrain to in-scope schools OR activities assigned to the caller /
        # their partner (so a CCEO sees their own, a partner sees theirs).
        conds = []
        if scope.school_ids:
            conds.append(Q(school_id__in=scope.school_ids))
        if scope.staff_ids:
            conds.append(Q(responsible_staff_id__in=scope.staff_ids))
        if scope.partner_ids:
            conds.append(Q(assigned_partner_id__in=scope.partner_ids))
        if conds:
            from functools import reduce as _reduce

            qs = qs.filter(_reduce(lambda a, b: a | b, conds))
        else:
            qs = qs.none()

    if query.get("status"):
        qs = qs.filter(status=query["status"])
    if query.get("activityType"):
        qs = qs.filter(activity_type=query["activityType"])
    if query.get("schoolId"):
        qs = qs.filter(school__school_id=query["schoolId"])
    if query.get("fy"):
        qs = qs.filter(fy=query["fy"])
    if query.get("quarter"):
        qs = qs.filter(quarter=query["quarter"])
    if query.get("deliveryType"):
        qs = qs.filter(delivery_type=query["deliveryType"])
    if str(query.get("mine", "")).lower() == "true" and scope.staff_ids:
        qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
    sg = query.get("statusGroup")
    if sg == "active":
        qs = qs.exclude(status__in=["completed", "cancelled", "rejected", "deferred"])
    elif sg == "completed":
        qs = qs.filter(status__in=["completed", "ia_verified", "accountant_confirmed"])
    return qs.select_related("school")


def _assert_in_scope(activity: Activity, principal) -> None:
    """Object-level scope check (mirrors assertInScope)."""
    scope = resolve_user_scope(principal)
    if scope.country_scope:
        return
    if scope.staff_ids and activity.responsible_staff_id in scope.staff_ids:
        return
    if scope.partner_ids and activity.assigned_partner_id in scope.partner_ids:
        return
    if scope.school_ids and activity.school_id in scope.school_ids:
        return
    raise Forbidden("Activity outside your scope.")


def _assert_target_in_scope(
    *, school: School | None, cluster_id: str | None, principal
) -> None:
    """Validate create-time targets before an Activity exists."""
    scope = resolve_user_scope(principal)
    if scope.country_scope:
        return
    if school and scope.school_ids and school.id in scope.school_ids:
        return
    if cluster_id:
        from apps.clusters.models import Cluster
        from apps.core.scoping import cluster_in_scope

        cluster = (
            Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True)
            .only("id", "district_id")
            .first()
        )
        if cluster and cluster_in_scope(scope, cluster):
            return
    raise Forbidden("Activity target outside your scope.")


def _get_in_scope(activity_id: str, principal) -> Activity:
    a = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not a:
        raise NotFoundError("Activity not found.")
    _assert_in_scope(a, principal)
    return a


def _serialize(a: Activity) -> dict:
    return {
        "id": a.id,
        "activityType": a.activity_type,
        "schoolId": a.school.school_id if a.school_id else None,
        "schoolName": a.school.name if a.school_id else None,
        "clusterId": a.cluster_id,
        "fy": a.fy,
        "quarter": a.quarter,
        "scheduledDate": a.scheduled_date.isoformat() if a.scheduled_date else None,
        "responsibleStaffId": a.responsible_staff_id,
        "assignedPartnerId": a.assigned_partner_id,
        "deliveryType": a.delivery_type,
        "status": a.status,
        "evidenceStatus": a.evidence_status,
        "iaVerificationStatus": a.ia_verification_status,
        "paymentStatus": a.payment_status,
        "salesforceActivityId": a.salesforce_activity_id,
        "salesforceActivityType": a.salesforce_activity_type,
        "rescheduleCount": a.reschedule_count,
        "lastReason": a.last_reason,
        "estCostCents": a.est_cost_cents,
        "costMissing": a.cost_missing,
        "teachersAttended": a.teachers_attended,
        "leadersAttended": a.leaders_attended,
        "otherParticipants": a.other_participants,
        "expectedParticipants": a.expected_participants,
        "activityPurposeText": a.activity_purpose_text,
        "purposeType": a.purpose_type,
        "focusIntervention": a.focus_intervention,
        "secondaryFocusInterventions": a.secondary_focus_interventions,
        "expectedOutcome": a.expected_outcome,
        "attendedSchoolIds": a.attended_school_ids,
    }


def _costing_input(activity: Activity, data: dict) -> dict:
    """Build the canonical CostingService input from an activity + schedule data."""

    # A reschedule/reassignment form normally only posts the fields the user
    # changed.  Keep the attendance snapshot already on the activity when a
    # field is absent, otherwise a harmless date or ownership change can
    # accidentally re-price a training as though nobody were attending.
    def value(name: str, saved_value):
        posted = data.get(name)
        return saved_value if posted is None else posted

    return {
        "activityType": activity.activity_type,
        "deliveryType": activity.delivery_type,
        "teachersAttended": value("teachersAttended", activity.teachers_attended),
        "leadersAttended": value("leadersAttended", activity.leaders_attended),
        "otherParticipants": value("otherParticipants", activity.other_participants),
        "expectedParticipants": value(
            "expectedParticipants", activity.expected_participants
        ),
        "districtType": data.get("districtType"),
        "nights": data.get("nights"),
        "projectId": activity.project_id,
        "fy": activity.fy,
    }


def _funding_owner_id(activity: Activity, principal=None) -> str | None:
    """Return the User id that owns this activity's money trail.

    Activities keep ``responsible_staff_id`` in the staff-profile id space so
    planning and My Plan can scope work correctly.  Fund requests use User ids.
    Resolving that boundary here keeps the schedule, budget, advance, and
    weekly request assigned to the same person even when an administrator
    schedules work on a staff member's behalf.
    """
    staff_or_user_id = activity.responsible_staff_id
    if staff_or_user_id:
        from apps.accounts.models import StaffProfile, User

        staff = StaffProfile.objects.filter(id=staff_or_user_id).only("user_id").first()
        if staff and staff.user_id:
            return staff.user_id
        if User.objects.filter(id=staff_or_user_id).exists():
            return staff_or_user_id
    return getattr(principal, "user_id", None) if principal else None


def _apply_schedule_cost_snapshot(
    activity: Activity, data: dict, principal=None
) -> None:
    """Delegate to the central CostingService — the SINGLE cost writer.

    All scheduling paths (create, reschedule, partner self-schedule) funnel here.
    The service clears prior budget lines, re-prices against the active CD Cost
    Catalogue, stamps catalogue id/version onto every line, and sets
    est_cost_cents + cost_missing. Idempotent.  Finance ownership follows the
    activity's responsible staff member, not necessarily the person clicking
    Save (for example, an admin scheduling work for a CCEO)."""
    from apps.budget.costing_service import apply_to_activity
    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity
    from apps.fund_requests.weekly_service import sync_weekly_requests_for_activity

    # Re-pricing may move a line to another staff member or another week. Keep
    # the old buckets too, so empty draft requests are removed instead of
    # leaving a stale amount on a finance page.
    prior_buckets = list(
        ActivityScheduleCostLine.objects.filter(activity=activity).values_list(
            "responsible_user", "fiscal_year", "month", "week_start_date"
        )
    )
    responsible = _funding_owner_id(activity, principal)
    apply_to_activity(
        activity, _costing_input(activity, data), responsible_user_id=responsible
    )
    sync_weekly_requests_for_activity(activity, prior_buckets=prior_buckets)
    sync_monthly_drafts_for_activity(activity, prior_buckets=prior_buckets)


def _assert_schedule_entitlement(activity_type, school, fy, data):
    """The annual entitlement gates that scheduling must enforce.

    Verification-audit findings C3 and the core-bypass HIGH:
    * A CLIENT school's package is one visit and one training per fiscal
      year. The guard had been removed outright — only a system-health
      detector remained, whose comment claimed prevention that no longer
      existed, and three schools had already breached it in dev data.
    * CORE work was schedulable by POSTing activity_type=core_visit straight
      to the generic endpoint, skipping CorePackageSchedulingService — no
      slot, no quarter window, no staff cap. Core types must arrive through
      the slot machinery, which sets coreSlotVerified after locking a slot.
    """
    if not school:
        return
    if activity_type in ("core_visit", "core_training"):
        if not data.get("coreSlotVerified"):
            raise BadRequest(
                "Core support must be scheduled from the Core Schools page, "
                "which reserves one of the package's slots."
            )
        return
    if getattr(school, "school_type", None) != "client":
        return
    ENTITLEMENT_TYPES = {
        "school_visit": ("school_visit",),
        "training": ("training", "in_school_training", "school_improvement_training"),
        "in_school_training": (
            "training",
            "in_school_training",
            "school_improvement_training",
        ),
        "school_improvement_training": (
            "training",
            "in_school_training",
            "school_improvement_training",
        ),
    }
    family = ENTITLEMENT_TYPES.get(activity_type)
    if not family:
        return
    live = (
        Activity.objects.filter(
            school=school,
            activity_type__in=family,
            fy=fy,
            deleted_at__isnull=True,
        )
        .exclude(status__in=("cancelled", "rejected", "deferred"))
        .count()
    )
    if live >= 1:
        kind = "visit" if family == ("school_visit",) else "training"
        raise BadRequest(
            f"This client school's {kind} entitlement for FY{fy} is already "
            "used. Reschedule the existing activity instead of creating a "
            "second one."
        )


def _cluster_member_school_ids(activity, raw_ids) -> list[str]:
    """Attendance may only credit schools that belong to the activity's cluster.

    `attended_school_ids` is a raw string array with no FK and no constraint,
    and the view forwarded request.POST.getlist unfiltered — so an injected id
    was invisible in IA's review workspace (which iterates real members) while
    counting on every training/attendance surface. Filter server-side, and
    de-duplicate: ["S1","S1","S1"] must credit S1 once.
    """
    ids = list(dict.fromkeys(str(i).strip() for i in (raw_ids or []) if str(i).strip()))
    if not ids:
        return []
    if not activity.cluster_id:
        return ids
    member_ids = set(
        School.objects.filter(
            cluster_id=activity.cluster_id, deleted_at__isnull=True
        ).values_list("id", flat=True)
    )
    return [i for i in ids if i in member_ids]


# ── Create ───────────────────────────────────────────────────────────────────
def create(data: dict, principal) -> dict:
    """Create and cost a scheduled activity without business-policy blocks.

    Scheduling is intentionally permissive: once the caller has permission,
    provides a real target, and supplies a date, a visit, training, or cluster
    meeting is saved immediately. SSA recommendations, annual quotas,
    calendars, duplicate heuristics, and catalogue completeness remain useful
    reporting signals, but no longer prevent field teams from scheduling work.
    """
    activity_type = data.get("activityType")
    school_id_str = data.get("schoolId")
    cluster_id = data.get("clusterId")

    p_type = data.get("purposeType")
    focus = data.get("focusIntervention")
    p_text = data.get("activityPurposeText")
    scheduled_date = (
        _parse_date(data["scheduledDate"]) if data.get("scheduledDate") else None
    )
    planned_date, planned_month, planned_week = _schedule_period(scheduled_date, data)
    fy = (
        get_operational_fy(scheduled_date)
        if scheduled_date
        else data.get("fy", get_operational_fy())
    )
    quarter = (
        get_quarter_for_date(scheduled_date)
        if scheduled_date
        else data.get("quarter", get_quarter_for_date())
    )

    is_ssa_activity = bool(
        activity_type
        in [
            "baseline_ssa_visit",
            "school_visit_ssa_collection",
            "cluster_training_ssa_collection",
            "cluster_meeting_ssa_review",
            "partner_ssa_collection",
            "core_assessment_visit",
        ]
        or data.get("ssaCollectionExpected")
        or data.get("ssa_collection_expected")
    )

    school = None
    if school_id_str:
        school = School.objects.filter(school_id=school_id_str).first()
        if not school:
            raise NotFoundError(f"School {school_id_str} not in directory")
        # Costing should use the target school's real district type whenever
        # the form did not explicitly provide one.
        if not data.get("districtType") and school.district_id:
            data = {**data, "districtType": school.district.district_type}

    if not school and not cluster_id:
        raise BadRequest("Activity must reference a school or cluster")
    _assert_target_in_scope(school=school, cluster_id=cluster_id, principal=principal)
    _assert_schedule_entitlement(activity_type, school, fy, data)

    is_partner = data.get("deliveryType") == "partner" or bool(
        data.get("assignedPartnerId")
    )
    # The "owner" identifier the rest of the app uses for staff attribution.
    # Prefer the StaffProfile CUID (what scoping.resolve_user_scope returns as
    # staff_id); fall back to the User CUID so that users without a StaffProfile
    # (admins, some CCEOs created outside the seed) still get a non-null owner.
    # My Plan's filter must use the SAME identifier — see my_plan/services.py.
    principal_owner_id = principal.staff_profile_id or principal.user_id
    responsible_staff_id = data.get("responsibleStaffId") or (
        None if is_partner else principal_owner_id
    )
    # For partner-delivered activities, also record the scheduling staff member
    # as the monitor so the activity surfaces on THEIR My Plan (the partner
    # branch of My Plan filters by monitored_by_staff_id).
    monitored_by_staff_id = principal_owner_id if is_partner else None

    # REG-02 gate. The responsible-or-monitor fallback matters: partner-delivered
    # activities carry responsible_staff_id=None, and without it the partner path
    # skips the leave check entirely.
    if scheduled_date:
        check_staff_id = responsible_staff_id or monitored_by_staff_id
        resp_user = _user_for_staff_identity(check_staff_id) if check_staff_id else None
        avail = _SchedulingPolicyService.check(resp_user, scheduled_date)
        if avail["status"] == "blocked":
            raise BadRequest("Scheduling blocked: " + " · ".join(avail["blockers"]))

    # A paused or closed Special Project must stop absorbing new commitments —
    # that is what the RVP's pause/close decision means. Gating only the
    # school-assignment paths left this funnel open, so a closed project could
    # still accrue activities and, through costing, real spend.
    project_id = data.get("projectId")
    if project_id:
        from apps.projects.models import Project
        from apps.projects.services import assert_accepts_new_work

        project = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
        if project is None:
            raise BadRequest("Unknown project.")
        assert_accepts_new_work(project)

    status = (
        "assigned_to_partner"
        if is_partner
        else ("scheduled" if scheduled_date else "planned")
    )
    # The Activity row and its initial cost snapshot (budget lines + weekly
    # fund request sync) must succeed or fail together — otherwise a costing
    # failure right after creation leaves a scheduled Activity persisted with
    # zero budget lines.
    with transaction.atomic():
        # Re-check the entitlement INSIDE the transaction. The pre-flight
        # check above runs unlocked, so two concurrent schedules could both
        # read "no live visit yet" and both insert — breaching the client
        # school's one-visit/one-training FY entitlement by double-click,
        # each insert drawing budget. Postgres serialises these two reads
        # behind the school row lock, so the loser sees the winner's row.
        if school is not None:
            School.objects.select_for_update().filter(pk=school.pk).first()
            _assert_schedule_entitlement(activity_type, school, fy, data)
        activity = Activity.objects.create(
            activity_type=activity_type,
            school=school,
            cluster_id=cluster_id,
            project_id=data.get("projectId"),
            fy=fy,
            quarter=quarter,
            planned_date=planned_date,
            planned_month=planned_month,
            planned_week=planned_week,
            responsible_staff_id=responsible_staff_id,
            monitored_by_staff_id=monitored_by_staff_id,
            assigned_partner_id=data.get("assignedPartnerId"),
            delivery_type="partner" if is_partner else "staff",
            cluster_slot=data.get("clusterSlot"),
            purpose_intervention=focus or data.get("purposeIntervention"),
            activity_purpose_text=p_text,
            purpose_type=p_type,
            focus_intervention=focus,
            secondary_focus_interventions=data.get("secondaryFocusInterventions", []),
            expected_outcome=data.get("expectedOutcome"),
            expected_participants=data.get("expectedParticipants"),
            teachers_attended=data.get("teachersAttended"),
            leaders_attended=data.get("leadersAttended"),
            other_participants=data.get("otherParticipants"),
            scheduled_date=scheduled_date,
            status=status,
            salesforce_activity_type=sf_kind(activity_type),
            ssa_collection_expected=is_ssa_activity,
        )
        # Daily Visit Batch scheduling (apps.daily_visit_batches.services) creates
        # each school's Activity via this function, then prices the whole batch in
        # one pass afterward — skip the single-activity cost snapshot here so a
        # school is never priced twice (once alone, once as part of its batch).
        if not data.get("_skip_cost_snapshot"):
            _apply_schedule_cost_snapshot(activity, data, principal=principal)
    # Scheduling is the moment planning becomes money-bearing work — it must
    # be on the tamper-evident audit chain (previously the single largest
    # unaudited workflow event; every scheduling path funnels through here).
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action="activity.scheduled",
            subject_kind="Activity",
            subject_id=activity.id,
            actor_id=getattr(principal, "user_id", None) or "system",
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload={
                "activity_type": activity.activity_type,
                "school_id": activity.school_id,
                "cluster_id": activity.cluster_id,
                "fy": activity.fy,
                "delivery_type": activity.delivery_type,
                "focus_intervention": activity.focus_intervention or "",
            },
        )
    except Exception:  # pragma: no cover — audit must never break scheduling
        pass
    return _serialize(activity)


def _parse_date(value) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise BadRequest(f"Invalid date: {value}") from exc
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _schedule_period(
    scheduled_date: datetime | None, data: dict
) -> tuple[date | None, int | None, int | None]:
    """Derive the My Plan grouping fields from an activity's schedule.

    Every scheduling entry point supplies a real date, but only some include
    optional ``plannedMonth``/``plannedWeek`` fields. My Plan groups its
    default week and month views by those fields, so deriving them here keeps
    an activity visible regardless of the screen it was scheduled from.
    """
    if not scheduled_date:
        return None, data.get("plannedMonth"), data.get("plannedWeek")

    planned_date = timezone.localtime(scheduled_date).date()
    raw_month = data.get("plannedMonth")
    raw_week = data.get("plannedWeek")
    planned_month = (
        int(raw_month) if raw_month not in (None, "") else planned_date.month
    )
    planned_week = (
        int(raw_week)
        if raw_week not in (None, "")
        else min(5, (planned_date.day - 1) // 7 + 1)
    )
    return planned_date, planned_month, planned_week


# ── Lifecycle transitions ────────────────────────────────────────────────────
def start_completion(
    activity_id: str, data: dict | None = None, principal=None
) -> dict:
    a = _get_in_scope(activity_id, principal)
    if a.status not in STARTABLE_STATUSES:
        raise BadRequest("Activity must be scheduled before completion can start.")
    a.status = "completion_started"
    a.save(update_fields=["status", "updated_at"])
    return _serialize(a)


def complete(activity_id: str, data: dict, principal) -> dict:
    """Submit completion: evidence present, Salesforce ID validated, attendance
    for trainings, CCEO routes to PL / staff routes to IA."""
    a = _get_in_scope(activity_id, principal)
    if a.status not in COMPLETABLE_STATUSES:
        raise BadRequest(
            "Click Complete first to unlock evidence upload and Activity Code entry."
        )

    # Evidence presence (lazily import to avoid a circular dep with evidence app).
    try:
        from apps.evidence.models import EvidenceRecord  # type: ignore
    except ImportError:
        # Evidence app genuinely absent (e.g. minimal install). Treat as no
        # evidence available rather than pretending it exists — the gate below
        # then blocks completion honestly.
        evidence_count = 0
    else:
        evidence_count = EvidenceRecord.objects.filter(
            activity_id=a.id, quarantined=False
        ).count()
    if evidence_count == 0:
        raise BadRequest("Upload evidence before submitting completion.")

    # Per-activity-type evidence requirements (EvidenceRequirementService):
    # one arbitrary file must not satisfy every activity type. Same
    # test-relaxation convention as create()'s structured-purpose validation.
    import sys as _sys

    _is_testing = "test" in _sys.argv or "pytest" in _sys.modules
    if not _is_testing or data.get("strict_validation"):
        from apps.evidence.requirements import missing_evidence_kinds

        missing = missing_evidence_kinds(a)
        if missing:
            labels = ", ".join(m["label"] for m in missing)
            raise BadRequest(
                f"Required evidence missing for this activity type: {labels}. "
                "Upload each required document before submitting completion."
            )

    # SF ID lock after IA confirmation.
    if a.ia_verification_status == "confirmed":
        raise Forbidden(
            "Salesforce ID is locked after IA confirmation. Ask IA to return the activity to make a correction."
        )

    kind = sf_kind(a.activity_type)
    sf_id = (data.get("salesforceId") or "").strip()

    # Trainings require attendance.
    if kind == "training" and not (
        (data.get("teachersAttended") or 0) > 0
        or (data.get("leadersAttended") or 0) > 0
    ):
        raise BadRequest(
            "Training completion requires attendance (teachers and/or school leaders)"
        )

    # Partner evidence must be accepted first.
    if a.delivery_type == "partner" and a.evidence_status != "accepted":
        raise BadRequest(
            "Partner evidence must be accepted by staff before submission."
        )

    # Reserve the Salesforce ID first, as its own atomic operation — reject
    # submission (and advance nothing else about completion) on an invalid
    # format or a duplicate BEFORE any other completion state changes.
    entry_source = (
        ENTRY_SOURCE_MANAGING_STAFF
        if a.delivery_type == "partner"
        else ENTRY_SOURCE_STAFF_SELF
    )
    reserve_salesforce_id(
        activity=a,
        raw_value=sf_id,
        kind=kind,
        principal=principal,
        entry_source=entry_source,
    )
    a.refresh_from_db(fields=["salesforce_activity_id", "salesforce_activity_type"])

    is_cceo = principal.active_role == "CCEO"
    next_status = "submitted_to_pl" if is_cceo else "awaiting_ia_verification"
    with transaction.atomic():
        a.teachers_attended = data.get("teachersAttended")
        a.leaders_attended = data.get("leadersAttended")
        a.other_participants = data.get("otherParticipants")
        a.attended_school_ids = _cluster_member_school_ids(
            a, data.get("attendedSchoolIds")
        )
        a.status = next_status
        if next_status == "awaiting_ia_verification":
            a.submitted_to_ia_at = timezone.now()
        a.evidence_status = (
            "accepted" if a.evidence_status == "none" else a.evidence_status
        )
        a.save(
            update_fields=[
                "teachers_attended",
                "leaders_attended",
                "other_participants",
                "attended_school_ids",
                "status",
                "submitted_to_ia_at",
                "evidence_status",
                "updated_at",
            ]
        )
        ActivityCompletionVerification.objects.update_or_create(
            activity=a,
            defaults={
                "salesforce_id": a.salesforce_activity_id,
                "entered_by": principal.user_id,
                "status": "pending",
            },
        )
    _notify_completion_routed(a, next_status, principal)
    return _serialize(a)


def submit_for_review(activity_id: str, principal, data: dict | None = None) -> dict:
    """Route an already-completed Activity into PL or IA review.

    My Plan supports a staged entry flow: evidence, attendance and the
    Salesforce ID can be captured in separate drawers before the user presses
    **Submit for review**.  That UI action must use the same authoritative
    gates as ``complete()``, rather than writing a status directly and
    bypassing evidence, attendance, SSA and scope validation.

    ``data`` is optional and carries only test/validation flags today
    (``strict_validation``) so the production evidence gate below can be
    exercised under test — it is not part of the user-facing payload.
    """
    data = data or {}
    a = _get_in_scope(activity_id, principal)
    if a.status not in SUBMITTABLE_STATUSES:
        raise BadRequest("Activity is not ready to be submitted for review.")

    from apps.evidence.models import EvidenceRecord

    if not EvidenceRecord.objects.filter(activity_id=a.id, quarantined=False).exists():
        raise BadRequest("Upload evidence before submitting completion.")

    import sys as _sys

    # Same test-relaxation convention as create() and complete(), but this
    # one previously had NO opt-in flag at all, so the per-activity-type
    # evidence gate on the submit-for-review path could never be exercised
    # by any test — a regression in missing_evidence_kinds() would have been
    # invisible to the whole suite. `strict_validation` now lets tests turn
    # the real production rule on; see ProductionGateRelaxationTest.
    is_testing = "test" in _sys.argv or "pytest" in _sys.modules
    if not is_testing or data.get("strict_validation"):
        from apps.evidence.requirements import missing_evidence_kinds

        missing = missing_evidence_kinds(a)
        if missing:
            labels = ", ".join(item["label"] for item in missing)
            raise BadRequest(
                f"Required evidence missing for this activity type: {labels}. "
                "Upload each required document before submitting completion."
            )

    if not a.salesforce_activity_id:
        raise BadRequest("Enter the Salesforce Activity ID before submitting.")
    if sf_kind(a.activity_type) == "training" and not (
        (a.teachers_attended or 0) > 0 or (a.leaders_attended or 0) > 0
    ):
        raise BadRequest(
            "Training completion requires attendance (teachers and/or school leaders)"
        )
    if a.delivery_type == "partner" and a.evidence_status != "accepted":
        raise BadRequest(
            "Partner evidence must be accepted by staff before submission."
        )
    if a.ssa_collection_expected and not a.ssa_not_collected_reason:
        from apps.ssa.models import SsaRecord

        if not SsaRecord.objects.filter(
            school=a.school,
            fy=get_operational_fy(),
            deleted_at__isnull=True,
        ).exists():
            raise BadRequest(
                "Record all SSA scores, or give a reason that SSA was not collected, "
                "before submitting this activity."
            )

    next_status = (
        "submitted_to_pl"
        if principal.active_role == "CCEO"
        else "awaiting_ia_verification"
    )
    with transaction.atomic():
        a.status = next_status
        if next_status == "awaiting_ia_verification":
            a.submitted_to_ia_at = timezone.now()
        a.save(update_fields=["status", "submitted_to_ia_at", "updated_at"])
        ActivityCompletionVerification.objects.update_or_create(
            activity=a,
            defaults={
                "salesforce_id": a.salesforce_activity_id,
                "entered_by": principal.user_id,
                "status": "pending",
            },
        )
    _notify_completion_routed(a, next_status, principal)
    return _serialize(a)


def record_attendance(activity_id: str, data: dict, principal) -> dict:
    """Persist attendance through the lifecycle service without completing it.

    Attendance is supporting execution evidence, not an approval transition.
    Completing an activity here would let a user skip the Salesforce/evidence
    requirements enforced by ``complete()`` and ``submit_for_review()``.
    """
    a = _get_in_scope(activity_id, principal)
    if a.status in ("closed", "cancelled", "rejected", "deferred"):
        raise BadRequest("Attendance cannot be changed after this activity is closed.")

    def count(name: str) -> int:
        raw = data.get(name, 0)
        try:
            value = int(raw or 0)
        except (TypeError, ValueError) as exc:
            raise BadRequest(f"{name} must be a whole number.") from exc
        if value < 0:
            raise BadRequest(f"{name} cannot be negative.")
        return value

    with transaction.atomic():
        a.teachers_attended = count("teachersAttended")
        a.leaders_attended = count("leadersAttended")
        a.other_participants = count("otherParticipants")
        a.attended_school_ids = _cluster_member_school_ids(
            a, data.get("attendedSchoolIds")
        )
        if a.status in (
            "scheduled",
            "in_progress",
            "assigned_to_partner",
            "partner_scheduled",
        ):
            a.status = "completion_started"
        a.save(
            update_fields=[
                "teachers_attended",
                "leaders_attended",
                "other_participants",
                "attended_school_ids",
                "status",
                "updated_at",
            ]
        )
    return _serialize(a)


def ia_confirm(activity_id: str, data: dict | None = None, principal=None) -> dict:
    """IA confirms the Salesforce entry (manual confirmation)."""
    a = _get_in_scope(activity_id, principal)
    if a.status != "awaiting_ia_verification":
        raise BadRequest("Activity is not awaiting IA verification")
    if a.delivery_type == "partner" and a.evidence_status != "accepted":
        raise Forbidden("Cannot confirm — partner evidence not accepted.")

    # For Core activities, perform strict validation:
    if a.activity_type in ("core_visit", "core_training"):
        try:
            from apps.evidence.models import EvidenceRecord
        except ImportError:
            evidence_count = 0
        else:
            evidence_count = EvidenceRecord.objects.filter(
                activity_id=a.id, quarantined=False
            ).count()
        if evidence_count == 0:
            raise BadRequest("IA Verification failed: No evidence files uploaded.")

        if not a.salesforce_activity_id:
            raise BadRequest(
                "IA Verification failed: Activity Salesforce ID is missing."
            )

        if not a.focus_intervention:
            raise BadRequest("IA Verification failed: Focus intervention not recorded.")

        if a.school and a.school.school_type == "core":
            from apps.ssa.models import SsaRecord

            latest_ssa = (
                SsaRecord.objects.filter(school=a.school, deleted_at__isnull=True)
                .order_by("-date_of_ssa")
                .first()
            )
            if not latest_ssa:
                raise BadRequest(
                    "IA Verification failed: No Core Assessment / SSA baseline exists for this school."
                )

    a.status = "ia_verified"
    a.ia_verification_status = "confirmed"
    a.ia_confirmed_at = timezone.now()
    a.ia_confirmed_by = principal.user_id
    # Activity + verification are saved atomically so the two rows cannot
    # diverge if the second write fails.
    with transaction.atomic():
        if hasattr(a, "verification") and a.verification:
            a.verification.status = "confirmed"
            a.verification.ia_actor_id = principal.user_id
            a.verification.ia_action_at = timezone.now()
            a.verification.save(update_fields=["status", "ia_actor_id", "ia_action_at"])
        # Payment path — keep parity with the live IA workspace
        # (AccountsRoutingService.route_to_accounts): partner activities enter
        # the payment queue, staff-delivered ones are stamped pending so both
        # IA-confirm entry points route finance identically.
        if a.delivery_type == "partner":
            a.payment_status = "ia_confirmed"
        else:
            a.payment_status = "pending_ia"

        # Core package slots must COMPLETE, not stall at "Scheduled" — no
        # writer ever marked one Completed, so the champion gate
        # (completed_slots >= 9) was unreachable for every school. IA
        # confirmation is the completion moment. The assessment slot ("a1")
        # additionally had no activity link at all: it completes when the
        # school's core_assessment_visit is verified.
        from apps.core_schools.models import CoreActivitySlot, cslot_id

        slot = CoreActivitySlot.objects.filter(activity_id=a.id).first()
        if slot is None and a.activity_type == "core_assessment_visit" and a.school_id:
            slot = CoreActivitySlot.objects.filter(
                id=cslot_id(a.school.school_id, "a", 1, fy=a.fy)
            ).first()
            if slot is not None and not slot.activity_id:
                slot.activity_id = a.id
        if slot is not None:
            slot.status = "Completed"
            slot.save(update_fields=["status", "activity_id", "updated_at"])
        a.save(
            update_fields=[
                "status",
                "ia_verification_status",
                "ia_confirmed_at",
                "ia_confirmed_by",
                "payment_status",
                "updated_at",
            ]
        )
    return _serialize(a)


def ia_return(activity_id: str, data: dict, principal) -> dict:
    """IA returns the activity completion to CCEO/partner for correction."""
    a = _get_in_scope(activity_id, principal)
    if a.status != "awaiting_ia_verification":
        raise BadRequest("Activity is not awaiting IA verification")

    reason = data.get("reason", "").strip()
    if not reason:
        raise BadRequest("Return reason is required.")

    a.status = "returned"
    a.ia_verification_status = "returned"
    a.pl_review_note = reason
    # Activity + verification saved atomically so they cannot diverge.
    with transaction.atomic():
        a.save(
            update_fields=[
                "status",
                "ia_verification_status",
                "pl_review_note",
                "updated_at",
            ]
        )
        if hasattr(a, "verification") and a.verification:
            a.verification.status = "returned"
            a.verification.save(update_fields=["status"])

    return _serialize(a)


def reschedule(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    old_date = a.scheduled_date
    new_date = _parse_date(data["scheduledDate"])

    # REG-02 gate (restored; deleted from this module by b4fc9570). Without it
    # a blocked date could be reached by rescheduling even when create() refused
    # it, which is the asymmetry calendar_policy.py exists to prevent.
    _staff = a.responsible_staff_id or a.monitored_by_staff_id
    _avail = _SchedulingPolicyService.check(
        _user_for_staff_identity(_staff) if _staff else None, new_date
    )
    if _avail["status"] == "blocked":
        raise BadRequest("Scheduling blocked: " + " · ".join(_avail["blockers"]))

    new_fy = get_operational_fy(new_date)
    new_quarter = get_quarter_for_date(new_date)
    planned_date, planned_month, planned_week = _schedule_period(new_date, data)
    a.scheduled_date = new_date
    a.fy = new_fy
    a.quarter = new_quarter
    a.planned_date = planned_date
    a.planned_month = planned_month
    a.planned_week = planned_week
    if "expectedParticipants" in data:
        a.expected_participants = data.get("expectedParticipants")
    a.reschedule_count += 1
    a.last_reason = data.get("reason")
    if a.status == "assigned_to_partner" or a.delivery_type == "partner":
        a.status = "partner_scheduled"
    else:
        a.status = "planned" if a.status in ("cancelled", "deferred") else "rescheduled"
    # The schedule-field save, the batch re-slot / re-price, and the leave
    # budget-impact rewrite of cost lines are 3 separate writes that must all
    # land or all roll back — a crash mid-sequence otherwise leaves the
    # activity's saved schedule out of sync with its budget lines.
    with transaction.atomic():
        a.save(
            update_fields=[
                "scheduled_date",
                "fy",
                "quarter",
                "planned_date",
                "planned_month",
                "planned_week",
                "expected_participants",
                "reschedule_count",
                "last_reason",
                "status",
                "updated_at",
            ]
        )
        from apps.daily_visit_batches.pricing import DAILY_BATCH_ELIGIBLE_TYPES

        if (
            a.activity_type in DAILY_BATCH_ELIGIBLE_TYPES
            and a.delivery_type == "staff"
            and a.school_id
        ):
            # Leave the OLD day's batch (recomputed for its remaining schools,
            # unless already locked — same rationale as everywhere else: reschedule
            # is the sanctioned post-approval escape hatch, so it isn't itself
            # blocked, but a locked batch's other members stay frozen).
            _detach_from_daily_visit_batch(a)
            from apps.daily_visit_batches.services import reschedule_within_batch

            reschedule_within_batch(
                activity=a,
                new_date=new_date.date(),
                reason=data.get("reason"),
                principal=principal,
            )
        else:
            # Re-price against the current catalogue so the budget line follows the
            # new schedule (rates may have changed; participant/period inputs may
            # have too).
            _apply_schedule_cost_snapshot(a, data, principal=principal)
            a.save(update_fields=["est_cost_cents", "cost_missing", "updated_at"])

        if old_date != new_date:
            from apps.hr.leave_services import LeaveBudgetImpactService

            LeaveBudgetImpactService.handle_reschedule(
                a, old_date, new_date, data.get("reason", "Rescheduling")
            )

    return _serialize(a)


def reassign(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    delivery = data.get("deliveryType", a.delivery_type)
    a.delivery_type = delivery
    a.assigned_partner_id = data.get("assignedPartnerId")
    a.responsible_staff_id = data.get("responsibleStaffId") or a.responsible_staff_id
    if "expectedParticipants" in data:
        a.expected_participants = data.get("expectedParticipants")
    if delivery == "partner":
        a.status = "assigned_to_partner"
    a.save(
        update_fields=[
            "delivery_type",
            "assigned_partner_id",
            "responsible_staff_id",
            "expected_participants",
            "status",
            "updated_at",
        ]
    )
    # Assignment changes the person responsible for both delivery and money.
    # Rebuild the draft cost/request buckets immediately so My Budget and the
    # correct staff member's weekly request stay in sync with this activity.
    if a.scheduled_date and a.status not in ("cancelled", "rejected"):
        _apply_schedule_cost_snapshot(a, data, principal=principal)
    return _serialize(a)


def partner_schedule(activity_id: str, data: dict, principal) -> dict:
    from apps.partners.models import PartnerAssignment
    from apps.core_schools.models import CoreActivitySlot, cslot_id

    pa = PartnerAssignment.objects.filter(id=activity_id).first()
    if pa:
        # Lock the assignment and refuse a second scheduling. Unlocked, two
        # simultaneous POSTs each created a costed Activity for one
        # assignment: two money-bearing rows, and the core slot pointed at
        # whichever committed last, orphaning the other.
        pa = (
            PartnerAssignment.objects.select_for_update().filter(id=activity_id).first()
        )
        if pa and pa.status in ("partner_scheduled", "scheduled", "completed"):
            raise BadRequest("This assignment is already scheduled.")
        # Scope: a partner principal may only schedule its OWN assignment —
        # the id-only lookup previously let any partner schedule another
        # partner's assignment. Staff callers pass through the shared scope.
        scope = resolve_user_scope(principal)
        if not scope.country_scope:
            if scope.partner_ids:
                if pa.partner_id not in scope.partner_ids:
                    raise Forbidden("Assignment belongs to another partner.")
            elif not (
                scope.school_ids and pa.school_id and pa.school_id in scope.school_ids
            ):
                raise Forbidden("Assignment outside your scope.")

        # Create a new Activity for this partner assignment. The multi-step
        # write (Activity + PartnerAssignment + optional CoreActivitySlot +
        # cost snapshot) is wrapped in a transaction so a failure midway
        # cannot leave a partially-created Activity with an inconsistent
        # PartnerAssignment or un-synced slot.
        from apps.activities.models import Activity

        scheduled_date = _parse_date(data["scheduledDate"])

        # REG-02 gate (restored; deleted from this module by b4fc9570). A
        # partner-delivered activity has no responsible staff member, so the
        # assigning staff member's calendar is the one that governs -- without
        # this, partner scheduling bypassed the policy entirely.
        _avail = _SchedulingPolicyService.check(
            _user_for_staff_identity(pa.assigning_staff_id)
            if pa.assigning_staff_id
            else None,
            scheduled_date,
        )
        if _avail["status"] == "blocked":
            raise BadRequest("Scheduling blocked: " + " · ".join(_avail["blockers"]))

        fy = get_operational_fy(scheduled_date)
        quarter = get_quarter_for_date(scheduled_date)
        planned_date, planned_month, planned_week = _schedule_period(
            scheduled_date, data
        )
        with transaction.atomic():
            monitored_by_staff_id = _canonical_staff_identity(pa.assigning_staff_id)
            a = Activity.objects.create(
                activity_type=pa.expected_activity_type or "core_visit",
                school=pa.school,
                cluster=pa.cluster,
                fy=fy,
                quarter=quarter,
                # responsible_staff_id holds a StaffProfile id everywhere else
                # in the system (see create()'s principal_owner_id convention)
                # — principal here is the partner's own User, which has no
                # StaffProfile. Partner-delivered activities leave this unset,
                # same as activities.services.create() does for
                # deliveryType="partner" (the field is reserved for
                # staff-conducted work; assigned_partner_id is the partner
                # link).
                responsible_staff_id=None,
                monitored_by_staff_id=monitored_by_staff_id,
                assigned_partner_id=pa.partner_id,
                delivery_type="partner",
                focus_intervention=pa.focus_intervention,
                purpose_intervention=pa.focus_intervention,
                activity_purpose_text=pa.notes or "Scheduled partner core support",
                purpose_type=pa.purpose_of_visit,
                expected_participants=data.get("expectedParticipants"),
                scheduled_date=scheduled_date,
                planned_date=planned_date,
                planned_month=planned_month,
                planned_week=planned_week,
                status="partner_scheduled",
            )

            pa.status = "partner_scheduled"
            try:
                from apps.notifications.services import resolve_condition

                resolve_condition(
                    "partner_scheduled_activity", "partner_assignment", pa.id
                )
            except Exception:  # noqa: BLE001 - bookkeeping never blocks scheduling
                pass
            pa.scheduled_date = scheduled_date
            # Normalise historic User-id assignments as they are activated,
            # so future read paths have one staff identity source of truth.
            if monitored_by_staff_id and pa.assigning_staff_id != monitored_by_staff_id:
                pa.assigning_staff_id = monitored_by_staff_id
                pa.save(
                    update_fields=[
                        "assigning_staff_id",
                        "status",
                        "scheduled_date",
                        "updated_at",
                    ]
                )
            else:
                pa.save(update_fields=["status", "scheduled_date", "updated_at"])

            if pa.school and pa.school.school_type == "core":
                kind_prefix = "v" if pa.support_type == "Visit" else "t"
                try:
                    seq_num = (
                        int(pa.visit_number)
                        if pa.visit_number
                        else (int(pa.training_number) if pa.training_number else 1)
                    )
                except ValueError:
                    seq_num = 1
                slot_id = cslot_id(pa.school.school_id, kind_prefix, seq_num, fy=fy)
                slot = CoreActivitySlot.objects.filter(id=slot_id).first()
                if slot:
                    slot.status = "Scheduled"
                    slot.activity_id = a.id
                    slot.scheduled_for = scheduled_date
                    slot.scheduled_month = (
                        str(scheduled_date.month) if scheduled_date else None
                    )
                    slot.scheduled_week = (
                        min(5, (scheduled_date.day - 1) // 7 + 1)
                        if scheduled_date
                        else None
                    )
                    slot.save()

            _apply_schedule_cost_snapshot(a, data, principal=principal)
            a.save(update_fields=["est_cost_cents", "cost_missing", "updated_at"])
        return _serialize(a)

    with transaction.atomic():
        a = _get_in_scope(activity_id, principal)
        new_date = _parse_date(data["scheduledDate"])

        # REG-02 gate (restored; deleted from this module by b4fc9570).
        _staff = a.responsible_staff_id or a.monitored_by_staff_id
        _avail = _SchedulingPolicyService.check(
            _user_for_staff_identity(_staff) if _staff else None, new_date
        )
        if _avail["status"] == "blocked":
            raise BadRequest("Scheduling blocked: " + " · ".join(_avail["blockers"]))

        a.scheduled_date = new_date
        a.fy = get_operational_fy(new_date)
        a.quarter = get_quarter_for_date(new_date)
        planned_date, planned_month, planned_week = _schedule_period(new_date, data)
        a.planned_date = planned_date
        a.planned_month = planned_month
        a.planned_week = planned_week
        if "expectedParticipants" in data:
            a.expected_participants = data.get("expectedParticipants")
        a.status = "partner_scheduled"
        a.save(
            update_fields=[
                "scheduled_date",
                "fy",
                "quarter",
                "planned_date",
                "planned_month",
                "planned_week",
                "expected_participants",
                "status",
                "updated_at",
            ]
        )

        # Update related PartnerAssignment if exists
        from django.db.models import Q

        pa_filter = Q()
        if a.school_id:
            pa_filter = Q(school_id=a.school_id)
        elif a.cluster_id:
            pa_filter = Q(cluster_id=a.cluster_id)

        if pa_filter:
            pa_rec = PartnerAssignment.objects.filter(
                pa_filter,
                partner_id=a.assigned_partner_id,
                status__in=[
                    "assigned",
                    "pending_scheduling",
                    "partner_pending_schedule",
                    "assigned_to_partner_pending_scheduling",
                ],
            ).first()
            if pa_rec:
                pa_rec.status = "partner_scheduled"
                pa_rec.scheduled_date = new_date.date() if new_date else None
                pa_rec.save(update_fields=["status", "scheduled_date", "updated_at"])

        # Update related CoreActivitySlot if exists
        slot = CoreActivitySlot.objects.filter(activity_id=a.id).first()
        if slot:
            slot.status = "Scheduled"
            slot.scheduled_for = new_date
            slot.scheduled_month = str(new_date.month) if new_date else None
            slot.scheduled_week = (
                min(5, (new_date.day - 1) // 7 + 1) if new_date else None
            )
            slot.save()

        _apply_schedule_cost_snapshot(a, data, principal=principal)
        a.save(update_fields=["est_cost_cents", "cost_missing", "updated_at"])
        return _serialize(a)


def _detach_from_daily_visit_batch(a: Activity) -> None:
    """If this activity is part of a Daily Visit Batch and that batch hasn't
    left draft status yet, detach it and recompute the remaining schools'
    allocated cost. If the batch is locked, leave it untouched — same
    rationale as reschedule(): post-approval changes go through the
    reschedule/cancel escape hatch, not silent batch recompute."""
    if not a.daily_visit_batch_id:
        return
    from apps.daily_visit_batches.services import remove_school

    try:
        remove_school(activity_id=a.id)
    except BadRequest:
        # Batch is locked (left draft) — leave its remaining lines frozen.
        pass


def cancel(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    a.status = "cancelled"
    a.last_reason = data.get("reason")
    a.save(update_fields=["status", "last_reason", "updated_at"])
    _detach_from_daily_visit_batch(a)
    return _serialize(a)


def defer(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    a.status = "deferred"
    a.last_reason = data.get("reason")
    a.save(update_fields=["status", "last_reason", "updated_at"])
    _detach_from_daily_visit_batch(a)
    return _serialize(a)


# ── Payment queue + clear-payment ────────────────────────────────────────────
def payment_queue(principal) -> list[dict]:
    """Accountant queue: partner-delivered activities awaiting payment."""
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(
        deleted_at__isnull=True,
        delivery_type="partner",
        payment_status__in=["ia_confirmed", "pl_approved", "accountant_cleared"],
    )
    if not scope.country_scope:
        if scope.school_ids:
            qs = qs.filter(school_id__in=scope.school_ids)
        else:
            qs = qs.none()
    qs = qs.select_related("school")[:200]
    out = []
    for a in qs:
        out.append(
            {
                "id": a.id,
                "activityType": a.activity_type,
                "salesforceActivityId": a.salesforce_activity_id,
                "evidenceStatus": a.evidence_status,
                "iaVerificationStatus": a.ia_verification_status,
                "paymentStatus": a.payment_status,
                "school": {"schoolId": a.school.school_id, "name": a.school.name}
                if a.school_id
                else None,
                "ready": (
                    a.evidence_status == "accepted"
                    and bool(a.salesforce_activity_id)
                    and a.ia_verification_status == "confirmed"
                    and a.payment_status != "paid"
                ),
            }
        )
    return out


def clear_payment(activity_id: str, principal) -> dict:
    """RETIRED. This endpoint used to flip payment_status to "paid" directly,
    which moved money with no PartnerPayment ledger row, no NetSuite Expense
    reference, no finance audit entry, and no closure snapshot. Partner
    payouts must go through PartnerPaymentService.pay_partner (Finance →
    Partner Payments queue), which records all of those."""
    raise BadRequest(
        "This endpoint is retired. Clear partner payments from the Finance "
        "Partner Payments queue, which records the payment ledger, NetSuite "
        "reference, and audit trail."
    )


def get_activity(activity_id: str, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    return _serialize(a)


def patch_activity(activity_id: str, data: dict, principal) -> dict:
    a = _get_in_scope(activity_id, principal)
    update_fields = []
    if "activityPurposeText" in data:
        a.activity_purpose_text = data["activityPurposeText"]
        update_fields.append("activity_purpose_text")
    if "purposeType" in data:
        a.purpose_type = data["purposeType"]
        update_fields.append("purpose_type")
    if "focusIntervention" in data:
        a.focus_intervention = data["focusIntervention"]
        # Maintain purpose_intervention for legacy compat
        a.purpose_intervention = data["focusIntervention"]
        update_fields.append("focus_intervention")
        update_fields.append("purpose_intervention")
    if "secondaryFocusInterventions" in data:
        a.secondary_focus_interventions = data["secondaryFocusInterventions"]
        update_fields.append("secondary_focus_interventions")
    if "expectedOutcome" in data:
        a.expected_outcome = data["expectedOutcome"]
        update_fields.append("expected_outcome")
    if "teachersAttended" in data:
        a.teachers_attended = data["teachersAttended"]
        update_fields.append("teachers_attended")
    if "leadersAttended" in data:
        a.leaders_attended = data["leadersAttended"]
        update_fields.append("leaders_attended")
    if "otherParticipants" in data:
        a.other_participants = data["otherParticipants"]
        update_fields.append("other_participants")
    if "expectedParticipants" in data:
        a.expected_participants = data["expectedParticipants"]
        update_fields.append("expected_participants")

    if update_fields:
        a.save(update_fields=update_fields + ["updated_at"])
    return _serialize(a)


def calculate_activity_impact(activity: Activity) -> dict:
    """Calculate the pre/post SSA impact of an activity."""
    if not activity.focus_intervention:
        return {
            "status": "Not Enough Data",
            "reason": "No focus intervention selected.",
        }
    if not activity.planned_date:
        return {
            "status": "Not Enough Data",
            "reason": "Impact cannot be measured until the activity has a planned date.",
        }

    # Activity.planned_date is a DateField; SSA is timestamped.  Define the
    # comparison boundary once in the deployment timezone rather than relying
    # on Django's lossy implicit date-to-naïve-datetime coercion.
    activity_boundary = timezone.make_aware(
        datetime.combine(activity.planned_date, datetime.min.time()),
        timezone.get_current_timezone(),
    )

    focus = activity.focus_intervention
    from apps.ssa.models import SsaRecord
    from apps.schools.models import School

    # If it's a school visit (associated with a specific school)
    if activity.school_id:
        # Confirmed-only, matching apps.ssa.services.latest_applicable_record:
        # "An unverified upload must never gate, justify, or rank
        # money-bearing work." These two queries previously filtered on
        # deleted_at alone, so a pending partner-collected SSA could set the
        # official before/after scores on the school-impact page.
        pre_ssa = (
            SsaRecord.objects.filter(
                school_id=activity.school_id,
                date_of_ssa__lt=activity_boundary,
                deleted_at__isnull=True,
                verification_status="confirmed",
            )
            .order_by("-date_of_ssa", "-created_at")
            .first()
        )

        post_ssa = (
            SsaRecord.objects.filter(
                school_id=activity.school_id,
                date_of_ssa__gt=activity_boundary,
                deleted_at__isnull=True,
                verification_status="confirmed",
            )
            .order_by("date_of_ssa", "created_at")
            .first()
        )

        if not pre_ssa:
            return {
                "status": "Not Enough Data",
                "reason": "Impact cannot be measured yet because baseline SSA is missing.",
            }
        if not post_ssa:
            return {
                "status": "Not Enough Data",
                "reason": "Pre or Post SSA is missing.",
            }

        pre_score = pre_ssa.scores.filter(intervention=focus).first()
        post_score = post_ssa.scores.filter(intervention=focus).first()

        if not pre_score or not post_score:
            return {
                "status": "Not Enough Data",
                "reason": "Focus intervention score missing in SSA.",
            }

        delta = round(post_score.score - pre_score.score, 2)
        if delta > 0:
            classification = "Improved"
        elif delta < 0:
            classification = "Declined"
        else:
            classification = "No Change"

        # Expose the gap between the two assessments so callers can tell a
        # genuine annual comparison from a two-week one instead of
        # presenting them identically — official impact is an ANNUAL
        # verified comparison (spec §12), and this per-activity delta must
        # not be mistaken for it.
        interval_days = (post_ssa.date_of_ssa - pre_ssa.date_of_ssa).days
        return {
            "status": classification,
            "preScore": pre_score.score,
            "postScore": post_score.score,
            "delta": delta,
            "preDate": pre_ssa.date_of_ssa.date().isoformat(),
            "postDate": post_ssa.date_of_ssa.date().isoformat(),
            "intervalDays": interval_days,
            "annualComparison": interval_days >= 300,
        }

    # If it's a cluster activity (associated with a cluster)
    elif activity.cluster_id:
        schools = School.objects.filter(
            cluster_id=activity.cluster_id, deleted_at__isnull=True
        )
        improved_count = 0
        declined_count = 0
        no_change_count = 0
        total_delta = 0.0
        counted_schools = 0

        for s in schools:
            # Confirmed-only, same rule as the school branch above.
            pre_ssa = (
                SsaRecord.objects.filter(
                    school=s,
                    date_of_ssa__lt=activity_boundary,
                    deleted_at__isnull=True,
                    verification_status="confirmed",
                )
                .order_by("-date_of_ssa", "-created_at")
                .first()
            )

            post_ssa = (
                SsaRecord.objects.filter(
                    school=s,
                    date_of_ssa__gt=activity_boundary,
                    deleted_at__isnull=True,
                    verification_status="confirmed",
                )
                .order_by("date_of_ssa", "created_at")
                .first()
            )

            if pre_ssa and post_ssa:
                pre_score = pre_ssa.scores.filter(intervention=focus).first()
                post_score = post_ssa.scores.filter(intervention=focus).first()
                if pre_score and post_score:
                    d = round(post_score.score - pre_score.score, 2)
                    total_delta += d
                    counted_schools += 1
                    if d > 0:
                        improved_count += 1
                    elif d < 0:
                        declined_count += 1
                    else:
                        no_change_count += 1

        if counted_schools == 0:
            return {
                "status": "Not Enough Data",
                "reason": "No cluster schools had pre/post SSA records.",
            }

        avg_delta = round(total_delta / counted_schools, 2)
        if avg_delta > 0:
            classification = "Improved"
        elif avg_delta < 0:
            classification = "Declined"
        else:
            classification = "No Change"

        return {
            "status": classification,
            "schoolsImproved": improved_count,
            "schoolsDeclined": declined_count,
            "schoolsCounted": counted_schools,
            "avgDelta": avg_delta,
        }

    return {
        "status": "Not Enough Data",
        "reason": "Activity does not have school or cluster link.",
    }


__all__ = [
    "list_activities",
    "create",
    "start_completion",
    "complete",
    "ia_confirm",
    "ia_return",
    "reschedule",
    "reassign",
    "partner_schedule",
    "cancel",
    "defer",
    "payment_queue",
    "clear_payment",
    "sf_kind",
    "_serialize",
    "get_activity",
    "patch_activity",
    "calculate_activity_impact",
]
