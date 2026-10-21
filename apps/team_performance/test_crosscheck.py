"""Every figure the ledger gives, recounted another way.

Owner, 2026-10-20: "tripple check every logic and calculation". A seeded,
random year of records — every activity status, visits and trainings by staff
and partners, online and in-school, cluster sessions with registers and with
the legacy attended list, school-less meetings, the Alumni project, Core
package slots, SSAs in every verification state, dates just outside the year
— is counted twice: by `Ledger`, and by the plain reading of the rules in
docs/team-performance-report.md below, which shares no code with it bar the
measures' definitions. Every work, Core package, SSA and new-school figure,
achieved and planned, must agree for the country, each officer and a pair of
officers, over every month, every quarter to date and the year.
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone as dt_tz

from apps.activities.cluster_attendance import CLUSTER_TRAINING_TYPES
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.activity_catalogue.models import ActivityCatalogueItem
from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    PROGRAMME_EVENT_TYPES,
    TRAINING_TYPES,
    VISIT_TYPES,
)
from apps.core_schools.models import CoreActivitySlot, CorePlan
from apps.projects.models import Project
from apps.schools.models import School
from apps.ssa.models import SsaRecord
from apps.team_performance import measures
from apps.team_performance.ledger import Ledger
from apps.team_performance.measures import Facts
from apps.team_performance.test_ledger import FY, YEAR, LedgerFixture, make_officer

#: The rules, restated (docs/team-performance-report.md).
ACHIEVED = {
    "submitted_to_pl",
    "awaiting_ia_verification",
    "ia_verified",
    "accountant_confirmed",
    "closed",
    "completed",
}
PLANNED = ACHIEVED | {
    "planned",
    "scheduled",
    "rescheduled",
    "partner_scheduled",
    "assigned_to_partner",
    "in_progress",
    "completion_started",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "returned_by_pl",
    "returned",
    "returned_by_ia",
}
OUT = ["cancelled", "rejected", "deferred", "not_planned", "awaiting_owner_approval"]
SESSIONS = set(CLUSTER_TRAINING_TYPES) | set(CLUSTER_MEETING_TYPES)
SLOT_DONE = {"completed", "closed", "ia_verified", "accountant_confirmed"}
COURSES = [code for code, _label in measures.COURSE_ROWS] + [
    "CC_SEL",
    "SSA_TRAINING",
    "BIBLICAL_INTEGRATION",
    "CORE_SCHOOL_ORIENTATION",
    "BT_UG_ACCOUNTANT_TRAINING",
]
EVENTS = [
    "FIELD_DISTRICT_MEETING",
    "PARTNER_MEETINGS_ADMIN",
    "STUDENT_LEADERSHIP_CAMPS",
]
FY_START, FY_END = YEAR


def _kind(activity_type: str) -> str:
    if activity_type in VISIT_TYPES:
        return "visit"
    if activity_type in TRAINING_TYPES:
        return "training"
    if activity_type in CLUSTER_MEETING_TYPES:
        return "meeting"
    if activity_type in PROGRAMME_EVENT_TYPES:
        return "event"
    return "other"


def _inside(day: date) -> date:
    return min(max(day, FY_START), FY_END - timedelta(days=1))


class Reference:
    """The rules, read plainly: events per measure as (holder, day, unit, qty)."""

    def __init__(self):
        self.done = defaultdict(list)
        self.plan = defaultdict(list)
        self.owner = {}
        self.core = {}
        for school in School.objects.filter(deleted_at__isnull=True):
            self.owner[str(school.pk)] = school.account_owner_id or None
            self.core[str(school.pk)] = school.school_type in ("core", "champion")
        for school in School.objects.filter(deleted_at__isnull=True):
            created = school.created_at.astimezone(dt_tz.utc).date()
            self._put(
                self.done, "new_schools", str(school.pk), None, created, school.pk
            )
        self.alumni = set(
            Project.objects.filter(name__icontains="alumni").values_list(
                "id", flat=True
            )
        )
        for activity in Activity.objects.filter(fy=FY, deleted_at__isnull=True):
            if activity.status in PLANNED:
                self._work(activity)
        self._package()
        self._ssa()

    def _put(self, store, key, school, officer, day, unit, qty=1):
        if day is None or not FY_START <= day < FY_END:
            return
        holder = self.owner.get(school) if school else officer
        store[key].append((holder, day, unit, qty))

    def _work(self, a: Activity):
        course = a.training_course.stable_code if a.training_course_id else ""
        item = a.catalogue_item.stable_code if a.catalogue_item_id else ""
        method = a.delivery_method_snapshot or (
            a.catalogue_item.delivery_method if a.catalogue_item_id else ""
        )
        kind = _kind(a.activity_type)
        if kind == "meeting" and a.meeting_kind == "training":
            kind = "training"
        sched = a.scheduled_date.date() if a.scheduled_date else None
        done_on = a.actual_delivery_date or a.planned_date or sched
        plan_on = a.planned_date or sched or a.actual_delivery_date
        complete = a.status in ACHIEVED
        # Who it reached: its school; else a session's register (invited for
        # the plan, attended for achievement), else its legacy attended list;
        # else, school-less, the officer responsible.
        reached = []  # (school, achieved, planned)
        officer_done = officer_plan = False
        if a.school_id:
            reached = [(str(a.school_id), complete, True)]
        else:
            register = list(
                ClusterActivityAttendance.objects.filter(activity=a).exclude(
                    invited=False, attended=False
                )
            )
            if a.activity_type in SESSIONS and register:
                reached = [
                    (str(r.school_id), complete and r.attended, True) for r in register
                ]
                officer_done = complete and not any(r.attended for r in register)
            elif a.activity_type in SESSIONS and a.attended_school_ids:
                reached = [(str(s), complete, True) for s in a.attended_school_ids]
            else:
                officer_done, officer_plan = complete, True
        for school, achieved, planned in reached + [(None, officer_done, officer_plan)]:
            if school is not None and school not in self.owner:
                continue
            facts = Facts(
                kind=kind,
                core=self.core[school] if school else None,
                topic=course or item,
                online=method == "online",
                partner=a.delivery_type == "partner",
                activity_type=a.activity_type,
                meeting=a.meeting_kind or "",
                alumni=a.project_id in self.alumni,
            )
            for m in measures.WORK_MEASURES:
                if not m.match(facts):
                    continue
                if m.unit == measures.SCHOOLS:
                    if school is None:
                        continue
                    unit, qty = school, 1
                elif m.unit == measures.PARTICIPANTS:
                    people = {
                        "teachers": a.teachers_attended or 0,
                        "leaders": a.leaders_attended or 0,
                    }
                    qty = people.get(m.people, sum(people.values()))
                    unit = a.id
                else:
                    unit, qty = a.id, 1
                officer = a.responsible_staff_id
                if achieved:
                    self._put(self.done, m.key, school, officer, done_on, unit, qty)
                if planned:
                    self._put(self.plan, m.key, school, officer, plan_on, unit, qty)

    def _package(self):
        activities = {a.id: a for a in Activity.objects.filter(deleted_at__isnull=True)}
        days = {"done": defaultdict(list), "plan": defaultdict(list)}
        for slot in CoreActivitySlot.objects.filter(core_plan__fy=FY):
            school = School.objects.get(school_id=slot.school_id)
            a = activities.get(slot.activity_id)
            key = (str(school.pk), slot.activity_type)
            if a is None:
                if slot.status in SLOT_DONE and slot.completed_at:
                    day = slot.completed_at.astimezone(dt_tz.utc).date()
                    days["done"][key].append(day)
                    days["plan"][key].append(day)
                continue
            if a.status in ACHIEVED:
                days["done"][key].append(a.actual_delivery_date or a.planned_date)
            if a.status in PLANNED:
                days["plan"][key].append(a.planned_date or a.actual_delivery_date)
        for which, store in (("done", self.done), ("plan", self.plan)):
            for (school, kind), dated in days[which].items():
                for n, day in enumerate(sorted(map(_inside, dated))[:4], start=1):
                    self._put(store, f"core_{kind}_{n}", school, None, day, school)

    def _ssa(self):
        for r in SsaRecord.objects.filter(
            fy=FY,
            deleted_at__isnull=True,
            verification_status__in=("pending", "confirmed"),
        ):
            school = str(r.school_id)
            day = _inside(r.date_of_ssa.astimezone(dt_tz.utc).date())
            key = "ssa_client" if not self.core[school] else "ssa_core_followup"
            self._put(self.done, key, school, None, day, school)
            self._put(self.done, "ssa_all", school, None, day, school)

    def count(self, store, key, owners, start, end):
        seen = {}
        for holder, day, unit, qty in store.get(key, []):
            if (owners is None or holder in owners) and start <= day < end:
                seen[unit] = qty
        if key in measures.PARTICIPANT_KEYS:
            return sum(seen.values())
        return len(seen)


class CrossCheckTest(LedgerFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        rng = random.Random(20261020)
        cls.ann = make_officer("ann@tp.test")
        officers = [cls.james, cls.mary, cls.ann]
        schools = [cls.core, cls.client_school, cls.other]
        for n in range(24):
            owner = officers[n % 3]
            kind = "core" if n % 3 == 0 else "client"
            school = cls.school(f"TP-X{n:02}", owner, kind)
            # Added before, inside and just after the year.
            School.objects.filter(pk=school.pk).update(
                created_at=datetime(2026, 9, 25, tzinfo=dt_tz.utc)
                + timedelta(days=rng.randint(0, 380))
            )
            schools.append(school)
        # A school nobody holds counts for the country alone.
        School.objects.filter(pk=schools[5].pk).update(account_owner_id=None)
        alumni = Project.objects.create(
            code="TP-ALUMNI", name="Alumni", category="selective_limited"
        )
        items = {
            i.stable_code: i
            for i in ActivityCatalogueItem.objects.filter(
                stable_code__in=COURSES + EVENTS
            )
        }

        def day():
            return FY_START + timedelta(days=rng.randint(-8, 372))

        def work(activity_type, **extra):
            planned = day()
            # Mostly done, some under way or booked, a few out of the plan.
            pool = rng.choices(
                [sorted(ACHIEVED), sorted(PLANNED - ACHIEVED), OUT], [5, 3, 2]
            )[0]
            return Activity.objects.create(
                activity_type=activity_type,
                status=rng.choice(pool),
                fy=FY,
                planned_date=planned,
                actual_delivery_date=rng.choice(
                    [None, None, planned + timedelta(days=rng.randint(-20, 20))]
                ),
                delivery_type=rng.choice(["staff", "staff", "partner"]),
                delivery_method_snapshot=rng.choice([None, "in_person", "online"]),
                teachers_attended=rng.randint(0, 9),
                leaders_attended=rng.randint(0, 4),
                responsible_staff_id=rng.choice(officers).staff_profile.id,
                project_id=alumni.id if rng.random() < 0.1 else None,
                **extra,
            )

        for _ in range(160):
            work(
                rng.choice(["school_visit", "core_visit", "follow_up_visit"]),
                school=rng.choice(schools),
            )
        for _ in range(400):
            work(
                rng.choice(["in_school_training", "training"]),
                school=rng.choice(schools),
                catalogue_item=items[rng.choice(COURSES)],
                training_course=items[rng.choice(COURSES)]
                if rng.random() < 0.4
                else None,
            )
        for _ in range(60):
            session = work(
                rng.choice(
                    [
                        "cluster_training",
                        "cluster_meeting",
                        "cluster_meeting_ssa_review",
                    ]
                ),
                cluster=cls.cluster,
                catalogue_item=items[rng.choice(COURSES)]
                if rng.random() < 0.6
                else None,
                meeting_kind=rng.choice(
                    ["", "training", "only_meeting", "cluster_leaders"]
                ),
            )
            style = rng.random()
            invited = rng.sample(schools, rng.randint(1, 6))
            if style < 0.5:
                for school in invited:
                    ClusterActivityAttendance.objects.create(
                        activity=session,
                        school=school,
                        invited=True,
                        attended=rng.random() < 0.6,
                    )
            elif style < 0.75:
                session.attended_school_ids = [str(s.pk) for s in invited]
                session.save(update_fields=["attended_school_ids"])
        for _ in range(30):
            work(
                rng.choice(["field_event", "youth_camp", "admin"]),
                cluster=cls.cluster,
                catalogue_item=items[rng.choice(EVENTS)],
            )
        for school in [s for s in schools if s.school_type == "core"]:
            plan = CorePlan.objects.create(
                id=f"cplan-{school.school_id}-{FY}", school_id=school.school_id, fy=FY
            )
            for kind in ("visit", "training"):
                for n in range(1, rng.randint(2, 6)):
                    linked = rng.random() < 0.8
                    activity = (
                        work(
                            "core_visit" if kind == "visit" else "in_school_training",
                            school=school,
                        )
                        if linked
                        else None
                    )
                    CoreActivitySlot.objects.create(
                        id=f"cslot-{school.school_id}-{kind[0]}{n}-{FY}",
                        core_plan=plan,
                        school_id=school.school_id,
                        intervention="leadership",
                        activity_type=kind,
                        sequence_number=n,
                        status=rng.choice(["Planned", "completed", "ia_verified"]),
                        completed_at=datetime.combine(
                            day(), datetime.min.time(), dt_tz.utc
                        ),
                        activity_id=activity.id if activity else None,
                    )
        for school in schools:  # one live SSA per school and year
            for _ in range(rng.random() < 0.8):
                SsaRecord.objects.create(
                    school=school,
                    fy=FY,
                    quarter="Q1",
                    date_of_ssa=datetime.combine(day(), datetime.min.time(), dt_tz.utc),
                    average_score=5.0,
                    verification_status=rng.choice(
                        ["pending", "confirmed", "returned", "flagged"]
                    ),
                    uploaded_by="test",
                )

    def test_every_figure_agrees_with_the_plain_reading_of_the_rules(self):
        ledger, ref = Ledger.load(FY), Reference()
        staff = [o.staff_profile.id for o in (self.james, self.mary, self.ann)]
        scopes = [None, *({s} for s in staff), set(staff[:2])]
        windows = [YEAR]
        for m in range(12):
            start = date(2026 + (m + 9) // 12, (m + 9) % 12 + 1, 1)
            following = date(start.year + start.month // 12, start.month % 12 + 1, 1)
            windows.append((start, following))
            if m % 3 == 2:
                windows.append((FY_START, following))
        keys = [m.key for m in measures.WORK_MEASURES] + [
            f"core_{k}_{n}" for k in ("visit", "training") for n in (1, 2, 3, 4)
        ]
        checked = 0
        for key in [*keys, "ssa_client", "ssa_core_followup", "ssa_all", "new_schools"]:
            for owners in scopes:
                for start, end in windows:
                    got = ledger.count(key, owners, start, end)
                    want = ref.count(ref.done, key, owners, start, end)
                    self.assertEqual(got, want, f"{key} {owners} {start}–{end}")
                    checked += 1
                    if key in keys:
                        got = ledger.planned(key, owners, start, end)
                        want = ref.count(ref.plan, key, owners, start, end)
                        self.assertEqual(got, want, f"planned {key} {owners} {start}")
                        checked += 1
        # The data reached nearly every kind of row, so a silent 0 cannot pass.
        empty = [k for k in keys if not ref.count(ref.done, k, None, *YEAR)]
        self.assertLessEqual(len(empty), 3, empty)
        self.assertGreater(checked, 10_000)
