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

A Programme Lead sets the ceiling for each officer they supervise, per
training and fiscal year (``TrainingCeiling``). Nothing else is stored: what
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

"Allocated" is not a word here. It keeps its meaning — a school assigned to a
partner or to a project — and training uses Scheduled, Ceiling, Balance and
Excess.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Case, CharField, Count, F, Q, When
from django.db.models.functions import Coalesce

from apps.core.activity_types import CLUSTER_MEETING_TYPES, TRAINING_TYPES
from apps.core.enums import MeetingKind
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

__all__ = [
    "DELIVERY_LABELS",
    "MODE_OF_DELIVERY",
    "GROUP",
    "IN_SCHOOL",
    "SummaryRow",
    "flag_counts",
    "summary_totals",
    "summary_sections",
    "course_name_of",
    "mode_of_delivery",
    "capacity",
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
#: The same two, as My Plan's Mode of Delivery column says them (owner,
#: 2026-10-06: "Cluster Group training or In-School training").
MODE_OF_DELIVERY = {GROUP: "Cluster Group Training", IN_SCHOOL: "In-School Training"}

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


def course_name_of(activity) -> str:
    """The training's name as the Training Catalogue gives it — Literacy,
    TAM, Leadership — read from the rows `course_id_of` reads, so a page
    that has them in memory pays no query; blank for a training nobody has
    named yet and for anything that is not a training.

    A training delivered at a cluster meeting keeps its course's name in
    the meeting's recommendation_source when the course itself was not
    linked, so that is the last place looked."""
    if not is_training(activity):
        return ""
    if activity.training_course_id:
        return activity.training_course.display_name or ""
    item = activity.catalogue_item
    if item is not None and item.is_training_course:
        return item.display_name or ""
    if activity.meeting_kind == MeetingKind.TRAINING:
        return (activity.recommendation_source or {}).get(
            "trainingCourseName", ""
        ) or ""
    return ""


def mode_of_delivery(activity) -> str:
    """ "Cluster Group Training" or "In-School Training"; blank for anything
    that is not a training (`delivery_of`)."""
    return MODE_OF_DELIVERY.get(delivery_of(activity), "")


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


def under_ceiling(activity) -> bool:
    """Whether this plan's schools count under a training ceiling: a group or
    in-school training that belongs to no project."""
    return delivery_of(activity) is not None and not activity.project_id


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


def _in_school_rows(*, owner_ids, fy, course_id=None, exclude_activity_id=None):
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
    if owner_ids is not None:
        rows = rows.filter(responsible_staff_id__in=list(owner_ids))
    if course_id:
        rows = rows.filter(course=course_id)
    if exclude_activity_id:
        rows = rows.exclude(id=exclude_activity_id)
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


def scheduled_count(
    profile, course_id: str, fy: str, *, exclude_activity_id: str | None = None
) -> dict:
    """Schools this staff member has scheduled for one training in one year,
    by delivery. Two counts, read from the persisted plans."""
    ids = _owner_ids(profile)
    kwargs = dict(
        owner_ids=ids,
        fy=str(fy),
        course_id=course_id,
        exclude_activity_id=exclude_activity_id,
    )
    group = _group_rows(**kwargs).count()
    in_school = _in_school_rows(**kwargs).count()
    return {GROUP: group, IN_SCHOOL: in_school, "total": group + in_school}


# ── The ceiling, held ───────────────────────────────────────────────────────
def _refusal(training_name, staff_name, ceiling, scheduled, requested, fy) -> str:
    """What the planner is told when a save would pass the ceiling (owner,
    2026-10-06: "tells the users that they have hit the ceiling and cannot
    add anymore schools")."""
    left = max(ceiling - scheduled, 0)
    head = (
        f"Training ceiling reached. {staff_name} may schedule {ceiling} "
        f"school{'s' if ceiling != 1 else ''} for {training_name} in FY {fy}, "
        f"and {scheduled} {'is' if scheduled == 1 else 'are'} already scheduled"
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
    requested: int,
    current: int = 0,
    exclude_activity_id: str | None = None,
) -> None:
    """Hold the ceiling for one write. Call inside the write's transaction.

    ``requested`` is how many schools the plan being written will hold once
    saved, ``current`` how many it holds now (0 for a new plan), and
    ``exclude_activity_id`` that plan, so its own schools are never counted
    twice. The ceiling row is locked before anything is counted, which is
    what serialises two people taking the last places.

    A write that does not grow the plan is never refused: with a ceiling
    lowered below what is scheduled, an officer can still untick a school or
    swap one for another.
    """
    from apps.planning.training_ceiling_models import TrainingCeiling

    if not staff_id or not course_id or requested <= current:
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
    if row is None:
        return
    elsewhere = scheduled_count(
        profile, course_id, fy, exclude_activity_id=exclude_activity_id
    )["total"]
    if elsewhere + requested > row.ceiling:
        raise BadRequest(
            _refusal(
                row.training.display_name,
                profile.user.name or "This staff member",
                row.ceiling,
                elsewhere + current,
                requested - current,
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
    reserve(staff_id=staff_id, course_id=course_id, fy=fy, requested=1)


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
    if TrainingCeiling.objects.filter(
        staff_id=profile.id, training_id=course_id, fy=str(fy)
    ).exists():
        raise BadRequest(
            "Tick the schools this training is for. A training ceiling is set "
            "for it, and a training with no school named cannot be counted "
            "under the ceiling."
        )


def reserve_for_session(activity, *, invited_after: int, invited_now: int) -> None:
    """A group delivery's invitation list is about to change."""
    if delivery_of(activity) != GROUP or activity.project_id:
        return
    reserve(
        staff_id=activity.responsible_staff_id,
        course_id=course_id_of(activity),
        fy=activity.fy,
        requested=invited_after,
        current=invited_now,
        exclude_activity_id=activity.id,
    )


def schools_held(activity) -> int:
    """How many places a persisted training holds under its ceiling."""
    if activity.project_id:
        return 0
    delivery = delivery_of(activity)
    if delivery == IN_SCHOOL:
        return 1
    if delivery == GROUP:
        from apps.activities.models import ClusterActivityAttendance

        return (
            ClusterActivityAttendance.objects.filter(activity=activity)
            .filter(Q(invited=True) | Q(attended=True))
            .count()
        )
    return 0


def reserve_for_move(activity, *, staff_id=None, fy=None) -> None:
    """A persisted training is moving to another year or another officer:
    its schools must fit under the ceiling it lands under."""
    new_staff = staff_id or activity.responsible_staff_id
    new_fy = str(fy or activity.fy)
    old = _profile(activity.responsible_staff_id)
    new = _profile(new_staff)
    same_staff = (old.id if old else None) == (new.id if new else None)
    if same_staff and new_fy == str(activity.fy):
        return
    if activity.status in RELEASED_STATUSES:
        return
    held = schools_held(activity)
    if not held:
        return
    reserve(
        staff_id=new_staff,
        course_id=course_id_of(activity),
        fy=new_fy,
        requested=held,
        exclude_activity_id=activity.id,
    )


def capacity(
    staff_id: str | None,
    course_id: str | None,
    fy: str,
    *,
    exclude_activity_id: str | None = None,
) -> dict:
    """What a drawer shows before a save: the ceiling, what is scheduled
    under it apart from the plan being edited, and what is left."""
    from apps.planning.training_ceiling_models import TrainingCeiling

    blank = {
        "managed": False,
        "ceiling": None,
        "scheduled": 0,
        "group": 0,
        "inSchool": 0,
        "remaining": None,
        "staffName": "",
        "fy": str(fy),
    }
    profile = _profile(staff_id) if staff_id and course_id else None
    if profile is None:
        return blank
    counts = scheduled_count(
        profile, course_id, fy, exclude_activity_id=exclude_activity_id
    )
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
        "scheduled": counts["total"],
        "group": counts[GROUP],
        "inSchool": counts[IN_SCHOOL],
        "remaining": None if ceiling is None else max(ceiling - counts["total"], 0),
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
    group: int
    in_school: int

    @property
    def total(self) -> int:
        return self.group + self.in_school

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
    group: dict[tuple, int] = {}
    for row in (
        _group_rows(owner_ids=by_identity, fy=fy)
        .values("activity__responsible_staff_id", "course")
        .annotate(n=Count("id"))
    ):
        key = (by_identity[row["activity__responsible_staff_id"]], row["course"])
        group[key] = group.get(key, 0) + row["n"]
    in_school: dict[tuple, int] = {}
    for row in (
        _in_school_rows(owner_ids=by_identity, fy=fy)
        .values("responsible_staff_id", "course")
        .annotate(n=Count("id"))
    ):
        key = (by_identity[row["responsible_staff_id"]], row["course"])
        in_school[key] = in_school.get(key, 0) + row["n"]

    keys = set(ceilings) | set(group) | set(in_school)
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
            group=group.get((staff_id, training_id), 0),
            in_school=in_school.get((staff_id, training_id), 0),
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
    """A Programme Lead sets the ceilings of the officers they supervise."""
    if _role(principal) != EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return False
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
    """The officers a Programme Lead may set a ceiling for."""
    if _role(principal) != EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return []
    return sorted(_supervised(principal), key=lambda p: (p.user.name or "").casefold())


def training_options() -> list[dict]:
    """Every active training in the Training Catalogue, with the SSA
    intervention it is fixed to."""
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
        .order_by("display_name", "stable_code")
        .values_list("id", "display_name")
    ]


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
    """Set or change one officer's ceiling for one training in one year.

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
            "A Programme Lead sets the training ceilings of the officers "
            "they supervise."
        )
    training = (
        effective_items().filter(is_training_course=True, id=training_id or "").first()
    )
    if training is None:
        raise BadRequest("Choose an active training from the Training Catalogue.")
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
                "A Programme Lead sets the training ceilings of the officers "
                "they supervise."
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
    """``{training id: {"group", "in_school", "total"}}``: every school the
    country's staff have planned for each training in the year — the schools
    invited to a group training or to a cluster meeting that is a training,
    and the schools of in-school trainings (owner, 2026-10-06: "Each training
    will fetch the schools inivited to attend or planned in-schools"). Only
    trainings with something planned are in it."""
    owners = _country_identities(country)
    planned: dict[str, dict] = {}

    def add(course, kind, n):
        row = planned.setdefault(course, {"group": 0, "in_school": 0, "total": 0})
        row[kind] += n
        row["total"] += n

    for row in (
        _group_rows(owner_ids=owners, fy=str(fy))
        .values("course")
        .annotate(n=Count("id"))
    ):
        add(row["course"], "group", row["n"])
    for row in (
        _in_school_rows(owner_ids=owners, fy=str(fy))
        .values("course")
        .annotate(n=Count("id"))
    ):
        add(row["course"], "in_school", row["n"])
    return planned


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
        training_id, {"group": 0, "in_school": 0, "total": 0}
    )
    return {
        "ceiling": ceiling,
        "planned": planned["total"],
        "group": planned["group"],
        "inSchool": planned["in_school"],
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
    principal, *, staff_id: str, training_id: str, fy: str, delivery: str = ""
) -> dict:
    """The schools one summary figure counts, one row per school and session.

    Refuses a staff member the reader may not see rather than listing
    nothing, so an edited link cannot read another officer's schools.
    """
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.core.enums import ActivityStatus

    profile = _profile(staff_id)
    if profile is None or not may_view_staff(principal, profile.id):
        raise Forbidden("That training summary is not yours to open.")
    training = ActivityCatalogueItem.objects.filter(id=training_id or "").first()
    if training is None:
        raise NotFoundError("That training was not found.")
    fy = str(fy or "")
    delivery = delivery if delivery in DELIVERY_LABELS else ""
    ids = _owner_ids(profile)
    status_labels = dict(ActivityStatus.choices)
    rows = []
    if delivery in ("", GROUP):
        for row in _group_rows(owner_ids=ids, fy=fy, course_id=training.id).values(
            "school_id",
            "school__name",
            "school__school_id",
            "activity_id",
            "activity__cluster__name",
            "activity__planned_date",
            "activity__status",
            "activity__activity_type",
        ):
            rows.append(
                {
                    "school_pk": row["school_id"],
                    "school_name": row["school__name"],
                    "school_code": row["school__school_id"] or "",
                    "delivery": DELIVERY_LABELS[GROUP],
                    "delivery_key": GROUP,
                    "is_meeting": row["activity__activity_type"] in _MEETING_TYPES,
                    "cluster": row["activity__cluster__name"] or "",
                    "date": row["activity__planned_date"],
                    "status": status_labels.get(
                        row["activity__status"], row["activity__status"]
                    ),
                    "activity_id": row["activity_id"],
                }
            )
    if delivery in ("", IN_SCHOOL):
        for row in _in_school_rows(owner_ids=ids, fy=fy, course_id=training.id).values(
            "id",
            "school_id",
            "school__name",
            "school__school_id",
            "planned_date",
            "status",
        ):
            rows.append(
                {
                    "school_pk": row["school_id"],
                    "school_name": row["school__name"],
                    "school_code": row["school__school_id"] or "",
                    "delivery": DELIVERY_LABELS[IN_SCHOOL],
                    "delivery_key": IN_SCHOOL,
                    "is_meeting": False,
                    "cluster": "",
                    "date": row["planned_date"],
                    "status": status_labels.get(row["status"], row["status"]),
                    "activity_id": row["id"],
                }
            )
    rows.sort(
        key=lambda r: (
            (r["school_name"] or "").casefold(),
            str(r["date"] or ""),
            r["activity_id"],
        )
    )
    summary = next(
        (
            row
            for row in summary_for_staff([profile], fy)
            if row.training_id == training.id
        ),
        None,
    )
    return {
        "staff_name": profile.user.name or profile.user.email,
        "training_name": training.display_name,
        "fy": fy,
        "delivery": delivery,
        "delivery_label": DELIVERY_LABELS.get(delivery, ""),
        "rows": rows,
        "summary": summary,
    }
