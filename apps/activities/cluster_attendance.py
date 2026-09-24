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
    # The array this table replaces is still written, and still holds every
    # attendance recorded before the table existed. Reading only the table
    # would make that history vanish from the counts on the day it shipped —
    # so both are read until the column is dropped.
    legacy = Activity.objects.filter(
        activity_type__in=CLUSTER_TRAINING_TYPES,
        status__in=CLUSTER_CREDIT_STATUSES,
        deleted_at__isnull=True,
    ).exclude(attended_school_ids=[])
    if fy:
        own = own.filter(fy=fy)
        cluster = cluster.filter(activity__fy=fy)
        legacy = legacy.filter(fy=fy)

    wanted = set(school_ids) if isinstance(school_ids, (list, tuple, set)) else None
    from_legacy = set()
    for attended in legacy.values_list("attended_school_ids", flat=True):
        for school_id in attended or []:
            if wanted is None or school_id in wanted:
                from_legacy.add(school_id)

    return (
        set(own.values_list("school_id", flat=True))
        | set(cluster.values_list("school_id", flat=True))
        | from_legacy
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
    from apps.schools.lifecycle_models import OPERATING_STATUSES

    members = set(
        School.objects.filter(
            cluster_id=activity.cluster_id,
            deleted_at__isnull=True,
            operational_status__in=OPERATING_STATUSES,
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

        # The head count is DERIVED from the ticks, so it has to be written
        # back. `Activity.expected_participants` is the figure costing prices
        # against, and nothing recomputed it when the invitation list changed
        # — so unticking a school left the session still priced for schools it
        # no longer invites. Same transaction as the ticks, because a stored
        # total that disagrees with the rows it comes from is the defect.
        sync_expected_participants(activity)
        # A Core School on this list has a package training booked by being on
        # it (owner, 2026-09-21). The invitation rows are written after the
        # Activity's own save, so the credit pass on `Activity.save` saw an
        # empty list; re-run it here, in the same transaction, and the slot is
        # taken — and released again when a school is unticked.
        from apps.core_schools.cluster_credit import credit_cluster_session

        credit_cluster_session(activity)
    return len(wanted)


def sync_expected_participants(activity) -> int:
    """Write the derived head count back and re-price if it moved.

    The number is never typed: composition per school times the schools
    actually invited. Returns the figure written.
    """
    total = expected_participants(activity)
    if activity.expected_participants == total:
        return total

    activity.expected_participants = total
    activity.save(update_fields=["expected_participants", "updated_at"])

    # Re-price after the ticks commit, through the one cost writer every other
    # scheduling path uses. Best effort on purpose: a session with no costed
    # catalogue item, or one whose budget is already approved, keeps what it
    # has. Failing the invitation edit because pricing could not refresh would
    # be the worse outcome — the ticks are the user's actual intent, and the
    # activity carries `cost_missing` for finance to see.
    def _reprice():
        try:
            from apps.activities.services import _apply_schedule_cost_snapshot

            _apply_schedule_cost_snapshot(activity, {})
        except Exception:  # noqa: BLE001
            return

    transaction.on_commit(_reprice)
    return total


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
        # The register is what decides a Core School's package training from
        # here on: a school that was invited and did not come gives its slot
        # back. Same transaction as the ticks.
        from apps.core_schools.cluster_credit import credit_cluster_session

        credit_cluster_session(activity)
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


def invited_head_counts(sessions) -> dict[str, int]:
    """The people each cluster session invited, for tables of many sessions.

    ``sessions`` is ``(activity_id, cluster_id)`` pairs. A session counts the
    people its invited schools bring, not the per-school figure stored on the
    activity: an invitation row may override the session's composition for
    its school. A session nobody has been invited to yet reads its stored head
    count, or its per-school figure across the cluster's member schools.

    Three queries whatever the number of sessions. A session with neither
    invitations nor a cluster is absent from the answer, so the caller keeps
    whatever figure it already had.
    """
    from collections import defaultdict

    from django.db.models import Count

    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.schools.models import School

    cluster_of = {
        activity_id: cluster_id for activity_id, cluster_id in sessions if activity_id
    }
    if not cluster_of:
        return {}
    activities = Activity.objects.in_bulk(list(cluster_of))
    member_counts = dict(
        School.objects.filter(
            cluster_id__in={c for c in cluster_of.values() if c},
            deleted_at__isnull=True,
        )
        .values("cluster_id")
        .annotate(total=Count("id"))
        .values_list("cluster_id", "total")
    )
    invites = defaultdict(list)
    for invite in ClusterActivityAttendance.objects.filter(
        activity_id__in=list(cluster_of), invited=True
    ):
        invites[invite.activity_id].append(invite)

    def composition(invite):
        return (invite.teachers, invite.leaders, invite.other)

    counts: dict[str, int] = {}
    for activity_id, cluster_id in cluster_of.items():
        activity = activities.get(activity_id)
        per_school = (
            (activity.participants_per_school or activity.teachers_per_school or 0)
            if activity
            else 0
        )
        invited = invites.get(activity_id, [])
        if invited:
            if not per_school and all(
                all(value is None for value in composition(invite))
                for invite in invited
            ):
                counts[activity_id] = (
                    (activity.expected_participants or 0) if activity else 0
                )
            else:
                counts[activity_id] = sum(
                    sum(value or 0 for value in composition(invite))
                    if any(value is not None for value in composition(invite))
                    else per_school
                    for invite in invited
                )
        elif cluster_id:
            counts[activity_id] = (
                activity.expected_participants
                if activity and activity.expected_participants
                else per_school * member_counts.get(cluster_id, 0)
            )
    return counts


def training_counts(school_ids, *, fy=None) -> dict[str, int]:
    """How many verified trainings each school has had, by either route.

    The school profile shows a number rather than a yes/no, so it needs this
    rather than ``trained_school_ids`` — but both must agree about what counts,
    which is why they live together and share the same status vocabularies.
    """
    from django.db.models import Count

    from apps.activities.models import Activity, ClusterActivityAttendance

    if school_ids is None:
        return {}
    if isinstance(school_ids, (list, tuple, set, frozenset)) and not school_ids:
        return {}

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

    # Same two-source rule as trained_school_ids: the array this table
    # replaces still holds pre-migration attendance, and dropping it from the
    # counts would make delivered work disappear from school profiles.
    legacy = Activity.objects.filter(
        activity_type__in=CLUSTER_TRAINING_TYPES,
        status__in=CLUSTER_CREDIT_STATUSES,
        deleted_at__isnull=True,
    ).exclude(attended_school_ids=[])
    if fy:
        legacy = legacy.filter(fy=fy)

    counts: dict[str, int] = {}
    for source in (
        own.values("school_id").annotate(n=Count("id")).values_list("school_id", "n"),
        cluster.values("school_id")
        .annotate(n=Count("id"))
        .values_list("school_id", "n"),
    ):
        for school_id, n in source:
            counts[school_id] = counts.get(school_id, 0) + n

    wanted = set(school_ids) if isinstance(school_ids, (list, tuple, set)) else None
    counted = set(cluster.values_list("activity_id", flat=True).distinct())
    for activity_id, attended in legacy.values_list("id", "attended_school_ids"):
        # An activity that already has rows is counted from them; adding the
        # array as well would credit the same session twice.
        if activity_id in counted:
            continue
        for school_id in attended or []:
            if wanted is None or school_id in wanted:
                counts[school_id] = counts.get(school_id, 0) + 1
    return counts


# ── Invitations for sessions planned before they were recorded ──────────────
#: Not yet delivered: the sessions whose invitation list is still the plan.
#: A delivered session's register (who attended) is the record of what
#: happened, and is never inferred.
UNDELIVERED_SESSION_STATUSES = (
    "planned",
    "scheduled",
    "rescheduled",
    "assigned_to_partner",
    "partner_scheduled",
    "in_progress",
    "completion_started",
)


def backfill_session_invitations(*, dry_run: bool = False) -> dict:
    """Name the invited schools on cluster sessions planned before invitations
    were recorded (owner, 2026-09-23: "backfill the invited schools for older
    cluster sessions").

    The drawers have written who was invited only since 2026-09-16, and a
    school counts toward a cluster session only when it is named on the
    session (school_planning_badges), so every session planned for the whole
    cluster before then read "Not Planned" on each of its schools. Such a
    session — live, not yet delivered, with no register row at all — is given
    what the drawer invites by default today: the cluster's active member
    schools, less the Partner-supported ones (partner_school_policy).

    Only the invitation register is written. The session's head count and
    cost are left exactly as they were priced; the Core package credit is run
    as a save of the session would run it. A session that already names any
    school, or has recorded attendance, is left alone, so running this twice
    changes nothing.
    """
    from django.db.models import Exists, OuterRef

    from apps.activities.models import Activity, ClusterActivityAttendance
    from apps.clusters.services import active_schools
    from apps.core_schools.cluster_credit import credit_cluster_session
    from apps.planning.partner_school_policy import partner_supported_members
    from apps.planning.school_planning_badges import CLUSTER_SESSION_TYPES

    sessions = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            cluster_id__isnull=False,
            activity_type__in=CLUSTER_SESSION_TYPES,
            status__in=UNDELIVERED_SESSION_STATUSES,
        )
        .filter(
            ~Exists(ClusterActivityAttendance.objects.filter(activity=OuterRef("pk")))
        )
        .exclude(attended_school_ids__len__gt=0)
        .order_by("created_at")
    )
    report = {"sessions": 0, "invitations": 0, "without_members": 0}
    for session in sessions:
        members = [s.id for s in active_schools(session.cluster_id)]
        supported = partner_supported_members(members)
        invited = [school_id for school_id in members if school_id not in supported]
        if not invited:
            report["without_members"] += 1
            continue
        report["sessions"] += 1
        report["invitations"] += len(invited)
        if dry_run:
            continue
        with transaction.atomic():
            ClusterActivityAttendance.objects.bulk_create(
                [
                    ClusterActivityAttendance(
                        activity=session,
                        school_id=school_id,
                        invited=True,
                        teachers=session.teachers_per_school,
                        leaders=session.leaders_per_school,
                        other=session.other_per_school,
                        recorded_by="backfill",
                    )
                    for school_id in invited
                ]
            )
            credit_cluster_session(session)
    return report
