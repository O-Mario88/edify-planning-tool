"""A Core package belongs to a fiscal year, and so does the work that fills it.

Owner, 2026-10-02: "Core School page are not fetching the number of visits.
People have planned first visit and second visits but they are not showing in
V1, V2, V3, V4 but the trainings are showing but also inflated numbers. The
staff are only supposed to plan for two visits and two trainings but it is
showing all the 4. The other two visits and trainings are supposed to be
assigned."

Two faults, found by replaying September's planning:

**The year.** Every door that booked Core work took the package of the day the
planner was sitting in, not of the day the work was planned for. Through
September staff planned October's first and second visits, which are FY2027
work, into the FY2026 package (the only one there was). On 1 October the Core
Schools page turned to FY2027, made each school a new package, and showed its
V1..V4 empty. The split beside them still read "staff 2/2", because it found
the work through the old package.

A package's work is now the work dated in the package's year. ``ensure_plan``
gives a Core school its package for a year the first time work is planned
into it, and ``refile`` moves the links already written.

**What fills it.** A cluster training or meeting took a training slot at
every Core school it invited, with no limit, so two group trainings and two
meetings read "4/4 trainings" with the Partner's half never assigned; and a
data collection (SSA Support) visit took one of the four visits. The owner,
the same day: cluster sessions are outside the package, and "the only visits
that count are in-school visits and Training Follow Up visits". So a
package's four trainings are in-school trainings and its four visits are
follow-up visits, two by staff and two assigned to a Partner, and ``refile``
gives back every slot a cluster session or a data collection visit holds.

``refile`` is written against whichever models it is handed, so the deploy
migration (historical models) and ``manage.py refile_core_package_work`` (the
live ones) run one piece of code. It reads no live service code.
"""

from __future__ import annotations

from apps.core.cuid import deterministic

#: Each side's share of each kind: two of the four visits, two of the four
#: trainings (``package_split.SIDE_CAP``; restated so a migration that runs
#: this never reads live code).
SIDE_CAP = 2

LEGACY_FY = "2026"
SLOT_LETTER = {"assessment": "a", "visit": "v", "training": "t"}
PACKAGE_SPEC = (("assessment", 1), ("visit", 4), ("training", 4))
OPEN_STATUS = "Planned"

CLOSED_PLAN_STATUSES = frozenset(
    {"Archived", "archived", "Cancelled", "cancelled", "Exited", "exited"}
)
#: Activity states in which work holds no slot.
UNCREDITED = frozenset(
    {"cancelled", "rejected", "deferred", "not_planned", "awaiting_owner_approval"}
)
CLUSTER_SESSION_TYPES = frozenset(
    {
        "cluster_training",
        "cluster_training_ssa_collection",
        "cluster_meeting",
        "cluster_meeting_ssa_review",
    }
)
#: Visits that are not package work: data collection, and the donor, story,
#: invitation and social visits (``package_credit.NON_PACKAGE_VISIT_*``).
NON_PACKAGE_TYPES = frozenset(
    {
        "school_visit_ssa_collection",
        "baseline_ssa_visit",
        "partner_ssa_collection",
        "donor_visit",
        "story_gathering_visit",
        "school_invitation",
        "social_visit",
    }
)
NON_PACKAGE_PURPOSES = frozenset(
    {
        "ssa_support",
        "donor_visit",
        "story_gathering",
        "school_invitation",
        "social_visit",
    }
)
#: What a slot carries about the work that fills it, moved with the work.
SLOT_WORK_FIELDS = (
    "status",
    "owner",
    "assigned_staff_id",
    "assigned_staff_name",
    "assigned_partner_id",
    "assigned_partner_name",
    "scheduled_month",
    "scheduled_week",
    "scheduled_for",
    "salesforce_id",
    "activity_id",
    "evidence_uri",
    "evidence_notes",
    "pl_verification_status",
    "ia_verification_status",
    "accountant_status",
    "netsuite_status",
    "teachers",
    "leaders",
    "participants",
    "returned_reason",
    "completed_at",
)
_OPEN_VALUES = {"status": OPEN_STATUS, "owner": "unassigned"}
DONE_STATUSES = frozenset(
    {"completed", "closed", "ia_verified", "accountant_confirmed"}
)


def plan_id(school_code: str, fy: str) -> str:
    """``models.cplan_id``, restated for the same reason as ``SIDE_CAP``."""
    if str(fy) == LEGACY_FY:
        return deterministic("cplan", school_code)
    return deterministic("cplan", school_code, str(fy))


def slot_id(school_code: str, kind: str, sequence: int, fy: str) -> str:
    letter = SLOT_LETTER[kind]
    if str(fy) == LEGACY_FY:
        return deterministic("cslot", school_code, f"{letter}{sequence}")
    return deterministic("cslot", school_code, str(fy), f"{letter}{sequence}")


def is_open(status) -> bool:
    """Whether a slot in this state is free to take work."""
    return (status or "").strip().lower() in ("", "planned", "not_planned", "pending")


def _clear(slot) -> None:
    for name in SLOT_WORK_FIELDS:
        setattr(slot, name, _OPEN_VALUES.get(name))


# ── A year's package ─────────────────────────────────────────────────────────
def ensure_plan(Plan, Slot, school_code: str, fy: str, *, defaults=None):
    """The school's package for ``fy``, made from its newest one if it has
    none for that year. Returns ``(plan, created)``; ``(None, False)`` for a
    school that has never had a package (onboarding makes the first one, with
    its baseline assessment) or whose package for that year is closed.
    """
    fy = str(fy)
    existing = Plan.objects.filter(school_id=school_code, fy=fy).first()
    if existing is not None:
        if existing.status in CLOSED_PLAN_STATUSES:
            return None, False
        return existing, False
    earlier = (
        Plan.objects.filter(school_id=school_code)
        .exclude(status__in=CLOSED_PLAN_STATUSES)
        .order_by("-fy")
        .first()
    )
    if earlier is None:
        return None, False
    values = {
        "school_id": school_code,
        "fy": fy,
        "status": "Active",
        "visits_target": earlier.visits_target or 4,
        "trainings_target": earlier.trainings_target or 4,
        "baseline_average": earlier.follow_up_average
        if earlier.follow_up_average is not None
        else earlier.baseline_average,
        "baseline_ssa_record_id": earlier.follow_up_ssa_record_id
        or earlier.baseline_ssa_record_id,
        "interventions": earlier.interventions,
        "created_by_name": "System (package for the year its work is planned in)",
        **(defaults or {}),
    }
    plan, created = Plan.objects.get_or_create(
        id=plan_id(school_code, fy), defaults=values
    )
    interventions = list(plan.interventions or []) or ["christlike_behaviour"]
    for kind, count in PACKAGE_SPEC:
        for sequence in range(1, count + 1):
            Slot.objects.get_or_create(
                id=slot_id(school_code, kind, sequence, fy),
                defaults={
                    "core_plan": plan,
                    "school_id": school_code,
                    "intervention": interventions[(sequence - 1) % len(interventions)],
                    "activity_type": kind,
                    "sequence_number": sequence,
                },
            )
    return plan, created


def _next_open(Slot, plan, kind: str):
    """The plan's next open slot of ``kind``, or a new one past its last."""
    slots = list(
        Slot.objects.filter(core_plan=plan, activity_type=kind).order_by(
            "sequence_number"
        )
    )
    for slot in slots:
        if is_open(slot.status) and not slot.activity_id:
            return slot
    sequence = max((s.sequence_number for s in slots), default=0) + 1
    interventions = list(plan.interventions or []) or ["christlike_behaviour"]
    slot, _made = Slot.objects.get_or_create(
        id=slot_id(plan.school_id, kind, sequence, plan.fy),
        defaults={
            "core_plan": plan,
            "school_id": plan.school_id,
            "intervention": interventions[0],
            "activity_type": kind,
            "sequence_number": sequence,
        },
    )
    return slot


def _recount(Slot, plan) -> None:
    """``services.resync_plan_completion`` over the models in hand."""
    done = {"visit": 0, "training": 0, "assessment": 0}
    for kind, status in Slot.objects.filter(core_plan=plan).values_list(
        "activity_type", "status"
    ):
        if status in DONE_STATUSES and kind in done:
            done[kind] += 1
    if (
        plan.visits_completed,
        plan.trainings_completed,
        plan.assessment_completed,
    ) != (done["visit"], done["training"], done["assessment"]):
        plan.visits_completed = done["visit"]
        plan.trainings_completed = done["training"]
        plan.assessment_completed = done["assessment"]
        plan.save(
            update_fields=[
                "visits_completed",
                "trainings_completed",
                "assessment_completed",
            ]
        )


def _compact(Slot, plan, kind: str) -> bool:
    """Close the gaps a release leaves: the plan's taken slots of ``kind``
    become its first ones, earliest dated first, so a package whose two
    trainings sat at T1 and T3 reads T1 and T2 with T3 and T4 open. Work held
    with no date (a Partner's hand-over) follows the dated work. Returns
    whether anything moved.
    """
    slots = list(
        Slot.objects.filter(core_plan=plan, activity_type=kind).order_by(
            "sequence_number"
        )
    )
    taken = [s for s in slots if s.activity_id or not is_open(s.status)]
    if [s.id for s in taken] == [s.id for s in slots[: len(taken)]]:
        ordered = sorted(
            taken, key=lambda s: (not s.scheduled_for, str(s.scheduled_for or ""))
        )
        if [s.id for s in ordered] == [s.id for s in taken]:
            return False
    payloads = sorted(
        ({name: getattr(s, name) for name in SLOT_WORK_FIELDS} for s in taken),
        key=lambda work: (
            not work["scheduled_for"],
            str(work["scheduled_for"] or ""),
        ),
    )
    for position, slot in enumerate(slots):
        if position < len(payloads):
            for name, value in payloads[position].items():
                setattr(slot, name, value)
        else:
            _clear(slot)
        slot.save()
    return True


def _day(activity):
    return str(activity.planned_date or "") or str(activity.scheduled_date or "")[:10]


# ── The repair ───────────────────────────────────────────────────────────────
def misfiled(Slot, Activity) -> list[tuple]:
    """``(slot, activity)`` for every slot whose work is dated in another
    fiscal year than its package's, oldest work first."""
    slots = list(
        Slot.objects.exclude(activity_id__isnull=True)
        .exclude(activity_id="")
        .filter(activity_type__in=("visit", "training"))
        .select_related("core_plan")
    )
    activities = {
        a.id: a
        for a in Activity.objects.filter(
            id__in={s.activity_id for s in slots}, deleted_at__isnull=True
        )
    }
    found = []
    for slot in slots:
        activity = activities.get(slot.activity_id)
        if activity is None or not activity.fy or activity.cluster_id:
            continue
        if not is_package_work(activity):
            continue  # released, not moved (`outside_package`)
        if str(activity.fy) != str(slot.core_plan.fy):
            found.append((slot, activity))
    found.sort(key=lambda pair: (_day(pair[1]), str(pair[1].created_at), pair[0].id))
    return found


def is_package_work(activity) -> bool:
    """Whether a visit or training at a school is package work: not a cluster
    session, not data collection, not a donor, story, invitation or social
    visit."""
    if activity.cluster_id or activity.activity_type in CLUSTER_SESSION_TYPES:
        return False
    return not (
        activity.activity_type in NON_PACKAGE_TYPES
        or (activity.purpose_type or "") in NON_PACKAGE_PURPOSES
    )


def outside_package(Slot, Activity, *, from_fy: str) -> list[tuple]:
    """``(slot, activity)`` for every slot of a package of ``from_fy`` onward
    held by work that is no part of a package: a cluster session or a data
    collection visit (owner, 2026-10-02)."""
    slots = list(
        Slot.objects.exclude(activity_id__isnull=True)
        .exclude(activity_id="")
        .filter(
            activity_type__in=("visit", "training"),
            core_plan__fy__gte=str(from_fy),
        )
        .select_related("core_plan")
        .order_by("core_plan_id", "activity_type", "sequence_number")
    )
    activities = {
        a.id: a
        for a in Activity.objects.filter(
            id__in={s.activity_id for s in slots}, deleted_at__isnull=True
        )
    }
    return [
        (slot, activities[slot.activity_id])
        for slot in slots
        if slot.activity_id in activities
        and not is_package_work(activities[slot.activity_id])
    ]


def refile(
    Plan,
    Slot,
    Activity,
    *,
    from_fy: str,
    write: bool = True,
    out=print,
    tag: str = "refile_core_package_work",
) -> dict:
    """Put every Core package's work in the package of its own year, and take
    out of the packages what is no part of one.

    1. For packages of ``from_fy`` onward: a slot held by a cluster training
       or meeting, or by a data collection visit, is given back.
    2. School visits and trainings linked to another year's package move to
       the package of the year they are dated in, oldest first so the
       earliest is V1. The slot they leave is open again.
    3. The packages touched in those years lose their gaps: taken slots first,
       earliest dated first.

    Nothing is removed and no activity is changed: only which package slot
    points at it. Returns what was (or, with ``write=False``, would be) done.
    """
    report = {"moved": [], "unplaced": [], "released": [], "plans": []}
    touched: dict[str, object] = {}

    def say(line: str) -> None:
        out(f"[{tag}] {line}")

    def label_of(slot) -> str:
        return f"{SLOT_LETTER[slot.activity_type].upper()}{slot.sequence_number}"

    # 1. Work that is no part of a package gives its slot back.
    for slot, activity in outside_package(Slot, Activity, from_fy=from_fy):
        plan = slot.core_plan
        why = (
            "a cluster session is outside the package"
            if activity.cluster_id or activity.activity_type in CLUSTER_SESSION_TYPES
            else "it is not a package visit"
        )
        report["released"].append({"slot": slot.id, "activity": activity.id})
        say(
            f"school {plan.school_id}: FY{plan.fy} {label_of(slot)} released from "
            f"{activity.activity_type} {activity.id} ({_day(activity)}): {why}"
        )
        if write:
            _clear(slot)
            slot.save()
            touched[plan.id] = plan

    # 2. School-level work in another year's package.
    for slot, activity in misfiled(Slot, Activity):
        source = slot.core_plan
        target, created = (
            ensure_plan(Plan, Slot, source.school_id, activity.fy)
            if write
            else (
                Plan.objects.filter(school_id=source.school_id, fy=str(activity.fy))
                .exclude(status__in=CLOSED_PLAN_STATUSES)
                .first(),
                False,
            )
        )
        label = label_of(slot)
        if target is None and write:
            report["unplaced"].append(activity.id)
            say(
                f"school {source.school_id}: {activity.activity_type} {activity.id} "
                f"({_day(activity)}) stays in FY{source.fy} {label}: no FY"
                f"{activity.fy} package can be made"
            )
            continue
        if created:
            report["plans"].append(target.id)
            say(f"school {source.school_id}: FY{activity.fy} package made")
        entry = {
            "activity": activity.id,
            "school": source.school_id,
            "from": f"FY{source.fy} {label}",
            "to_fy": str(activity.fy),
        }
        if write:
            destination = _next_open(Slot, target, slot.activity_type)
            for name in SLOT_WORK_FIELDS:
                setattr(destination, name, getattr(slot, name))
            destination.save()
            _clear(slot)
            slot.save()
            touched[source.id] = source
            touched[target.id] = target
            entry["to"] = f"FY{target.fy} {label_of(destination)}"
        report["moved"].append(entry)
        say(
            f"school {source.school_id}: {activity.activity_type} {activity.id} "
            f"({_day(activity)}) FY{source.fy} {label} -> "
            f"{entry.get('to', 'FY' + str(activity.fy))}"
        )

    if write:
        for plan in touched.values():
            # A year this repair re-read keeps no gaps; an earlier year's
            # package keeps the numbers it has always had.
            if str(plan.fy) >= str(from_fy):
                for kind in ("visit", "training"):
                    if _compact(Slot, plan, kind):
                        say(
                            f"school {plan.school_id}: FY{plan.fy} {kind}s "
                            "renumbered"
                        )
            _recount(Slot, plan)
    say(
        f"{len(report['released'])} slot(s) released from cluster sessions and "
        f"data collection visits, {len(report['moved'])} visit(s)/training(s) "
        f"moved to their own year's package, {len(report['plans'])} package(s) "
        f"made, {len(report['unplaced'])} left in place"
    )
    return report


__all__ = [
    "SIDE_CAP",
    "ensure_plan",
    "is_open",
    "is_package_work",
    "misfiled",
    "outside_package",
    "plan_id",
    "refile",
    "slot_id",
]
