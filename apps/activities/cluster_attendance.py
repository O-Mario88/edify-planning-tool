"""Which schools a cluster session actually reached.

A cluster training or meeting belongs to a cluster, not a school, so its
``school`` FK is null. Every surface that asks "has this school been trained?"
by filtering ``school_id`` therefore misses cluster-delivered work entirely —
which is how a school that sat through a cluster training reads as No Training
on the Priority Schools table while reading as trained on its own profile.

This module is the one answer to that question. Surfaces call
``trained_school_ids`` rather than each deriving it from a different filter.
"""

from __future__ import annotations

from django.db import transaction

from apps.core.activity_types import COMPLETED_WORK_STATUSES, ActivityType
from apps.core.exceptions import BadRequest

#: Cluster attendance credits only verified work. "completed" is a status no
#: production transition writes — only the demo seeder — so gating on it would
#: credit unverified seed rows while skipping real verified work, which ends at
#: ia_verified or closed. This mirrors the rule the school profile already
#: applies to the cluster arm.
CLUSTER_CREDIT_STATUSES = ("ia_verified", "accountant_confirmed", "closed")

#: School-level training keeps the wider "work is done" vocabulary it has
#: always used, so adding the missing cluster arm does not quietly re-rule
#: what already counted. The asymmetry is inherited, not introduced here:
#: tightening it would drop schools that today read as trained, which is a
#: policy decision rather than a gap to close.

#: A meeting is not a training. Both attach to the school's history, but only
#: a training may answer "has this school been trained?" — counting meetings
#: let a school with four meetings and no training read as trained.
CLUSTER_TRAINING_TYPES = (
    ActivityType.CLUSTER_TRAINING,
    ActivityType.CLUSTER_TRAINING_SSA_COLLECTION,
)

#: School-level training keeps its own FK; it never needed an attendance row.
SCHOOL_TRAINING_TYPES = (
    ActivityType.TRAINING,
    ActivityType.IN_SCHOOL_TRAINING,
    ActivityType.SCHOOL_IMPROVEMENT_TRAINING,
    ActivityType.CORE_TRAINING,
)


def trained_school_ids(school_ids, *, fy=None) -> set[str]:
    """School ids with at least one verified training this FY, by either route.

    Both arms matter: a school trained in its own classroom carries the
    activity's ``school`` FK, and a school trained at a cluster session carries
    an attendance row instead. Asking only the first is the bug this exists to
    prevent.
    """
    from apps.activities.models import Activity, ClusterActivityAttendance

    # `school_ids` may be a plain list or a `.values("id")` subquery — the
    # analytics services pass the latter so the id set is never dragged into
    # Python. Both are valid on the right of `__in`, so neither is
    # materialised here.
    if school_ids is None:
        return set()
    if isinstance(school_ids, (list, tuple, set, frozenset)) and not school_ids:
        return set()

    own = Activity.objects.filter(
        school_id__in=school_ids,
        activity_type__in=SCHOOL_TRAINING_TYPES,
        status__in=COMPLETED_WORK_STATUSES,
        deleted_at__isnull=True,
    )
    cluster = ClusterActivityAttendance.objects.filter(
        school_id__in=school_ids,
        attended=True,
        activity__activity_type__in=CLUSTER_TRAINING_TYPES,
        activity__status__in=CLUSTER_CREDIT_STATUSES,
        activity__deleted_at__isnull=True,
    )
    if fy:
        own = own.filter(fy=fy)
        cluster = cluster.filter(activity__fy=fy)

    return set(own.values_list("school_id", flat=True)) | set(
        cluster.values_list("school_id", flat=True)
    )


def set_invited_schools(activity, school_ids, *, actor_id="") -> int:
    """Record which member schools are being invited to a cluster session.

    Snapshot, not a live view of membership: an approved budget must keep the
    schools it was priced with, so a school joining the cluster in November
    cannot silently re-price an activity approved in August.
    """
    from apps.activities.models import ClusterActivityAttendance
    from apps.schools.models import School

    if not activity.cluster_id:
        raise BadRequest("Only a cluster activity invites schools by name.")

    wanted = _clean_ids(school_ids)
    members = set(
        School.objects.filter(
            cluster_id=activity.cluster_id, deleted_at__isnull=True
        ).values_list("id", flat=True)
    )
    unknown = wanted - members
    if unknown:
        raise BadRequest(
            "Only schools in this cluster can be invited to its session. "
            "Add a school from another cluster as a guest when it attends."
        )

    with transaction.atomic():
        rows = {
            r.school_id: r
            for r in ClusterActivityAttendance.objects.filter(activity=activity)
        }
        for school_id in wanted:
            row = rows.get(school_id)
            if row is None:
                ClusterActivityAttendance.objects.create(
                    activity=activity,
                    school_id=school_id,
                    invited=True,
                    teachers=activity.teachers_per_school,
                    leaders=activity.leaders_per_school,
                    other=activity.other_per_school,
                    recorded_by=actor_id or "",
                )
            elif not row.invited:
                row.invited = True
                row.save(update_fields=["invited", "updated_at"])
        # Un-inviting only clears the invitation. A row that already records
        # attendance is a fact about what happened and is never removed by a
        # change of plan.
        stale = [
            r
            for sid, r in rows.items()
            if sid not in wanted and r.invited and not r.attended and not r.is_guest
        ]
        if stale:
            ClusterActivityAttendance.objects.filter(
                id__in=[r.id for r in stale]
            ).delete()
    return len(wanted)


def _clean_ids(raw) -> set[str]:
    return {str(i).strip() for i in (raw or []) if str(i).strip()}


def confirm_attendance(activity, school_ids, *, actor_id="") -> int:
    """Confirm which of the invited schools actually came.

    Ticking is bounded by the invitation list plus any guest already added, so
    a stray id posted by a browser cannot credit a school nobody saw. A school
    that was invited and did not come simply stays unticked — its row
    keeps the invitation as the record that it was asked.
    """
    from apps.activities.models import ClusterActivityAttendance

    confirmed = _clean_ids(school_ids)
    rows = list(ClusterActivityAttendance.objects.filter(activity=activity))
    known = {r.school_id for r in rows}
    unknown = confirmed - known
    if unknown:
        raise BadRequest(
            "Those schools were not invited to this session. Add a school "
            "that turned up unexpectedly as a guest, so it is visible as one."
        )

    with transaction.atomic():
        for row in rows:
            attended = row.school_id in confirmed
            if row.attended != attended:
                row.attended = attended
                row.recorded_by = actor_id or row.recorded_by
                row.save(update_fields=["attended", "recorded_by", "updated_at"])
    return len(confirmed)


def add_guest_school(
    activity, school_id, *, teachers=None, leaders=None, other=None, actor_id=""
):
    """Attach a school from outside this cluster to the session it attended.

    Real sessions draw schools from beyond their own cluster, and refusing to
    record that made the register a lie. The attendance is recorded against
    the canonical school, so the training lands on that school's profile and
    makes it eligible for the follow-up visit the session earned — exactly as
    it would for a member.

    The guest brings its own head counts: the cluster's uniform per-school
    composition describes the schools that were planned for, not one that
    walked in.
    """
    from apps.activities.models import ClusterActivityAttendance
    from apps.schools.models import School

    school = School.objects.filter(id=school_id, deleted_at__isnull=True).first()
    if school is None:
        raise BadRequest(
            "That school is not in the directory. Add it first — a school "
            "needs its Salesforce id before work can be recorded against it."
        )
    if school.cluster_id and str(school.cluster_id) == str(activity.cluster_id):
        raise BadRequest(
            "That school belongs to this cluster, so invite it rather than "
            "adding it as a guest."
        )

    row, created = ClusterActivityAttendance.objects.get_or_create(
        activity=activity,
        school=school,
        defaults={
            "invited": False,
            "attended": True,
            "is_guest": True,
            "teachers": teachers,
            "leaders": leaders,
            "other": other,
            "recorded_by": actor_id or "",
        },
    )
    if not created:
        row.attended = True
        row.is_guest = True
        row.teachers = teachers if teachers is not None else row.teachers
        row.leaders = leaders if leaders is not None else row.leaders
        row.other = other if other is not None else row.other
        row.save(
            update_fields=[
                "attended",
                "is_guest",
                "teachers",
                "leaders",
                "other",
                "updated_at",
            ]
        )
    return row


def expected_participants(activity) -> int:
    """Head count from the invitation list, not from cluster size.

    The planner states the composition once and ticks the schools; the total
    is the product, derived and never typed. Guests are excluded — they are
    recorded when they arrive, so they were never budgeted for.
    """
    from apps.activities.models import ClusterActivityAttendance

    per_school = sum(
        v or 0
        for v in (
            activity.teachers_per_school,
            activity.leaders_per_school,
            activity.other_per_school,
        )
    )
    invited = ClusterActivityAttendance.objects.filter(
        activity=activity, invited=True, is_guest=False
    ).count()
    return per_school * invited
