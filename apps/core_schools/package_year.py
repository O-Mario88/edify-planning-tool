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
every Core school it invited, with no limit and on neither half, so two group
trainings and two meetings read "4/4 trainings" with the Partner's half never
assigned; and a data collection (SSA Support) visit took one of the four
visits. The owner, the same day: "the only visits that count are in-school
visits and Training Follow Up visits", and the package's trainings "should
include both in-school training and group trainings planned through clusters.
So if a core school is part of a group training, it should be counted in the
core package."

So a package's four visits are follow-up visits and its four trainings are
in-school trainings and group trainings, two by staff and two by a Partner. A
group training is on the half of whoever delivers it and takes a slot while
that half has room; past it the session is still the school's training, on
its history, and fills no slot (a group session is never refused over one
school). A cluster meeting is not a training and a data collection visit is
not a package visit: ``refile`` gives back every slot either holds, and puts
the group trainings where this rule has them.

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
#: A group training planned through a school's cluster: one of the package's
#: trainings. A cluster meeting is not a training.
CLUSTER_TRAINING_TYPES = frozenset(
    {"cluster_training", "cluster_training_ssa_collection"}
)
CLUSTER_MEETING_TYPES = frozenset({"cluster_meeting", "cluster_meeting_ssa_review"})
CLUSTER_SESSION_TYPES = CLUSTER_TRAINING_TYPES | CLUSTER_MEETING_TYPES
#: A training delivered at the school (``cluster_attendance``).
SCHOOL_TRAINING_TYPES = frozenset(
    {"training", "in_school_training", "school_improvement_training", "core_training"}
)

#: A session whose register has been confirmed and that has not been
#: abandoned. `completion_started` is deliberately absent: attendance recorded
#: while the session is still being completed is a draft, and a slot left in a
#: status the scheduler reads as open could be scheduled over.
SESSION_CREDITED_STATUSES = frozenset(
    {
        "submitted_to_pl",
        "awaiting_ia_verification",
        "returned",
        "returned_by_pl",
        "completed",
        "ia_verified",
        "accountant_confirmed",
        "closed",
    }
)
#: A session that is booked but whose register has not been confirmed. The
#: invitation alone takes the slot here, so the package reads "planned" from
#: the day the session is scheduled (owner, 2026-09-21) — the same reading a
#: training booked from the Core Schools page gives.
SESSION_PLANNED_STATUSES = frozenset(
    {
        "planned",
        "scheduled",
        "rescheduled",
        "assigned_to_partner",
        "partner_scheduled",
        "in_progress",
        "completion_started",
        "evidence_uploaded",
        "evidence_accepted",
        "salesforce_id_required",
        "returned_by_ia",
    }
)
#: Every status in which a session holds a slot at all. Outside it — a
#: cancelled, rejected, deferred or unplanned session — the slots go back.
SESSION_LIVE_STATUSES = SESSION_CREDITED_STATUSES | SESSION_PLANNED_STATUSES
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


def is_group_training(activity) -> bool:
    """A training planned through a cluster, for the schools on its list."""
    return bool(activity.cluster_id) and (
        activity.activity_type in CLUSTER_TRAINING_TYPES
    )


def side_of(activity) -> str:
    """The half of the package work is on: whoever delivers it."""
    return "partner" if activity.delivery_type == "partner" else "staff"


def session_school_ids(rows, activity) -> set:
    """School pks whose place at this session counts as their training, from
    its attendance ``rows`` of ``(school_id, invited, attended, is_guest)``.

    Booked and not yet registered, the invitation is the commitment: every
    invited member school. Register confirmed: attended *and* invited, so a
    school that was invited and did not come gives its slot back. A session
    scheduled before invitations were recorded by name has no invitation row
    at all; the whole cluster was invited, so attendance alone counts.
    """
    invited = {school_id for school_id, i, _a, guest in rows if i and not guest}
    if activity.status in SESSION_PLANNED_STATUSES:
        return invited
    attended = {school_id for school_id, _i, a, _g in rows if a}
    attended |= set(activity.attended_school_ids or [])
    if not invited:
        guests = {school_id for school_id, _i, _a, guest in rows if guest}
        return attended - guests
    return attended & invited


def is_package_work(activity) -> bool:
    """Whether work is package work: a visit or training at the school, or a
    group training planned through its cluster. Not a cluster meeting, not
    data collection, not a donor, story, invitation or social visit."""
    if activity.cluster_id or activity.activity_type in CLUSTER_SESSION_TYPES:
        return is_group_training(activity)
    return not (
        activity.activity_type in NON_PACKAGE_TYPES
        or (activity.purpose_type or "") in NON_PACKAGE_PURPOSES
    )


def outside_package(Slot, Activity, *, from_fy: str) -> list[tuple]:
    """``(slot, activity)`` for every slot of a package of ``from_fy`` onward
    held by work that is no part of a package: a cluster meeting or a data
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


def _slot_status(activity_status) -> str:
    """The status a slot takes from the work that fills it: a slot's own
    "Planned" means open (``core_planning_services.core_slot_status``)."""
    status = activity_status or ""
    return "Scheduled" if status.strip().lower() == "planned" else status


def _fill_from_session(slot, activity) -> None:
    from django.utils import timezone

    when = activity.planned_date
    if when is None and activity.scheduled_date:
        when = timezone.localtime(activity.scheduled_date).date()
    slot.activity_id = activity.id
    slot.status = _slot_status(activity.status)
    slot.owner = side_of(activity)
    slot.assigned_staff_id = activity.responsible_staff_id
    slot.assigned_partner_id = activity.assigned_partner_id
    slot.scheduled_for = when
    slot.scheduled_month = (
        str(activity.planned_month) if activity.planned_month else None
    )
    slot.scheduled_week = activity.planned_week


class _GroupTrainings:
    """The group trainings of the years re-read, put where the rule has them.

    A group training fills a training slot of each Core school it counts for
    (``session_school_ids``), in the package of the year it is dated in, on
    the half of whoever delivers it, earliest first while that half has room.
    What each half already holds is the trainings at the school dated in the
    year and the hand-overs holding a slot — ``package_split``'s count, read
    here from the models in hand.

    ``release`` gives back the slots that rule does not have a group training
    in; ``place`` fills the slots it does. They are two passes because the
    school's own misfiled work moves between them (``refile``).
    """

    def __init__(self, Plan, Slot, Activity, Attendance, School, *, from_fy, skip):
        from collections import defaultdict

        from django.db.models import Count, Q

        self.Plan, self.Slot = Plan, Slot
        from_fy = str(from_fy)
        group = Activity.objects.filter(
            cluster_id__isnull=False, activity_type__in=CLUSTER_TRAINING_TYPES
        )
        live = group.filter(
            deleted_at__isnull=True,
            status__in=SESSION_LIVE_STATUSES,
            fy__gte=from_fy,
        )
        if skip:
            # Alumni: a project no SSA intervention measures is no part of a
            # package (``package_credit.outside_package``).
            live = live.exclude(project_id__in=list(skip))
        self.sessions = {a.id: a for a in live}

        rows = defaultdict(list)
        for (
            activity_id,
            school_pk,
            invited,
            attended,
            guest,
        ) in Attendance.objects.filter(activity_id__in=list(self.sessions)).values_list(
            "activity_id", "school_id", "invited", "attended", "is_guest"
        ):
            rows[activity_id].append((school_pk, invited, attended, guest))
        counted = {
            activity_id: session_school_ids(rows.get(activity_id, []), activity)
            for activity_id, activity in self.sessions.items()
        }
        code_of = dict(
            School.objects.filter(
                id__in={pk for pks in counted.values() for pk in pks},
                school_type="core",
                deleted_at__isnull=True,
            ).values_list("id", "school_id")
        )
        #: (school code, fiscal year) -> the group trainings that count there.
        self.wanted = defaultdict(list)
        for activity_id, pks in counted.items():
            activity = self.sessions[activity_id]
            for pk in pks:
                if pk in code_of:
                    self.wanted[(code_of[pk], str(activity.fy))].append(activity)

        #: (school code, package year) -> the slots a group training holds.
        self.current = defaultdict(list)
        for slot in (
            Slot.objects.filter(
                activity_type="training", activity_id__in=group.values("id")
            )
            .select_related("core_plan")
            .order_by("core_plan_id", "sequence_number")
        ):
            if str(slot.core_plan.fy) >= from_fy or slot.activity_id in self.sessions:
                self.current[(slot.school_id, str(slot.core_plan.fy))].append(slot)

        self.keys = sorted(set(self.wanted) | set(self.current))
        codes = {code for code, _fy in self.keys}
        self.used = defaultdict(lambda: {"staff": 0, "partner": 0})
        if not codes:
            return
        at_school = (
            Activity.objects.filter(
                school__school_id__in=codes,
                fy__gte=from_fy,
                deleted_at__isnull=True,
                cluster_id__isnull=True,
                activity_type__in=SCHOOL_TRAINING_TYPES,
            )
            .exclude(status__in=UNCREDITED)
            .exclude(purpose_type__in=NON_PACKAGE_PURPOSES)
        )
        if skip:
            at_school = at_school.exclude(project_id__in=list(skip))
        for code, fy, delivery, n in (
            at_school.values_list("school__school_id", "fy", "delivery_type")
            .annotate(n=Count("id"))
            .order_by()
        ):
            side = "partner" if delivery == "partner" else "staff"
            self.used[(code, str(fy))][side] += n
        for slot in (
            Slot.objects.filter(
                activity_type="training",
                school_id__in=codes,
                core_plan__fy__gte=from_fy,
                owner="partner",
            )
            .filter(Q(activity_id__isnull=True) | Q(activity_id=""))
            .select_related("core_plan")
        ):
            # A hand-over a Partner has not dated holds its slot.
            if not is_open(slot.status):
                self.used[(slot.school_id, str(slot.core_plan.fy))]["partner"] += 1

        #: What ``release`` leaves for ``place``.
        self.to_place: dict[tuple, list] = {}
        self.carried: dict[tuple, dict] = {}

    def _why_not(self, slot, key, full) -> str:
        session = self.sessions.get(slot.activity_id)
        if session is None:
            return "the session is not a live group training of this year"
        if str(session.fy) != key[1]:
            return f"it is dated in FY{session.fy}"
        if session not in self.wanted.get(key, []):
            return "the school is not on its list"
        side = side_of(session)
        if session.id in full:
            return f"the {side} half already has its {SIDE_CAP} trainings"
        return "it already holds a slot of this package"

    def release(self, *, write, say, report, touched, label_of) -> None:
        for key in self.keys:
            count = dict(self.used[key])
            kept, full = [], set()
            for session in sorted(
                self.wanted.get(key, []),
                key=lambda a: (_day(a), str(a.created_at), a.id),
            ):
                side = side_of(session)
                if count[side] < SIDE_CAP:
                    count[side] += 1
                    kept.append(session)
                else:
                    full.add(session.id)
            kept_ids = {session.id for session in kept}
            holding: set[str] = set()
            for slot in self.current.get(key, []):
                if slot.activity_id in kept_ids and slot.activity_id not in holding:
                    holding.add(slot.activity_id)
                    continue
                plan = slot.core_plan
                self.carried.setdefault(
                    (key[0], slot.activity_id),
                    {name: getattr(slot, name) for name in SLOT_WORK_FIELDS},
                )
                report["released"].append(
                    {"slot": slot.id, "activity": slot.activity_id}
                )
                say(
                    f"school {plan.school_id}: FY{plan.fy} {label_of(slot)} released "
                    f"from group training {slot.activity_id}: "
                    f"{self._why_not(slot, key, full)}"
                )
                if write:
                    _clear(slot)
                    slot.save()
                    touched[plan.id] = plan
            self.to_place[key] = [s for s in kept if s.id not in holding]

    def place(self, *, write, say, report, touched, label_of) -> None:
        for key in self.keys:
            code, fy = key
            for session in self.to_place.get(key, []):
                plan, created = (
                    ensure_plan(self.Plan, self.Slot, code, fy)
                    if write
                    else (
                        self.Plan.objects.filter(school_id=code, fy=fy)
                        .exclude(status__in=CLOSED_PLAN_STATUSES)
                        .first(),
                        False,
                    )
                )
                if created:
                    report["plans"].append(plan.id)
                    say(f"school {code}: FY{fy} package made")
                entry = {"activity": session.id, "school": code, "to_fy": fy}
                if write:
                    slot = None
                    if plan is not None:
                        slot = next(
                            (
                                candidate
                                for candidate in self.Slot.objects.filter(
                                    core_plan=plan, activity_type="training"
                                ).order_by("sequence_number")
                                if is_open(candidate.status)
                                and not candidate.activity_id
                            ),
                            None,
                        )
                    if slot is None:
                        report["unplaced"].append(session.id)
                        say(
                            f"school {code}: group training {session.id} "
                            f"({_day(session)}) takes no FY{fy} slot: none is open"
                        )
                        continue
                    carried = self.carried.get((code, session.id))
                    if carried:
                        for name, value in carried.items():
                            setattr(slot, name, value)
                        slot.owner = side_of(session)
                    else:
                        _fill_from_session(slot, session)
                    slot.save()
                    touched[plan.id] = plan
                    entry["to"] = f"FY{fy} {label_of(slot)}"
                report["credited"].append(entry)
                say(
                    f"school {code}: group training {session.id} ({_day(session)}) "
                    f"-> {entry.get('to', 'a training slot of FY' + fy)} "
                    f"({side_of(session)} half)"
                )


def refile(
    Plan,
    Slot,
    Activity,
    Attendance,
    School,
    *,
    from_fy: str,
    write: bool = True,
    out=print,
    tag: str = "refile_core_package_work",
    outside_projects=(),
) -> dict:
    """Put every Core package's work in the package of its own year, and take
    out of the packages what is no part of one.

    1. For packages of ``from_fy`` onward: a slot held by a cluster meeting or
       by a data collection visit is given back.
    2. A slot a group training holds where the rule does not have it — another
       year's package, a school off its list, a half that already has its two
       — is given back (``_GroupTrainings``).
    3. School visits and trainings linked to another year's package move to
       the package of the year they are dated in, oldest first so the
       earliest is V1. The slot they leave is open again.
    4. The group trainings that count and hold no slot take one.
    5. The packages touched in those years lose their gaps: taken slots first,
       earliest dated first.

    ``outside_projects`` are the projects no SSA intervention measures
    (Alumni), whose work is no part of a package. Nothing is removed and no
    activity is changed: only which package slot points at it. Returns what
    was (or, with ``write=False``, would be) done.
    """
    report = {
        "moved": [],
        "unplaced": [],
        "released": [],
        "credited": [],
        "plans": [],
    }
    touched: dict[str, object] = {}

    def say(line: str) -> None:
        out(f"[{tag}] {line}")

    def label_of(slot) -> str:
        return f"{SLOT_LETTER[slot.activity_type].upper()}{slot.sequence_number}"

    # 1. Work that is no part of a package gives its slot back.
    for slot, activity in outside_package(Slot, Activity, from_fy=from_fy):
        plan = slot.core_plan
        why = (
            "a cluster meeting is not a training"
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

    # 2. Group trainings where the rule does not have them.
    group = _GroupTrainings(
        Plan,
        Slot,
        Activity,
        Attendance,
        School,
        from_fy=from_fy,
        skip=outside_projects,
    )
    passes = {
        "write": write,
        "say": say,
        "report": report,
        "touched": touched,
        "label_of": label_of,
    }
    group.release(**passes)

    # 3. School-level work in another year's package.
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

    # 4. The group trainings that count take their slots.
    group.place(**passes)

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
        f"{len(report['released'])} slot(s) given back, "
        f"{len(report['moved'])} visit(s)/training(s) moved to their own year's "
        f"package, {len(report['credited'])} group training place(s) filled, "
        f"{len(report['plans'])} package(s) made, {len(report['unplaced'])} "
        "left in place"
    )
    return report


__all__ = [
    "CLUSTER_MEETING_TYPES",
    "CLUSTER_SESSION_TYPES",
    "CLUSTER_TRAINING_TYPES",
    "SESSION_CREDITED_STATUSES",
    "SESSION_LIVE_STATUSES",
    "SESSION_PLANNED_STATUSES",
    "SIDE_CAP",
    "ensure_plan",
    "is_group_training",
    "is_open",
    "is_package_work",
    "misfiled",
    "outside_package",
    "plan_id",
    "refile",
    "session_school_ids",
    "side_of",
    "slot_id",
]
