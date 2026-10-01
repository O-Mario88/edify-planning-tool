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

What one side of a package holds:

* the visits and trainings linked to the package's slots, by who delivers
  them (``Activity.delivery_type``);
* live package work at the school in the package's year that no slot links
  yet — the post-commit credit (`package_credit`) has not run, or the work
  predates it — so a bulk save or an old row cannot slip past the count;
* on the partner side, the partner hand-overs at the school still waiting to
  be dated (each holds its slot from the moment it is made).

Not on either side: cluster sessions (a group session is credited to the
package by `cluster_credit`, but it is nobody's half of the split and is never
refused over one school), the companion visit of an in-school training pair,
and donor, story, invitation and social visits, which are not package work.

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


def _not_package_work(activity_type, purpose_type) -> bool:
    from apps.core_schools.package_credit import (
        NON_PACKAGE_VISIT_PURPOSES,
        NON_PACKAGE_VISIT_TYPES,
    )
    from apps.planning.visit_gate import COMPANION_VISIT_PURPOSE

    purpose = str(purpose_type or "")
    return (
        str(activity_type or "") in NON_PACKAGE_VISIT_TYPES
        or purpose in NON_PACKAGE_VISIT_PURPOSES
        or purpose == COMPANION_VISIT_PURPOSE
    )


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


def _plan_for(plans: list, fy: str, operational_fy: str):
    """The package work of ``fy`` belongs to — `package_credit.plan_for_activity`
    over rows already read: that year's plan; for a later year with none, the
    school's live package; never a later package for an earlier year's work."""
    exact = next((p for p in plans if str(p.fy) == fy), None)
    if exact is not None or (fy and fy < operational_fy):
        return exact
    return _live_plan(plans, operational_fy)


def _live_plan(plans: list, operational_fy: str):
    """`services.get_live_core_plan` over rows already read."""
    current = next((p for p in plans if str(p.fy) == operational_fy), None)
    if current is not None:
        return current
    return max(plans, key=lambda p: str(p.fy), default=None)


def package_splits(
    schools,
    fy: str | None = None,
    *,
    exclude_activity_id: str | None = None,
    exclude_assignment_id: str | None = None,
) -> dict[str, PackageSplit]:
    """The split of each Core school's package for ``fy`` (the operational
    year by default), keyed by ``School.id``, in five queries whatever the
    count. ``schools`` are School rows (id, school_id, school_type are read);
    a school that is not Core, or has no package, gets an empty split that is
    open on every side.

    ``exclude_activity_id`` leaves out work being moved or re-dated;
    ``exclude_assignment_id`` leaves out the hand-over a partner is dating, so
    neither counts against itself.
    """
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy
    from apps.core_schools.models import CoreActivitySlot
    from apps.core_schools.package_credit import (
        UNCREDITED_STATUSES,
        assignment_kind,
        package_kind_for,
        package_work_q,
    )
    from apps.partners.models import PartnerAssignment

    operational_fy = str(get_operational_fy())
    fy = str(fy or operational_fy)
    rows = list(schools)
    out = {s.id: PackageSplit(school_id=s.id, fy=fy) for s in rows}
    core = [s for s in rows if getattr(s, "school_type", None) == "core"]
    if not core:
        return out

    plans_by_code = _plans_by_school({s.school_id for s in core})
    plan_of: dict[str, object] = {}
    for s in core:
        plan = _plan_for(plans_by_code.get(s.school_id, []), fy, operational_fy)
        if plan is not None:
            plan_of[s.id] = plan
            out[s.id].plan_id = plan.id
            out[s.id].fy = str(plan.fy)
    if not plan_of:
        return out
    school_of_plan = {plan.id: sid for sid, plan in plan_of.items()}

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

    # 1. Work the packages' slots already link.
    linked = {
        row["activity_id"]: (row["core_plan_id"], row["activity_type"])
        for row in CoreActivitySlot.objects.filter(
            core_plan_id__in=list(school_of_plan), activity_id__isnull=False
        ).values("activity_id", "core_plan_id", "activity_type")
    }
    if linked:
        live = (
            Activity.objects.filter(
                id__in=list(linked), deleted_at__isnull=True, cluster__isnull=True
            )
            .exclude(status__in=UNCREDITED_STATUSES)
            .values("id", "activity_type", "purpose_type", "delivery_type")
        )
        for row in live:
            if row["id"] == exclude_activity_id:
                continue
            plan_id, slot_kind = linked[row["id"]]
            # A slot linked before the outreach rule to a donor or story
            # visit is not package work any more, whatever the slot says.
            # Any other linked work counts by the slot it fills.
            if _not_package_work(row["activity_type"], row["purpose_type"]):
                continue
            _add(out[school_of_plan[plan_id]], slot_kind, row["delivery_type"])

    # 2. Package work at these schools that no slot links yet.
    unlinked = (
        Activity.objects.filter(school_id__in=list(plan_of), deleted_at__isnull=True)
        .filter(package_work_q())
        .exclude(status__in=UNCREDITED_STATUSES)
        .exclude(
            id__in=CoreActivitySlot.objects.filter(activity_id__isnull=False).values(
                "activity_id"
            )
        )
        .values(
            "id", "school_id", "fy", "activity_type", "purpose_type", "delivery_type"
        )
    )
    code_of = {s.id: s.school_id for s in core}
    for row in unlinked:
        if row["id"] == exclude_activity_id:
            continue
        sid = row["school_id"]
        work_plan = _plan_for(
            plans_by_code.get(code_of[sid], []), str(row["fy"] or ""), operational_fy
        )
        if work_plan is None or work_plan.id != plan_of[sid].id:
            continue
        kind = package_kind_for(row["activity_type"], row["purpose_type"])
        if kind is not None:
            _add(out[sid], kind, row["delivery_type"])

    # 3. Partner hand-overs still waiting to be dated. They belong to the
    #    school's live package, as the slot each one holds does
    #    (`package_credit.reserve_for_assignment`).
    live_plan_ids = {
        sid
        for sid, plan in plan_of.items()
        if _live_plan(plans_by_code.get(code_of[sid], []), operational_fy) is plan
    }
    if live_plan_ids:
        for handover in PartnerAssignment.objects.filter(
            school_id__in=list(live_plan_ids),
            status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
        ).only(
            "id",
            "school_id",
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
