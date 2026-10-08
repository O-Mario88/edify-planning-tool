"""Training Coverage — every school committed to a training, in one picture.

Owner, 2026-10-08: "The partner has 10 schools assigned, but because they
haven't scheduled them yet, the Training Summary thinks there are only 5."
A school handed to a Partner for a training was on no training table until the
Partner dated it, and on none of the officer's afterwards: the summary read
only the trainings filed under the officer as the person delivering them.

Nothing is stored here. The picture is assembled, each time it is asked for,
from the records that already hold each state, and from no other:

    Training Catalogue   which training          ActivityCatalogueItem
    Training Ceiling     how many schools        TrainingCeiling,
                                                 TrainingCountryCeiling
    In-school, staff     planned by staff        Activity (a training at a
                                                 school, staff-delivered)
    In-school, Partner   assigned to a Partner   PartnerAssignment, not yet
                                                 scheduled (the hand-over)
                         scheduled by the        Activity (the training the
                         Partner                 hand-over became)
    Group training       schools on the session  ClusterActivityAttendance
                                                 (invited by name)
    Delivery             started, evidence,      Activity.status, the one
                         IA, completed           workflow every page reads

A hand-over and the activity it becomes are one commitment at two moments
(``PartnerAssignment.scheduled_activity``): *Assigned → Scheduled* moves a
school along, it never adds one. So **Partner Assigned** is every school with
a Partner for the training, **Partner Scheduled** those of them the Partner
has dated, and **Awaiting Partner Scheduling** the difference — the schools
staff follow up with the Partner.

Each school and training resolves to one status and the next action it waits
on (``Commitment``), and every figure on a training table is a count of these
rows, so a number and the list behind it cannot disagree. The counting itself
— which rows, whose they are, a school once per training — is
``apps.planning.training_ceilings``, the same sums the ceiling is held by.

A school on two sessions of one training is two rows here and one school in
every figure (owner, 2026-10-08: a ceiling counts each school once). The rows
stay apart because a second session can be legitimate; the figure does not
double because a ceiling is a number of schools.

A project's training is the project's and is not read here: its schools are
the schools added to the project (``apps.planning.training_summary``).
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.activity_types import (
    COMPLETED_WORK_STATUSES,
    UNDER_WAY_ACTIVITY_STATUSES,
)
from apps.core.exceptions import Forbidden, NotFoundError
from apps.planning import training_ceilings

__all__ = [
    "Commitment",
    "FIGURES",
    "FIGURE_LABELS",
    "GROUP",
    "PARTNER",
    "STAFF",
    "SHOW_OPTIONS",
    "STATUS_LABELS",
    "STATUS_ORDER",
    "commitments",
    "progress",
    "schools_behind",
    "table",
    "trainings_committed",
    "uncovered",
]

# ── Who delivers, and how ───────────────────────────────────────────────────
STAFF = "staff"
PARTNER = "partner"
GROUP = "group"
ROUTE_LABELS = {
    STAFF: "In-School · Staff",
    PARTNER: "In-School · Partner",
    GROUP: "Group Training",
}

# ── Where a school stands for a training ────────────────────────────────────
NOT_COVERED = "not_covered"
STAFF_PLANNED = "staff_planned"
PARTNER_ASSIGNED = "partner_assigned"
PARTNER_SCHEDULED = "partner_scheduled"
GROUP_SCHEDULED = "group_scheduled"
IN_PROGRESS = "in_progress"
COMPLETED = "completed"

STATUS_LABELS = {
    NOT_COVERED: "Not Covered",
    STAFF_PLANNED: "Staff Planned",
    PARTNER_ASSIGNED: "Partner Assigned — Awaiting Schedule",
    PARTNER_SCHEDULED: "Partner Scheduled",
    GROUP_SCHEDULED: "Group Scheduled",
    IN_PROGRESS: "In Progress",
    COMPLETED: "Completed",
}
#: The order a filter offers them in: the life of a commitment.
STATUS_ORDER = (
    NOT_COVERED,
    STAFF_PLANNED,
    PARTNER_ASSIGNED,
    PARTNER_SCHEDULED,
    GROUP_SCHEDULED,
    IN_PROGRESS,
    COMPLETED,
)
STATUS_TONES = {
    NOT_COVERED: "danger",
    STAFF_PLANNED: "info",
    PARTNER_ASSIGNED: "warning",
    PARTNER_SCHEDULED: "info",
    GROUP_SCHEDULED: "info",
    IN_PROGRESS: "info",
    COMPLETED: "success",
}

# ── The figures a training table shows, each a list of schools ──────────────
FIGURE_COVERED = "covered"
FIGURE_STAFF = "staff"
FIGURE_PARTNER = "partner"
FIGURE_PARTNER_SCHEDULED = "partner_scheduled"
FIGURE_AWAITING = "awaiting"
FIGURE_GROUP = "group"
FIGURE_REMAINING = "remaining"
FIGURE_LABELS = {
    FIGURE_COVERED: "Schools covered",
    FIGURE_STAFF: "Staff planned",
    FIGURE_PARTNER: "Partner assigned",
    FIGURE_PARTNER_SCHEDULED: "Partner scheduled",
    FIGURE_AWAITING: "Awaiting partner scheduling",
    FIGURE_GROUP: "Group scheduled",
    FIGURE_REMAINING: "Schools not yet covered",
}
FIGURES = tuple(FIGURE_LABELS)
#: The two deliveries a summary link used to name, as the figures they are.
_DELIVERY_FIGURES = {
    training_ceilings.GROUP: (GROUP,),
    training_ceilings.IN_SCHOOL: (STAFF, PARTNER),
}


@dataclass
class Commitment:
    """One school committed to one training, or — ``NOT_COVERED`` — a school
    that takes the training and has no commitment yet."""

    school_pk: str
    school_name: str
    school_code: str
    school_type: str
    training_id: str
    training_name: str
    staff_id: str
    staff_name: str
    route: str  # STAFF | PARTNER | GROUP | "" (not covered)
    status: str
    #: Who acts next: the officer, or the Partner's name.
    responsible: str = ""
    partner_name: str = ""
    cluster: str = ""
    date: object = None
    activity_id: str = ""
    assignment_id: str = ""
    is_meeting: bool = False
    #: Partner work the Partner has put on a day of its own.
    dated: bool = False
    #: The same school on a row above: listed, not counted again.
    repeat: bool = False

    @property
    def route_label(self) -> str:
        return ROUTE_LABELS.get(self.route, "—")

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]

    @property
    def tone(self) -> str:
        return STATUS_TONES[self.status]

    @property
    def scheduled(self) -> bool:
        """On a day: planned by staff, on a group session, or dated by the
        Partner. A hand-over the Partner has not dated is not."""
        return self.status not in (NOT_COVERED, PARTNER_ASSIGNED)

    @property
    def next_action(self) -> str:
        """Who owns the next step, in a word or two."""
        if self.status == NOT_COVERED:
            return "Plan"
        if self.status == PARTNER_ASSIGNED:
            return "Partner to schedule"
        if self.status == COMPLETED:
            return "None"
        if self.route == PARTNER:
            return (
                "Partner to complete"
                if self.status == IN_PROGRESS
                else "Partner to conduct"
            )
        return "Complete and submit" if self.status == IN_PROGRESS else "Conduct"

    @property
    def href(self) -> str:
        """The record this row is read from."""
        if self.activity_id:
            return f"/my-plan/{self.activity_id}"
        if self.assignment_id:
            return "/partner-oversight/"
        return f"/schools/{self.school_pk}"

    # The drawer's older template keys, kept so a saved link still renders.
    @property
    def delivery(self) -> str:
        return self.route_label

    @property
    def delivery_key(self) -> str:
        return GROUP if self.route == GROUP else training_ceilings.IN_SCHOOL


def _status_of(route: str, activity_status: str, *, dated: bool = True) -> str:
    if activity_status in COMPLETED_WORK_STATUSES:
        return COMPLETED
    if activity_status in UNDER_WAY_ACTIVITY_STATUSES:
        return IN_PROGRESS
    if route == GROUP:
        return GROUP_SCHEDULED
    if route == PARTNER:
        return PARTNER_SCHEDULED if dated else PARTNER_ASSIGNED
    return STAFF_PLANNED


def _names(model, ids, field: str = "name") -> dict:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(model.objects.filter(id__in=ids).values_list("id", field))


def _by_identity(profiles) -> tuple[dict, dict]:
    """``{identity: profile id}`` and ``{profile id: name}``: a record names
    its officer by staff profile or by account."""
    by_identity, names = {}, {}
    for profile in profiles:
        if profile is None:
            continue
        names[profile.id] = profile.user.name or profile.user.email
        for identity in training_ceilings._owner_ids(profile):
            by_identity[identity] = profile.id
    return by_identity, names


def commitments(profiles, fy: str, *, training_id: str | None = None) -> list:
    """Every school these staff members have committed to a training in the
    year, one row per school and session, in four queries: group sessions,
    in-school trainings staff planned, trainings a Partner has taken on as an
    activity, and hand-overs still waiting for the Partner's date."""
    from apps.activity_catalogue.models import ActivityCatalogueItem
    from apps.partners.models import Partner

    by_identity, staff_names = _by_identity(profiles)
    if not by_identity:
        return []
    fy = str(fy)
    kwargs = dict(owner_ids=list(by_identity), fy=fy, course_id=training_id or None)
    meeting_types = training_ceilings._MEETING_TYPES
    rows: list[Commitment] = []
    partner_ids: set = set()

    def add(owner, **fields):
        staff_id = by_identity.get(owner)
        if staff_id is None:
            return
        rows.append(
            Commitment(
                staff_id=staff_id,
                staff_name=staff_names[staff_id],
                training_name="",
                **fields,
            )
        )

    for row in training_ceilings._group_rows(**kwargs).values(
        "school_id",
        "school__name",
        "school__school_id",
        "school__school_type",
        "course",
        "activity_id",
        "activity__responsible_staff_id",
        "activity__cluster__name",
        "activity__planned_date",
        "activity__status",
        "activity__activity_type",
    ):
        owner = row["activity__responsible_staff_id"]
        add(
            owner,
            school_pk=row["school_id"],
            school_name=row["school__name"],
            school_code=row["school__school_id"] or "",
            school_type=row["school__school_type"] or "",
            training_id=row["course"],
            route=GROUP,
            status=_status_of(GROUP, row["activity__status"]),
            responsible=staff_names.get(by_identity.get(owner), ""),
            cluster=row["activity__cluster__name"] or "",
            date=row["activity__planned_date"],
            activity_id=row["activity_id"],
            is_meeting=row["activity__activity_type"] in meeting_types,
            dated=True,
        )
    for row in training_ceilings._in_school_rows(**kwargs).values(
        "id",
        "school_id",
        "school__name",
        "school__school_id",
        "school__school_type",
        "course",
        "responsible_staff_id",
        "planned_date",
        "status",
    ):
        owner = row["responsible_staff_id"]
        add(
            owner,
            school_pk=row["school_id"],
            school_name=row["school__name"],
            school_code=row["school__school_id"] or "",
            school_type=row["school__school_type"] or "",
            training_id=row["course"],
            route=STAFF,
            status=_status_of(STAFF, row["status"]),
            responsible=staff_names.get(by_identity.get(owner), ""),
            date=row["planned_date"],
            activity_id=row["id"],
            dated=True,
        )
    for row in training_ceilings._partner_rows(**kwargs).values(
        "id",
        "school_id",
        "school__name",
        "school__school_id",
        "school__school_type",
        "course",
        "owner",
        "dated",
        "assigned_partner_id",
        "planned_date",
        "status",
    ):
        partner_ids.add(row["assigned_partner_id"])
        add(
            row["owner"],
            school_pk=row["school_id"],
            school_name=row["school__name"],
            school_code=row["school__school_id"] or "",
            school_type=row["school__school_type"] or "",
            training_id=row["course"],
            route=PARTNER,
            status=_status_of(PARTNER, row["status"], dated=bool(row["dated"])),
            partner_name=row["assigned_partner_id"] or "",
            date=row["planned_date"] if row["dated"] else None,
            activity_id=row["id"],
            dated=bool(row["dated"]),
        )
    for row in training_ceilings._handover_rows(
        owner_ids=list(by_identity), fy=fy, course_id=training_id or None
    ).values(
        "id",
        "school_id",
        "school__name",
        "school__school_id",
        "school__school_type",
        "course",
        "owner",
        "partner_id",
    ):
        partner_ids.add(row["partner_id"])
        add(
            row["owner"],
            school_pk=row["school_id"],
            school_name=row["school__name"],
            school_code=row["school__school_id"] or "",
            school_type=row["school__school_type"] or "",
            training_id=row["course"],
            route=PARTNER,
            status=PARTNER_ASSIGNED,
            partner_name=row["partner_id"] or "",
            assignment_id=row["id"],
        )

    partners = dict(
        Partner.all_objects.filter(id__in={p for p in partner_ids if p}).values_list(
            "id", "name"
        )
    )
    trainings = _names(
        ActivityCatalogueItem, {row.training_id for row in rows}, "display_name"
    )
    for row in rows:
        row.training_name = trainings.get(row.training_id, "Training")
        if row.route == PARTNER:
            row.partner_name = partners.get(row.partner_name, "") or "Partner"
            row.responsible = row.partner_name
    return _in_order(rows)


def _in_order(rows: list) -> list:
    """By school, then training, then day; a school's second row for the same
    training and officer is marked as the same school."""
    rows.sort(
        key=lambda r: (
            (r.school_name or "").casefold(),
            r.training_name.casefold(),
            r.staff_name.casefold(),
            str(r.date or "9999"),
            r.activity_id or r.assignment_id,
        )
    )
    seen: set = set()
    for row in rows:
        key = (row.school_pk, row.training_id, row.staff_id)
        row.repeat = key in seen
        seen.add(key)
    return rows


def uncovered(profile, training, fy: str, *, covered_ids=None) -> list:
    """The schools this staff member holds that take a training and have no
    commitment to this one yet: operating schools of the types that are
    trained (Core, Client, Core Trained, Core Graduate), not a duplicate of
    another record. The answer to "which schools have not been planned?"."""
    from apps.planning.country_oversight import policy, rules
    from apps.schools.lifecycle_service import active_schools

    if covered_ids is None:
        covered_ids = training_ceilings.covered(
            training_ceilings.scheduled_schools(profile, training.id, fy)
        )
    name = profile.user.name or profile.user.email
    held = (
        active_schools()
        .filter(
            account_owner_id__in=training_ceilings._owner_ids(profile),
            school_type__in=rules.TRAINED_TYPES,
        )
        .exclude(duplicate_status__in=policy.EXCLUDED_DUPLICATE_STATUSES)
        .exclude(id__in=list(covered_ids))
        .order_by("name")
        .values("id", "name", "school_id", "school_type")
    )
    return [
        Commitment(
            school_pk=row["id"],
            school_name=row["name"],
            school_code=row["school_id"] or "",
            school_type=row["school_type"] or "",
            training_id=training.id,
            training_name=training.display_name,
            staff_id=profile.id,
            staff_name=name,
            route="",
            status=NOT_COVERED,
            responsible=name,
        )
        for row in held
    ]


def progress(rows) -> dict:
    """How far the commitments have moved, in schools, each once and at the
    furthest it has reached: on a day, started, completed."""
    scheduled, started, completed = set(), set(), set()
    for row in rows:
        key = (row.school_pk, row.training_id)
        if row.scheduled:
            scheduled.add(key)
        if row.status in (IN_PROGRESS, COMPLETED):
            started.add(key)
        if row.status == COMPLETED:
            completed.add(key)
    return {
        "scheduled": len(scheduled),
        "started": len(started),
        "completed": len(completed),
    }


def _of_figure(rows: list, figure: str) -> list:
    """The rows one figure counts. Awaiting is the schools with a Partner
    that the Partner has dated none of, as the figure is worked out: a school
    with one hand-over waiting and another dated is scheduled, not awaiting."""
    if figure in ("", FIGURE_COVERED):
        return rows
    if figure == FIGURE_STAFF:
        return [r for r in rows if r.route == STAFF]
    if figure == FIGURE_GROUP:
        return [r for r in rows if r.route == GROUP]
    partner = [r for r in rows if r.route == PARTNER]
    if figure == FIGURE_PARTNER:
        return partner
    dated = {(r.school_pk, r.training_id, r.staff_id) for r in partner if r.dated}
    if figure == FIGURE_PARTNER_SCHEDULED:
        return [r for r in partner if r.dated]
    if figure == FIGURE_AWAITING:
        return [
            r for r in partner if (r.school_pk, r.training_id, r.staff_id) not in dated
        ]
    return rows


def _remark(rows: list) -> list:
    """Mark repeats again after a filter: the first row left for a school is
    the one that counts."""
    seen: set = set()
    for row in rows:
        key = (row.school_pk, row.training_id, row.staff_id)
        row.repeat = key in seen
        seen.add(key)
    return rows


def schools_behind(
    principal,
    *,
    staff_id: str,
    training_id: str = "",
    fy: str,
    delivery: str = "",
    figure: str = "",
) -> dict:
    """The schools one figure of a staff member's training summary counts,
    one row per school and session.

    ``figure`` names it: every school covered, those staff planned, those
    assigned to a Partner, those the Partner has scheduled or has not, those
    on a group training, or the schools not yet covered. With no training
    named, every training the person has a school committed to.

    The figure is schools: a school on two sessions is two rows, the second
    marked ``repeat``, and ``school_count`` is the figure.

    Refuses a staff member the reader may not see rather than listing
    nothing, so an edited link cannot read another officer's schools.
    """
    from apps.activity_catalogue.models import ActivityCatalogueItem

    profile = training_ceilings._profile(staff_id)
    if profile is None or not training_ceilings.may_view_staff(principal, profile.id):
        raise Forbidden("That training summary is not yours to open.")
    training = None
    if training_id:
        training = ActivityCatalogueItem.objects.filter(id=training_id).first()
        if training is None:
            raise NotFoundError("That training was not found.")
    fy = str(fy or "")
    figure = figure if figure in FIGURES else ""
    delivery = delivery if delivery in _DELIVERY_FIGURES else ""

    every = commitments([profile], fy, training_id=training.id if training else None)
    if figure == FIGURE_REMAINING and training is not None:
        rows = uncovered(
            profile, training, fy, covered_ids={row.school_pk for row in every}
        )
    elif delivery and not figure:
        rows = [r for r in every if r.route in _DELIVERY_FIGURES[delivery]]
    else:
        rows = _of_figure(every, figure)
    rows = _remark(rows)

    summary = None
    if training is not None:
        summary = next(
            (
                row
                for row in training_ceilings.summary_for_staff([profile], fy)
                if row.training_id == training.id
            ),
            None,
        )
    label = FIGURE_LABELS.get(figure) or training_ceilings.DELIVERY_LABELS.get(
        delivery, ""
    )
    return {
        "staff_id": profile.id,
        "staff_name": profile.user.name or profile.user.email,
        "training_id": training.id if training else "",
        "training_name": training.display_name if training else "All trainings",
        "fy": fy,
        "delivery": delivery,
        "figure": figure,
        "delivery_label": label,
        "rows": rows,
        "school_count": len({(r.school_pk, r.training_id) for r in rows}),
        "summary": summary,
        "progress": progress(every),
        "show_training": training is None,
    }


#: What the coverage table can be narrowed to: a figure's schools, or the
#: schools at a stage of delivery whichever way they are covered.
SHOW_OPTIONS = (
    ("", "Every school"),
    (FIGURE_COVERED, "Covered"),
    (FIGURE_STAFF, "Staff planned"),
    (FIGURE_PARTNER, "Partner assigned"),
    (FIGURE_PARTNER_SCHEDULED, "Partner scheduled"),
    (FIGURE_AWAITING, "Awaiting partner scheduling"),
    (FIGURE_GROUP, "Group scheduled"),
    (IN_PROGRESS, "In progress"),
    (COMPLETED, "Completed"),
    (FIGURE_REMAINING, "Not yet covered"),
)
_SHOW_KEYS = frozenset(key for key, _label in SHOW_OPTIONS)


def table(
    profiles,
    fy: str,
    *,
    training_id: str = "",
    staff_id: str = "",
    show: str = "",
) -> dict:
    """The consolidated Training Coverage table for a set of staff: every
    school and training they have a commitment for, and — once one training
    is chosen — the schools they hold that are not covered for it yet.

    ``show`` narrows it to the schools one figure counts, or to those in
    progress or completed. Not Covered rows exist only against a training: a
    school is uncovered *for a training*.
    """
    from apps.activity_catalogue.models import ActivityCatalogueItem

    profiles = [p for p in profiles if p is not None]
    if staff_id:
        profiles = [p for p in profiles if p.id == staff_id]
    show = show if show in _SHOW_KEYS else ""
    training = None
    if training_id:
        training = ActivityCatalogueItem.objects.filter(id=training_id).first()
    rows = commitments(profiles, str(fy), training_id=training.id if training else None)
    # Schools at each status, before the table is narrowed.
    at: dict[str, set] = {}
    for row in rows:
        at.setdefault(row.status, set()).add((row.school_pk, row.training_id))
    covered_count = len({(row.school_pk, row.training_id) for row in rows})

    missing: list = []
    if training is not None and show in ("", FIGURE_REMAINING):
        covered_by: dict[str, set] = {}
        for row in rows:
            covered_by.setdefault(row.staff_id, set()).add(row.school_pk)
        for profile in profiles:
            missing.extend(
                uncovered(
                    profile,
                    training,
                    str(fy),
                    covered_ids=covered_by.get(profile.id, set()),
                )
            )
        at[NOT_COVERED] = {(row.school_pk, row.training_id) for row in missing}

    if show == FIGURE_REMAINING:
        rows = missing
    elif show in (IN_PROGRESS, COMPLETED):
        rows = [row for row in rows if row.status == show]
    elif show:
        rows = _of_figure(rows, show)
    else:
        rows = rows + missing
    rows = _in_order(rows)
    return {
        "rows": rows,
        "training": training,
        "show": show,
        "school_count": len({(r.school_pk, r.training_id) for r in rows}),
        "covered_count": covered_count,
        "counts": [
            {"key": key, "label": STATUS_LABELS[key], "count": len(at[key])}
            for key in STATUS_ORDER
            if at.get(key)
        ],
        "needs_training": show == FIGURE_REMAINING and training is None,
    }


def trainings_committed(profiles, fy: str) -> list[dict]:
    """The trainings these staff have a school committed to, for a filter."""
    seen: dict[str, str] = {}
    for row in training_ceilings.summary_for_staff(profiles, str(fy)):
        if row.total:
            seen.setdefault(row.training_id, row.training_name)
    return [
        {"id": training_id, "name": name}
        for training_id, name in sorted(seen.items(), key=lambda kv: kv[1].casefold())
    ]
