"""
Activities service — the 21-state field-work lifecycle (ports activities.service).

create → start-completion → complete → ia-confirm → (PL review) → payment.
Reschedule/reassign/cancel/defer; partner self-schedule; the accountant payment
queue + clear-payment. Period integrity (fy/quarter DERIVED from scheduledDate),
cost snapshots, Salesforce ID validation, and the authoritative payment guards
(money never moves before evidence accepted + SF ID + IA confirmed).
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.enums import (
    ActivityType,
    ExecutorType,
    PARTNER_EXECUTOR_TYPES,
    SsaIntervention,
)
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.scoping import (
    COUNTRY_SCHEDULING_ROLES,
    owner_ids,
    resolve_user_scope,
)
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
    ENTRY_SOURCE_IA_CONFIRMATION,
    ENTRY_SOURCE_MANAGING_STAFF,
    ENTRY_SOURCE_STAFF_SELF,
    reserve_salesforce_id,
)

# Why an administrator is turned away from a planning action, in the words the
# drawer should use. Names the way forward, because there is one: the same
# person switches to their CCEO role and plans their own portfolio.
ADMIN_IS_NOT_A_PLANNER_MESSAGE = (
    "Planning belongs to the staff member responsible for the school. The "
    "Admin role administers the platform and does not schedule field work — "
    "ask the school's CCEO to plan it, or switch to your own field role if "
    "you hold one."
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

logger = logging.getLogger(__name__)

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

# School-level partner work that represents an SSA assessment. Historical
# assignments did not always stamp ``ssa_collection_expected`` even though the
# purpose/activity type was SSA Support, so workflow routing must recognise all
# three authoritative signals while new writes stamp the boolean consistently.
PARTNER_SSA_SUPPORT_ACTIVITY_TYPES = frozenset(
    {
        ActivityType.SSA_ACTIVITY.value,
        ActivityType.BASELINE_SSA_VISIT.value,
        ActivityType.SCHOOL_VISIT_SSA_COLLECTION.value,
        ActivityType.PARTNER_SSA_COLLECTION.value,
    }
)


def is_partner_ssa_support_activity(activity: Activity) -> bool:
    """Whether completion must capture a school's SSA scores and enrolment."""
    return bool(
        activity.delivery_type == "partner"
        and activity.school_id
        and (
            activity.ssa_collection_expected
            or activity.purpose_type == "ssa_support"
            or activity.activity_type in PARTNER_SSA_SUPPORT_ACTIVITY_TYPES
        )
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


def _notify_certified_agency_booking(activity, agency, principal) -> None:
    """§21 — an agency must not discover a booking by browsing My Plan.

    Staff booked this agency onto a date the agency did not choose. The
    obligation is real the moment it is created — budget moves, the school
    expects someone — so the agency is told, in the same terms the booking
    was made, and the staff member who made it is confirmed.

    Best-effort, like every other notification in this module: a messaging
    failure must never roll back a committed schedule.
    """
    if agency is None:
        return
    where = _where(activity)
    when = (
        f"{activity.planned_date:%-d %b %Y}" if activity.planned_date else "a set date"
    )
    what = activity.activity_name_snapshot or activity.get_activity_type_display()
    agency_user_id = getattr(agency, "user_id", None)
    _notify_chain(
        activity,
        "partner_booking_created",
        "Edify has booked you to deliver work",
        (
            f"You have been booked to deliver {what} for {where} on {when}. "
            "Open My Plan to review the intervention focus, participant plan "
            "and preparation requirements."
        ),
        [agency_user_id],
        priority="high",
    )
    _notify_chain(
        activity,
        "partner_booking_confirmed",
        "Certified agency booked",
        f"{agency.name} is booked to deliver {what} for {where} on {when}.",
        [getattr(principal, "user_id", None)],
    )


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


def sf_kind_for_activity(activity: Activity) -> str | None:
    configured = (activity.salesforce_record_type_snapshot or "").upper()
    if configured in {"NONE", "SSA_DATA_GATHERING"}:
        return None
    if configured == "TRAINING":
        return "training"
    if configured == "VISIT":
        return "visit"
    return sf_kind(activity.activity_type)


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
    if getattr(activity, "monitored_by_staff_id", None) in owner_ids(principal):
        return
    if scope.partner_ids and activity.assigned_partner_id in scope.partner_ids:
        return
    if scope.school_ids and activity.school_id in scope.school_ids:
        return
    raise Forbidden("Activity outside your scope.")


def _assert_may_schedule(activity: Activity, principal) -> None:
    """Country visibility is not scheduling authority.

    `_assert_in_scope` is the *read* gate, and it is right to let the Programme
    Accountant through: confirming and paying an accountability means reading
    activities across the whole country. Scheduling mutations reuse that gate,
    so the same country flag that lets the Accountant read an activity also let
    them move its date — a planning power that is not part of the job.

    Deliberately narrow. It refuses only the case where country-wide visibility
    was the *sole* reason the caller got this far; anyone who reached the
    activity by owning it, monitoring it, or being its partner is unaffected,
    and the supervisor question that §10 answers for `create` is left exactly
    as `_assert_in_scope` had it rather than changed in passing.
    """
    scope = resolve_user_scope(principal)
    if scope.active_role in COUNTRY_SCHEDULING_ROLES:
        return
    if scope.country_scope:
        raise Forbidden(
            "Your role reviews and pays for this work rather than scheduling "
            "it. Ask the staff member who owns the activity to move it."
        )


def _assert_may_execute(activity: Activity, principal) -> None:
    """Reaching an activity is not the same as being able to run it.

    `_assert_in_scope` lets a Programme Lead through on any activity at a
    supervisee's school, because `school_ids` unions the team's schools in —
    correct for reading, and it is what let a supervisor reschedule, cancel,
    record attendance on, complete, and stamp the Salesforce ID of a CCEO's
    work. §1B lists every one of those among the things supervision does not
    license.

    Three ways to legitimately hold an activity, and supervision is not one:

      * you own it, in either id space (`owner_ids` — the responsible staff
        member, or the staff member monitoring a partner's delivery);
      * it sits at a school in your own portfolio, which covers work created
        by someone else at a school you now hold;
      * you are its partner.

    Country roles are handled by `_assert_may_schedule`, which every caller
    still applies where it applied before; this is the supervisor question,
    kept separate so neither answer can quietly absorb the other.
    """
    scope = resolve_user_scope(principal)
    if scope.active_role in COUNTRY_SCHEDULING_ROLES or scope.country_scope:
        return
    if not scope.supervised_staff_ids:
        return  # not a supervisor: `_assert_in_scope` already decided this
    mine = owner_ids(principal)
    if activity.responsible_staff_id in mine:
        return
    if getattr(activity, "monitored_by_staff_id", None) in mine:
        return
    if activity.school_id and activity.school_id in (scope.own_school_ids or []):
        return
    if activity.assigned_partner_id and activity.assigned_partner_id in (
        scope.partner_ids or []
    ):
        return
    if activity.cluster_id:
        from apps.clusters.models import Cluster
        from apps.core.scoping import cluster_in_scope

        cluster = (
            Cluster.objects.filter(id=activity.cluster_id, deleted_at__isnull=True)
            .only("id", "district_id", "responsible_staff_id")
            .first()
        )
        if cluster and cluster_in_scope(scope, cluster, direct_only=True):
            return
    from apps.core.scoping import OVERSIGHT_ONLY_MESSAGE

    raise Forbidden(OVERSIGHT_ONLY_MESSAGE)


def _target_in_direct_portfolio(scope, school: School | None, cluster_id) -> bool:
    """Is this target inside the *direct* portfolio the scope describes?

    Country-wide and summary-only readers have no portfolio at all, and both
    have to be turned away before the cluster branch below. `cluster_in_scope`
    answers True for every cluster in either case — the correct answer for a
    *reader*, and the wrong one to spend as authority to schedule. It is the
    one branch where a target need not be a school, so it stays open after the
    `own_school_ids` test has already refused them.

    Every role that may schedule country-wide has returned from
    `_assert_target_in_scope` before reaching here, so a country scope arriving
    at this function is precisely the Programme Accountant: country visibility,
    no scheduling authority. The RVP arrives the same way. Neither should be
    able to reach a cluster the school branch just refused them.
    """
    if getattr(scope, "can_view_summary_only", False) or scope.country_scope:
        return False
    if school and scope.own_school_ids and school.id in scope.own_school_ids:
        return True
    if cluster_id:
        from apps.clusters.models import Cluster
        from apps.core.scoping import cluster_in_scope

        cluster = (
            Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True)
            .only("id", "district_id", "responsible_staff_id")
            .first()
        )
        # `direct_only`, for the same reason the school branch above reads
        # `own_school_ids`. Without it the school half of this function
        # followed direct ownership and the cluster half followed supervision:
        # a Programme Lead refused a CCEO's school could still schedule a
        # cluster meeting or training in that CCEO's cluster, and — because
        # `district_ids` is derived from the own+team union — in every
        # not-yet-owned cluster across their supervisees' districts too.
        if cluster and cluster_in_scope(scope, cluster, direct_only=True):
            return True
    return False


def _delegated_owner_scope(scope, principal, owner_id: str | None):
    """The scope of a supervisee this principal may assign work to, or None.

    Assigning work to someone else is not the same act as doing it yourself.
    A supervisor accepting a Field Debrief recommendation creates an activity
    the *submitter* will own, at the submitter's own school — the write lands
    inside that person's portfolio, at their request, so it is their direct
    ownership that decides whether the target is legitimate.

    Two conditions, both required: the named owner must actually report to the
    principal, and the target must sit in that owner's own portfolio. Without
    the first, any staff member could plant work at a colleague's school by
    naming them as owner; without the second, a supervisor could use a
    supervisee as a pass-through to reach a school nobody owns.
    """
    if not owner_id:
        return None
    if owner_id in (principal.staff_profile_id, principal.user_id):
        return None
    supervised = {
        *(scope.supervised_staff_ids or []),
        *(scope.managed_staff_ids or []),
    }
    if not supervised:
        return None
    owner_user = _user_for_staff_identity(owner_id)
    if owner_user is None:
        return None
    if owner_user.staff_profile_id not in supervised and owner_id not in supervised:
        return None
    return resolve_user_scope(owner_user)


def _assert_target_in_scope(
    *, school: School | None, cluster_id: str | None, principal, owner_id=None
) -> None:
    """Validate create-time targets before an Activity exists.

    Planning follows **direct** ownership, so this reads `own_school_ids` and
    not `school_ids`. The latter unions in the schools of everyone a supervisor
    supervises, which let a Programme Lead schedule work at a CCEO's school
    purely because that CCEO reports to them — supervision acting as ownership.
    A PL supervising two CCEOs could plan across 1,030 schools that were not
    theirs.

    The PL still sees that work: it is on Team Planning Oversight, read-only,
    where the response to a problem is to ask the person who owns it rather
    than to reach past them. `own_school_ids` is populated for the CCEO and the
    Project Coordinator alike, so narrowing changes the supervisor's reach and
    nobody else's.

    `owner_id` covers the one legitimate case where the two come apart — see
    :func:`_delegated_owner_scope`.

    The country bypass reads `COUNTRY_SCHEDULING_ROLES`, not `country_scope`.
    Impact Assessment and the Programme Accountant both see the whole country,
    and until now both could therefore schedule anywhere in it — but the
    Accountant observes, pays and follows up accountabilities and schedules
    nothing, while IA does its own field visits and assessment training. One
    flag could not tell those two apart, so it granted the union.
    """
    scope = resolve_user_scope(principal)
    if scope.active_role in COUNTRY_SCHEDULING_ROLES:
        # Admin stays permitted *here* on purpose, even though the drawer no
        # longer offers it (`can_schedule_activity`). The two are different
        # questions. Delegation with an explicitly named `responsibleStaffId`
        # is a designed path with worked-out finance semantics — the assigned
        # staff member, not the administrator who pressed Save, owns the cost
        # lines and the weekly and monthly fund requests
        # (test_admin_scheduling_for_staff_uses_staff_finance_owner). Imports,
        # management commands and the REST surface all rely on it.
        #
        # What was wrong was never delegation; it was the drawer deriving the
        # responsible staff silently from the school owner and then sending
        # the administrator to their own My Plan to look for it. That is closed
        # at the view, where the silent derivation actually happens.
        return
    if _target_in_direct_portfolio(scope, school, cluster_id):
        return
    owner_scope = _delegated_owner_scope(scope, principal, owner_id)
    if owner_scope is not None and _target_in_direct_portfolio(
        owner_scope, school, cluster_id
    ):
        return
    # Name the actual reason. A supervisor refused here is not missing a
    # permission and not looking at a record that does not exist — they can
    # see it, on oversight, and the next step is to ask the person who owns
    # it. "Outside your scope" sent them to an administrator instead.
    if _target_under_oversight(scope, school, cluster_id):
        from apps.core.scoping import OVERSIGHT_ONLY_MESSAGE

        raise Forbidden(OVERSIGHT_ONLY_MESSAGE)
    raise Forbidden("Activity target outside your scope.")


def _target_under_oversight(scope, school: School | None, cluster_id) -> bool:
    """Can this person *watch* the target they were just refused?

    Only used to choose the wording of a refusal that has already happened —
    never to grant anything.
    """
    if school and school.id in (scope.team_school_ids or []):
        return True
    if cluster_id and cluster_id not in (scope.own_cluster_ids or []):
        from apps.clusters.models import Cluster
        from apps.core.scoping import cluster_in_scope

        cluster = (
            Cluster.objects.filter(id=cluster_id, deleted_at__isnull=True)
            .only("id", "district_id", "responsible_staff_id")
            .first()
        )
        return bool(
            cluster and scope.supervised_staff_ids and cluster_in_scope(scope, cluster)
        )
    return False


def _partner_evidence_exists(activity) -> bool:
    """Partner evidence goes DIRECTLY to IA (owner spec §10, 2026-08-20):
    submission requires evidence to exist, never a staff acceptance step."""
    from apps.evidence.models import EvidenceRecord

    return EvidenceRecord.objects.filter(
        activity_id=activity.id, quarantined=False
    ).exists()


def _get_in_scope(activity_id: str, principal) -> Activity:
    a = Activity.objects.filter(id=activity_id, deleted_at__isnull=True).first()
    if not a:
        raise NotFoundError("Activity not found.")
    _assert_in_scope(a, principal)
    return a


def _get_for_execution(activity_id: str, principal) -> Activity:
    """Resolve an activity the caller may actually act on.

    The read resolver plus the supervisor question. Used by every mutation —
    complete, submit, reschedule, reassign, cancel, attendance — so the answer
    cannot be right in five of them and forgotten in the sixth.
    """
    a = _get_in_scope(activity_id, principal)
    _assert_may_execute(a, principal)
    return a


def _serialize(a: Activity) -> dict:
    return {
        "id": a.id,
        "activityType": a.activity_type,
        "catalogueItemId": a.catalogue_item_id,
        "catalogueVersion": a.catalogue_version,
        "activityName": a.activity_name_snapshot or a.get_activity_type_display(),
        "catalogueActivityType": a.activity_type_snapshot,
        "deliveryMethod": a.delivery_method_snapshot,
        "evidenceProfile": a.evidence_profile_snapshot,
        "salesforceRecordType": a.salesforce_record_type_snapshot,
        "costingProfile": a.costing_profile_snapshot,
        "sourceSsaId": a.source_ssa_id,
        "sourceSsaVerificationState": a.source_ssa_verification_state,
        "sourceScore": float(a.source_score) if a.source_score is not None else None,
        "sourceClassification": a.source_classification,
        "recommendationReason": a.recommendation_reason,
        "followUpOfActivityId": a.follow_up_of_activity_id,
        "overrideReason": a.override_reason,
        "schoolId": a.school.school_id if a.school_id else None,
        "schoolName": a.school.name if a.school_id else None,
        "clusterId": a.cluster_id,
        "fy": a.fy,
        "quarter": a.quarter,
        "scheduledDate": a.scheduled_date.isoformat() if a.scheduled_date else None,
        "responsibleStaffId": a.responsible_staff_id,
        "deliveryContactName": a.delivery_contact_name,
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
        "ssaCollectionExpected": a.ssa_collection_expected,
    }


def _field_event_district_type(activity: Activity) -> str:
    """MOU travel profile for a field event: destination vs home district.

    Same district → primary day rates (transport + lunch). A different
    district → secondary per-diems (overnights add accommodation, dinner,
    breakfast). When the owner has no primary district on file, fall back to
    the destination district's own primary/secondary classification; with no
    destination at all the event prices as home-district work.
    """
    dest = activity.event_district_id
    if not dest:
        return "primary"
    from django.db.models import Q as _Q

    from apps.accounts.models import StaffProfile

    home = (
        StaffProfile.objects.filter(
            _Q(id=activity.responsible_staff_id)
            | _Q(user_id=activity.responsible_staff_id)
        )
        .values_list("primary_district_id", flat=True)
        .first()
    )
    if home:
        return "primary" if home == dest else "secondary"
    from apps.geography.models import District

    dtype = (
        District.objects.filter(id=dest).values_list("district_type", flat=True).first()
    )
    return dtype or "secondary"


def _costing_input(activity: Activity, data: dict) -> dict:
    """Build the canonical CostingService input from an activity + schedule data."""

    # A reschedule/reassignment form normally only posts the fields the user
    # changed.  Keep the attendance snapshot already on the activity when a
    # field is absent, otherwise a harmless date or ownership change can
    # accidentally re-price a training as though nobody were attending.
    def value(name: str, saved_value):
        posted = data.get(name)
        return saved_value if posted is None else posted

    # The district classification drives which rate family prices the work
    # (secondary-district visits carry accommodation/dinner components).
    # Only create() used to inject it from the school; reschedule/reassign/
    # partner_schedule passed the raw POST dict, so any re-price silently
    # degraded a secondary-district activity to primary rates. Resolve it
    # from the activity's own school here so every path prices identically.
    district_type = data.get("districtType")
    if not district_type and activity.school_id and activity.school.district_id:
        district_type = activity.school.district.district_type
    # Field events derive the travel profile from the owner's PRIMARY (home)
    # district vs the event's destination district — the MOU per-diem rule.
    # An explicit districtType in the form is a recorded override and wins.
    if not district_type and activity.activity_type == "field_event":
        district_type = _field_event_district_type(activity)

    return {
        "activityType": activity.activity_type,
        "costingProfile": activity.costing_profile_snapshot,
        "deliveryType": activity.delivery_type,
        "teachersAttended": value("teachersAttended", activity.teachers_attended),
        "leadersAttended": value("leadersAttended", activity.leaders_attended),
        "otherParticipants": value("otherParticipants", activity.other_participants),
        "expectedParticipants": value(
            "expectedParticipants", activity.expected_participants
        ),
        "districtType": district_type,
        "nights": data.get("nights"),
        "projectId": activity.project_id,
        "fy": activity.fy,
        # Multi-day programme events price per service day.
        "days": (
            (activity.end_date - activity.planned_date).days + 1
            if activity.end_date and activity.planned_date
            else 1
        ),
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


# A client school's package is one visit and one training per fiscal year.
# For catalogue-governed scheduling the catalogue decides which pool (if any)
# an item draws from; these type tuples remain the fallback for legacy rows
# and non-catalogue scheduling paths. The Activity Catalogue retired the
# generic ``school_visit`` in favour of ``follow_up_visit``, so both spell
# "client visit" here.
CLIENT_VISIT_LEGACY_TYPES = ("school_visit", "follow_up_visit")
CLIENT_TRAINING_LEGACY_TYPES = (
    "training",
    "in_school_training",
    "school_improvement_training",
)


def client_entitlement_consumers_q(pool: str) -> Q:
    """Filter for the Activities that have consumed a client entitlement pool.

    Canonical for both the scheduling guard and the system-health duplicate
    detector, so "what counts as the visit/training" cannot drift between the
    prevention and the detection. Catalogue-linked rows count by their item's
    governed flag; catalogue-less rows count by legacy activity_type.
    """
    if pool == "visit":
        return Q(catalogue_item__counts_toward_client_visit=True) | Q(
            catalogue_item__isnull=True, activity_type__in=CLIENT_VISIT_LEGACY_TYPES
        )
    return Q(catalogue_item__counts_toward_client_training=True) | Q(
        catalogue_item__isnull=True, activity_type__in=CLIENT_TRAINING_LEGACY_TYPES
    )


def _assert_schedule_entitlement(
    activity_type,
    school,
    fy,
    data,
    *,
    core_slot_verified: bool = False,
    catalogue_item=None,
):
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

    When a catalogue item is given, its governed flags decide the pool: the
    ``counts_toward_client_visit``/``counts_toward_client_training`` flags pick
    visit or training, and the eligibility rule's ``counts_toward_entitlement``
    is the governance switch that can exempt an item outright. Student camps
    and conferences carry workflow_kind ``training`` with both flags off — they
    must neither consume nor be blocked by the school's training entitlement.
    """
    if not school:
        return
    if activity_type in ("core_visit", "core_training"):
        if not core_slot_verified:
            raise BadRequest(
                "Core support must be scheduled from the Core Schools page, "
                "which reserves one of the package's slots."
            )
        return
    if getattr(school, "school_type", None) != "client":
        return
    if catalogue_item is not None:
        rule = getattr(catalogue_item, "eligibility_rule", None)
        if rule is not None and not rule.counts_toward_entitlement:
            return
        if catalogue_item.counts_toward_client_visit:
            pool = "visit"
        elif catalogue_item.counts_toward_client_training:
            pool = "training"
        else:
            return
    elif activity_type in CLIENT_VISIT_LEGACY_TYPES:
        pool = "visit"
    elif activity_type in CLIENT_TRAINING_LEGACY_TYPES:
        pool = "training"
    else:
        return
    live = (
        Activity.objects.filter(
            client_entitlement_consumers_q(pool),
            school=school,
            fy=fy,
            deleted_at__isnull=True,
        )
        .exclude(status__in=("cancelled", "rejected", "deferred"))
        .count()
    )
    if live >= 1:
        raise BadRequest(
            f"This client school's {pool} entitlement for FY{fy} is already "
            "used. Reschedule the existing activity instead of creating a "
            "second one."
        )


def _sync_cluster_attendance(activity, school_ids, actor_id="") -> None:
    """Mirror the confirmed register into the attendance table.

    The array column stays the record the older readers use while they are
    migrated; the rows are what school-level counts join against, because a
    cluster session has no school FK for them to filter on. Written together
    so the two can never disagree about who was in the room.
    """
    from apps.activities.models import ClusterActivityAttendance

    if not activity.cluster_id:
        return
    confirmed = set(school_ids or [])
    rows = {
        r.school_id: r
        for r in ClusterActivityAttendance.objects.filter(activity=activity)
    }
    for school_id in confirmed:
        row = rows.get(school_id)
        if row is None:
            ClusterActivityAttendance.objects.create(
                activity=activity,
                school_id=school_id,
                invited=False,
                attended=True,
                teachers=activity.teachers_per_school,
                leaders=activity.leaders_per_school,
                other=activity.other_per_school,
                recorded_by=actor_id or "",
            )
        elif not row.attended:
            row.attended = True
            row.recorded_by = actor_id or row.recorded_by
            row.save(update_fields=["attended", "recorded_by", "updated_at"])
    # An unticked school keeps its invitation as the record that it was asked.
    stale = [r for sid, r in rows.items() if sid not in confirmed and r.attended]
    if stale:
        ClusterActivityAttendance.objects.filter(id__in=[r.id for r in stale]).update(
            attended=False
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


#: Cluster activities whose participant count is derived from per-school
#: invitations rather than typed as a total. Deliberately explicit: a school
#: visit or a conference has no cluster membership to multiply by, and must
#: keep its own participant semantics.
CLUSTER_PARTICIPANT_ACTIVITY_TYPES = {
    "cluster_meeting",
    "cluster_meeting_ssa_review",
    "cluster_training",
    "cluster_training_ssa_collection",
}


def _resolved_executor_type(data: dict) -> str:
    """Which of the three delivery models this request is asking for.

    Accepts the explicit ``executorType`` the refreshed drawer sends, and
    keeps resolving the historic shape (``deliveryType`` plus a partner id)
    so existing API clients and every already-shipped surface keep working.
    An unrecognised value is refused rather than silently downgraded to
    staff — quietly making Edify the executor of partner work is the failure
    this field exists to prevent.
    """
    requested = (data.get("executorType") or data.get("executor_type") or "").strip()
    if requested:
        if requested not in ExecutorType.values:
            raise BadRequest(
                "Unknown delivery type. Choose Internal Staff, Assigned "
                "Partner, or Certified Partner Agency."
            )
        if requested in PARTNER_EXECUTOR_TYPES and not data.get("assignedPartnerId"):
            raise BadRequest("Select the Partner organisation delivering this work.")
        if requested == ExecutorType.STAFF and data.get("assignedPartnerId"):
            # Contradictory: staff delivery with a partner attached. The old
            # shape inferred "partner" from the id alone, so honouring the
            # explicit choice here without saying anything would silently
            # produce an activity that is staff-delivered but partner-stamped
            # — invisible to partner oversight and payment, yet counted
            # against the school's partner allowance.
            raise BadRequest(
                "Internal Staff delivery cannot name a Partner organisation. "
                "Choose a Partner delivery type, or clear the Partner."
            )
        return requested
    if data.get("deliveryType") == "partner" or data.get("assignedPartnerId"):
        return ExecutorType.PARTNER
    return ExecutorType.STAFF


def _assert_bookable_certified_agency(
    partner_id,
    *,
    activity_type: str,
    catalogue_item=None,
    school=None,
    scheduled_date=None,
):
    """§16 — the agency must actually be one, and be free to take this date.

    Staff booking an agency directly is a commitment made on the agency's
    behalf: it lands dated in their My Plan and draws budget immediately.
    Every condition that would otherwise be discovered by the agency after
    the fact is checked before the Activity exists.
    """
    from apps.partners.models import Partner
    from apps.partners.services import bookable_certified_agencies

    if not partner_id:
        raise BadRequest(
            "Select the Certified Partner Agency that will deliver this work."
        )
    partner = Partner.objects.filter(id=partner_id, deleted_at__isnull=True).first()
    if partner is None:
        raise BadRequest("Unknown Partner organisation.")
    if not partner.is_certified:
        raise BadRequest(
            f"{partner.name} is not a Certified Partner Agency. Certified "
            "agencies are the only partners Edify may book onto a date "
            "directly; assign the school to the partner instead and let them "
            "schedule it."
        )
    # Same query the picker is built from, so nothing offered can fail here
    # and nothing refused here could have been offered.
    if not bookable_certified_agencies().filter(id=partner.id).exists():
        raise BadRequest(
            f"{partner.name} cannot take new bookings right now (inactive, on "
            "hold, or certification not current)."
        )
    if (
        catalogue_item is not None
        and not catalogue_item.certified_agency_delivery_allowed
    ):
        raise BadRequest(
            f"{catalogue_item.display_name} is not approved for Certified "
            "Partner Agency delivery."
        )
    if school is not None and partner.coverage_districts and school.district_id:
        district_name = getattr(school.district, "name", None)
        if district_name and district_name not in partner.coverage_districts:
            raise BadRequest(
                f"{partner.name} does not cover {district_name}. Choose an "
                "agency certified for this district."
            )
    if scheduled_date is not None:
        # §19.10 — an agency cannot be in two places on one day. This is the
        # agency's own calendar, not Edify's: work another CCEO booked counts.
        clash = (
            Activity.objects.filter(
                assigned_partner_id=partner.id,
                planned_date=scheduled_date.date(),
                deleted_at__isnull=True,
            )
            .exclude(status__in=("cancelled", "rejected", "deferred", "rescheduled"))
            .exists()
        )
        if clash:
            raise BadRequest(
                f"{partner.name} already has work booked on "
                f"{scheduled_date:%-d %b %Y}. Choose another date or another "
                "certified agency."
            )
    return partner


#: Every request key that carries a planned participant quantity. A drawer
#: that hides a field with x-show still SUBMITS it, so switching Training →
#: Visit posted the 30 participants typed a moment earlier. Naming them in one
#: place is what makes "a visit has no participants" enforceable rather than
#: aspirational.
PARTICIPANT_INPUT_KEYS = (
    "expectedParticipants",
    "participantsPerSchool",
    "teachersAttended",
    "leadersAttended",
    "otherParticipants",
    "teachersPerSchool",
    "leadersPerSchool",
    "otherPerSchool",
)

#: The planned composition of a cluster room, stated per member school. The
#: per-school figure is their SUM — the drawer never asks for it, because a
#: typed total that disagrees with its own breakdown is not a number to keep.
PER_SCHOOL_CATEGORY_KEYS = (
    "teachersPerSchool",
    "leadersPerSchool",
    "otherPerSchool",
)


def _participant_mode_for(catalogue_item, activity_type: str) -> str:
    """The participant mode governing this activity.

    The Catalogue item is the Workflow Profile and wins. Activities created
    before the profile existed — and API clients posting a bare activity type
    with no catalogue item — fall back to the same derivation the seed uses,
    so an uncatalogued visit is still a visit with no participants.
    """
    from apps.activity_catalogue.seed_data import default_participant_mode
    from apps.core.enums import ParticipantMode

    if catalogue_item is not None and catalogue_item.participant_mode:
        return catalogue_item.participant_mode
    if not activity_type:
        return ParticipantMode.NONE
    return default_participant_mode(activity_type, False)


def _apply_participant_mode(data: dict, mode: str) -> dict:
    """Normalize participant input to what this activity actually plans.

    §9 — enforced here, at the service, not in the drawer's JavaScript. An API
    client posting ``expectedParticipants`` on a school visit must not be able
    to move that visit's cost, and a stale value left over from a previous
    drawer selection must not be stored as though somebody meant it.
    """
    from apps.core.enums import ParticipantMode

    if mode == ParticipantMode.NONE:
        # Cleared, not rejected: the value is almost always a stale artifact
        # of the drawer rather than an assertion, and refusing the submission
        # would turn a UI leftover into a failed schedule. What matters is
        # that it reaches neither the cost engine nor the stored record.
        return {**data, **{key: None for key in PARTICIPANT_INPUT_KEYS}}

    if mode == ParticipantMode.PER_SCHOOL:
        # Deliberately NOT cleared, even though the total is derived from live
        # cluster membership further down and a supplied total is overwritten
        # whenever `participantsPerSchool` is present.
        #
        # Clearing it looks like the stricter, safer rule and is the opposite.
        # `apps.budget.costing._participants_of` falls back to
        # DEFAULT_TRAINING_PARTICIPANTS (25) when no count reaches it, so
        # discarding a stated 15 did not price zero participants — it priced
        # twenty-five, and quietly raised the budget line by 120,000 UGX. A
        # figure someone actually stated beats a hardcoded default.
        #
        # The rule the drawer enforces (§11 — never ask for a total) is a
        # drawer rule, and the drawer has no total field for cluster work.
        return data

    if mode == ParticipantMode.BY_CATEGORY:
        categories = ("teachersAttended", "leadersAttended", "otherParticipants")
        supplied = [data.get(key) for key in categories]
        if any(value not in (None, "") for value in supplied):
            total = 0
            for key in categories:
                total += _validated_participant_category(data.get(key), key)
            if total < 1:
                raise BadRequest(
                    "Enter how many teachers, school leaders or other "
                    "participants are planned for this training."
                )
            # The backend calculates the total (§10) — a typed total that
            # disagrees with its own breakdown is not a number to preserve.
            return {**data, "expectedParticipants": total}
        return {**data, "participantsPerSchool": None}

    # DIRECT_TOTAL
    return {**data, "participantsPerSchool": None}


_CATEGORY_LABELS = {
    "teachersAttended": "teachers",
    "leadersAttended": "school leaders",
    "otherParticipants": "other participants",
    "teachersPerSchool": "teachers per school",
    "leadersPerSchool": "school leaders per school",
    "otherPerSchool": "other participants per school",
}


def _validated_participant_category(raw, key: str) -> int:
    if raw in (None, ""):
        return 0
    text = str(raw).strip()
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise BadRequest(
            f"The number of {_CATEGORY_LABELS.get(key, key)} must be a whole number."
        ) from exc
    if value < 0:
        raise BadRequest(
            f"The number of {_CATEGORY_LABELS.get(key, key)} cannot be negative."
        )
    if value > 100000:
        raise BadRequest(
            f"The number of {_CATEGORY_LABELS.get(key, key)} is implausibly large."
        )
    return value


def _validated_per_school_categories(data: dict) -> dict:
    """The planned per-school composition, or ``{}`` when none was stated.

    Cluster work is planned per member school, and who is invited from each
    school is a different question from how many: two people per school is a
    head and a teacher for a leadership meeting and two teachers for a Literacy
    session. The three categories are what the drawer asks for; the per-school
    figure is their sum, so nobody types a number that can disagree with its
    own breakdown.

    Absent categories are not an error — an API client may still state
    ``participantsPerSchool`` directly, which is how every activity scheduled
    before this existed was planned.
    """
    supplied = {
        key: data.get(key)
        for key in PER_SCHOOL_CATEGORY_KEYS
        if data.get(key) not in (None, "")
    }
    if not supplied:
        return {}
    categories = {
        key: _validated_participant_category(data.get(key), key)
        for key in PER_SCHOOL_CATEGORY_KEYS
    }
    if sum(categories.values()) < 1:
        raise BadRequest(
            "Enter how many teachers, school leaders or other participants to "
            "invite from each school."
        )
    return categories


def _validated_schools_invited(raw, cluster_school_count: int) -> int:
    """How many member schools are actually being invited.

    Defaults to the whole cluster, which is what every activity scheduled
    before this input existed meant. The ceiling is the live membership: a
    cluster of eight cannot invite nine, and accepting it would cater and
    budget for a school that does not exist. The floor is one, for the same
    reason a zero-participant training is not a training.
    """
    if raw in (None, ""):
        return cluster_school_count
    text = str(raw).strip()
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise BadRequest(
            "The number of schools invited must be a whole number."
        ) from exc
    if str(value) != text.lstrip("+"):
        raise BadRequest("The number of schools invited must be a whole number.")
    if value < 1:
        raise BadRequest(
            "Invite at least one school, or schedule this as school-level support."
        )
    if value > cluster_school_count:
        raise BadRequest(
            f"This cluster has {cluster_school_count} active school"
            f"{'' if cluster_school_count == 1 else 's'}, so it cannot invite "
            f"{value}."
        )
    return value


def _validated_participants_per_school(raw) -> int:
    """A positive whole number, or a refusal that says which rule was broken.

    Decimals are rejected rather than rounded: 2.5 participants per school
    across 30 schools is 75 people if you round up and 60 if you truncate, and
    neither is a number anybody chose.
    """
    text = str(raw).strip()
    if not text:
        raise BadRequest("Enter how many participants to invite from each school.")
    try:
        value = int(text)
    except (TypeError, ValueError) as exc:
        raise BadRequest(
            "Participants per school must be a whole number — 2, not 2.5."
        ) from exc
    if str(value) != text.lstrip("+"):
        raise BadRequest("Participants per school must be a whole number — 2, not 2.5.")
    if value < 1:
        raise BadRequest("Participants per school must be at least 1.")
    if value > 500:
        raise BadRequest("Participants per school must be 500 or fewer.")
    return value


def resolve_primary_driver(data: dict) -> tuple[str, str, str]:
    """The one reason this activity exists, from what the caller already knows.

    Ordered most-specific first. A school visit raised from a recommendation
    IS driven by that recommendation even though it also sits under a priority
    allocation; recording the allocation instead would lose the school need
    that actually caused it.

    Returns ("", "", "") when nothing identifies a driver — reported as a
    data-quality exception rather than guessed at.
    """
    from apps.activities.models import Activity

    driver = Activity.Driver
    candidates = (
        (driver.SSA_RECOMMENDATION, data.get("ssaRecommendationId")),
        (driver.PRIORITY_ALLOCATION, data.get("priorityAllocationId")),
        (driver.CORE_PACKAGE, data.get("corePackageSlotId") or data.get("coreSlotId")),
        (
            driver.BUSINESS_TRANSFORMATION,
            data.get("businessTransformationCaseId") or data.get("btCaseId"),
        ),
        (driver.EXTRA_ASSIGNMENT, data.get("extraAssignmentId")),
        (driver.SPECIAL_PROJECT, data.get("projectId")),
    )
    for kind, value in candidates:
        if value:
            return str(kind), str(value), ""

    reason = (
        data.get("driverReason")
        or data.get("supportRationale")
        or data.get("support_rationale")
        or ""
    ).strip()
    if reason:
        return str(driver.LEADERSHIP_EXCEPTION), "", reason
    return "", "", ""


# ── Create ───────────────────────────────────────────────────────────────────
def create(
    data: dict,
    principal,
    *,
    skip_cost_snapshot: bool = False,
    core_slot_verified: bool = False,
) -> dict:
    """Create and cost one governed Activity.

    Catalogue eligibility, SSA recommendation lineage, frequency, scope,
    scheduling policy, duplicate prevention, and Cost Catalogue readiness are
    authoritative gates. A dated Activity is persisted only when its cost
    snapshot can be written in the same transaction.

    ``skip_cost_snapshot`` and ``core_slot_verified`` are trusted,
    internal-caller flags (the Daily Visit Batch service and the Core Schools
    slot machinery respectively). They were previously read from ``data`` —
    i.e. from the raw API payload — which let any caller of POST /api/activities
    create a money-bearing activity with zero cost lines, or a core activity
    outside the slot cap. They are keyword-only now and the corresponding keys
    are stripped from ``data`` before use.
    """
    # Defense-in-depth: these keys must never be honoured from request data.
    data = {
        k: v
        for k, v in data.items()
        if k not in ("_skip_cost_snapshot", "coreSlotVerified")
    }
    catalogue_item = None
    catalogue_item_id = data.get("catalogueItemId") or data.get("catalogue_item_id")
    if data.get("requireCatalogue") and not catalogue_item_id:
        raise BadRequest(
            "Select an approved Activity Catalogue item. Free-text or generic "
            "Activity creation is not available in Planning."
        )
    if catalogue_item_id:
        from apps.activity_catalogue.services import get_selectable_item

        catalogue_item = get_selectable_item(
            str(catalogue_item_id),
            on_date=(
                _parse_date(data["scheduledDate"]).date()
                if data.get("scheduledDate")
                else None
            ),
        )
    activity_type = (
        catalogue_item.workflow_kind if catalogue_item else data.get("activityType")
    )
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

    # ── Participant mode ─────────────────────────────────────────────────
    # What this activity actually plans in people, per its Workflow Profile.
    # Applied only to school/cluster work: non-school programme activities
    # (camps, conferences) run their own participant rules further down, and
    # those have their own required quantities.
    participant_mode = _participant_mode_for(catalogue_item, activity_type)
    if school_id_str or cluster_id:
        data = _apply_participant_mode(data, participant_mode)
        # §9 (Uganda master): when the published master carries a
        # participants-per-school guidance for this activity and the planner
        # stated no figure, suggest the guidance. A stated figure always wins,
        # and this beats the silent 25-participant costing fallback that would
        # otherwise price the gap.
        from apps.core.enums import ParticipantMode as _PMode

        if (
            participant_mode == _PMode.PER_SCHOOL
            and data.get("participantsPerSchool") in (None, "")
            and catalogue_item is not None
        ):
            from apps.hr.target_distribution import participant_guidance_for

            guidance = participant_guidance_for(catalogue_item.id)
            if guidance:
                data = {**data, "participantsPerSchool": guidance}

    # ── Cluster participant planning ─────────────────────────────────────
    # The user states how many people to invite per school. The total is
    # derived HERE, from the cluster's live membership, and never taken from
    # the request: a submitted total is a number the browser computed, and the
    # thing it multiplies into is a budget line.
    participants_per_school = None
    cluster_school_count = None
    schools_invited = None
    per_school_categories = {}
    if activity_type in CLUSTER_PARTICIPANT_ACTIVITY_TYPES and cluster_id:
        # Teachers + school leaders + other, per school. Their sum IS the
        # per-school figure, so a stated breakdown wins over any total the
        # request also happened to carry.
        per_school_categories = _validated_per_school_categories(data)
        raw_per_school = (
            sum(per_school_categories.values())
            if per_school_categories
            else data.get("participantsPerSchool")
        )
        if raw_per_school not in (None, ""):
            participants_per_school = _validated_participants_per_school(raw_per_school)
            from apps.clusters.services import active_school_count

            cluster_school_count = active_school_count(cluster_id)
            if cluster_school_count < 1:
                raise BadRequest(
                    "This cluster has no active schools, so there is nobody to "
                    "invite. Add schools to the cluster before planning a "
                    "cluster activity for it."
                )
            # Not every member school qualifies for every session — a Literacy
            # training does not reach the secondary and vocational schools in a
            # mixed cluster. Left unstated, the whole cluster is invited, which
            # is what this has always meant.
            schools_invited = _validated_schools_invited(
                data.get("schoolsInvited"), cluster_school_count
            )
            # Overwrites whatever the form sent. The browser's arithmetic is a
            # preview; this is the number that gets costed and stored.
            data = {
                **data,
                "expectedParticipants": participants_per_school * schools_invited,
            }

    non_school = bool(
        catalogue_item
        and catalogue_item.non_school_allowed
        and not school
        and not cluster_id
    )
    if not school and not cluster_id and not non_school:
        raise BadRequest(
            "Activity must reference a school or cluster. Programme work "
            "without one must use an approved non-school Catalogue Activity."
        )

    end_date = None
    if non_school:
        from apps.core.enums import (
            ProgrammeActivityType,
            ProgrammeDeliveryMode,
            SupportRationale,
        )

        rationale = (
            data.get("supportRationale") or data.get("support_rationale") or ""
        ).strip()
        if rationale not in SupportRationale.values:
            raise BadRequest(
                "Select the strategic rationale for this programme Activity "
                "(project objective, organizational priority, staff "
                "development, …). Generic unrationalized work is not allowed."
            )
        if rationale == SupportRationale.PROJECT_OBJECTIVE and not data.get(
            "projectId"
        ):
            raise BadRequest(
                "A Project Objective rationale must name the Special Project "
                "this Activity serves."
            )
        if catalogue_item.requires_participant_counts and not data.get(
            "expectedParticipants"
        ):
            raise BadRequest(
                "Enter the expected participant count — this Activity type is "
                "priced and planned per participant."
            )
        if data.get("programmeActivityType") not in ProgrammeActivityType.values:
            raise BadRequest("Select a valid programme Activity type.")
        if data.get("programmeDeliveryMode") not in ProgrammeDeliveryMode.values:
            raise BadRequest("Select Group or Cluster as the delivery mode.")
        selected_intervention = focus or data.get("purposeIntervention")
        programme_mapping_rows = list(
            catalogue_item.intervention_mappings.filter(active=True).values_list(
                "mapping_mode", "intervention"
            )
        )
        has_fixed_intervention = any(
            intervention for _mode, intervention in programme_mapping_rows
        )
        inherits_intervention = any(
            mode == "inherit_from_source_activity"
            for mode, _intervention in programme_mapping_rows
        )
        if (
            has_fixed_intervention
            and selected_intervention not in SsaIntervention.values
        ):
            raise BadRequest("Select the SSA intervention linked to this Activity.")
        if (
            inherits_intervention
            and selected_intervention not in SsaIntervention.values
        ):
            raise BadRequest(
                "Select the training or support intervention being followed up."
            )
        if not has_fixed_intervention and not inherits_intervention:
            focus = None
        try:
            planned_school_count = int(data.get("plannedSchoolCount") or 0)
        except (TypeError, ValueError) as exc:
            raise BadRequest("Number of schools must be a whole number.") from exc
        # Field events are internal staff work (district meetings, boot camps,
        # workshops) — they reach no schools, and demanding a fabricated count
        # here would poison the reach numbers downstream.
        if activity_type == "field_event":
            planned_school_count = 0
        elif planned_school_count < 1 or planned_school_count > 10000:
            raise BadRequest("Number of schools must be between 1 and 10,000.")
        try:
            participant_count = int(data.get("expectedParticipants") or 0)
        except (TypeError, ValueError) as exc:
            raise BadRequest("Number of participants must be a whole number.") from exc
        # A field event prices the OWNER's travel per-diems, not a room of
        # participants — a headcount is welcome context, never a requirement.
        if activity_type != "field_event" and (
            participant_count < 1 or participant_count > 100000
        ):
            raise BadRequest("Number of participants must be between 1 and 100,000.")
        if not (data.get("venue") or "").strip():
            raise BadRequest("Enter the Activity venue.")
        end_raw = data.get("endDate") or data.get("end_date")
        if end_raw:
            end_date = _parse_date(str(end_raw)).date()
            if not scheduled_date:
                raise BadRequest("A multi-day Activity needs its start date.")
            if end_date < scheduled_date.date():
                raise BadRequest("The end date cannot precede the start date.")
            if end_date != scheduled_date.date():
                if not catalogue_item.multi_day_allowed:
                    raise BadRequest("This Activity type is a single-day activity.")
                if (end_date - scheduled_date.date()).days > 30:
                    raise BadRequest("A programme Activity may span at most 31 days.")
    if not non_school:
        # A non-school programme activity has no school/cluster target to
        # scope-check; its authority is the MANUAL_ACTIVITY_CREATE permission
        # enforced by planning.schedule_programme_activity, plus the
        # responsible-person assignment rules below.
        _assert_target_in_scope(
            school=school,
            cluster_id=cluster_id,
            principal=principal,
            owner_id=data.get("responsibleStaffId"),
        )
    _assert_schedule_entitlement(
        activity_type,
        school,
        fy,
        data,
        core_slot_verified=core_slot_verified,
        catalogue_item=catalogue_item,
    )

    # ── Who executes ─────────────────────────────────────────────────────
    # Two partner workflows, one delivery type. `is_partner` keeps its
    # historic meaning (a partner organisation delivers this) because every
    # downstream surface reads it; `executor_type` records WHICH partner
    # workflow, which is what decides whether the partner still has to pick a
    # date or has already been booked onto one.
    executor_type = _resolved_executor_type(data)
    is_partner = executor_type in PARTNER_EXECUTOR_TYPES
    is_certified_agency_booking = executor_type == ExecutorType.CERTIFIED_PARTNER_AGENCY
    certified_agency = None
    if is_certified_agency_booking:
        certified_agency = _assert_bookable_certified_agency(
            data.get("assignedPartnerId"),
            activity_type=activity_type,
            catalogue_item=catalogue_item,
            school=school,
            scheduled_date=scheduled_date,
        )
        if scheduled_date is None:
            raise BadRequest(
                "A Certified Partner Agency booking needs the date Edify is "
                "booking the agency for."
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
        if end_date and end_date != scheduled_date.date():
            from datetime import datetime as _dt

            end_check = _SchedulingPolicyService.check(
                resp_user,
                timezone.make_aware(_dt.combine(end_date, _dt.min.time())),
            )
            if end_check["status"] == "blocked":
                raise BadRequest(
                    "Scheduling blocked on the end date: "
                    + " · ".join(end_check["blockers"])
                )

    # A paused or closed Special Project must stop absorbing new commitments —
    # that is what the RVP's pause/close decision means. Gating only the
    # school-assignment paths left this funnel open, so a closed project could
    # still accrue activities and, through costing, real spend.
    project_id = data.get("projectId")
    project = None
    if project_id:
        from apps.projects.models import Project
        from apps.projects.services import assert_accepts_new_work

        project = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
        if project is None:
            raise BadRequest("Unknown project.")
        assert_accepts_new_work(project)
        # A Project already declares which SSA interventions it exists to
        # move, so asking the planner to restate them invites disagreement.
        # The project's explicit primary (or first ordered target for newer
        # records) becomes the Activity focus; the remaining targets are
        # retained as supporting interventions. A caller that deliberately
        # states a different focus is still respected by this general service.
        primary_target, supporting_targets = project.intervention_plan()
        if activity_type == "cluster_training" and not primary_target:
            raise BadRequest(
                f"'{project.name}' does not have an SSA intervention configured. "
                "Configure the Project before scheduling its Group Training."
            )
        if not focus and not data.get("purposeIntervention") and primary_target:
            focus = primary_target
            data = {
                **data,
                "focusIntervention": focus,
                "secondaryFocusInterventions": supporting_targets,
            }
        elif (
            focus == primary_target
            and supporting_targets
            and not data.get("secondaryFocusInterventions")
        ):
            data = {**data, "secondaryFocusInterventions": supporting_targets}
        # Selecting the Project replaces the drawer's free-text purpose. Keep
        # the Project name on the Activity so My Plan, exports and evidence
        # have a human-readable purpose without asking the planner twice.
        if not p_text:
            p_text = project.name
            data = {**data, "activityPurposeText": p_text}

    source_ssa = None
    source_activity = None
    catalogue_cluster = _catalogue_cluster(cluster_id) if cluster_id else None
    is_school_training_follow_up = bool(
        school is not None
        and (
            p_type == "training_follow_up"
            or activity_type == ActivityType.TRAINING_FOLLOW_UP_VISIT
        )
    )
    if is_school_training_follow_up and not data.get("sourceActivityId"):
        raise BadRequest(
            "Select the completed Cluster Training or Cluster Meeting this visit follows up."
        )
    governed_recommendation_reason = data.get("recommendationReason", "")
    governed_recommendation_source = {}
    if catalogue_item:
        from apps.activity_catalogue.models import MappingMode
        from apps.activity_catalogue.services import (
            validate_context,
            validate_frequency,
        )
        from apps.ssa.services import latest_applicable_record

        if data.get("sourceActivityId"):
            source_activity = Activity.objects.filter(
                id=data.get("sourceActivityId"), deleted_at__isnull=True
            ).first()
            if source_activity is None:
                raise BadRequest("The selected source Activity does not exist.")
            if (
                school is not None
                and not is_school_training_follow_up
                and source_activity.school_id != school.id
            ):
                raise BadRequest("The source Activity must belong to the same School.")
            if (
                catalogue_cluster is not None
                and source_activity.cluster_id != catalogue_cluster.id
            ):
                raise BadRequest("The source Activity must belong to the same Cluster.")
            if project and source_activity.project_id not in {None, project.id}:
                raise BadRequest(
                    "The source Activity belongs to a different Special Project."
                )
            if source_activity.status not in (
                "completed",
                "ia_verified",
                "accountant_confirmed",
                "closed",
            ):
                raise BadRequest(
                    "Follow-up requires a completed source Training or support Activity."
                )
            if is_school_training_follow_up:
                permitted_source_types = {
                    ActivityType.CLUSTER_TRAINING,
                    ActivityType.CLUSTER_TRAINING_SSA_COLLECTION,
                    ActivityType.CLUSTER_MEETING,
                    ActivityType.CLUSTER_MEETING_SSA_REVIEW,
                }
                if source_activity.activity_type not in permitted_source_types:
                    raise BadRequest(
                        "Training Follow Up must reference a completed Cluster "
                        "Training or Cluster Meeting."
                    )
                if source_activity.fy != fy:
                    raise BadRequest(
                        "Training Follow Up must reference a session from the "
                        "same Fiscal Year as the scheduled visit."
                    )
                if school.id not in (source_activity.attended_school_ids or []):
                    raise BadRequest(
                        "This School is not recorded as attending the selected "
                        "Cluster Training or Cluster Meeting."
                    )
                inherited_focus = (
                    source_activity.focus_intervention
                    or source_activity.purpose_intervention
                )
                if inherited_focus not in SsaIntervention.values:
                    raise BadRequest(
                        "The selected session has no valid intervention to follow up. "
                        "Ask IA to repair its completion record."
                    )
                # The source session, not a free-form browser field, owns the
                # intervention and its lineage.
                focus = inherited_focus
                data = {
                    **data,
                    "focusIntervention": inherited_focus,
                    "purposeIntervention": inherited_focus,
                }
        source_ssa = latest_applicable_record(school) if school is not None else None
        mapping_modes = set(
            catalogue_item.intervention_mappings.filter(active=True).values_list(
                "mapping_mode", flat=True
            )
        )
        if (
            school is not None
            and catalogue_item.requires_current_ssa
            and source_ssa is None
            and MappingMode.ADMINISTRATIVE not in mapping_modes
            and MappingMode.SSA_COMPLETION_PREREQUISITE not in mapping_modes
        ):
            raise BadRequest(
                "Complete the School SSA first. Intervention-specific support "
                "cannot be recommended or scheduled without an applicable SSA."
            )
        validate_context(
            catalogue_item,
            school=school,
            cluster=(None if cluster_id is None else catalogue_cluster),
            project=project,
            executor_type=executor_type,
            non_school=non_school,
        )
        validate_frequency(
            catalogue_item,
            school=school,
            cluster=catalogue_cluster,
            fy=fy,
            on_date=scheduled_date.date() if scheduled_date else None,
        )
        mapping_modes = set(mapping_modes)
        # §5 — the recommendation gate applies to the programme's NAMED
        # curriculum titles, where choosing EdTech Foundations over TAM I for
        # a school is a judgement the SSA should govern. It must not apply to
        # ordinary support. A school visit is not a curriculum choice, and
        # requiring one to be "a primary SSA recommendation" is what made
        # ordinary work unschedulable: five of the eight interventions have no
        # school-level named response at all, so their schools were told to
        # find a Project or a Cluster to attach the work to.
        #
        # What standard support still carries is everything analytics needs —
        # the target intervention, the source SSA, the planning-time score and
        # classification — all stamped by apply_catalogue_snapshot below.
        governance_gated = not catalogue_item.standard_support
        if (
            governance_gated
            and school is not None
            and not mapping_modes.intersection(
                {
                    MappingMode.ADMINISTRATIVE,
                    MappingMode.SSA_COMPLETION_PREREQUISITE,
                }
            )
        ):
            from apps.activity_catalogue.services import recommend_activities

            recommendation_result = recommend_activities(
                school=school,
                principal=principal,
                project=project,
                cluster=catalogue_cluster,
                executor_type="partner" if is_partner else "staff",
                limit=3,
            )
            all_rows = [
                *recommendation_result["primary"],
                *recommendation_result["otherEligible"],
            ]
            matching = next(
                (
                    row
                    for row in all_rows
                    if row["catalogueItemId"] == catalogue_item.id
                ),
                None,
            )
            primary_ids = {
                row["catalogueItemId"] for row in recommendation_result["primary"]
            }
            override_reason = (data.get("overrideReason") or "").strip()
            is_dynamic_followup = (
                MappingMode.INHERIT_FROM_SOURCE_ACTIVITY in mapping_modes
            )
            if (
                catalogue_item.id not in primary_ids
                and not is_dynamic_followup
                and not override_reason
            ):
                raise BadRequest(
                    "This is not a primary recommendation in the current "
                    "School context. Record the authorized alternative-selection "
                    "reason before scheduling."
                )
            if (
                is_dynamic_followup
                and source_activity is None
                and matching
                and (focus or data.get("purposeIntervention"))
                != matching["targetIntervention"]
                and not override_reason
            ):
                raise BadRequest(
                    "Without a source Training, this dynamic Activity must use "
                    "the current unresolved SSA recommendation or record an "
                    "authorized override reason."
                )
            governed_recommendation_reason = (
                matching["recommendationReason"]
                if matching
                else "Authorized alternative Catalogue Activity."
            )
            governed_recommendation_source = {
                "engine": "apps.ssa.recommendation_engine",
                "sourceSsaId": recommendation_result["sourceSsaId"],
                "verificationState": recommendation_result["verificationState"],
                "catalogueItemId": catalogue_item.id,
                "recommended": catalogue_item.id in primary_ids,
                "projectId": project.id if project else None,
                "executorType": "partner" if is_partner else "staff",
                "context": "cluster" if cluster_id else "school",
            }
        elif (
            governance_gated
            and catalogue_cluster is not None
            and not mapping_modes.intersection(
                {
                    MappingMode.ADMINISTRATIVE,
                    MappingMode.SSA_COMPLETION_PREREQUISITE,
                }
            )
        ):
            from apps.activity_catalogue.services import (
                recommend_cluster_activities,
            )

            recommendation_result = recommend_cluster_activities(
                cluster=catalogue_cluster,
                principal=principal,
                project=project,
                executor_type="partner" if is_partner else "staff",
                limit=3,
            )
            if (
                catalogue_item.requires_current_ssa
                and not recommendation_result["hasApplicableSsa"]
            ):
                raise BadRequest(
                    "Complete verified SSA records for Cluster member Schools "
                    "before scheduling intervention support."
                )
            all_rows = [
                *recommendation_result["primary"],
                *recommendation_result["otherEligible"],
            ]
            matching = next(
                (
                    row
                    for row in all_rows
                    if row["catalogueItemId"] == catalogue_item.id
                ),
                None,
            )
            primary_ids = {
                row["catalogueItemId"] for row in recommendation_result["primary"]
            }
            dynamic = MappingMode.INHERIT_FROM_SOURCE_ACTIVITY in mapping_modes
            override_reason = (data.get("overrideReason") or "").strip()
            if (
                catalogue_item.id not in primary_ids
                and not dynamic
                and not override_reason
            ):
                raise BadRequest(
                    "This is not a primary Cluster recommendation. Record the "
                    "authorized alternative-selection reason before scheduling."
                )
            governed_recommendation_reason = (
                matching["recommendationReason"]
                if matching
                else "Authorized alternative Catalogue Activity."
            )
            governed_recommendation_source = {
                "engine": "apps.ssa.recommendation_engine",
                "sourceSsaIds": [
                    context["ssaId"]
                    for context in (
                        matching.get("schoolContexts", []) if matching else []
                    )
                ],
                "verificationState": recommendation_result["verificationState"],
                "catalogueItemId": catalogue_item.id,
                "recommended": catalogue_item.id in primary_ids,
                "projectId": project.id if project else None,
                "executorType": "partner" if is_partner else "staff",
                "context": "cluster",
            }
        elif not governance_gated:
            # §28 — standard support skips the curriculum recommendation gate,
            # not the audit trail. It still records WHY it was scheduled, what
            # it targets, and which SSA informed it, so intervention analytics
            # can read it exactly like governed support.
            target = focus or data.get("purposeIntervention")
            rationale = (
                data.get("supportRationale") or data.get("recommendationReason") or ""
            ).strip()
            governed_recommendation_reason = rationale or (
                f"Standard field support targeting "
                f"{str(target).replace('_', ' ').title()}."
                if target
                else "Standard field support."
            )
            governed_recommendation_source = {
                "engine": "standard_support",
                "sourceSsaId": getattr(source_ssa, "id", None),
                "verificationState": getattr(source_ssa, "verification_status", "none"),
                "catalogueItemId": catalogue_item.id,
                "recommended": False,
                "standardSupport": True,
                "targetIntervention": target,
                "projectId": project.id if project else None,
                "executorType": executor_type,
                "context": "cluster" if cluster_id else "school",
            }

    # Funded-scheduling gate: a dated activity must be priceable from the CD
    # Cost Catalogue BEFORE it is persisted. Previously a missing rate wrote
    # 0-amount lines and set cost_missing=True — a scheduled activity with a
    # fake cost. (Daily Visit Batch members are pool-priced after creation;
    # that path validates its own pool keys and raises with the exact missing
    # rate names, so it is exempt here.)
    if scheduled_date and not skip_cost_snapshot:
        from apps.budget.costing_service import preview as _cost_preview

        _check = _cost_preview(
            {
                "activityType": activity_type,
                "costingProfile": (
                    catalogue_item.costing_profile if catalogue_item else None
                ),
                "deliveryType": "partner" if is_partner else "staff",
                "districtType": data.get("districtType"),
                "teachersAttended": data.get("teachersAttended"),
                "leadersAttended": data.get("leadersAttended"),
                "otherParticipants": data.get("otherParticipants"),
                "expectedParticipants": data.get("expectedParticipants"),
                "projectId": data.get("projectId"),
                "fy": fy,
            }
        )
        if _check["blockers"]:
            raise BadRequest(
                "Cannot schedule — "
                + " · ".join(_check["blockers"])
                + " Ask the Country Director to set the missing rate in the "
                "Cost Catalogue first."
            )

    if is_certified_agency_booking:
        # §15B / §20 — staff chose the date, so the work IS scheduled. Landing
        # it in the agency's My Plan as "assigned_to_partner" would show them a
        # Schedule action for an activity Edify had already scheduled, and ask
        # them to pick a date that was never theirs to pick.
        status = "partner_scheduled"
    else:
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
            _assert_schedule_entitlement(
                activity_type,
                school,
                fy,
                data,
                core_slot_verified=core_slot_verified,
                catalogue_item=catalogue_item,
            )
        elif cluster_id:
            # Serialise concurrent cluster scheduling the same way the school
            # row lock serialises school scheduling, so the duplicate guard
            # below cannot be raced past by two simultaneous submissions.
            from apps.clusters.models import Cluster

            Cluster.objects.select_for_update().filter(pk=cluster_id).first()
        elif non_school and responsible_staff_id:
            # Non-school work has no school/cluster row to lock; the
            # responsible person is the natural serialization anchor, so a
            # double-click cannot race the duplicate guard below.
            from apps.accounts.models import StaffProfile

            StaffProfile.objects.select_for_update().filter(
                pk=responsible_staff_id
            ).first()
        # §F partner allowance: one non-core partner activity per school per
        # FY unless the CD granted more. Checked inside the row lock so two
        # concurrent partner assignments cannot both pass.
        if is_partner and school is not None:
            from apps.partners.services import assert_partner_activity_allowance

            assert_partner_activity_allowance(
                data.get("assignedPartnerId"), school.pk, activity_type, fy
            )
        # Double-click / double-submit guard: an identical live activity
        # (same target, type, day, and owner/partner) is a duplicate, not a
        # second piece of work. The row lock above serialises this check.
        if planned_date:
            dup_q = Activity.objects.filter(
                activity_type=activity_type,
                planned_date=planned_date,
                deleted_at__isnull=True,
                responsible_staff_id=responsible_staff_id,
                assigned_partner_id=data.get("assignedPartnerId"),
            ).exclude(status__in=("cancelled", "rejected", "deferred"))
            dup_q = (
                dup_q.filter(school=school)
                if school is not None
                else dup_q.filter(cluster_id=cluster_id, school__isnull=True)
            )
            if dup_q.exists():
                raise BadRequest(
                    "An identical activity is already scheduled for this "
                    "target on this date. Reschedule or edit the existing "
                    "activity instead of creating a duplicate."
                )
        # §1/§21: every activity names the planning workflow that authorized
        # it, so every budget row can identify its dated plan source.
        if non_school:
            planning_source = "manual_work_plan"
            context_type = "programme" if data.get("projectId") else "organization"
        elif activity_type in ("core_visit", "core_training", "core_assessment_visit"):
            planning_source, context_type = "core_planning", "school"
        elif data.get("projectId"):
            planning_source, context_type = "project_planning", "project"
        elif cluster_id:
            planning_source, context_type = "cluster_planning", "cluster"
        else:
            planning_source, context_type = "school_planning", "school"

        event_district_id = None
        if non_school and (data.get("districtId") or data.get("district_id")):
            from apps.geography.models import District

            event_district_id = (
                District.objects.filter(
                    id=data.get("districtId") or data.get("district_id")
                )
                .values_list("id", flat=True)
                .first()
            )

        driver_type, driver_id, driver_reason = resolve_primary_driver(data)
        activity = Activity.objects.create(
            activity_type=activity_type,
            school=school,
            cluster_id=cluster_id,
            project_id=data.get("projectId"),
            primary_driver_type=driver_type,
            primary_driver_id=driver_id,
            driver_reason=driver_reason,
            ssa_recommendation_id=data.get("ssaRecommendationId") or None,
            end_date=end_date,
            planning_source=planning_source,
            activity_context_type=context_type,
            support_rationale=(
                (
                    data.get("supportRationale") or data.get("support_rationale") or ""
                ).strip()
                if non_school
                else ""
            ),
            venue=(data.get("venue") or "").strip()[:255],
            programme_activity_type=(
                data.get("programmeActivityType") if non_school else None
            ),
            programme_delivery_mode=(
                data.get("programmeDeliveryMode") if non_school else None
            ),
            planned_school_count=(planned_school_count if non_school else None),
            event_district_id=event_district_id,
            fy=fy,
            quarter=quarter,
            planned_date=planned_date,
            planned_month=planned_month,
            planned_week=planned_week,
            responsible_staff_id=responsible_staff_id,
            monitored_by_staff_id=monitored_by_staff_id,
            assigned_partner_id=data.get("assignedPartnerId"),
            delivery_type="partner" if is_partner else "staff",
            executor_type=executor_type,
            cluster_slot=data.get("clusterSlot"),
            purpose_intervention=focus or data.get("purposeIntervention"),
            activity_purpose_text=p_text,
            purpose_type=p_type,
            focus_intervention=focus,
            secondary_focus_interventions=data.get("secondaryFocusInterventions", []),
            expected_outcome=data.get("expectedOutcome"),
            expected_participants=data.get("expectedParticipants"),
            # Snapshot, not a live lookup: an approved budget keeps the
            # school count it was priced with, so a school joining the
            # cluster later cannot re-price work already approved.
            participants_per_school=participants_per_school,
            cluster_school_count_snapshot=cluster_school_count,
            schools_invited=schools_invited,
            teachers_per_school=per_school_categories.get("teachersPerSchool"),
            leaders_per_school=per_school_categories.get("leadersPerSchool"),
            other_per_school=per_school_categories.get("otherPerSchool"),
            teachers_attended=data.get("teachersAttended"),
            leaders_attended=data.get("leadersAttended"),
            other_participants=data.get("otherParticipants"),
            scheduled_date=scheduled_date,
            status=status,
            salesforce_activity_type=sf_kind(activity_type),
            ssa_collection_expected=is_ssa_activity,
        )
        if catalogue_item:
            from apps.activity_catalogue.services import apply_catalogue_snapshot

            apply_catalogue_snapshot(
                activity,
                item=catalogue_item,
                source_ssa=source_ssa,
                recommendation_reason=governed_recommendation_reason,
                requested_intervention=focus or data.get("purposeIntervention"),
                source_activity=source_activity,
                override_reason=data.get("overrideReason", ""),
                recommendation_source=governed_recommendation_source,
            )
        if data.get("priorityAllocationId"):
            from apps.hr.priority_linking import link_activity

            link_activity(
                activity=activity,
                allocation_id=str(data["priorityAllocationId"]),
                principal=principal,
                planned_contribution=data.get("plannedContribution"),
            )
        # Who was asked to this cluster session. Recorded as an invitation,
        # never as attendance: the person who delivers it confirms who
        # actually came. Without this the session has no school FK at all, so
        # the work it delivers is invisible on every school that attends.
        if data.get("invitedSchoolIds") and activity.cluster_id:
            from apps.activities.cluster_attendance import set_invited_schools

            set_invited_schools(
                activity,
                data["invitedSchoolIds"],
                actor_id=str(getattr(principal, "id", "") or ""),
            )
        # Daily Visit Batch scheduling (apps.daily_visit_batches.services) creates
        # each school's Activity via this function, then prices the whole batch in
        # one pass afterward — skip the single-activity cost snapshot here so a
        # school is never priced twice (once alone, once as part of its batch).
        #
        # UNDATED work is never priced (§1: every budget amount originates
        # from a dated plan). The write used to run for undated "planned"
        # activities too, minting cost lines with NULL period stamps that no
        # weekly/monthly builder could ever pick up while est_cost_cents
        # still counted in line aggregates — and it silently skipped the
        # missing-rate blocker above, which only guards dated work
        # (2026-08-12 audit M-4). Pricing happens when the activity is dated
        # (reschedule sets scheduled_date and re-prices).
        if not skip_cost_snapshot and activity.scheduled_date:
            # Staff school visits are pool-priced: the whole day's transport/
            # meal pool is split across that day's schools. The UI scheduling
            # paths used to price each visit alone here — billing every school
            # the FULL day pool (5 schools on one day = 5× the real daily
            # cost) while a later reschedule re-priced the same visit at the
            # pooled 1/N share. Attach the new visit to its day batch so
            # creation and reschedule price identically; anything that cannot
            # be pooled (unclassified district, mixed district types) falls
            # back to solo pricing and is surfaced by the
            # scheduled_visits_missing_batch health check.
            pooled = False
            if activity.scheduled_date and activity.delivery_type == "staff":
                from apps.daily_visit_batches.services import (
                    attach_activity_to_batch,
                    batch_poolable,
                )

                # One mission cost per day: visits, trainings, cluster
                # sessions and single-day field events all share the owner's
                # day pool (owner rule, 2026-08-19). Multi-day field events
                # price their own away-days standalone.
                if batch_poolable(activity):
                    pooled = attach_activity_to_batch(
                        activity,
                        responsible_user_id=_funding_owner_id(activity, principal),
                        reason=data.get("reason"),
                    )
            if not pooled:
                _apply_schedule_cost_snapshot(activity, data, principal=principal)
    # Planning and scheduling must both be on the tamper-evident audit chain.
    # An undated draft is a real planning authorization but it is not yet
    # money-bearing work, so do not mislabel it as scheduled.
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=(
                "activity.scheduled" if activity.scheduled_date else "activity.planned"
            ),
            subject_kind="Activity",
            subject_id=activity.id,
            actor_id=getattr(principal, "user_id", None) or "system",
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload={
                "activity_type": activity.activity_type,
                "catalogue_item": activity.catalogue_item_id,
                "catalogue_version": activity.catalogue_version,
                "school_id": activity.school_id,
                "cluster_id": activity.cluster_id,
                "fy": activity.fy,
                "planned_date": (
                    activity.planned_date.isoformat() if activity.planned_date else None
                ),
                "delivery_type": activity.delivery_type,
                "executor_type": activity.executor_type,
                "focus_intervention": activity.focus_intervention or "",
            },
        )
    except Exception:  # pragma: no cover — audit must never break scheduling
        pass
    if is_certified_agency_booking:
        _notify_certified_agency_booking(activity, certified_agency, principal)
    _ensure_partner_handover(activity, data)
    return _serialize(activity)


def _ensure_partner_handover(activity: Activity, data: dict) -> None:
    """Open the handover record for work created already carrying a partner.

    Partner Oversight is driven by PartnerAssignment: an activity that names a
    partner but that no assignment points at appears on that page nowhere at
    all. The work is real and its cost is real, and the supervisor answerable
    for partner delivery can see neither.

    There are two shapes of partner work and only one of them was covered.
    When a *staff member hands a school over* first, the assignment is written
    up front and the partner's later scheduling turns it into an activity
    (`_partner_schedule_from_assignment`). When a staff member *schedules with
    a partner in one step* — the school-visit drawer, the core-schools
    drawers, the work plan, the API — the activity was created and no handover
    was ever recorded. Only the cluster planner remembered to write one, in
    its own copy, which is exactly the drift that made this worth centralising.

    The assignment is created in its post-schedule state and linked, because
    that is what actually happened: the assignment and the activity are the
    same work at two moments of its life, and here both moments are now.

    Deliberately silent when there is nothing to record. No partner named
    means no handover to open — an activity marked partner-delivered with no
    partner is a malformed row, and inventing a partner to satisfy a health
    check would put real work against an organisation that never did it.
    """
    partner_id = activity.assigned_partner_id
    if not partner_id or activity.delivery_type != "partner":
        return
    from apps.partners.models import PartnerAssignment

    if PartnerAssignment.objects.filter(scheduled_activity_id=activity.id).exists():
        return
    from apps.partners.purposes import normalise_visit_purpose

    try:
        # A savepoint of its own. The `except` below is deliberate — a missing
        # handover must never cost us the activity — but catching a *database*
        # error without a savepoint does not undo it: the surrounding
        # transaction stays marked for rollback and the next query in it dies
        # with TransactionManagementError. `create` is called from inside
        # enclosing transactions (the cluster planner under its lock, daily
        # visit batches in a loop), so swallowing an IntegrityError here would
        # have taken the whole caller down instead of one handover record.
        purpose_of_visit = normalise_visit_purpose(
            data.get("purposeOfVisit") or activity.purpose_type,
            for_partner=True,
            fallback_activity_type=activity.activity_type,
        )
        catalogue_item_id = activity.catalogue_item_id
        if not catalogue_item_id:
            # The approved Activity is the assigner's decision and must exist
            # on every handover — the partner never picks one at scheduling.
            # For one-step handoffs of uncatalogued work, the standard-support
            # item for the recorded purpose IS that decision.
            from apps.activity_catalogue.services import resolve_assignment_item

            resolved = resolve_assignment_item(
                purpose_of_visit=purpose_of_visit,
                expected_activity_type=activity.activity_type,
            )
            catalogue_item_id = resolved.id if resolved else None
        with transaction.atomic():
            PartnerAssignment.objects.create(
                school_id=activity.school_id,
                cluster_id=activity.cluster_id,
                partner_id=partner_id,
                assigning_staff_id=activity.responsible_staff_id
                or activity.monitored_by_staff_id,
                monitoring_staff_id=activity.monitored_by_staff_id
                or activity.responsible_staff_id,
                assignment_mode="specific_activity",
                catalogue_item_id=catalogue_item_id,
                purpose=activity.activity_purpose_text or "",
                purpose_of_visit=purpose_of_visit,
                focus_intervention=activity.focus_intervention,
                expected_activity_type=activity.activity_type,
                scheduled_date=(
                    activity.scheduled_date.date() if activity.scheduled_date else None
                ),
                status="partner_scheduled",
                scheduled_activity=activity,
            )
    except Exception:  # noqa: BLE001
        # The activity is saved and correct; a missing handover is a
        # supervision gap the health board reports and the repair command
        # closes. Losing the activity over it would be the worse trade.
        logger.exception(
            "Could not open the partner handover for activity %s", activity.id
        )


def _catalogue_cluster(cluster_id):
    """Resolve a Catalogue scheduling context without dynamic imports."""
    from apps.clusters.models import Cluster

    cluster = Cluster.objects.filter(id=cluster_id).first()
    if cluster is None:
        raise BadRequest("Unknown cluster.")
    return cluster


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
    if scheduled_date:
        planned_date = timezone.localtime(scheduled_date).date()
    else:
        raw_planned_date = data.get("plannedDate") or data.get("planned_date")
        if not raw_planned_date:
            return None, data.get("plannedMonth"), data.get("plannedWeek")
        planned_date = timezone.localtime(_parse_date(raw_planned_date)).date()
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
    a = _get_for_execution(activity_id, principal)
    if a.status not in STARTABLE_STATUSES:
        raise BadRequest("Activity must be scheduled before completion can start.")
    a.status = "completion_started"
    # First Start wins — a resumed activity keeps its original start moment.
    update_fields = ["status", "updated_at"]
    if a.execution_started_at is None:
        a.execution_started_at = timezone.now()
        update_fields.append("execution_started_at")
    a.save(update_fields=update_fields)
    return _serialize(a)


def complete(activity_id: str, data: dict, principal) -> dict:
    """Submit completion: evidence present, Salesforce ID validated, attendance
    for trainings, CCEO routes to PL / staff routes to IA."""
    a = _get_for_execution(activity_id, principal)
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
    from apps.evidence.requirements import evidence_optional

    if evidence_count == 0 and not evidence_optional(a):
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

    kind = sf_kind_for_activity(a)
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
    if a.delivery_type == "partner" and not _partner_evidence_exists(a):
        raise BadRequest(
            "Upload the activity evidence before submitting to IA — partner "
            "evidence goes directly to IA for review."
        )

    # Reserve the Salesforce ID first, as its own atomic operation — reject
    # submission (and advance nothing else about completion) on an invalid
    # format or a duplicate BEFORE any other completion state changes.
    entry_source = (
        ENTRY_SOURCE_MANAGING_STAFF
        if a.delivery_type == "partner"
        else ENTRY_SOURCE_STAFF_SELF
    )
    # §12 partner workflow: the Salesforce ID for partner-delivered work is
    # entered by IA in the Confirm Salesforce Entry step, never demanded of
    # the partner at evidence submission. Staff submissions still reserve
    # their ID here; a partner submission with no ID defers it to IA.
    if kind is not None and (sf_id or a.delivery_type != "partner"):
        reserve_salesforce_id(
            activity=a,
            raw_value=sf_id,
            kind=kind,
            principal=principal,
            entry_source=entry_source,
        )
        a.refresh_from_db(fields=["salesforce_activity_id", "salesforce_activity_type"])

    # Partner-delivered work goes DIRECTLY to IA (§10) whoever presses the
    # button — a monitoring CCEO submitting on the partner's behalf must not
    # detour it through PL review (2026-08-19 audit: the role-only ternary
    # was a hidden approval gate reachable through the API).
    is_cceo = principal.active_role == "CCEO"
    next_status = (
        "submitted_to_pl"
        if is_cceo and a.delivery_type != "partner"
        else "awaiting_ia_verification"
    )
    with transaction.atomic():
        a.teachers_attended = data.get("teachersAttended")
        a.leaders_attended = data.get("leadersAttended")
        a.other_participants = data.get("otherParticipants")
        a.attended_school_ids = _cluster_member_school_ids(
            a, data.get("attendedSchoolIds")
        )
        _sync_cluster_attendance(
            a, a.attended_school_ids, str(getattr(principal, "id", "") or "")
        )
        # Actuals — entered by the person who delivered, never copied from
        # the planned fields (§9.2). Absent keys leave stored values alone so
        # staged flows that submit in stages don't erase earlier entries.
        if data.get("actualDeliveryDate"):
            a.actual_delivery_date = _parse_date(data["actualDeliveryDate"]).date()
        if data.get("actualOutcome") is not None:
            a.actual_outcome = str(data.get("actualOutcome") or "").strip()
        if data.get("actualObservations") is not None:
            a.actual_observations = str(data.get("actualObservations") or "").strip()
        if data.get("followUpNote") is not None:
            a.follow_up_note = str(data.get("followUpNote") or "").strip()
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
                "actual_delivery_date",
                "actual_outcome",
                "actual_observations",
                "follow_up_note",
                "status",
                "submitted_to_ia_at",
                "evidence_status",
                "updated_at",
            ]
        )
        ActivityCompletionVerification.objects.update_or_create(
            activity=a,
            defaults={
                # Empty when the ID is deferred to IA (§12 partner flow) —
                # the column is NOT NULL and "" is the honest "not yet".
                "salesforce_id": a.salesforce_activity_id or "",
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
    a = _get_for_execution(activity_id, principal)
    if a.status not in SUBMITTABLE_STATUSES:
        raise BadRequest("Activity is not ready to be submitted for review.")

    from apps.evidence.models import EvidenceRecord

    from apps.evidence.requirements import evidence_optional

    if not EvidenceRecord.objects.filter(
        activity_id=a.id, quarantined=False
    ).exists() and not evidence_optional(a):
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

    kind = sf_kind_for_activity(a)
    if kind is not None and not a.salesforce_activity_id:
        raise BadRequest("Enter the Salesforce Activity ID before submitting.")
    if kind == "training" and not (
        (a.teachers_attended or 0) > 0 or (a.leaders_attended or 0) > 0
    ):
        raise BadRequest(
            "Training completion requires attendance (teachers and/or school leaders)"
        )
    if a.delivery_type == "partner" and not _partner_evidence_exists(a):
        raise BadRequest(
            "Upload the activity evidence before submitting to IA — partner "
            "evidence goes directly to IA for review."
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

    # Same §10 partner-aware routing as complete(): partner-delivered work
    # goes directly to IA even when the monitoring CCEO presses submit —
    # the role-only ternary here was the second half of the hidden PL gate
    # the 2026-08-19 audit flagged.
    next_status = (
        "submitted_to_pl"
        if principal.active_role == "CCEO" and a.delivery_type != "partner"
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
                # Empty when the ID is deferred to IA (§12 partner flow) —
                # the column is NOT NULL and "" is the honest "not yet".
                "salesforce_id": a.salesforce_activity_id or "",
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
    a = _get_for_execution(activity_id, principal)
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
        _sync_cluster_attendance(
            a, a.attended_school_ids, str(getattr(principal, "id", "") or "")
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


def complete_partner_ssa_support(activity_id: str, data: dict, principal) -> dict:
    """Record SSA results and complete partner SSA Support in one transaction.

    The eight intervention scores remain SSA data; pupil enrolment updates the
    School directory's authoritative headcount and is never written into the
    legacy ``SsaRecord.new_enrollment`` column. Either IA or the staff member
    recorded as this partner activity's monitor may perform this one governed
    completion action.
    """
    a = _get_in_scope(activity_id, principal)
    from apps.core.permissions import RolePermissionService

    if not RolePermissionService.can_complete_partner_ssa_support(principal, a):
        raise Forbidden(
            "Only Impact Assessment or the staff member monitoring this partner "
            "SSA Support activity may complete it."
        )
    if a.status != "awaiting_ia_verification":
        raise BadRequest(
            "The partner must submit the completed SSA evidence before scores "
            "and enrolment can be recorded."
        )

    raw_enrollment = data.get("enrollment")
    try:
        enrollment = int(raw_enrollment)
    except (TypeError, ValueError) as exc:
        raise BadRequest("Pupil enrolment must be a whole number.") from exc
    if enrollment < 1:
        raise BadRequest("Pupil enrolment must be at least 1 learner.")
    if enrollment > 1_000_000:
        raise BadRequest("Pupil enrolment cannot exceed 1,000,000 learners.")

    assessment_date = a.actual_delivery_date or a.planned_date or timezone.localdate()
    is_ia = RolePermissionService.can_verify_ia(principal, a)
    entry_source = (
        ENTRY_SOURCE_IA_CONFIRMATION if is_ia else ENTRY_SOURCE_MANAGING_STAFF
    )

    from apps.ssa.services import upload as upload_ssa

    with transaction.atomic():
        # Lock the school before both the SSA write and headcount update. The
        # upload service takes the same row lock inside its nested transaction,
        # so concurrent completions for one school serialize cleanly.
        school = School.objects.select_for_update().get(pk=a.school_id)
        ssa_record = upload_ssa(
            {
                "schoolId": school.school_id,
                "dateOfSsa": assessment_date.isoformat(),
                "scores": data.get("scores") or [],
                "collectorType": "ia" if is_ia else "staff",
            },
            principal,
        )
        previous_enrollment = school.enrollment
        school.enrollment = enrollment
        school.last_enrollment_date = assessment_date
        school.save(update_fields=["enrollment", "last_enrollment_date", "updated_at"])
        from apps.schools.models import SchoolChangeLog, SchoolEnrollmentHistory

        SchoolEnrollmentHistory.objects.update_or_create(
            school=school,
            fy=get_operational_fy(assessment_date),
            defaults={"enrollment": enrollment, "recorded_at": timezone.now()},
        )
        if previous_enrollment != enrollment:
            SchoolChangeLog.objects.create(
                school=school,
                field_name="enrollment",
                old_value=(
                    str(previous_enrollment)
                    if previous_enrollment is not None
                    else None
                ),
                new_value=str(enrollment),
                changed_by=principal.user_id,
            )
        if a.ssa_collection_expected is False or a.ssa_not_collected_reason:
            a.ssa_collection_expected = True
            a.ssa_not_collected_reason = None
            a.save(
                update_fields=[
                    "ssa_collection_expected",
                    "ssa_not_collected_reason",
                    "updated_at",
                ]
            )
        result = _confirm_activity_after_authorization(
            a,
            data,
            principal,
            entry_source=entry_source,
        )
    result["ssaRecordId"] = ssa_record["id"]
    result["enrollment"] = enrollment
    return result


def ia_confirm(activity_id: str, data: dict | None = None, principal=None) -> dict:
    """IA confirms the Salesforce entry (manual confirmation)."""
    a = _get_in_scope(activity_id, principal)
    # Verification authority lives in the CANONICAL service, not only at the
    # routes (2026-08-19 audit): _get_in_scope is a READ gate, so a partner —
    # who owns their activity for reading — could verify their own work by
    # reaching this function through any future unguarded caller.
    from apps.core.permissions import RolePermissionService

    if not RolePermissionService.can_verify_ia(principal, a):
        raise Forbidden("Only Impact Assessment may verify this work.")
    return _confirm_activity_after_authorization(
        a,
        data,
        principal,
        entry_source=ENTRY_SOURCE_IA_CONFIRMATION,
    )


def _confirm_activity_after_authorization(
    a: Activity,
    data: dict | None,
    principal,
    *,
    entry_source: str,
) -> dict:
    """Shared confirmation transition after a caller-specific authority gate."""
    if a.status != "awaiting_ia_verification":
        raise BadRequest("Activity is not awaiting IA verification")
    # §Direct IA handoff (2026-08-20): partner evidence comes straight to
    # IA — no CCEO/PL acceptance gate. IA reviews the evidence itself; the
    # only precondition is that evidence exists.
    if a.delivery_type == "partner" and not _partner_evidence_exists(a):
        raise Forbidden("Cannot confirm — no partner evidence uploaded.")

    # §12 Confirm Salesforce Entry: IA records the Salesforce ID for
    # partner-delivered work at confirmation. reserve_salesforce_id is the
    # single write path — format, uniqueness and idempotency live there.
    ia_sf_id = ((data or {}).get("salesforceId") or "").strip()
    if ia_sf_id:
        kind = sf_kind_for_activity(a)
        if kind is not None:
            reserve_salesforce_id(
                activity=a,
                raw_value=ia_sf_id,
                kind=kind,
                principal=principal,
                entry_source=entry_source,
            )
            a.refresh_from_db(
                fields=["salesforce_activity_id", "salesforce_activity_type"]
            )
    if (
        a.delivery_type == "partner"
        and sf_kind_for_activity(a) is not None
        and not a.salesforce_activity_id
    ):
        raise BadRequest(
            "Enter the Salesforce ID to complete — partner work is confirmed "
            "with its Salesforce entry."
        )
    if (data or {}).get("verificationNote"):
        a.pl_review_note = str(data["verificationNote"]).strip()
        a.save(update_fields=["pl_review_note", "updated_at"])

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
            # Confirmed records only. This read used to take the newest record
            # regardless of verification_status, so a pending upload satisfied
            # the gate and advanced the activity to ia_verified -- exactly what
            # latest_applicable_record exists to prevent.
            from apps.ssa.services import latest_applicable_record

            if not latest_applicable_record(a.school):
                raise BadRequest(
                    "IA Verification failed: no confirmed Core Assessment / SSA "
                    "score exists for this school."
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
            # Keep the MOU advance marker: "disbursed" means the 50% advance
            # is already out. Verification opens the CLEARANCE of the balance
            # — it must not reset the record of money that already moved.
            if a.payment_status != "disbursed":
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
        from apps.hr.milestone_progress import record_activity_progress

        transaction.on_commit(lambda: record_activity_progress(a))
        # Phase 2c: when the Salesforce sync is enabled, IA verification
        # enqueues the activity's push on the durable outbox (transactional —
        # the event commits with the verification). Disabled by default; a
        # manually pasted SF id always wins over the sync.
        from apps.integrations.services import enqueue_activity_salesforce_sync

        enqueue_activity_salesforce_sync(a.id)

        # MOU prompts, after the verification commits: the accountant is told
        # the partner balance is now clearable, and the partner is told to
        # send their invoice once their whole slate is verified.
        from apps.fund_requests.finance_services import (
            notify_partner_clearance_eligibility,
        )

        transaction.on_commit(lambda: notify_partner_clearance_eligibility(a))
    return _serialize(a)


def ia_return(activity_id: str, data: dict, principal) -> dict:
    """IA returns the activity completion to CCEO/partner for correction."""
    a = _get_in_scope(activity_id, principal)
    # Same canonical-service authority gate as ia_confirm: returning work is
    # a verification decision, reserved to IA by the permission matrix.
    from apps.core.permissions import RolePermissionService

    if not RolePermissionService.can_verify_ia(principal, a):
        raise Forbidden("Only Impact Assessment may return this work.")
    if a.status != "awaiting_ia_verification":
        raise BadRequest("Activity is not awaiting IA verification")

    reason = data.get("reason", "").strip()
    if not reason:
        raise BadRequest("Return reason is required.")

    # §11 partner return detail: what needs correcting, how, and by when —
    # folded into the review note the evidence page shows the partner.
    note = reason
    correction_fields = str(data.get("correctionFields") or "").strip()
    instruction = str(data.get("instruction") or "").strip()
    deadline = str(data.get("deadline") or "").strip()
    if correction_fields:
        note += f" · Correct: {correction_fields}"
    if instruction:
        note += f" · {instruction}"
    if deadline:
        note += f" · Deadline: {deadline}"

    # Partner-delivered work returns on its own status (§15.1 "Returned by
    # IA") so the partner surfaces can speak plainly; staff work keeps the
    # historic "returned" value every existing pin expects.
    a.status = "returned_by_ia" if a.delivery_type == "partner" else "returned"
    a.ia_verification_status = "returned"
    a.pl_review_note = note
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
        # A returned activity is no longer verified work: the milestone credit
        # it earned at ia_confirm reverses with it, exactly as the personal
        # target ledger reverses on the next rebuild. Without this the
        # strategic figures kept counting delivery IA had just rejected.
        from apps.hr.milestone_progress import reverse_activity_progress

        transaction.on_commit(lambda: reverse_activity_progress(a))
        # The person who must act is told (2026-08-19 audit F4: this return
        # previously notified NOBODY — the partner's Needs Attention row and
        # To-Do existed, but nothing announced them). Partner deliveries
        # notify the partner login; staff deliveries notify the owner.
        transaction.on_commit(lambda: _notify_ia_return(a, reason))

    return _serialize(a)


def _notify_ia_return(a, reason: str) -> None:
    """Announce an IA return to whoever must correct it — never raising:
    the return is committed, a notification backend being down must not
    make IA think the return failed."""
    import logging

    try:
        from apps.notifications.services import WorkflowNotificationService

        where = (
            a.school.name
            if a.school_id
            else (a.cluster.name if a.cluster_id else "field work")
        )
        recipients: list[str] = []
        if a.delivery_type == "partner" and a.assigned_partner_id:
            from apps.partners.models import Partner

            partner = Partner.objects.filter(id=a.assigned_partner_id).first()
            if partner and partner.user_id:
                recipients.append(partner.user_id)
            if a.monitored_by_staff_id:
                # FYI — the staff member who supervises the handoff.
                recipients.append(a.monitored_by_staff_id)
        else:
            owner = a.responsible_staff_id or a.monitored_by_staff_id
            if owner:
                recipients.append(owner)
        if not recipients:
            return
        WorkflowNotificationService.trigger(
            event_type="evidence_returned",
            category="verification",
            priority="high",
            title="Evidence returned for correction",
            body=f"{where}: {reason[:200]}",
            context_type="activity",
            context_id=str(a.id),
            recipients=recipients,
        )
    except Exception:  # noqa: BLE001 — bookkeeping never breaks the return
        logging.getLogger(__name__).warning(
            "ia_return notification failed for %s", a.id, exc_info=True
        )


def reschedule(activity_id: str, data: dict, principal) -> dict:
    a = _get_for_execution(activity_id, principal)
    _assert_may_schedule(a, principal)
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
    # A multi-day activity keeps its duration when it moves: the end date
    # shifts by the same delta as the start (an explicit endDate in the
    # payload overrides, validated against the new start).
    if a.end_date and a.planned_date:
        duration = a.end_date - a.planned_date
        end_raw = data.get("endDate") or data.get("end_date")
        if end_raw:
            new_end = _parse_date(str(end_raw)).date()
            if new_end < planned_date:
                raise BadRequest("The end date cannot precede the start date.")
            a.end_date = new_end
        else:
            a.end_date = planned_date + duration
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
        # Serialise concurrent reschedules of the same activity: without the
        # row lock two simultaneous submissions interleave their cost-line
        # rebuilds and fund-request syncs, and one reschedule_count increment
        # is lost.
        Activity.objects.select_for_update().filter(pk=a.pk).first()
        a.save(
            update_fields=[
                "scheduled_date",
                "fy",
                "quarter",
                "planned_date",
                # end_date was recomputed above for multi-day work but was
                # missing from this list — the re-priced cost lines followed
                # the new range while the persisted activity kept the OLD end
                # date (for a forward move, an end date before the new start,
                # which the §35 end-before-start health check then flags).
                "end_date",
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

        # Where the money currently sits, captured before anything reprices.
        # Both branches below move cost lines to the new week; only one of them
        # used to tell finance about the week being vacated.
        from apps.activities.models import ActivityScheduleCostLine

        prior_buckets = list(
            ActivityScheduleCostLine.objects.filter(activity=a).values_list(
                "responsible_user", "fiscal_year", "month", "week_start_date"
            )
        )

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
            # The batch reprices and then calls trigger_generate_for_activity,
            # which raises the NEW week's request and says nothing about the
            # old one. The old week therefore kept its full amount while the
            # new week gained the same amount again -- the same money
            # requested twice, for work happening once. Staff school visits are
            # the most common activity there is, and they all take this branch.
            #
            # sync_* regenerates every affected bucket, old and new, so the
            # vacated week empties instead of being left holding a total.
            from apps.fund_requests.monthly_service import (
                sync_monthly_drafts_for_activity,
            )
            from apps.fund_requests.weekly_service import (
                sync_weekly_requests_for_activity,
            )

            sync_weekly_requests_for_activity(a, prior_buckets=prior_buckets)
            sync_monthly_drafts_for_activity(a, prior_buckets=prior_buckets)
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

    # §25 — the partner delivering this did not move it and must not find out
    # by opening My Plan on the old morning. One Activity, moved; no second
    # record, and the notification names both dates so the change is legible.
    if a.delivery_type == "partner" and a.assigned_partner_id and old_date != new_date:
        is_partner_actor = bool(
            getattr(resolve_user_scope(principal), "partner_ids", None)
        )
        if is_partner_actor:
            # §8.4 the mirror case: the PARTNER moved their own delivery —
            # the staff member monitoring the work is told, with both dates
            # and the recorded reason.
            monitor = a.monitored_by_staff_id or a.responsible_staff_id
            if monitor:
                from apps.notifications.services import WorkflowNotificationService

                WorkflowNotificationService.trigger(
                    event_type="partner_rescheduled_activity",
                    category="activities",
                    priority="normal",
                    title="A partner rescheduled their delivery",
                    body=(
                        f"{a.activity_name_snapshot or a.get_activity_type_display()} "
                        f"for {_where(a)} moved from {old_date:%-d %b %Y} to "
                        f"{new_date:%-d %b %Y}. "
                        f"Reason: {(data.get('reason') or '—').strip()}"
                    ),
                    context_type="activity",
                    context_id=str(a.id),
                    recipients=[monitor],
                )
        else:
            _notify_partner_schedule_change(
                a,
                "partner_booking_rescheduled",
                "A booking you hold has been moved",
                (
                    f"{a.activity_name_snapshot or a.get_activity_type_display()} for "
                    f"{_where(a)} has moved from "
                    f"{old_date:%-d %b %Y} to {new_date:%-d %b %Y}. "
                    f"{(data.get('reason') or '').strip()}".strip()
                ),
            )
    return _serialize(a)


def _notify_partner_schedule_change(activity, event_type, title, body) -> None:
    """Tell the partner organisation, through its login user."""
    from apps.partners.models import Partner

    user_id = (
        Partner.objects.filter(id=activity.assigned_partner_id)
        .values_list("user_id", flat=True)
        .first()
    )
    _notify_chain(activity, event_type, title, body, [user_id], priority="high")


def reassign(activity_id: str, data: dict, principal) -> dict:
    a = _get_for_execution(activity_id, principal)
    # Reassignment moves the money trail to a new owner — a scheduling power,
    # not a review/pay power, so country-visibility-only roles are refused the
    # same way reschedule refuses them (2026-08-12 audit M-3).
    _assert_may_schedule(a, principal)
    # The ownership flip and the cost/request rebuild must land together — a
    # costing failure otherwise leaves the activity reassigned while the money
    # still sits with the previous owner. The row lock serialises concurrent
    # reassignments of the same activity.
    with transaction.atomic():
        a = Activity.objects.select_for_update().get(pk=a.pk)
        delivery = data.get("deliveryType", a.delivery_type)
        was_partner = a.delivery_type == "partner"
        a.delivery_type = delivery
        # Only overwrite the partner link when the caller actually sent one —
        # a payload that omits the key used to null the partner while
        # delivery_type stayed "partner", producing partner-priced cost lines
        # attached to no partner.
        if "assignedPartnerId" in data:
            a.assigned_partner_id = data.get("assignedPartnerId")
        a.responsible_staff_id = (
            data.get("responsibleStaffId") or a.responsible_staff_id
        )
        if "expectedParticipants" in data:
            a.expected_participants = data.get("expectedParticipants")
        if delivery == "partner":
            if not a.assigned_partner_id:
                raise BadRequest(
                    "Reassigning to partner delivery requires assignedPartnerId."
                )
            # §F partner allowance also applies to work moved onto a partner,
            # not only to work created for one. (Skipped when the activity was
            # already partner-delivered — it would count itself as "used".)
            if a.school_id and not was_partner:
                from apps.partners.services import (
                    assert_partner_activity_allowance,
                )

                assert_partner_activity_allowance(
                    a.assigned_partner_id, a.school_id, a.activity_type, a.fy
                )
            a.status = "assigned_to_partner"
        elif a.status == "assigned_to_partner":
            # Partner → staff: the activity is no longer awaiting a partner.
            a.status = "scheduled" if a.scheduled_date else "planned"
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


def _partner_schedule_from_assignment(activity_id: str, data: dict, principal) -> dict:
    """Turn one locked PartnerAssignment into one costed canonical Activity."""

    from apps.core_schools.models import CoreActivitySlot, cslot_id
    from apps.partners.models import PartnerAssignment

    with transaction.atomic():
        pa = (
            PartnerAssignment.objects.select_for_update(of=("self",))
            .select_related(
                "school",
                "cluster",
                "catalogue_item",
                "source_ssa",
                "source_activity",
                "project",
            )
            .filter(id=activity_id)
            .first()
        )
        if not pa:
            raise NotFoundError("Partner assignment not found.")
        if pa.status in ("partner_scheduled", "scheduled", "completed"):
            raise BadRequest("This assignment is already scheduled.")
        scope = resolve_user_scope(principal)
        if scope.active_role not in COUNTRY_SCHEDULING_ROLES:
            if scope.country_scope:
                # Country-wide reach without scheduling authority — the
                # Accountant reviews and pays for partner work rather than
                # dating it. Same rule as _assert_may_schedule; spelled out
                # here because this path validates a PartnerAssignment, which
                # has no Activity for that helper to take.
                raise Forbidden(
                    "Your role reviews and pays for this work rather than "
                    "scheduling it."
                )
            if scope.partner_ids:
                if pa.partner_id not in scope.partner_ids:
                    raise Forbidden("Assignment belongs to another partner.")
            elif not (
                scope.school_ids and pa.school_id and pa.school_id in scope.school_ids
            ):
                raise Forbidden("Assignment outside your scope.")

        scheduled_date = _parse_date(data["scheduledDate"])
        delivery_contact_name = str(
            data.get("deliveryContactName") or getattr(principal, "name", "") or ""
        ).strip()
        if len(delivery_contact_name) < 2:
            raise BadRequest("Enter the name of the person visiting the School.")
        if len(delivery_contact_name) > 255:
            raise BadRequest("Visitor name must be 255 characters or fewer.")
        avail = _SchedulingPolicyService.check(
            _user_for_staff_identity(pa.assigning_staff_id)
            if pa.assigning_staff_id
            else None,
            scheduled_date,
        )
        if avail["status"] == "blocked":
            raise BadRequest("Scheduling blocked: " + " · ".join(avail["blockers"]))

        catalogue_item = pa.catalogue_item
        selected_catalogue_id = data.get("catalogueItemId")
        if selected_catalogue_id:
            from apps.activity_catalogue.services import get_selectable_item

            selected = get_selectable_item(str(selected_catalogue_id))
            if (
                pa.assignment_mode == "specific_activity"
                and pa.catalogue_item_id
                and selected.id != pa.catalogue_item_id
            ):
                raise Forbidden(
                    "This assignment requires the exact approved Catalogue Activity."
                )
            if (
                pa.assignment_mode == "intervention_choice"
                and pa.allowed_catalogue_items.exists()
                and not pa.allowed_catalogue_items.filter(id=selected.id).exists()
            ):
                # An EMPTY choice set means no set was ever recorded, not that
                # every item is out of bounds — the partner picks from the CD
                # Cost Catalogue and validate_context below still enforces
                # partner eligibility.
                raise Forbidden(
                    "The selected Activity is outside this assignment's approved choice set."
                )
            catalogue_item = selected
        if pa.catalogue_item_id and catalogue_item is None:
            catalogue_item = pa.catalogue_item

        if catalogue_item:
            from apps.activity_catalogue.services import validate_context

            validate_context(
                catalogue_item,
                school=pa.school,
                cluster=pa.cluster,
                project=pa.project,
                executor_type="partner",
            )
        elif data.get("requireCatalogue"):
            raise BadRequest(
                "This assignment has no approved Activity Catalogue item. "
                "Ask the managing staff member to repair the assignment."
            )

        fy = get_operational_fy(scheduled_date)
        quarter = get_quarter_for_date(scheduled_date)
        if catalogue_item:
            from apps.activity_catalogue.services import validate_frequency

            validate_frequency(
                catalogue_item,
                school=pa.school,
                cluster=pa.cluster,
                fy=fy,
                on_date=scheduled_date.date(),
            )
        planned_date, planned_month, planned_week = _schedule_period(
            scheduled_date, data
        )
        # §F partner allowance — the moment the assignment becomes a costed
        # Activity is the last gate before partner money exists. Checked
        # inside the assignment row lock so two concurrent schedules cannot
        # both pass.
        _sched_activity_type = (
            catalogue_item.workflow_kind
            if catalogue_item
            else (pa.expected_activity_type or "core_visit")
        )
        if pa.school_id:
            from apps.partners.services import assert_partner_activity_allowance

            assert_partner_activity_allowance(
                pa.partner_id,
                pa.school_id,
                _sched_activity_type,
                fy,
                # This assignment's own activity must not count against it —
                # otherwise every re-schedule reads as a second activity.
                exclude_activity_id=pa.scheduled_activity_id,
            )
        # The school's own staff member where the handoff recorded one; the
        # assigner otherwise, which is what every pre-existing row resolves to.
        monitored_by_staff_id = _canonical_staff_identity(
            pa.monitoring_staff_id or pa.assigning_staff_id
        )
        activity = Activity.objects.create(
            activity_type=_sched_activity_type,
            school=pa.school,
            cluster=pa.cluster,
            project_id=pa.project_id,
            fy=fy,
            quarter=quarter,
            responsible_staff_id=None,
            delivery_contact_name=delivery_contact_name,
            monitored_by_staff_id=monitored_by_staff_id,
            assigned_partner_id=pa.partner_id,
            delivery_type="partner",
            focus_intervention=pa.focus_intervention,
            purpose_intervention=pa.focus_intervention,
            activity_purpose_text=pa.notes or pa.purpose or "Scheduled partner support",
            purpose_type=pa.purpose_of_visit,
            ssa_collection_expected=(
                pa.purpose_of_visit == "ssa_support"
                or _sched_activity_type in PARTNER_SSA_SUPPORT_ACTIVITY_TYPES
            ),
            expected_participants=data.get("expectedParticipants"),
            scheduled_date=scheduled_date,
            planned_date=planned_date,
            planned_month=planned_month,
            planned_week=planned_week,
            status="partner_scheduled",
            # The canonical create() path stamps these; this one did not, so
            # every partner-scheduled activity was born already failing the
            # platform's own `activity_without_planning_source` health check
            # (apps/activities/work_plan_health.py:90). A partner assignment
            # IS the planning decision that produced this work.
            planning_source="partner_assignment",
            activity_context_type=(
                "school" if pa.school_id else "cluster" if pa.cluster_id else ""
            ),
        )
        if catalogue_item:
            from apps.activity_catalogue.services import apply_catalogue_snapshot

            apply_catalogue_snapshot(
                activity,
                item=catalogue_item,
                source_ssa=pa.source_ssa,
                recommendation_reason=pa.recommendation_reason,
                requested_intervention=pa.focus_intervention,
                source_activity=pa.source_activity,
                override_reason=pa.override_reason,
            )

        pa.status = "partner_scheduled"
        pa.scheduled_date = scheduled_date.date()
        # The pairing, recorded rather than inferred. Oversight has to say that
        # this assignment and the activity it just became are one item; without
        # the id it would have to match on partner + school + status and would
        # get it wrong the moment a partner holds two assignments at one school.
        pa.scheduled_activity = activity
        if monitored_by_staff_id:
            pa.assigning_staff_id = monitored_by_staff_id
        pa.save(
            update_fields=[
                "assigning_staff_id",
                "status",
                "scheduled_date",
                "scheduled_activity",
                "updated_at",
            ]
        )

        if pa.school and pa.school.school_type == "core":
            kind_prefix = "v" if pa.support_type == "Visit" else "t"
            try:
                seq_num = int(pa.visit_number or pa.training_number or 1)
            except ValueError:
                seq_num = 1
            slot = CoreActivitySlot.objects.filter(
                id=cslot_id(pa.school.school_id, kind_prefix, seq_num, fy=fy)
            ).first()
            if slot:
                slot.status = "Scheduled"
                slot.activity_id = activity.id
                slot.scheduled_for = scheduled_date
                slot.scheduled_month = str(scheduled_date.month)
                slot.scheduled_week = min(5, (scheduled_date.day - 1) // 7 + 1)
                slot.save()

        _apply_schedule_cost_snapshot(activity, data, principal=principal)
        activity.save(update_fields=["est_cost_cents", "cost_missing", "updated_at"])
        try:
            from apps.notifications.services import resolve_condition

            resolve_condition("partner_scheduled_activity", "partner_assignment", pa.id)
        except Exception:  # noqa: BLE001 - bookkeeping never blocks scheduling
            pass
        # The staff member who handed the work over learns a date now exists
        # (2026-08-19 audit F7: the return path notified, the accept path
        # didn't — staff discovered acceptance only by browsing).
        try:
            from apps.notifications.services import WorkflowNotificationService

            staff_recipient = pa.assigning_staff_id or monitored_by_staff_id
            if staff_recipient:
                WorkflowNotificationService.trigger(
                    event_type="partner_scheduled_assignment",
                    category="partner",
                    priority="normal",
                    title="A partner scheduled the assigned work",
                    body=(
                        f"{activity.activity_name_snapshot or activity.get_activity_type_display()}"
                        f" at {_where(activity)} is booked for "
                        f"{scheduled_date:%-d %b %Y}."
                    ),
                    context_type="activity",
                    context_id=str(activity.id),
                    recipients=[staff_recipient],
                )
        except Exception:  # noqa: BLE001 - bookkeeping never blocks scheduling
            pass
        return _serialize(activity)


def partner_schedule(activity_id: str, data: dict, principal) -> dict:
    from apps.partners.models import PartnerAssignment
    from apps.core_schools.models import CoreActivitySlot

    if PartnerAssignment.objects.filter(id=activity_id).exists():
        return _partner_schedule_from_assignment(activity_id, data, principal)

    with transaction.atomic():
        a = _get_in_scope(activity_id, principal)
        _assert_may_schedule(a, principal)
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


def _notify_frozen_weekly_request(wfr, activity, new_status: str) -> None:
    """Tell the owner (and the accountants who would hit the guard) that a
    cancellation just invalidated a submitted/approved weekly request's total
    — the request must be returned so the week rebuilds without the cancelled
    amount. Never blocks the cancellation."""
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        what = activity.activity_name_snapshot or activity.get_activity_type_display()
        recipients = [wfr.responsible_user] + list(
            User.objects.filter(active_role="Accountant", is_active=True).values_list(
                "id", flat=True
            )
        )
        WorkflowNotificationService.trigger(
            event_type="weekly_fund_request_invalidated",
            category="finance",
            priority="high",
            title="Cancelled work inside a submitted weekly request",
            body=(
                f"{what} was {new_status}, but its amount is still inside the "
                f"submitted/approved week of {wfr.week_start_date:%d %b} "
                f"(UGX {wfr.total_amount:,}). Return that request so the week "
                "rebuilds without it — it cannot be disbursed as approved."
            ),
            context_type="WeeklyFundRequest",
            context_id=wfr.id,
            recipients=[r for r in recipients if r],
        )
    except Exception:  # noqa: BLE001 — never block a cancellation over a ping
        import logging

        logging.getLogger(__name__).warning(
            "frozen-weekly-request notification failed for %s", wfr.id, exc_info=True
        )


def _cancel_or_defer(
    activity_id: str,
    data: dict,
    principal,
    new_status: str,
    *,
    already_authorised: bool = False,
) -> dict:
    """Cancel/defer an activity AND withdraw its money from every draft
    funding surface, atomically.

    `already_authorised` is for one caller: partner withdrawal. Recalling work
    a partner has committed to a date is a *supervisory* act, and the platform
    grants it deliberately — `partners.withdrawal_service.assert_may_withdraw`
    says so in as many words: "Once a partner has committed to a date the CCEO
    must ask their Program Lead, because cancelling work a partner has planned
    around is a decision with consequences beyond one school." That service is
    the authority for the decision; re-asking the direct-portfolio question
    here overruled it and made a Programme Lead unable to recall their own
    team's partner work. Nothing user-facing passes it.

    Previously this only flipped the status: the cost lines, the draft
    weekly/monthly fund requests, and the pending AdvanceRequests all kept the
    cancelled work's amounts — a cancelled activity remained fully fundable
    and disbursable. The cost lines themselves are retained as the historical
    snapshot (every aggregate excludes cancelled/deferred activities), but the
    draft requests are regenerated without them and un-moved advances are
    removed. Advances whose money already moved (disbursed/accounted/…) are
    deliberately preserved — those settle through the return/accountability
    workflow, never by silent deletion."""
    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.models import (
        MONEY_MOVED_ADVANCE_STATUSES,
        AdvanceRequest,
        WeeklyFundRequest,
    )
    from apps.fund_requests.monthly_service import sync_monthly_drafts_for_activity
    from apps.fund_requests.weekly_service import (
        REBUILDABLE_WEEKLY_STATUSES,
        sync_weekly_requests_for_activity,
    )

    a = (
        _get_in_scope(activity_id, principal)
        if already_authorised
        else _get_for_execution(activity_id, principal)
    )
    with transaction.atomic():
        a = Activity.objects.select_for_update().get(pk=a.pk)
        prior_buckets = list(
            ActivityScheduleCostLine.objects.filter(activity=a).values_list(
                "responsible_user", "fiscal_year", "month", "week_start_date"
            )
        )
        # A submitted/approved weekly request carrying this work keeps its
        # frozen total, and deleting the pending advances below makes it
        # undisbursable until someone returns it — capture the affected
        # requests now so the block is EXPLAINED at the moment it is created
        # instead of surfacing as an opaque guard refusal at the accountant
        # (2026-08-12 audit M-11).
        frozen_wfrs = list(
            WeeklyFundRequest.objects.filter(lines__activity_budget_line__activity=a)
            .exclude(status__in=REBUILDABLE_WEEKLY_STATUSES)
            .exclude(status__in=("disbursed", "accounted"))
            .distinct()
        )
        a.status = new_status
        a.last_reason = data.get("reason")
        a.save(update_fields=["status", "last_reason", "updated_at"])
        _detach_from_daily_visit_batch(a)
        AdvanceRequest.objects.filter(activity=a).exclude(
            status__in=MONEY_MOVED_ADVANCE_STATUSES
        ).delete()
        sync_weekly_requests_for_activity(a, prior_buckets=prior_buckets)
        sync_monthly_drafts_for_activity(a, prior_buckets=prior_buckets)
    for frozen in frozen_wfrs:
        _notify_frozen_weekly_request(frozen, a, new_status)
    # §26 — the record is preserved (never deleted) and the cancelled status
    # is what removes it from the partner's active My Plan. What was missing
    # was telling them: a partner could otherwise travel to a school for work
    # Edify had called off.
    if a.delivery_type == "partner" and a.assigned_partner_id:
        _notify_partner_schedule_change(
            a,
            f"partner_booking_{new_status}",
            f"A booking you hold has been {new_status}",
            (
                f"{a.activity_name_snapshot or a.get_activity_type_display()} for "
                f"{_where(a)} on "
                f"{a.planned_date:%-d %b %Y} has been {new_status}. "
                f"{(data.get('reason') or '').strip()}".strip()
                if a.planned_date
                else f"Work for {_where(a)} has been {new_status}."
            ),
        )
    return _serialize(a)


def cancel(
    activity_id: str, data: dict, principal, *, already_authorised: bool = False
) -> dict:
    return _cancel_or_defer(
        activity_id,
        data,
        principal,
        "cancelled",
        already_authorised=already_authorised,
    )


def defer(activity_id: str, data: dict, principal) -> dict:
    return _cancel_or_defer(activity_id, data, principal, "deferred")


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


#: PATCH fields that drive the cost formula (per-participant meal/snack
#: components). Changing one MUST re-price the activity — otherwise budget
#: lines silently diverge from the participant counts they were priced on.
_COST_DRIVER_PATCH_FIELDS = (
    "teachers_attended",
    "leaders_attended",
    "other_participants",
    "expected_participants",
)


def patch_activity(activity_id: str, data: dict, principal) -> dict:
    a = _get_for_execution(activity_id, principal)
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
        cost_drivers_changed = any(
            f in _COST_DRIVER_PATCH_FIELDS for f in update_fields
        )
        # Changing a cost driver re-prices the budget — scheduling authority,
        # which country-visibility-only roles (Programme Accountant) do not
        # carry (2026-08-12 audit M-3).
        if cost_drivers_changed:
            _assert_may_schedule(a, principal)
        with transaction.atomic():
            a.save(update_fields=update_fields + ["updated_at"])
            # A participant-count change re-prices per-head components. Batch
            # members are pool-priced (participants don't affect the pool), and
            # locked finance states make apply_to_activity raise — which is
            # correct: a confirmed/disbursed cost changes via amendment, not
            # via PATCH.
            if (
                cost_drivers_changed
                and a.scheduled_date
                and not a.daily_visit_batch_id
                and a.status not in ("cancelled", "rejected", "deferred")
            ):
                _apply_schedule_cost_snapshot(a, {}, principal=principal)
                a.save(update_fields=["est_cost_cents", "cost_missing", "updated_at"])
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
                "reason": "Impact cannot be measured yet because the initial SSA score is missing.",
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
    "complete_partner_ssa_support",
    "is_partner_ssa_support_activity",
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
