"""The Core package's 2 + 2 split — who delivers its visits and trainings.

Owner, 2026-09-30: a Core School's package is four visits and four trainings,
"2 each for staff and the other 2 for partners", and every door that puts
package work on a Core School keeps to it — the Core Schools drawers, the
Planning and cluster-school drawers, a Special Project, a partner hand-over,
the partner dating one, moving work between staff and a partner, autopilot and
the API. This replaces the 2026-09-28 rule ("staff may fill the package while
the partner has planned none; the partner side and the trainings are not
capped").

The doors ask `assert_side_open`; the Core Schools row and drawers and the
visit gate read `package_splits`, so a control never offers what its POST
refuses.

What one side of a year's package holds (owner, 2026-10-02: a package's work
is the work dated in its year):

* the visits and trainings AT THE SCHOOL dated in the package's fiscal year,
  by who delivers them (``Activity.delivery_type``) — whichever slot they are
  linked to, or none yet, so a bulk save, an old row or a link the repair has
  not reached cannot slip past the count;
* the group trainings planned through the school's cluster that fill one of
  the package's training slots, by who delivers the session (owner,
  2026-10-02: "if a core school is part of a group training, it should be
  counted in the core package"). A session takes a slot only while its half
  has room (`cluster_credit`), so the slots it holds are its count;
* on the partner side, the partner hand-overs at the school still waiting to
  be dated (each holds its slot from the moment it is made), counted in the
  running year.

Not on either side, and never refused over a package: the companion visit of
an in-school training pair; donor, story, invitation and social visits; data
collection (SSA Support) visits; cluster meetings, which are not trainings; a
group training past its half's two, which is on the school's history and in
no slot (a group session is never refused over one school); and the work of a
project no SSA intervention measures (Alumni; owner, 2026-10-02).

Nothing here touches work that already exists. It answers whether NEW work
fits, and a package already over a side (planned before the rule) simply takes
no more on that side.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.exceptions import BadRequest

STAFF = "staff"
PARTNER = "partner"
VISIT = "visit"
TRAINING = "training"

#: Each side's share of each kind: two of the four visits, two of the four
#: trainings.
SIDE_CAP = 2

_KIND_WORDS = {VISIT: ("visit", "visits"), TRAINING: ("training", "trainings")}


@dataclass
class PackageSplit:
    """One Core package's work, by kind and by who delivers it."""

    school_id: str
    plan_id: str | None = None
    fy: str = ""
    staff_visits: int = 0
    partner_visits: int = 0
    #: Partner hand-overs waiting to be dated, counted on the partner side.
    partner_pending_visits: int = 0
    staff_trainings: int = 0
    partner_trainings: int = 0
    partner_pending_trainings: int = 0

    @property
    def has_package(self) -> bool:
        return self.plan_id is not None

    def used(self, kind: str, side: str) -> int:
        if kind == VISIT:
            if side == STAFF:
                return self.staff_visits
            return self.partner_visits + self.partner_pending_visits
        if side == STAFF:
            return self.staff_trainings
        return self.partner_trainings + self.partner_pending_trainings

    def is_open(self, kind: str, side: str) -> bool:
        """May one more piece of ``kind`` work go to ``side``? Always, for a
        school with no package: the split is the package's rule."""
        return not self.has_package or self.used(kind, side) < SIDE_CAP

    def refusal(self, kind: str, side: str, school_name: str) -> str:
        """Why the side is full, in the sentence every door says."""
        one, many = _KIND_WORDS[kind]
        other = "partner" if side == STAFF else "staff"
        who = "staff" if side == STAFF else "partner"
        return (
            f"{school_name} already has its {SIDE_CAP} {who} core {many} "
            f"({self.used(kind, side)}/{SIDE_CAP}). A Core package is "
            f"{SIDE_CAP} staff and {SIDE_CAP} partner {many}, so the next "
            f"{one} here is the {other}'s."
        )

    def as_dict(self) -> dict:
        return {
            "staff_visits": self.staff_visits,
            "partner_visits": self.used(VISIT, PARTNER),
            "staff_trainings": self.staff_trainings,
            "partner_trainings": self.used(TRAINING, PARTNER),
            "side_cap": SIDE_CAP,
        }


def side_of(data: dict) -> str:
    """The side an activity payload is delivered by."""
    partner = data.get("deliveryType") == "partner" or bool(
        str(data.get("assignedPartnerId") or "").strip()
    )
    return PARTNER if partner else STAFF


def _plans_by_school(codes) -> dict[str, list]:
    from apps.core_schools.models import CorePlan
    from apps.core_schools.services import CORE_PLAN_CLOSED_STATUSES

    plans: dict[str, list] = {}
    for plan in (
        CorePlan.objects.filter(school_id__in=codes)
        .exclude(status__in=CORE_PLAN_CLOSED_STATUSES)
        .only("id", "school_id", "fy")
    ):
        plans.setdefault(plan.school_id, []).append(plan)
    return plans


#: ``PackageSplit.plan_id`` for a Core school that has packages and none yet
#: for the year asked about: the year's split applies all the same, and the
#: package is made with the first work planned into it
#: (``services.ensure_core_plan``).
PACKAGE_NOT_MADE_YET = ""


def package_splits(
    schools,
    fy: str | None = None,
    *,
    exclude_activity_id: str | None = None,
    exclude_assignment_id: str | None = None,
) -> dict[str, PackageSplit]:
    """The split of each Core school's package for ``fy`` (the operational
    year by default), keyed by ``School.id``, in seven queries whatever the
    count. ``schools`` are School rows (id, school_id, school_type are read);
    a school that is not Core, or has never had a package, gets an empty split
    that is open on every side.

    ``exclude_activity_id`` leaves out work being moved or re-dated;
    ``exclude_assignment_id`` leaves out the hand-over a partner is dating, so
    neither counts against itself.
    """
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.core_schools.package_credit import (
        UNCREDITED_STATUSES,
        assignment_kind,
        not_outside_package_q,
        package_kind_for,
        package_work_q,
    )
    from apps.core_schools import package_year
    from apps.core_schools.models import CoreActivitySlot
    from apps.partners.models import PartnerAssignment

    operational_fy = str(get_operational_fy())
    fy = str(fy or operational_fy)
    rows = list(schools)
    out = {s.id: PackageSplit(school_id=s.id, fy=fy) for s in rows}
    core = [s for s in rows if getattr(s, "school_type", None) == "core"]
    if not core:
        return out

    plans_by_code = _plans_by_school({s.school_id for s in core})
    packaged: list[str] = []
    school_of_plan: dict[str, str] = {}
    for s in core:
        plans = plans_by_code.get(s.school_id, [])
        exact = next((p for p in plans if str(p.fy) == fy), None)
        if exact is not None:
            out[s.id].plan_id = exact.id
            school_of_plan[exact.id] = s.id
        elif plans and fy >= operational_fy:
            out[s.id].plan_id = PACKAGE_NOT_MADE_YET
        else:
            continue
        packaged.append(s.id)
    if not packaged:
        return out

    def _add(split: PackageSplit, kind: str, delivery_type: str | None) -> None:
        partner = delivery_type == PARTNER
        if kind == VISIT:
            if partner:
                split.partner_visits += 1
            else:
                split.staff_visits += 1
        elif kind == TRAINING:
            if partner:
                split.partner_trainings += 1
            else:
                split.staff_trainings += 1

    # 1. The visits and trainings at these schools dated in the year.
    work = (
        Activity.objects.filter(school_id__in=packaged, fy=fy, deleted_at__isnull=True)
        .filter(package_work_q())
        .filter(not_outside_package_q())
        .exclude(status__in=UNCREDITED_STATUSES)
        .values("id", "school_id", "activity_type", "purpose_type", "delivery_type")
    )
    for row in work:
        if row["id"] == exclude_activity_id:
            continue
        kind = package_kind_for(
            row["activity_type"],
            row["purpose_type"],
            delivery_type=row["delivery_type"] or "staff",
        )
        if kind is not None:
            _add(out[row["school_id"]], kind, row["delivery_type"])

    # 2. Group trainings in the packages' training slots. A session takes a
    #    slot only while its half has room, so what it holds is what it counts.
    held = [
        (activity_id, plan_id)
        for activity_id, plan_id in CoreActivitySlot.objects.filter(
            core_plan_id__in=list(school_of_plan),
            activity_type="training",
            activity_id__isnull=False,
        ).values_list("activity_id", "core_plan_id")
        if activity_id and activity_id != exclude_activity_id
    ]
    if held:
        delivered_by = dict(
            Activity.objects.filter(
                id__in={activity_id for activity_id, _plan in held},
                cluster_id__isnull=False,
                activity_type__in=package_year.CLUSTER_TRAINING_TYPES,
                deleted_at__isnull=True,
            )
            .filter(not_outside_package_q())
            .exclude(status__in=UNCREDITED_STATUSES)
            .values_list("id", "delivery_type")
        )
        for activity_id, plan_id in held:
            if activity_id in delivered_by:
                _add(out[school_of_plan[plan_id]], TRAINING, delivered_by[activity_id])

    # 3. Partner hand-overs still waiting to be dated. They have no date, so
    #    they are the running year's (`package_credit.reserve_for_assignment`).
    if fy == operational_fy:
        for handover in PartnerAssignment.objects.filter(
            school_id__in=packaged,
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        ).only(
            "id",
            "school_id",
            "project_id",
            "support_type",
            "visit_number",
            "training_number",
            "expected_activity_type",
            "purpose_of_visit",
        ):
            if handover.id == exclude_assignment_id:
                continue
            kind = assignment_kind(handover)
            split = out[handover.school_id]
            if kind == VISIT:
                split.partner_pending_visits += 1
            elif kind == TRAINING:
                split.partner_pending_trainings += 1
    return out


def package_split(school, fy: str | None = None, **exclude) -> PackageSplit:
    return package_splits([school], fy, **exclude)[school.id]


def assert_side_open(
    school,
    kind: str | None,
    side: str,
    *,
    fy: str | None = None,
    exclude_activity_id: str | None = None,
    exclude_assignment_id: str | None = None,
) -> PackageSplit | None:
    """Refuse package work the side has no room for; else the split.

    A no-op (None) for work that is not package work, and for a school that is
    not Core or carries no package for the year.
    """
    if school is None or kind not in (VISIT, TRAINING):
        return None
    if getattr(school, "school_type", None) != "core":
        return None
    split = package_split(
        school,
        fy,
        exclude_activity_id=exclude_activity_id,
        exclude_assignment_id=exclude_assignment_id,
    )
    if not split.is_open(kind, side):
        raise BadRequest(
            split.refusal(kind, side, getattr(school, "name", "This school"))
        )
    return split


__all__ = [
    "PARTNER",
    "SIDE_CAP",
    "STAFF",
    "TRAINING",
    "VISIT",
    "PackageSplit",
    "assert_side_open",
    "package_split",
    "package_splits",
    "side_of",
]
