"""Undo a planning change made by mistake (owner, 2026-09-28).

"can you create a function for users to undo plans done by mistake. for
example if a user assign schools to partner they are not supposed to assign
can you make sure the actions can be reversed." And: "Same with assigning to
project, adding a school to clusters".

Three changes can be taken back by the person who made them:

* a school (or cluster) handed to a Partner  — ``PartnerAssignment``;
* a school added to a Special Project        — ``ProjectSchoolAssignment``;
* a school added to, or moved into, a cluster — ``SchoolClusterMembership``.

Nothing new is stored to make this possible. Each of those rows already says
who made it and when, so "your recent changes" is read straight from them, and
every door that makes such a change — the Planning drawer and bulk bar, the
Project and Cluster drawers, Core Schools, the school profile — is covered
without each one having to remember to record something.

An undo is for a mistake, not a change of plan, so it has two limits:

* **Time** — ``UNDO_WINDOW``. After a week the change has been lived with,
  and taking it back is a decision the ordinary tools make with a reason:
  withdrawing work from the Partner, removing a school from the Project.
* **Nothing built on it yet.** A handover the Partner has already scheduled,
  a project school with work planned under the project, a school that has
  moved cluster again: undoing any of those would pull the floor from under
  something else. Such a change says why it cannot be undone and which tool
  can take it back instead.

What an undo leaves behind is the audit entry naming what was reversed (a
handover's whole row rides in it) and, for clusters, the membership history,
which records the join and the undo both. A handover the Partner never acted
on is removed outright rather than marked withdrawn: it was never real work,
so it must not read as a withdrawal on the Partner's record or leave a
"returned" row for anyone to resolve.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.core.exceptions import BadRequest, ConflictError, NotFoundError

logger = logging.getLogger(__name__)

#: How long a change stays undoable by the person who made it.
UNDO_WINDOW = timedelta(days=7)

KIND_PARTNER = "partner"
KIND_PROJECT = "project"
KIND_CLUSTER = "cluster"
KINDS = (KIND_PARTNER, KIND_PROJECT, KIND_CLUSTER)

#: Written as the reason on the cluster membership an undo restores, so the
#: restoring row is never offered back as a change of its own to undo.
UNDO_REASON_PREFIX = "Undo:"

#: At most this many rows are reversed in one request (a bulk toast's batch).
MAX_BATCH = 100


@dataclass(frozen=True)
class Change:
    """One change a person made that the Recent changes list shows."""

    kind: str
    id: str
    made_at: datetime
    #: What changed, in the words of the page it was made on.
    summary: str
    #: What pressing Undo will do.
    effect: str
    #: Why it cannot be undone now; empty when it can.
    blocked: str = ""

    @property
    def can_undo(self) -> bool:
        return not self.blocked

    @property
    def kind_label(self) -> str:
        return {
            KIND_PARTNER: "Partner",
            KIND_PROJECT: "Project",
            KIND_CLUSTER: "Cluster",
        }[self.kind]


@dataclass(frozen=True)
class Undone:
    """What an undo did, and which clusters and projects it touched so the
    pages showing them can refresh."""

    message: str
    cluster_ids: tuple[str, ...] = ()
    project_ids: tuple[str, ...] = ()


# ── Who made it ─────────────────────────────────────────────────────────────
def actor_ids(principal) -> set[str]:
    """Every id a change may carry for this person.

    Handovers record the StaffProfile id, falling back to the User id for an
    Admin with no profile; projects and clusters record the User id.
    """
    values = (
        getattr(principal, "staff_profile_id", None),
        getattr(principal, "user_id", None),
        getattr(principal, "id", None),
    )
    return {str(value) for value in values if value}


def _window_start(now=None):
    return (now or timezone.now()) - UNDO_WINDOW


def _too_old(made_at, now=None) -> bool:
    return made_at is None or made_at < _window_start(now)


def _age_refusal(what: str) -> str:
    return (
        f"Changes can be undone for {UNDO_WINDOW.days} days. This one is older "
        f"— {what}."
    )


# ── Partner handovers ───────────────────────────────────────────────────────
def _partner_blocked(assignment, *, has_withdrawal: bool, now=None) -> str:
    from apps.partners.models import PartnerAssignment

    partner = getattr(assignment.partner, "name", None) or "The partner"
    if _too_old(assignment.created_at, now):
        return _age_refusal("withdraw it from Partner Monitoring instead")
    if assignment.status == PartnerAssignment.STATUS_RETURNED_TO_STAFF:
        return f"{partner} no longer holds it — it was handed back or withdrawn."
    if (
        assignment.scheduled_activity_id
        or assignment.status not in PartnerAssignment.UNSCHEDULED_STATUSES
    ):
        return (
            f"{partner} has already scheduled it. Withdraw it from Partner "
            "Monitoring instead, so the activity and its cost are unwound."
        )
    if has_withdrawal:
        return "A withdrawal is already open on it."
    if assignment.replaces_assignment_id:
        return (
            "It replaced another partner's work. Withdraw it instead, so the "
            "school is not left without support."
        )
    return ""


def _partner_target(assignment) -> str:
    school = getattr(assignment.school, "name", None)
    cluster = getattr(assignment.cluster, "name", None)
    return school or (f"{cluster} cluster" if cluster else "A school")


def _partner_summary(assignment) -> str:
    partner = getattr(assignment.partner, "name", None) or "a partner"
    work = ""
    if assignment.catalogue_item_id and assignment.catalogue_item:
        work = f" — {assignment.catalogue_item.display_name}"
    elif assignment.expected_activity_type:
        work = f" — {assignment.expected_activity_type.replace('_', ' ')}"
    project = ""
    if assignment.project_id and assignment.project:
        project = f" (project: {assignment.project.name})"
    return f"{_partner_target(assignment)} assigned to {partner}{work}{project}"


def _partner_rows(ids: set[str], since):
    from apps.partners.models import PartnerAssignment
    from apps.partners.withdrawal_models import PartnerAssignmentWithdrawal

    return (
        PartnerAssignment.objects.filter(
            assigning_staff_id__in=ids, created_at__gte=since
        )
        .select_related("school", "cluster", "partner", "project", "catalogue_item")
        .annotate(
            has_withdrawal=Exists(
                PartnerAssignmentWithdrawal.objects.filter(assignment=OuterRef("pk"))
            )
        )
    )


def _partner_change(assignment, now=None) -> Change:
    partner = getattr(assignment.partner, "name", None) or "the partner"
    return Change(
        kind=KIND_PARTNER,
        id=assignment.id,
        made_at=assignment.created_at,
        summary=_partner_summary(assignment),
        effect=f"Takes it back from {partner} as if it was never assigned.",
        blocked=_partner_blocked(
            assignment,
            has_withdrawal=bool(getattr(assignment, "has_withdrawal", False)),
            now=now,
        ),
    )


def _undo_partner(principal, assignment_id: str) -> Undone:
    from apps.audit.services import log as audit_log
    from apps.core_schools.package_credit import release_assignment_slot
    from apps.notifications.services import resolve_condition
    from apps.partners.models import PartnerAssignment
    from apps.partners.withdrawal_models import PartnerAssignmentWithdrawal

    with transaction.atomic():
        assignment = (
            PartnerAssignment.objects.select_for_update(of=("self",))
            .select_related("school", "cluster", "partner", "project", "catalogue_item")
            .filter(id=assignment_id, assigning_staff_id__in=actor_ids(principal))
            .first()
        )
        if assignment is None:
            raise NotFoundError("That assignment is not one you made.")
        blocked = _partner_blocked(
            assignment,
            has_withdrawal=PartnerAssignmentWithdrawal.objects.filter(
                assignment=assignment
            ).exists(),
        )
        if blocked:
            raise ConflictError(blocked)

        summary = _partner_summary(assignment)
        school_id = assignment.school_id
        project_id = assignment.project_id
        cluster_id = assignment.cluster_id
        snapshot = {
            "partnerId": assignment.partner_id,
            "schoolId": school_id,
            "clusterId": assignment.cluster_id,
            "projectId": assignment.project_id,
            "catalogueItemId": assignment.catalogue_item_id,
            "expectedActivityType": assignment.expected_activity_type,
            "purposeOfVisit": assignment.purpose_of_visit,
            "scheduledDate": assignment.scheduled_date.isoformat()
            if assignment.scheduled_date
            else None,
            "supportType": assignment.support_type,
            "visitNumber": assignment.visit_number,
            "trainingNumber": assignment.training_number,
            "assigningStaffId": assignment.assigning_staff_id,
            "status": assignment.status,
            "createdAt": assignment.created_at.isoformat(),
        }

        # A Core School's package slot goes back to the package, open to be
        # planned again — the same release a withdrawal makes.
        release_assignment_slot(assignment)
        # The Partner's "New assignment" notice would otherwise open onto
        # nothing.
        resolve_condition(
            "partner_scheduled_activity", "partner_assignment", assignment.id
        )
        _resolve_core_support_notice(assignment)
        audit_log(
            action="partner.assignment_undone",
            subject_kind="PartnerAssignment",
            subject_id=assignment.id,
            actor_id=getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            reason="Undone by the person who assigned it.",
            payload={"previous": snapshot, "new": None},
        )
        assignment.delete()

    if school_id:
        _resync_partner_support(school_id)
    return Undone(
        f"Undone: {summary}.",
        cluster_ids=(cluster_id,) if cluster_id else (),
        project_ids=(project_id,) if project_id else (),
    )


def _resolve_core_support_notice(assignment) -> None:
    """Core Schools tells the Partner about a handover a second time, by
    school ("New Core School Support Assignment"). That notice names no
    assignment, so it is closed only when this was the Partner's last live
    handover at the school."""
    from apps.notifications.services import resolve_condition
    from apps.partners.models import Partner, PartnerAssignment

    if not assignment.school_id:
        return
    still_there = (
        PartnerAssignment.objects.filter(
            school_id=assignment.school_id, partner_id=assignment.partner_id
        )
        .exclude(pk=assignment.pk)
        .exclude(status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        .exists()
    )
    if still_there:
        return
    recipients = [
        uid
        for uid in Partner.objects.filter(id=assignment.partner_id).values_list(
            "user_id", flat=True
        )
        if uid
    ]
    if recipients:
        resolve_condition(
            "core_school_assigned",
            "School",
            assignment.school_id,
            recipient_ids=recipients,
        )


def _resync_partner_support(school_id: str) -> None:
    """The multiple-Partner exception follows the live rows (it is kept in
    step on save; a removal has to ask for it)."""
    try:
        from apps.partners.support_responsibility import (
            sync_multiple_partner_exception,
            visibility_enabled,
        )

        if visibility_enabled():
            sync_multiple_partner_exception(school_id)
    except Exception:  # noqa: BLE001 - bookkeeping never fails an undo
        logger.warning("multiple-partner exception sync failed", exc_info=True)


# ── Project enrolments ──────────────────────────────────────────────────────
def _project_blocked(enrolment, now=None) -> str:
    from apps.activities.models import Activity
    from apps.partners.models import PartnerAssignment

    if _too_old(enrolment.created_at, now):
        return _age_refusal("ask the Project Coordinator to remove the school")
    if getattr(enrolment.project, "deleted_at", None):
        return "The project has been deleted."
    planned = (
        Activity.objects.filter(
            project_id=enrolment.project_id,
            school_id=enrolment.school_id,
            deleted_at__isnull=True,
        )
        .exclude(status="cancelled")
        .exists()
    )
    if planned:
        return (
            "Work is already planned for this school under the project. Cancel "
            "that work first."
        )
    handed_over = (
        PartnerAssignment.objects.filter(
            project_id=enrolment.project_id, school_id=enrolment.school_id
        )
        .exclude(status=PartnerAssignment.STATUS_RETURNED_TO_STAFF)
        .exists()
    )
    if handed_over:
        return (
            "It has been assigned to a partner under this project. Undo or "
            "withdraw that assignment first."
        )
    return ""


def _project_summary(enrolment) -> str:
    school = getattr(enrolment.school, "name", None) or "A school"
    project = getattr(enrolment.project, "name", None) or "a project"
    return f"{school} added to {project}"


def _project_rows(ids: set[str], since):
    from apps.projects.models import ProjectSchoolAssignment

    return ProjectSchoolAssignment.objects.filter(
        assigned_by__in=ids, created_at__gte=since
    ).select_related("project", "school")


def _project_change(enrolment, now=None) -> Change:
    project = getattr(enrolment.project, "name", None) or "the project"
    return Change(
        kind=KIND_PROJECT,
        id=enrolment.id,
        made_at=enrolment.created_at,
        summary=_project_summary(enrolment),
        effect=f"Takes the school out of {project}.",
        blocked=_project_blocked(enrolment, now=now),
    )


def _undo_project(principal, enrolment_id: str) -> Undone:
    """Take the school out of the project as if it was never added.

    ``projects.services.remove_school`` is the Project Coordinator's tool and
    writes an enrolment-history row, because a school that leaves a project
    had a spell in it. A school added by mistake and taken out before any work
    was planned had none, so no history row is written; the audit entry is
    the record.
    """
    from apps.audit.services import log as audit_log
    from apps.projects.models import ProjectSchoolAssignment

    with transaction.atomic():
        enrolment = (
            ProjectSchoolAssignment.objects.select_for_update(of=("self",))
            .select_related("project", "school")
            .filter(id=enrolment_id, assigned_by__in=actor_ids(principal))
            .first()
        )
        if enrolment is None:
            raise NotFoundError("That project school is not one you added.")
        blocked = _project_blocked(enrolment)
        if blocked:
            raise ConflictError(blocked)
        summary = _project_summary(enrolment)
        audit_log(
            action="project.school_enrolment_undone",
            subject_kind="School",
            subject_id=enrolment.school_id,
            actor_id=getattr(principal, "user_id", None),
            actor_role=getattr(principal, "active_role", None),
            reason="Undone by the person who added it.",
            payload={
                "previous": {
                    "projectId": enrolment.project_id,
                    "enrolled": True,
                    "addedAt": enrolment.created_at.isoformat(),
                    "assignmentReason": enrolment.assignment_reason or "",
                    "matchedIntervention": enrolment.matched_intervention or "",
                    "baselineScore": enrolment.baseline_score,
                },
                "new": {"projectId": enrolment.project_id, "enrolled": False},
            },
        )
        project_id = enrolment.project_id
        enrolment.delete()
    return Undone(f"Undone: {summary}.", project_ids=(project_id,))


# ── Cluster memberships ─────────────────────────────────────────────────────
def _previous_membership(membership):
    """The membership this one replaced: closed at the instant it opened.

    ``sync_membership_history`` closes the old row and opens the new one with
    the same timestamp, so equality is exact. None when the school was
    unclustered before.
    """
    from apps.clusters.models import SchoolClusterMembership

    return (
        SchoolClusterMembership.objects.filter(
            school_id=membership.school_id, ended_at=membership.started_at
        )
        .select_related("cluster")
        .first()
    )


def _usable_cluster(cluster) -> bool:
    from apps.core.enums import ClusterRecordStatus

    return bool(
        cluster is not None
        and cluster.deleted_at is None
        and cluster.status == ClusterRecordStatus.ACTIVE
    )


def _owner_accepts(cluster, school) -> bool:
    """Whether the membership service would let the school back into
    ``cluster``: an owned cluster takes only its owner's schools."""
    from apps.clusters.eligibility import owner_id_variants, portfolio_owner_profile_id

    owner = (cluster.responsible_staff_id or "").strip()
    if not owner:
        return True
    return owner in owner_id_variants(portfolio_owner_profile_id(school) or "")


def _cluster_plan(membership, principal, now=None) -> tuple[object, str, str]:
    """(cluster to return to or None, what undo will do, why it cannot)."""
    from apps.core.scoping import direct_portfolio_schools, or_empty, resolve_user_scope
    from apps.schools.models import School

    school = membership.school
    current = getattr(membership.cluster, "name", None) or "the cluster"
    if _too_old(membership.started_at, now):
        return None, "", _age_refusal("change the cluster from the school instead")
    if school is None or school.deleted_at is not None:
        return None, "", "The school is no longer on the platform."
    if school.cluster_id != membership.cluster_id:
        return None, "", "The school has moved cluster again since."
    writable = or_empty(direct_portfolio_schools(resolve_user_scope(principal)), School)
    if not writable.filter(id=school.id).exists():
        return None, "", "The school is no longer in your portfolio."

    previous = _previous_membership(membership)
    before = previous.cluster if previous is not None else None
    if before is None:
        return None, f"Takes the school out of {current}; it is unclustered again.", ""
    if not _usable_cluster(before):
        return (
            None,
            f"Takes the school out of {current}. Its previous cluster, "
            f"{before.name}, is no longer active, so it is left unclustered.",
            "",
        )
    if not _owner_accepts(before, school):
        return (
            None,
            "",
            f"Its previous cluster, {before.name}, belongs to another staff "
            "member now. Change the cluster from the school instead.",
        )
    return before, f"Moves the school back to {before.name}.", ""


def _cluster_summary(membership, previous_cluster_name: str = "") -> str:
    school = getattr(membership.school, "name", None) or "A school"
    cluster = getattr(membership.cluster, "name", None) or "a cluster"
    if previous_cluster_name:
        return f"{school} moved from {previous_cluster_name} to {cluster}"
    return f"{school} added to {cluster}"


def _cluster_rows(ids: set[str], since):
    from apps.clusters.models import SchoolClusterMembership

    return (
        SchoolClusterMembership.objects.filter(
            started_by__in=ids, started_at__gte=since, ended_at__isnull=True
        )
        .exclude(start_reason__startswith=UNDO_REASON_PREFIX)
        .select_related("school", "cluster")
    )


def _cluster_change(membership, principal, now=None) -> Change:
    previous = _previous_membership(membership)
    previous_name = getattr(getattr(previous, "cluster", None), "name", "") or ""
    _target, effect, blocked = _cluster_plan(membership, principal, now=now)
    return Change(
        kind=KIND_CLUSTER,
        id=membership.id,
        made_at=membership.started_at,
        summary=_cluster_summary(membership, previous_name),
        effect=effect,
        blocked=blocked,
    )


def _undo_cluster(principal, membership_id: str) -> Undone:
    from apps.clusters.models import SchoolClusterMembership
    from apps.clusters.services import set_school_cluster_membership
    from apps.schools.models import School

    with transaction.atomic():
        membership = (
            SchoolClusterMembership.objects.filter(
                id=membership_id,
                started_by__in=actor_ids(principal),
                ended_at__isnull=True,
            )
            .exclude(start_reason__startswith=UNDO_REASON_PREFIX)
            .first()
        )
        if membership is None:
            raise NotFoundError(
                "That cluster change is not one you made, or the school has "
                "moved since."
            )
        # The school row is the membership's lock (the membership service
        # takes the same one), so nobody moves the school between this check
        # and the move back.
        membership.school = School.objects.select_for_update().get(
            pk=membership.school_id
        )
        previous = _previous_membership(membership)
        previous_name = getattr(getattr(previous, "cluster", None), "name", "") or ""
        target, _effect, blocked = _cluster_plan(membership, principal)
        if blocked:
            raise ConflictError(blocked)
        summary = _cluster_summary(membership, previous_name)
        set_school_cluster_membership(
            membership.school,
            target,
            getattr(principal, "user_id", None) or "",
            reason=f"{UNDO_REASON_PREFIX} {summary} by mistake.",
            actor_role=getattr(principal, "active_role", "") or "",
        )
    where = f"back in {target.name}" if target else "unclustered again"
    touched = (membership.cluster_id, target.id) if target else (membership.cluster_id,)
    return Undone(f"Undone: {summary}. The school is {where}.", cluster_ids=touched)


# ── The public surface ──────────────────────────────────────────────────────
def recent_changes(principal, *, now=None) -> list[Change]:
    """This person's changes from the last ``UNDO_WINDOW``, newest first.

    Includes the ones that can no longer be undone, each with its reason, so
    a change that disappeared from the list is one that was undone — never
    one the list quietly stopped showing.
    """
    ids = actor_ids(principal)
    if not ids:
        return []
    now = now or timezone.now()
    since = _window_start(now)
    changes = [
        *(_partner_change(row, now) for row in _partner_rows(ids, since)),
        *(_project_change(row, now) for row in _project_rows(ids, since)),
        *(_cluster_change(row, principal, now) for row in _cluster_rows(ids, since)),
    ]
    changes.sort(key=lambda change: change.made_at, reverse=True)
    return changes


_UNDOERS = {
    KIND_PARTNER: _undo_partner,
    KIND_PROJECT: _undo_project,
    KIND_CLUSTER: _undo_cluster,
}


def undo(principal, kind: str, change_id: str) -> Undone:
    """Reverse one change this person made, and say what happened.

    Every check is made again here, under a row lock where the row is the
    change itself: the list may have been open for an hour, and the Partner
    may have scheduled the work in the meantime.
    """
    undoer = _UNDOERS.get(kind)
    if undoer is None:
        raise BadRequest("Choose a change to undo.")
    if not change_id:
        raise BadRequest("Choose a change to undo.")
    return undoer(principal, change_id)


def undo_many(principal, kind: str, change_ids) -> tuple[list[Undone], list[str]]:
    """Reverse a batch — what a bulk action's toast offers to undo.

    Each change is its own decision: one the Partner has already scheduled
    is reported and the rest still go. Returns (done, refused messages).
    """
    done, refused = [], []
    unique = list(dict.fromkeys(str(value) for value in change_ids if value))
    for change_id in unique[:MAX_BATCH]:
        try:
            done.append(undo(principal, kind, change_id))
        except (BadRequest, ConflictError, NotFoundError) as exc:
            refused.append(str(exc))
    return done, refused


__all__ = [
    "KINDS",
    "KIND_CLUSTER",
    "KIND_PARTNER",
    "KIND_PROJECT",
    "UNDO_WINDOW",
    "Change",
    "Undone",
    "actor_ids",
    "recent_changes",
    "undo",
    "undo_many",
]
