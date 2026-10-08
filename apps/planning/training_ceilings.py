"""Training ceilings — the one place their numbers are worked out and held.

Owner, 2026-10-06. Four things, and no layer between them:

    Training Catalogue  what training is this?
    Training Ceiling    how many schools may this team member schedule for it?
    Training Schedule   when and how is it delivered?
    Training Schools    which schools are scheduled for it?

A training is delivered one of two ways, and never a third:

* **Group Training** — a cluster session (a group training, or a cluster
  meeting classified *Training*). Its schools are the schools invited to it
  by name (``ClusterActivityAttendance.invited``).
* **In-School Training** — one training at one school (the activity's own
  ``school``).

A Programme Lead sets the ceiling for themselves and for each officer they
supervise, per training and fiscal year (``TrainingCeiling``). Nothing else is stored: what
is scheduled is counted here from the persisted plans, so the drawers, the
summary tables and the save all read one figure, and a second drawer never
hands out a fresh allowance.

The ceiling is held on the server. ``reserve`` locks the ceiling row before it
counts, so two people adding the last places are served one after the other
and the second is refused. A browser that greys out its boxes is a courtesy;
this is the rule.

No ceiling set means no limit: an officer nobody has given a ceiling schedules
as before. The reporting side still reads every state — a ceiling lowered
below what is scheduled, or rows written by an import, show as Excess rather
than a negative balance.

A ceiling is a number of schools, so a school is counted once (owner,
2026-10-08: "some are blocking before hitting the ceiling"). A school on two
sessions of the same training, or with a group session and an in-school one,
was counted once for each: three schools trained twice filled six places, and
an officer was refused with half their ceiling unused. It is one school under
an officer's ceiling, and one school for the country, however many sessions
it is on.

A training a live Special Project delivers is the project's (owner,
2026-10-08: "read only project ... so that there are no repeated trainings").
Its schools are the schools added to the project, against the capacity its
coordinator set; it has no training ceiling, counts under none, and is listed
once, under its project (``project_training_ids``).

A school handed to a Partner for a training is a school committed to that
training from the moment it is handed over (owner, 2026-10-08: "the training
summary should not wait for partner scheduling ... Assigned must still count
toward training coverage/capacity"). The hand-over is the commitment; the
Partner dating it moves the same commitment on a stage and adds no school. So
an in-school training is delivered by staff or by a Partner, and a Partner's
is read from two records that are one piece of work at two moments:

* the hand-over still waiting for the Partner's date (``PartnerAssignment``,
  not yet scheduled), and
* the training the Partner has dated (the ``Activity`` the hand-over became),
  or work created already carrying a Partner.

It is filed under the staff member who follows it: its monitor, else whoever
assigned it or is responsible for it, else whoever holds the school — the
order the planning monitors credit Partner work in. A hand-over has no date,
so it is waiting now: it is read in the running year and in a year being
planned ahead, never in a year that has closed.

"Allocated" is not a word here. It keeps its meaning — a school assigned to a
partner or to a project — and training uses Scheduled, Ceiling, Balance and
Excess. Nor is every committed school "scheduled": staff *plan* an in-school
training, a school is *assigned* to a Partner and then *scheduled* by it, and
a school is *scheduled* on a group training. The four are never added into one
number without saying which is which (``apps.planning.training_coverage``).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Case, CharField, F, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce, NullIf

from apps.activities.training_names import MODE_OF_DELIVERY as _MODE_OF_DELIVERY
from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
from apps.core.enums import MeetingKind
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

__all__ = [
    "DELIVERY_LABELS",
    "MODE_OF_DELIVERY",
    "GROUP",
    "IN_SCHOOL",
    "PARTNER",
    "PARTNER_SCHEDULED",
    "covered",
    "handovers_read_in",
    "reserve_for_handover",
    "SummaryRow",
    "flag_counts",
    "summary_totals",
    "summary_sections",
    "capacity",
    "ceiling_staff_of",
    "course_id_of",
    "delivery_of",
    "is_training",
    "may_set_ceiling",
    "may_view_staff",
    "assert_schools_named",
    "reserve",
    "reserve_for_activity",
    "reserve_for_session",
    "schools_behind",
    "set_ceiling",
    "remove_ceiling",
    "summary_for_staff",
    "team_summary",
    "team_profiles",
    "under_ceiling",
    "own_summary",
    "ceiling_staff_options",
    "training_options",
    "project_of_training",
    "project_training_ids",
    "project_training_mappings",
    "scheduled_count",
    "scheduled_schools",
    "schools_of",
    "COUNTRY_CEILING_ROLES",
    "country_capacity",
    "country_ceilings",
    "country_of",
    "country_scheduled",
    "may_set_country_ceiling",
    "remove_country_ceiling",
    "set_country_ceiling",
]

GROUP = "group"
IN_SCHOOL = "in_school"
#: The two ways a training is delivered. There is no third.
DELIVERY_LABELS = {GROUP: "Group Training", IN_SCHOOL: "In-School Training"}
#: An in-school training a Partner delivers: every school committed to the
#: Partner for it, and those of them the Partner has dated. Not a third way of
#: delivering a training — who delivers the in-school one.
PARTNER = "partner"
PARTNER_SCHEDULED = "partner_scheduled"
#: The same two, as My Plan's Mode of Delivery column says them (owner,
#: 2026-10-06: "Cluster Group training or In-School training"): the one
#: definition, My Plan's (apps.activities.training_names).
MODE_OF_DELIVERY = dict(_MODE_OF_DELIVERY)
assert set(MODE_OF_DELIVERY) == {GROUP, IN_SCHOOL}

#: A plan in one of these no longer holds its schools' places.
RELEASED_STATUSES = ("cancelled", "rejected", "deferred", "not_planned")

_TRAINING_TYPES = tuple(getattr(t, "value", t) for t in TRAINING_TYPES)
_MEETING_TYPES = tuple(getattr(t, "value", t) for t in CLUSTER_MEETING_TYPES)


# ── What counts ─────────────────────────────────────────────────────────────
def is_training(activity) -> bool:
    """A training, or a cluster meeting classified as one."""
    if activity.activity_type in _TRAINING_TYPES:
        return True
    return (
        activity.activity_type in _MEETING_TYPES
        and activity.meeting_kind == MeetingKind.TRAINING
    )


def delivery_of(activity) -> str | None:
    """Group Training or In-School Training; None for anything else.

    Decided by what the plan is attached to: a school of its own is an
    in-school delivery, a cluster with no school is a group delivery.
    """
    if not is_training(activity):
        return None
    if activity.school_id:
        return IN_SCHOOL
    if activity.cluster_id:
        return GROUP
    return None


def course_id_of(activity) -> str | None:
    """The Training Catalogue entry a training delivers.

    The course named beside the workflow (an in-school delivery, a training
    at a cluster meeting), else the catalogue item when it is itself a course
    (a group training).
    """
    if activity.training_course_id:
        return activity.training_course_id
    item = activity.catalogue_item
    if item is not None and item.is_training_course:
        return item.id
    return None


def _training_q(prefix: str = "") -> Q:
    return Q(**{f"{prefix}activity_type__in": _TRAINING_TYPES}) | Q(
        **{
            f"{prefix}activity_type__in": _MEETING_TYPES,
            f"{prefix}meeting_kind": MeetingKind.TRAINING,
        }
    )


def _outside_projects_q(prefix: str = "") -> Q:
    """Training planned outside a Special Project. A project's training is
    read from the project — the schools each person added to it, against the
    capacity its coordinator set — and is not counted under a training
    ceiling as well (owner, 2026-10-06; apps.planning.training_summary)."""
    return Q(**{f"{prefix}project_id__isnull": True}) | Q(**{f"{prefix}project_id": ""})


def project_training_mappings():
    """The trainings live Special Projects deliver: every active link between
    a live project and a Training entry of the Activity Catalogue."""
    from apps.activity_catalogue.models import (
        ActivityProjectMapping,
        CatalogueActivityType,
    )
    from apps.projects.models import LIVE_PROJECT_STATUSES

    return ActivityProjectMapping.objects.filter(
        active=True,
        project__deleted_at__isnull=True,
        project__status__in=[status.value for status in LIVE_PROJECT_STATUSES],
        catalogue_item__activity_type=CatalogueActivityType.TRAINING,
    )


def project_training_ids() -> frozenset[str]:
    """The catalogue ids of those trainings. Each is read from its project
    and nowhere else: not a row of its own on a summary, and not under a
    training ceiling (owner, 2026-10-08)."""
    return frozenset(
        project_training_mappings().values_list("catalogue_item_id", flat=True)
    )


def project_of_training(course_id: str | None) -> str:
    """The name of the live project that delivers this training; "" when it
    is nobody's."""
    if not course_id:
        return ""
    return (
        project_training_mappings()
        .filter(catalogue_item_id=course_id)
        .order_by("project__name")
        .values_list("project__name", flat=True)
        .first()
        or ""
    )


def _not_a_projects(rows):
    """Leave out the trainings a live project delivers, wherever they were
    scheduled from: annotated rows, by their ``course``."""
    return rows.exclude(
        course__in=project_training_mappings().values("catalogue_item_id")
    )


def under_ceiling(activity) -> bool:
    """Whether this plan's schools count under a training ceiling: a group or
    in-school training that belongs to no project and is no project's own."""
    if delivery_of(activity) is None or activity.project_id:
        return False
    return course_id_of(activity) not in project_training_ids()


def _course_expr(prefix: str = ""):
    """The course id of a training row, in SQL (``course_id_of``)."""
    return Coalesce(
        F(f"{prefix}training_course_id"),
        Case(
            When(
                **{f"{prefix}catalogue_item__is_training_course": True},
                then=F(f"{prefix}catalogue_item_id"),
            ),
            output_field=CharField(),
        ),
        output_field=CharField(),
    )


def _school_training_rows(*, fy, course_id=None, exclude_activity_id=None):
    """Every training planned at a school of its own, outside projects,
    whoever delivers it."""
    from apps.activities.models import Activity

    rows = (
        Activity.objects.filter(
            _training_q(),
            _outside_projects_q(),
            fy=fy,
            deleted_at__isnull=True,
            school__isnull=False,
        )
        .exclude(status__in=RELEASED_STATUSES)
        .annotate(course=_course_expr())
        .exclude(course__isnull=True)
    )
    rows = _not_a_projects(rows)
    if course_id:
        rows = rows.filter(course=course_id)
    if exclude_activity_id:
        rows = rows.exclude(id=exclude_activity_id)
    return rows


def _in_school_rows(*, owner_ids, fy, course_id=None, exclude_activity_id=None):
    """In-school trainings staff deliver, filed under the officer who planned
    them. One a Partner delivers is the Partner's (``_partner_rows``)."""
    rows = _school_training_rows(
        fy=fy, course_id=course_id, exclude_activity_id=exclude_activity_id
    ).exclude(delivery_type="partner")
    if owner_ids is not None:
        rows = rows.filter(responsible_staff_id__in=list(owner_ids))
    return rows


def _blank_as_null(name: str):
    return NullIf(F(name), Value(""), output_field=CharField())


def _open_handovers():
    """Hand-overs a Partner has not dated yet."""
    from apps.partners.models import PartnerAssignment

    return PartnerAssignment.objects.filter(
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES
    )


def _partner_rows(*, owner_ids, fy, course_id=None, exclude_activity_id=None):
    """In-school trainings a Partner delivers, once they are an activity: the
    training a hand-over became when the Partner dated it, and work created
    already carrying a Partner. Each row says whose it is (``owner``: its
    monitor, else who is responsible for it, else who holds the school) and
    whether the Partner has dated it (``dated``): a booked Certified Partner
    Agency is on its day too, though staff chose it.

    An activity an open hand-over still carries is read from the hand-over
    (``_handover_rows``), so the school is one commitment and one row."""
    from apps.core.enums import ExecutorType
    from apps.planning.country_oversight import rules

    rows = (
        _school_training_rows(
            fy=fy, course_id=course_id, exclude_activity_id=exclude_activity_id
        )
        .filter(delivery_type="partner")
        .exclude(
            id__in=_open_handovers()
            .filter(source_activity_id__isnull=False)
            .values("source_activity_id")
        )
        .annotate(
            owner=Coalesce(
                _blank_as_null("monitored_by_staff_id"),
                _blank_as_null("responsible_staff_id"),
                F("school__account_owner_id"),
                output_field=CharField(),
            ),
            dated=Case(
                When(
                    rules.partner_planned_q()
                    | (
                        rules.planned_q()
                        & Q(executor_type=ExecutorType.CERTIFIED_PARTNER_AGENCY.value)
                    ),
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
    )
    if owner_ids is not None:
        rows = rows.filter(owner__in=list(owner_ids))
    return rows


def handovers_read_in(fy) -> bool:
    """Whether a hand-over still waiting for the Partner's date is read in
    this year. It has no date of its own, so it is waiting now: the running
    year's, and a later year's while that year is being planned, never a
    closed year's."""
    from apps.core.fy import get_operational_fy

    try:
        return int(str(fy)) >= int(str(get_operational_fy()))
    except (TypeError, ValueError):
        return str(fy) == str(get_operational_fy())


def _handover_rows(*, owner_ids, fy, course_id=None, exclude_assignment_id=None):
    """Schools handed to a Partner for a training and still waiting for the
    Partner's date: the training hand-overs (the course a hand-over names, or
    a course chosen as its activity) at a school, outside projects, that the
    Partner has neither dated nor let go. ``owner`` is whose they are: the
    hand-over's monitor, else who assigned it, else who holds the school."""
    from apps.partners.models import PartnerAssignment

    if not handovers_read_in(fy):
        return PartnerAssignment.objects.none().annotate(
            course=_course_expr(), owner=F("monitoring_staff_id")
        )
    rows = (
        _open_handovers()
        .filter(school__isnull=False, project__isnull=True)
        .annotate(
            course=_course_expr(),
            owner=Coalesce(
                _blank_as_null("monitoring_staff_id"),
                _blank_as_null("assigning_staff_id"),
                F("school__account_owner_id"),
                output_field=CharField(),
            ),
        )
        .exclude(course__isnull=True)
    )
    rows = _not_a_projects(rows)
    if owner_ids is not None:
        rows = rows.filter(owner__in=list(owner_ids))
    if course_id:
        rows = rows.filter(course=course_id)
    if exclude_assignment_id:
        rows = rows.exclude(id=exclude_assignment_id)
    return rows


def _group_rows(*, owner_ids, fy, course_id=None, exclude_activity_id=None):
    """One row per school attached to a group delivery: every school invited
    to it by name, and any school recorded as attending that was not on the
    list (a walk-in, or a guest from another cluster). Owner, 2026-10-06:
    "make sure all the schools added to a training are counted" — whichever
    cluster's session they were added to."""
    from apps.activities.models import ClusterActivityAttendance

    rows = (
        ClusterActivityAttendance.objects.filter(
            _training_q("activity__"),
            _outside_projects_q("activity__"),
            Q(invited=True) | Q(attended=True),
            activity__fy=fy,
            activity__deleted_at__isnull=True,
            activity__school__isnull=True,
            activity__cluster__isnull=False,
        )
        .exclude(activity__status__in=RELEASED_STATUSES)
        .annotate(course=_course_expr("activity__"))
        .exclude(course__isnull=True)
    )
    rows = _not_a_projects(rows)
    if owner_ids is not None:
        rows = rows.filter(activity__responsible_staff_id__in=list(owner_ids))
    if course_id:
        rows = rows.filter(course=course_id)
    if exclude_activity_id:
        rows = rows.exclude(activity_id=exclude_activity_id)
    return rows


# ── Staff identity ──────────────────────────────────────────────────────────
def _profile(staff_or_user_id):
    """The StaffProfile behind either id an activity may carry."""
    from apps.accounts.models import StaffProfile

    if not staff_or_user_id:
        return None
    return (
        StaffProfile.objects.filter(
            Q(id=staff_or_user_id) | Q(user_id=staff_or_user_id),
            deleted_at__isnull=True,
        )
        .select_related("user")
        .first()
    )


def _owner_ids(profile) -> list[str]:
    return [value for value in (profile.id, profile.user_id) if value]


def scheduled_schools(
    profile,
    course_id: str,
    fy: str,
    *,
    exclude_activity_id: str | None = None,
    exclude_assignment_id: str | None = None,
) -> dict:
    """The schools this staff member has committed to one training in one
    year: sets of school ids read from the persisted records. A school on
    several sessions is in a set once.

    ``GROUP`` are the schools on their group trainings, ``IN_SCHOOL`` the
    schools staff have planned an in-school training at, ``PARTNER`` the
    schools assigned to a Partner for it — waiting for the Partner's date or
    dated — and ``PARTNER_SCHEDULED`` those of them the Partner has dated,
    which is part of ``PARTNER`` and never a second set of schools."""
    ids = _owner_ids(profile)
    kwargs = dict(owner_ids=ids, fy=str(fy), course_id=course_id)
    activity = dict(kwargs, exclude_activity_id=exclude_activity_id)
    partner, partner_scheduled = set(), set()
    for school_id, dated in _partner_rows(**activity).values_list("school_id", "dated"):
        partner.add(school_id)
        if dated:
            partner_scheduled.add(school_id)
    partner.update(
        _handover_rows(
            **kwargs, exclude_assignment_id=exclude_assignment_id
        ).values_list("school_id", flat=True)
    )
    return {
        GROUP: set(_group_rows(**activity).values_list("school_id", flat=True)),
        IN_SCHOOL: set(_in_school_rows(**activity).values_list("school_id", flat=True)),
        PARTNER: partner,
        PARTNER_SCHEDULED: partner_scheduled,
    }


def covered(schools: dict) -> set:
    """Every school of ``scheduled_schools``, once: the schools the training
    is committed to, however each is delivered."""
    return schools[GROUP] | schools[IN_SCHOOL] | schools[PARTNER]


def scheduled_count(
    profile, course_id: str, fy: str, *, exclude_activity_id: str | None = None
) -> dict:
    """How many schools this staff member has committed to one training in
    one year. Each school counts once: ``total`` is the schools, not the
    sessions, so it can be less than the routes added up."""
    schools = scheduled_schools(
        profile, course_id, fy, exclude_activity_id=exclude_activity_id
    )
    return {
        GROUP: len(schools[GROUP]),
        IN_SCHOOL: len(schools[IN_SCHOOL]),
        PARTNER: len(schools[PARTNER]),
        PARTNER_SCHEDULED: len(schools[PARTNER_SCHEDULED]),
        "total": len(covered(schools)),
    }


# ── The ceiling, held ───────────────────────────────────────────────────────
def _refusal(training_name, staff_name, ceiling, scheduled, requested, fy) -> str:
    """What the planner is told when a save would pass the ceiling (owner,
    2026-10-06: "tells the users that they have hit the ceiling and cannot
    add anymore schools")."""
    left = max(ceiling - scheduled, 0)
    head = (
        f"Training ceiling reached. {staff_name} may schedule {ceiling} "
        f"school{'s' if ceiling != 1 else ''} for {training_name} in FY {fy}, "
        f"and {scheduled} {'is' if scheduled == 1 else 'are'} already covered "
        "(planned by staff, assigned to a partner or on a group training)"
    )
    if left <= 0:
        return f"{head}, so no more schools can be added."
    return (
        f"{head}, so only {left} more school{'s' if left != 1 else ''} can be "
        f"added and {requested} {'was' if requested == 1 else 'were'} selected. "
        f"Untick {requested - left} and save again."
    )


def reserve(
    *,
    staff_id: str | None,
    course_id: str | None,
    fy: str,
    schools,
    held=(),
    exclude_activity_id: str | None = None,
    exclude_assignment_id: str | None = None,
) -> None:
    """Hold the ceiling for one write. Call inside the write's transaction.

    ``schools`` are the schools the plan being written will hold once saved,
    ``held`` the ones it holds now (none for a new plan), and
    ``exclude_activity_id`` that plan, so its own schools are never counted
    twice. The ceiling row is locked before anything is counted, which is
    what serialises two people taking the last places.

    What is counted is schools, whichever way each is committed: planned by
    staff, on a group training, or assigned to a Partner — dated by the
    Partner or not (owner, 2026-10-08). A school the officer has already
    committed to this training takes no new place, so adding it is never
    refused. Nor is a write that adds no school: with a ceiling lowered below
    what is covered, an officer can still untick a school or swap one for
    another.
    """
    from apps.planning.training_ceiling_models import TrainingCeiling

    schools = {str(school_id) for school_id in schools if school_id}
    held = {str(school_id) for school_id in held if school_id}
    if not staff_id or not course_id or not (schools - held):
        return
    profile = _profile(staff_id)
    if profile is None:
        return
    row = (
        TrainingCeiling.objects.select_for_update()
        .select_related("training")
        .filter(staff_id=profile.id, training_id=course_id, fy=str(fy))
        .first()
    )
    if row is None or course_id in project_training_ids():
        # No ceiling, or a project's training: its schools are the project's,
        # against the capacity its coordinator set.
        return
    elsewhere = covered(
        scheduled_schools(
            profile,
            course_id,
            fy,
            exclude_activity_id=exclude_activity_id,
            exclude_assignment_id=exclude_assignment_id,
        )
    )
    before = len(elsewhere | held)
    after = len(elsewhere | schools)
    if after > before and after > row.ceiling:
        raise BadRequest(
            _refusal(
                row.training.display_name,
                profile.user.name or "This staff member",
                row.ceiling,
                before,
                after - before,
                str(fy),
            )
        )


def reserve_for_activity(
    *,
    activity_type: str,
    meeting_kind: str = "",
    staff_id: str | None,
    course_id: str | None,
    fy: str,
    school_id: str | None,
) -> None:
    """A new training at one school takes one place (In-School Training)."""
    if not school_id or not course_id:
        return
    if activity_type not in _TRAINING_TYPES and not (
        activity_type in _MEETING_TYPES and meeting_kind == MeetingKind.TRAINING
    ):
        return
    reserve(staff_id=staff_id, course_id=course_id, fy=fy, schools={school_id})


def reserve_for_handover(
    *, school_id, course_id, monitoring_staff_id=None, assigning_staff_id=None
) -> None:
    """A school is about to be handed to a Partner for a training: it takes a
    place under the ceiling of the staff member the hand-over is filed under,
    as a training staff plan there does (owner, 2026-10-08: "the assignment
    itself represents a legitimate planned/committed school for training
    capacity purposes"). Held in the running year, where a hand-over with no
    date is read; the Partner dating it later takes no second place."""
    from apps.core.fy import get_operational_fy

    if not school_id or not course_id:
        return
    reserve(
        staff_id=monitoring_staff_id or assigning_staff_id,
        course_id=course_id,
        fy=str(get_operational_fy()),
        schools={school_id},
    )


def assert_schools_named(
    *, activity_type: str, meeting_kind: str = "", staff_id, course_id, fy
) -> None:
    """A group delivery planned with no school named, for an officer who has
    a ceiling for that training, is refused: its schools could not be
    counted. Without a ceiling the older reading stands (nobody named means
    the cluster as a whole) and nothing is asked."""
    from apps.planning.training_ceiling_models import TrainingCeiling

    if activity_type not in _TRAINING_TYPES and not (
        activity_type in _MEETING_TYPES and meeting_kind == MeetingKind.TRAINING
    ):
        return
    profile = _profile(staff_id)
    if profile is None or not course_id:
        return
    if (
        TrainingCeiling.objects.filter(
            staff_id=profile.id, training_id=course_id, fy=str(fy)
        ).exists()
        and course_id not in project_training_ids()
    ):
        raise BadRequest(
            "Tick the schools this training is for. A training ceiling is set "
            "for it, and a training with no school named cannot be counted "
            "under the ceiling."
        )


def reserve_for_session(activity, *, schools_after, schools_now) -> None:
    """A group delivery's invitation list is about to change: the schools it
    will hold once saved, and the ones it holds now."""
    if delivery_of(activity) != GROUP or activity.project_id:
        return
    reserve(
        staff_id=activity.responsible_staff_id,
        course_id=course_id_of(activity),
        fy=activity.fy,
        schools=schools_after,
        held=schools_now,
        exclude_activity_id=activity.id,
    )


def schools_of(activity) -> set[str]:
    """The schools a persisted training holds under its ceiling."""
    if activity.project_id:
        return set()
    delivery = delivery_of(activity)
    if delivery == IN_SCHOOL:
        return {activity.school_id}
    if delivery == GROUP:
        from apps.activities.models import ClusterActivityAttendance

        return set(
            ClusterActivityAttendance.objects.filter(activity=activity)
            .filter(Q(invited=True) | Q(attended=True))
            .values_list("school_id", flat=True)
        )
    return set()


def schools_held(activity) -> int:
    """How many places a persisted training holds under its ceiling."""
    return len(schools_of(activity))


def ceiling_staff_of(activity) -> str | None:
    """Whose ceiling a persisted training sits under: the officer responsible
    for it, or — for one a Partner delivers — the staff member who follows
    it, as ``_partner_rows`` files it."""
    if (activity.delivery_type or "") != "partner":
        return activity.responsible_staff_id
    return (
        activity.monitored_by_staff_id
        or activity.responsible_staff_id
        or getattr(activity.school, "account_owner_id", None)
    )


def reserve_for_move(activity, *, staff_id=None, fy=None) -> None:
    """A persisted training is moving to another year or another officer:
    its schools must fit under the ceiling it lands under."""
    new_staff = staff_id or ceiling_staff_of(activity)
    new_fy = str(fy or activity.fy)
    old = _profile(ceiling_staff_of(activity))
    new = _profile(new_staff)
    same_staff = (old.id if old else None) == (new.id if new else None)
    if same_staff and new_fy == str(activity.fy):
        return
    if activity.status in RELEASED_STATUSES:
        return
    held = schools_of(activity)
    if not held:
        return
    reserve(
        staff_id=new_staff,
        course_id=course_id_of(activity),
        fy=new_fy,
        schools=held,
        exclude_activity_id=activity.id,
    )


def capacity(
    staff_id: str | None,
    course_id: str | None,
    fy: str,
    *,
    exclude_activity_id: str | None = None,
    school_id: str | None = None,
) -> dict:
    """What a drawer shows before a save: the ceiling, the schools covered
    under it apart from the plan being edited — planned by staff, on a group
    training or assigned to a Partner — and what is left.

    ``schoolIds`` names those schools, so a drawer can tell a school that
    takes a new place from one already counted; ``counted`` says whether
    ``school_id`` — the one school an in-school drawer is for — is among
    them, and so takes no place.
    """
    from apps.planning.training_ceiling_models import TrainingCeiling

    blank = {
        "managed": False,
        "ceiling": None,
        "scheduled": 0,
        "group": 0,
        "inSchool": 0,
        "partner": 0,
        "partnerScheduled": 0,
        "awaitingPartner": 0,
        "remaining": None,
        "schoolIds": [],
        "counted": False,
        "project": "",
        "staffName": "",
        "fy": str(fy),
    }
    profile = _profile(staff_id) if staff_id and course_id else None
    if profile is None:
        return blank
    project = project_of_training(course_id)
    if project:
        # A project's training: read from the project, under no ceiling.
        return {**blank, "project": project, "staffName": profile.user.name or ""}
    schools = scheduled_schools(
        profile, course_id, fy, exclude_activity_id=exclude_activity_id
    )
    counted = covered(schools)
    ceiling = (
        TrainingCeiling.objects.filter(
            staff_id=profile.id, training_id=course_id, fy=str(fy)
        )
        .values_list("ceiling", flat=True)
        .first()
    )
    return {
        "managed": ceiling is not None,
        "ceiling": ceiling,
        "scheduled": len(counted),
        "group": len(schools[GROUP]),
        "inSchool": len(schools[IN_SCHOOL]),
        "partner": len(schools[PARTNER]),
        "partnerScheduled": len(schools[PARTNER_SCHEDULED]),
        "awaitingPartner": len(schools[PARTNER] - schools[PARTNER_SCHEDULED]),
        "remaining": None if ceiling is None else max(ceiling - len(counted), 0),
        "schoolIds": sorted(counted),
        "counted": bool(school_id) and str(school_id) in counted,
        "project": "",
        "staffName": profile.user.name or "",
        "fy": str(fy),
    }


# ── The summary ─────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class SummaryRow:
    staff_id: str
    staff_name: str
    training_id: str
    training_name: str
    intervention: str
    ceiling_id: str
    ceiling: int | None
    #: Schools on a group session, and schools staff have planned an
    #: in-school training at.
    group: int
    in_school: int
    #: Schools in more than one of the routes, counted once in ``total``.
    both: int = 0
    #: Schools assigned to a Partner for the training, and those of them the
    #: Partner has dated: part of ``partner``, never more schools.
    partner: int = 0
    partner_scheduled: int = 0

    @property
    def total(self) -> int:
        """Schools covered for the training: each one once, however it is
        delivered and on however many sessions."""
        return self.group + self.in_school + self.partner - self.both

    @property
    def awaiting_partner(self) -> int:
        """Schools assigned to a Partner that the Partner has not dated."""
        return max(self.partner - self.partner_scheduled, 0)

    @property
    def balance(self) -> int | None:
        """Places left; never negative. None when no ceiling is set."""
        if self.ceiling is None:
            return None
        return max(self.ceiling - self.total, 0)

    @property
    def excess(self) -> int:
        """Schools scheduled above the ceiling; 0 when within it or unset."""
        if self.ceiling is None:
            return 0
        return max(self.total - self.ceiling, 0)

    @property
    def state(self) -> str:
        if self.ceiling is None:
            return "unset"
        if self.total > self.ceiling:
            return "above"
        if self.total == self.ceiling:
            return "reached"
        return "available"

    @property
    def flag(self) -> str:
        """What the Programme Lead reads at a glance (owner, 2026-10-06:
        "flag which training has more ... than it should and which one has
        less schools than it should have")."""
        if self.state == "above":
            return f"{self.excess} above ceiling"
        if self.state == "available":
            return f"{self.balance} below ceiling"
        if self.state == "reached":
            return "At ceiling"
        return "No ceiling set"

    @property
    def flag_tone(self) -> str:
        return {
            "unset": "neutral",
            "above": "danger",
            "available": "warning",
            "reached": "success",
        }[self.state]

    @property
    def utilization(self) -> int | None:
        """Schools scheduled as a share of the ceiling, as Project Capacity
        reads an allocation; None with no ceiling, and a ceiling of zero
        with anything scheduled reads as fully used."""
        if self.ceiling is None:
            return None
        if self.ceiling == 0:
            return 100 if self.total else 0
        return round(self.total * 100 / self.ceiling)


def flag_counts(rows) -> dict:
    """How many rows stand above, below and at their ceiling."""
    counts = {"above": 0, "available": 0, "reached": 0, "unset": 0}
    for row in rows:
        counts[row.state] += 1
    return counts


def summary_totals(rows) -> dict:
    """One line over a person's rows, the shape of the Project Capacity
    section head (owner, 2026-10-06: "use project capacity table format"):
    trainings, the ceilings added up, schools scheduled under them, the
    balance left and the excess above them.

    `ceiling` and `under_ceiling` add up the rows that HAVE a ceiling, so a
    training with none set neither inflates the balance nor hides as
    excess; `unlimited` says how many such rows there are."""
    rows = list(rows)
    with_ceiling = [r for r in rows if r.ceiling is not None]
    return {
        "trainings": len(rows),
        "ceiling": sum(r.ceiling for r in with_ceiling) if with_ceiling else None,
        "scheduled": sum(r.total for r in rows),
        "under_ceiling": sum(r.total for r in with_ceiling),
        "group": sum(r.group for r in rows),
        "in_school": sum(r.in_school for r in rows),
        "partner": sum(r.partner for r in rows),
        "partner_scheduled": sum(r.partner_scheduled for r in rows),
        "awaiting_partner": sum(r.awaiting_partner for r in rows),
        "balance": sum(r.balance for r in with_ceiling) if with_ceiling else None,
        "excess": sum(r.excess for r in with_ceiling),
        "unlimited": len(rows) - len(with_ceiling),
        "flags": flag_counts(rows),
    }


def summary_sections(rows) -> list[dict]:
    """The rows filed one person a section, in the order `summary_for_staff`
    gives them (by name): each with the person's totals, so a page can give
    every officer their own tab and table (owner, 2026-10-06: "each lead
    should have their own")."""
    sections: dict[str, dict] = {}
    for row in rows:
        section = sections.get(row.staff_id)
        if section is None:
            section = sections[row.staff_id] = {
                "staff_id": row.staff_id,
                "staff_name": row.staff_name,
                "rows": [],
            }
        section["rows"].append(row)
    for section in sections.values():
        section["totals"] = summary_totals(section["rows"])
    return list(sections.values())


def _counted_twice(*routes: set) -> int:
    """How many times a school is in more than one route: what the routes
    added up exceed the schools by."""
    return sum(len(route) for route in routes) - len(set().union(*routes))


def summary_for_staff(profiles, fy: str) -> list[SummaryRow]:
    """One row per staff member and training with a ceiling or anything
    scheduled, for any number of staff in five queries."""
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.activity_catalogue.training_intervention import fixed_interventions
    from apps.core.enums import SsaIntervention
    from apps.planning.training_ceiling_models import TrainingCeiling

    profiles = [p for p in profiles if p is not None]
    if not profiles:
        return []
    fy = str(fy)
    by_identity = {}
    for profile in profiles:
        for identity in _owner_ids(profile):
            by_identity[identity] = profile.id
    names = {p.id: (p.user.name or p.user.email) for p in profiles}

    ceilings = {
        (row["staff_id"], row["training_id"]): row
        for row in TrainingCeiling.objects.filter(
            staff_id__in=list(names), fy=fy
        ).values("id", "staff_id", "training_id", "ceiling")
    }
    # The schools behind each figure, so one on several sessions is one.
    group: dict[tuple, set] = {}
    for staff, course, school_id in (
        _group_rows(owner_ids=by_identity, fy=fy)
        .values_list("activity__responsible_staff_id", "course", "school_id")
        .distinct()
    ):
        group.setdefault((by_identity[staff], course), set()).add(school_id)
    in_school: dict[tuple, set] = {}
    for staff, course, school_id in (
        _in_school_rows(owner_ids=by_identity, fy=fy)
        .values_list("responsible_staff_id", "course", "school_id")
        .distinct()
    ):
        in_school.setdefault((by_identity[staff], course), set()).add(school_id)
    # Schools assigned to a Partner: the hand-overs still waiting, and the
    # trainings the Partner has dated. One school, one commitment.
    partner: dict[tuple, set] = {}
    partner_scheduled: dict[tuple, set] = {}
    for staff, course, school_id, dated in (
        _partner_rows(owner_ids=by_identity, fy=fy)
        .values_list("owner", "course", "school_id", "dated")
        .distinct()
    ):
        key = (by_identity[staff], course)
        partner.setdefault(key, set()).add(school_id)
        if dated:
            partner_scheduled.setdefault(key, set()).add(school_id)
    for staff, course, school_id in (
        _handover_rows(owner_ids=by_identity, fy=fy)
        .values_list("owner", "course", "school_id")
        .distinct()
    ):
        partner.setdefault((by_identity[staff], course), set()).add(school_id)

    # A project's training holds no ceiling here, whatever was set before it
    # became the project's.
    projects_own = project_training_ids()
    ceilings = {key: row for key, row in ceilings.items() if key[1] not in projects_own}
    keys = set(ceilings) | set(group) | set(in_school) | set(partner)
    trainings = dict(
        ActivityCatalogueItem.objects.filter(
            id__in={training_id for _staff, training_id in keys}
        ).values_list("id", "display_name")
    )
    fixed = fixed_interventions()
    labels = dict(SsaIntervention.choices)
    rows = [
        SummaryRow(
            staff_id=staff_id,
            staff_name=names[staff_id],
            training_id=training_id,
            training_name=trainings.get(training_id, "Training"),
            intervention=labels.get(fixed.get(training_id, ""), ""),
            ceiling_id=(ceilings.get((staff_id, training_id)) or {}).get("id", ""),
            ceiling=(ceilings.get((staff_id, training_id)) or {}).get("ceiling"),
            group=len(group.get((staff_id, training_id), ())),
            in_school=len(in_school.get((staff_id, training_id), ())),
            partner=len(partner.get((staff_id, training_id), ())),
            partner_scheduled=len(partner_scheduled.get((staff_id, training_id), ())),
            both=_counted_twice(
                group.get((staff_id, training_id), set()),
                in_school.get((staff_id, training_id), set()),
                partner.get((staff_id, training_id), set()),
            ),
        )
        for staff_id, training_id in keys
    ]
    rows.sort(key=lambda r: (r.staff_name.casefold(), r.training_name.casefold()))
    return rows


# ── Who sees and sets what ──────────────────────────────────────────────────
def _own_profile(principal):
    return _profile(getattr(principal, "staff_profile_id", None))


def _supervised(principal) -> list:
    """The officers this Programme Lead line-manages (apps.hr.team_roster)."""
    from apps.hr.team_roster import team_members

    return list(team_members(principal))


def team_profiles(lead_staff_id) -> list:
    """The officers under one Programme Lead, by the lead's staff id — for a
    page drawn for a lead other than the reader (Admin, in support)."""
    from types import SimpleNamespace

    from apps.hr.team_roster import team_members

    if not lead_staff_id:
        return []
    return list(team_members(SimpleNamespace(staff_profile_id=lead_staff_id)))


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


def may_set_ceiling(principal, staff_profile_id: str) -> bool:
    """A Programme Lead sets their own ceiling and the ceilings of the
    officers they supervise (owner, 2026-10-06: "they can set their own
    ceiling and that of their CCEOs"). A Lead schedules trainings too, and
    had no ceiling anybody could set."""
    if _role(principal) != EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return False
    if not staff_profile_id:
        return False
    if staff_profile_id == getattr(principal, "staff_profile_id", None):
        return True
    return staff_profile_id in {p.id for p in _supervised(principal)}


def may_view_staff(principal, staff_profile_id: str) -> bool:
    """Whose training summary and schools this reader may open: their own; a
    Programme Lead, the officers they supervise; the Country Director, Impact
    Assessment and Admin, anybody's, read-only."""
    if not staff_profile_id:
        return False
    if staff_profile_id == getattr(principal, "staff_profile_id", None):
        return True
    role = _role(principal)
    if role in (
        EdifyRole.ADMIN.value,
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.IMPACT_ASSESSMENT.value,
    ):
        # The country's read-only readers (owner, 2026-10-06).
        return True
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return staff_profile_id in {p.id for p in _supervised(principal)}
    return False


def own_summary(principal, fy: str) -> list[SummaryRow]:
    """My Training Summary: the reader's own rows and nobody else's."""
    profile = _own_profile(principal)
    return summary_for_staff([profile], fy) if profile else []


def team_summary(profiles, fy: str) -> list[SummaryRow]:
    """The Programme Lead's table: every supervised officer's rows."""
    return summary_for_staff(profiles, fy)


def ceiling_staff_options(principal) -> list:
    """The people a Programme Lead may set a ceiling for: the Lead first,
    then the officers they supervise, by name. The Lead used to be missing
    from the list, and so from every table built from it."""
    if _role(principal) != EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return []
    own = _own_profile(principal)
    officers = sorted(
        (p for p in _supervised(principal) if own is None or p.id != own.id),
        key=lambda p: (p.user.name or "").casefold(),
    )
    return [own, *officers] if own is not None else officers


def training_options() -> list[dict]:
    """Every active training in the Training Catalogue a ceiling can be set
    for, with the SSA intervention it is fixed to. A training a live project
    delivers is not one of them: its schools are capped by the project."""
    from apps.activity_catalogue.services import effective_items
    from apps.activity_catalogue.training_intervention import fixed_interventions
    from apps.core.enums import SsaIntervention

    fixed = fixed_interventions(fresh=True)
    labels = dict(SsaIntervention.choices)
    return [
        {
            "id": item_id,
            "name": name,
            "intervention": labels.get(fixed.get(item_id, ""), ""),
        }
        for item_id, name in effective_items()
        .filter(is_training_course=True)
        .exclude(id__in=project_training_mappings().values("catalogue_item_id"))
        .order_by("display_name", "stable_code")
        .values_list("id", "display_name")
    ]


def _assert_not_a_projects(training) -> None:
    project = project_of_training(training.id)
    if project:
        raise BadRequest(
            f"{training.display_name} is delivered under the {project} project. "
            "Its schools are the schools added to that project, against the "
            "capacity its coordinator set, so it takes no training ceiling."
        )


def _clean_ceiling(raw, *, most: int = 5000, noun: str = "training ceiling") -> int:
    text = str(raw if raw is not None else "").strip()
    if not text.isdigit():
        raise BadRequest(f"The {noun} is a whole number of schools.")
    value = int(text)
    if value < 1:
        raise BadRequest(f"The {noun} is at least 1 school.")
    if value > most:
        raise BadRequest(f"That {noun} is implausibly large.")
    return value


def _clean_fy(fy) -> str:
    from apps.core.fy import fy_options

    fy = str(fy or "").strip()
    if fy not in fy_options():
        raise BadRequest("Choose the fiscal year this ceiling applies to.")
    return fy


def _actor(principal) -> str:
    return str(
        getattr(principal, "staff_profile_id", None)
        or getattr(principal, "user_id", None)
        or getattr(principal, "id", "")
    )


def set_ceiling(
    principal, *, staff_id: str, training_id: str, fy: str, ceiling, note: str = ""
):
    """Set or change one person's ceiling for one training in one year.

    A ceiling may be set below what is already scheduled — the summary then
    shows the difference as Excess and no more schools can be added — because
    lowering it is a decision about the future, not a correction of the past.
    """
    from django.db import transaction

    from apps.activity_catalogue.services import effective_items
    from apps.audit.services import log as audit_log
    from apps.planning.training_ceiling_models import TrainingCeiling

    profile = _profile(staff_id)
    if profile is None:
        raise NotFoundError("That staff member was not found.")
    if not may_set_ceiling(principal, profile.id):
        raise Forbidden(
            "A Programme Lead sets their own training ceiling and those of "
            "the officers they supervise."
        )
    training = (
        effective_items().filter(is_training_course=True, id=training_id or "").first()
    )
    if training is None:
        raise BadRequest("Choose an active training from the Training Catalogue.")
    _assert_not_a_projects(training)
    fy = _clean_fy(fy)
    value = _clean_ceiling(ceiling)
    with transaction.atomic():
        row = (
            TrainingCeiling.objects.select_for_update()
            .filter(staff_id=profile.id, training_id=training.id, fy=fy)
            .first()
        )
        previous = row.ceiling if row else None
        if row is None:
            row = TrainingCeiling(staff_id=profile.id, training_id=training.id, fy=fy)
        row.ceiling = value
        row.set_by = _actor(principal)
        row.set_by_role = _role(principal)
        row.note = (note or "").strip()[:512]
        row.save()
        audit_log(
            action="training_ceiling.set",
            subject_kind="TrainingCeiling",
            subject_id=row.id,
            actor_id=str(getattr(principal, "id", "") or ""),
            actor_role=_role(principal),
            payload={
                "staffId": profile.id,
                "staffName": profile.user.name,
                "trainingId": training.id,
                "training": training.display_name,
                "fy": fy,
                "from": previous,
                "to": value,
                "note": row.note,
            },
        )
    return row


def remove_ceiling(principal, ceiling_id: str) -> dict:
    """Take a ceiling away: the officer then schedules that training without
    a limit, as before one was set. What is scheduled is untouched."""
    from django.db import transaction

    from apps.audit.services import log as audit_log
    from apps.planning.training_ceiling_models import TrainingCeiling

    with transaction.atomic():
        row = (
            TrainingCeiling.objects.select_for_update()
            .select_related("training", "staff__user")
            .filter(id=ceiling_id or "")
            .first()
        )
        if row is None:
            raise NotFoundError("That training ceiling was not found.")
        if not may_set_ceiling(principal, row.staff_id):
            raise Forbidden(
                "A Programme Lead sets their own training ceiling and those "
                "of the officers they supervise."
            )
        detail = {
            "staffId": row.staff_id,
            "staffName": row.staff.user.name,
            "trainingId": row.training_id,
            "training": row.training.display_name,
            "fy": row.fy,
            "from": row.ceiling,
            "to": None,
        }
        row_id = row.id
        row.delete()
        audit_log(
            action="training_ceiling.removed",
            subject_kind="TrainingCeiling",
            subject_id=row_id,
            actor_id=str(getattr(principal, "id", "") or ""),
            actor_role=_role(principal),
            payload=detail,
        )
    return detail


# ── The country's ceiling ───────────────────────────────────────────────────
#: Who sets the Country Ceiling (owner, 2026-10-06: "The admin IA will set
#: the Country Ceiling and Leads will set each staff ceiling").
COUNTRY_CEILING_ROLES = frozenset(
    {EdifyRole.ADMIN.value, EdifyRole.IMPACT_ASSESSMENT.value}
)


def may_set_country_ceiling(principal) -> bool:
    """Admin and Impact Assessment set the Country Ceiling. Nobody else does:
    a Programme Lead sets their officers' ceilings, and the Country Director
    reads."""
    return _role(principal) in COUNTRY_CEILING_ROLES


def country_of(principal) -> str:
    """The country a reader's figures are for: their own profile's, else the
    platform's."""
    from apps.planning.fy_policy import default_country

    profile = getattr(principal, "staff_profile", None)
    return (getattr(profile, "country", "") or "").strip() or default_country()


def _country_identities(country: str) -> list[str]:
    """Every id a plan may name its owner by, for the staff of a country —
    whoever they are and whether or not they are still in post, because what
    they planned is still the country's."""
    from apps.accounts.models import StaffProfile

    staff = StaffProfile.objects.all()
    if country:
        staff = staff.filter(Q(country=country) | Q(country=""))
    identities: set[str] = set()
    for profile_id, user_id in staff.values_list("id", "user_id"):
        identities.add(profile_id)
        if user_id:
            identities.add(user_id)
    return sorted(identities)


def country_scheduled(fy: str, country: str) -> dict[str, dict]:
    """``{training id: {"group", "in_school", "partner", "partner_scheduled",
    "awaiting_partner", "total"}}``: every school the country has committed
    to each training in the year — the schools invited to a group training or
    to a cluster meeting that is a training, the schools staff have planned
    an in-school training at (owner, 2026-10-06: "Each training will fetch
    the schools inivited to attend or planned in-schools"), and the schools
    assigned to a Partner for it, dated by the Partner or not (owner,
    2026-10-08). ``total`` is the schools, each once. Only trainings with
    something committed are in it."""
    owners = _country_identities(country)
    fy = str(fy)
    schools: dict[str, dict] = {}

    def row_of(course):
        return schools.setdefault(
            course,
            {GROUP: set(), IN_SCHOOL: set(), PARTNER: set(), PARTNER_SCHEDULED: set()},
        )

    for kind, rows in (
        (GROUP, _group_rows(owner_ids=owners, fy=fy)),
        (IN_SCHOOL, _in_school_rows(owner_ids=owners, fy=fy)),
        (PARTNER, _handover_rows(owner_ids=owners, fy=fy)),
    ):
        for course, school_id in rows.values_list("course", "school_id").distinct():
            row_of(course)[kind].add(school_id)
    for course, school_id, dated in (
        _partner_rows(owner_ids=owners, fy=fy)
        .values_list("course", "school_id", "dated")
        .distinct()
    ):
        row_of(course)[PARTNER].add(school_id)
        if dated:
            row_of(course)[PARTNER_SCHEDULED].add(school_id)
    # A school is one school for the country, whoever planned it, however it
    # is delivered and on however many sessions.
    return {
        course: {
            "group": len(row[GROUP]),
            "in_school": len(row[IN_SCHOOL]),
            "partner": len(row[PARTNER]),
            "partner_scheduled": len(row[PARTNER_SCHEDULED]),
            "awaiting_partner": len(row[PARTNER] - row[PARTNER_SCHEDULED]),
            "total": len(covered(row)),
        }
        for course, row in schools.items()
    }


def country_ceilings(fy: str, country: str) -> dict[str, dict]:
    """``{training id: {"id", "ceiling"}}`` for the country and year."""
    from apps.planning.training_ceiling_models import TrainingCountryCeiling

    return {
        row["training_id"]: row
        for row in TrainingCountryCeiling.objects.filter(
            fy=str(fy), country=country
        ).values("id", "training_id", "ceiling")
    }


def country_capacity(training_id: str, fy: str, country: str) -> dict:
    """What the Country Ceiling drawer shows for one training: the ceiling
    now, what is planned under it and what is left."""
    ceiling = (country_ceilings(fy, country).get(training_id) or {}).get("ceiling")
    planned = country_scheduled(fy, country).get(
        training_id,
        {
            "group": 0,
            "in_school": 0,
            "partner": 0,
            "partner_scheduled": 0,
            "awaiting_partner": 0,
            "total": 0,
        },
    )
    return {
        "ceiling": ceiling,
        "planned": planned["total"],
        "group": planned["group"],
        "inSchool": planned["in_school"],
        "partner": planned["partner"],
        "partnerScheduled": planned["partner_scheduled"],
        "awaitingPartner": planned["awaiting_partner"],
        "remaining": None if ceiling is None else max(ceiling - planned["total"], 0),
        "over": 0 if ceiling is None else max(planned["total"] - ceiling, 0),
        "fy": str(fy),
        "country": country,
    }


def _country_ceiling_refusal() -> Forbidden:
    return Forbidden("Admin and Impact Assessment set the Country Ceiling.")


def set_country_ceiling(
    principal, *, training_id: str, fy: str, ceiling, country: str = "", note: str = ""
):
    """Set or change the country's ceiling for one training in one year.

    It may be set below what is already planned: the summary then shows
    nothing remaining and the planned figure above it. It is the country's
    number to read plans against; an officer's own ceiling, set by their
    Programme Lead, is what holds a schedule back (``reserve``).
    """
    from django.db import transaction

    from apps.activity_catalogue.services import effective_items
    from apps.audit.services import log as audit_log
    from apps.planning.training_ceiling_models import TrainingCountryCeiling

    if not may_set_country_ceiling(principal):
        raise _country_ceiling_refusal()
    training = (
        effective_items().filter(is_training_course=True, id=training_id or "").first()
    )
    if training is None:
        raise BadRequest("Choose an active training from the Training Catalogue.")
    _assert_not_a_projects(training)
    fy = _clean_fy(fy)
    value = _clean_ceiling(ceiling, most=100000, noun="Country Ceiling")
    country = (country or "").strip() or country_of(principal)
    with transaction.atomic():
        row = (
            TrainingCountryCeiling.objects.select_for_update()
            .filter(training_id=training.id, fy=fy, country=country)
            .first()
        )
        previous = row.ceiling if row else None
        if row is None:
            row = TrainingCountryCeiling(
                training_id=training.id, fy=fy, country=country
            )
        row.ceiling = value
        row.set_by = _actor(principal)
        row.set_by_role = _role(principal)
        row.note = (note or "").strip()[:512]
        row.save()
        audit_log(
            action="training_country_ceiling.set",
            subject_kind="TrainingCountryCeiling",
            subject_id=row.id,
            actor_id=str(getattr(principal, "id", "") or ""),
            actor_role=_role(principal),
            payload={
                "trainingId": training.id,
                "training": training.display_name,
                "country": country,
                "fy": fy,
                "from": previous,
                "to": value,
                "note": row.note,
            },
        )
    return row


def remove_country_ceiling(principal, ceiling_id: str) -> dict:
    """Take the Country Ceiling away. What is planned is untouched."""
    from django.db import transaction

    from apps.audit.services import log as audit_log
    from apps.planning.training_ceiling_models import TrainingCountryCeiling

    if not may_set_country_ceiling(principal):
        raise _country_ceiling_refusal()
    with transaction.atomic():
        row = (
            TrainingCountryCeiling.objects.select_for_update()
            .select_related("training")
            .filter(id=ceiling_id or "")
            .first()
        )
        if row is None:
            raise NotFoundError("That Country Ceiling was not found.")
        detail = {
            "trainingId": row.training_id,
            "training": row.training.display_name,
            "country": row.country,
            "fy": row.fy,
            "from": row.ceiling,
            "to": None,
        }
        row_id = row.id
        row.delete()
        audit_log(
            action="training_country_ceiling.removed",
            subject_kind="TrainingCountryCeiling",
            subject_id=row_id,
            actor_id=str(getattr(principal, "id", "") or ""),
            actor_role=_role(principal),
            payload=detail,
        )
    return detail


# ── The schools behind a figure ─────────────────────────────────────────────
def schools_behind(
    principal,
    *,
    staff_id: str,
    training_id: str = "",
    fy: str,
    delivery: str = "",
    figure: str = "",
) -> dict:
    """The schools one summary figure counts, one row per school and session
    (``apps.planning.training_coverage.schools_behind``, where each row says
    how the school is covered, who is responsible and what it waits on)."""
    from apps.planning import training_coverage

    return training_coverage.schools_behind(
        principal,
        staff_id=staff_id,
        training_id=training_id,
        fy=fy,
        delivery=delivery,
        figure=figure,
    )
