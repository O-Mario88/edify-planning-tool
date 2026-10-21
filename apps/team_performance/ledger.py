"""One read of a year's records, as dated events per measure per officer.

Every Team Performance figure is a count over a date window: the month, a
quarter to date, the year, or the year as it stood at the end of last week.
So the records are read once, each turned into events — (day, unit,
quantity), filed under the measure it counts toward and the officer whose
school it was — and every window is a slice of those lists. The page asks
thousands of questions of one read; none goes back to the database.

The rules (docs/team-performance-report.md):

* work is achieved "when the officer completes it" (owner, 2026-10-20): from
  submission to the PL on (`ACHIEVED_STATUSES`). Work sent back, cancelled or
  rejected is not, and comes back in when it is submitted again. It is dated
  by the day it was done (`actual_delivery_date`), else the day it was planned;
* work is planned while it is in somebody's plan — not started, under way or
  done (`PLANNED_STATUSES`) — dated by the day it was planned for. Records
  that nobody plans (SSAs, uploads, stories, loans) have no planned figure;
* a cluster session reaches the schools that attended it, through the
  attendance register and the legacy attended list; it was planned for the
  schools invited to it as well;
* a Core school's visits and trainings are its package slots, each counted by
  the status of the work done in it;
* uploaded and typed records count "once uploaded" (owner, 2026-10-20):
  pending or confirmed, never returned or flagged (`UPLOADED_STATUSES`);
* work is credited to the school's account owner, whoever delivered it.
"""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.core.activity_types import (
    CLUSTER_MEETING_TYPES,
    COMPLETED_WORK_STATUSES,
    NOT_STARTED_ACTIVITY_STATUSES,
    PROGRAMME_EVENT_TYPES,
    TRAINING_TYPES,
    UNDER_WAY_ACTIVITY_STATUSES,
    VISIT_TYPES,
)
from apps.core.fy import get_fy_date_range

from . import measures
from .measures import Facts

#: Disbursed loans: everything after the lender paid out, cancelled excluded.
DISBURSED_LOAN_STATUSES = ("disbursed", "active", "repaid", "defaulted")
ACTIVE_STATUSES = ("active", "reopened")
#: Achieved: the officer has completed it and sent it on (owner, 2026-10-20,
#: "When the officer completes it"). A Salesforce ID comes before submission,
#: so work waiting for one is not complete yet.
ACHIEVED_STATUSES = frozenset(
    ("submitted_to_pl", "awaiting_ia_verification", *COMPLETED_WORK_STATUSES)
)
#: In somebody's plan: not started, under way or done. Cancelled, rejected,
#: deferred and unplanned work, and a request still awaiting its owner's
#: approval, is in no one's plan.
PLANNED_STATUSES = frozenset(
    (
        *NOT_STARTED_ACTIVITY_STATUSES,
        *UNDER_WAY_ACTIVITY_STATUSES,
        *COMPLETED_WORK_STATUSES,
    )
)
#: Uploaded or typed records count once uploaded (owner, 2026-10-20); one
#: returned or flagged by its reviewer does not.
UPLOADED_STATUSES = ("pending", "confirmed")

_WORK_FIELDS = (
    "id",
    "activity_type",
    "catalogue_item__stable_code",
    "training_course__stable_code",
    "delivery_method_snapshot",
    "catalogue_item__delivery_method",
    "delivery_type",
    "actual_delivery_date",
    "planned_date",
    "scheduled_date",
    "teachers_attended",
    "leaders_attended",
    "meeting_kind",
    "project_id",
)


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


def _day(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return (
            timezone.localtime(value).date()
            if timezone.is_aware(value)
            else value.date()
        )
    return value


class _School:
    __slots__ = (
        "pk",
        "code",
        "owner",
        "core",
        "active",
        "start",
        "closed",
        "clustered",
        "region",
    )

    def __init__(self, pk, code, owner, core, active, start, closed, clustered, region):
        self.pk = pk
        self.code = code
        self.owner = owner
        self.core = core
        self.active = active
        self.start = start
        self.closed = closed
        self.clustered = clustered
        self.region = region


class Ledger:
    """The year's records as events; `count` answers any window."""

    def __init__(self, fy: str):
        self.fy = str(fy)
        start, end = get_fy_date_range(self.fy)
        self.fy_start, self.fy_end = start.date(), end.date()
        #: Any id a school's owner is written as -> the officer's staff id.
        self.officer_of: dict[str, str] = {}
        self.schools: dict[str, _School] = {}
        self._by_code: dict[str, str] = {}
        # measure -> officer (None for a school nobody holds) -> sorted events
        self._events: dict[str, dict[str | None, list]] = defaultdict(
            lambda: defaultdict(list)
        )
        #: The same for planned work, dated by the day it was planned for.
        self._planned: dict[str, dict[str | None, list]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._matches: dict[Facts, tuple[str, ...]] = {}
        self.recruits: dict[str, date] = {}
        #: School -> the year's latest SSA average.
        self.ssa_scores: dict[str, float] = {}
        #: The Alumni project(s), whose work is the Alumni Data row.
        self.alumni_projects: frozenset[str] = frozenset()
        #: Every region of the country, in the workbook's order.
        self.regions: list[str] = []
        #: A counted record that is not a school (a session, a story) -> how
        #: many of the schools it reached are in each region.
        self._unit_regions: dict = defaultdict(Counter)
        #: Narrowed to some officers' schools: reads ask for those schools only.
        self.narrowed = False

    # ── Loading ─────────────────────────────────────────────────────────────
    @classmethod
    def load(cls, fy: str, *, owners: set[str] | None = None) -> Ledger:
        """Read the year. ``owners`` (staff ids) narrows it to their schools,
        for a reader who sees only their own."""
        ledger = cls(fy)
        ledger._load_officers()
        ledger._load_alumni_projects()
        ledger.narrowed = owners is not None
        ledger._load_schools(owners)
        ledger._load_regions()
        if ledger.schools or owners is None:
            ledger._load_work()
            ledger._load_core_package()
            ledger._load_recruits()
            ledger._load_ssa()
            ledger._load_evidence()
            ledger._load_msc(owners)
            ledger._load_loans()
        ledger._load_unattached_events(owners)
        for store in (ledger._events, ledger._planned):
            for streams in store.values():
                for events in streams.values():
                    events.sort(key=_first)
        return ledger

    def _load_officers(self) -> None:
        from apps.accounts.models import StaffProfile

        for staff_id, user_id in StaffProfile.objects.values_list("id", "user_id"):
            self.officer_of[str(staff_id)] = str(staff_id)
            if user_id:
                self.officer_of[str(user_id)] = str(staff_id)

    def _load_alumni_projects(self) -> None:
        """The Alumni project, by name or code: the platform keeps no other
        mark of it (it is the project that targets General only)."""
        from apps.projects.models import Project

        self.alumni_projects = frozenset(
            Project.objects.filter(deleted_at__isnull=True)
            .filter(Q(name__icontains="alumni") | Q(code__icontains="alumni"))
            .values_list("id", flat=True)
        )

    def _load_schools(self, owners) -> None:
        from apps.hr.target_distribution import CORE_FAMILY
        from apps.schools.models import School

        rows = School.objects.filter(deleted_at__isnull=True)
        if owners is not None:
            identities = {k for k, v in self.officer_of.items() if v in owners}
            rows = rows.filter(account_owner_id__in=identities)
        for row in rows.values_list(
            "id",
            "school_id",
            "account_owner_id",
            "school_type",
            "operational_status",
            "created_at",
            "closure_effective_date",
            "closed_at",
            "cluster_id",
            "region__name",
        ):
            (
                pk,
                code,
                owner,
                kind,
                status,
                created,
                closes,
                closed_at,
                cluster,
                region,
            ) = row
            school = _School(
                pk=str(pk),
                code=code or "",
                owner=self.officer_of.get(str(owner)) if owner else None,
                core=kind in CORE_FAMILY,
                active=status in ACTIVE_STATUSES,
                start=_day(created),
                closed=None
                if status in ACTIVE_STATUSES
                else (closes or _day(closed_at)),
                clustered=bool(cluster),
                region=(region or "").replace(" Region", "").strip(),
            )
            self.schools[school.pk] = school
            if school.code:
                self._by_code[school.code] = school.pk
            # Added to the platform this year, typed in or uploaded: a new
            # school (owner, 2026-10-20).
            self._add("new_schools", school, school.start, school.pk)

    def _load_regions(self) -> None:
        from apps.geography.models import Region

        from .roster import REGION_ORDER

        names = [
            name.replace(" Region", "").strip()
            for name in Region.objects.filter(country="Uganda").values_list(
                "name", flat=True
            )
        ]
        self.regions = sorted(
            names,
            key=lambda n: (
                REGION_ORDER.index(n) if n in REGION_ORDER else len(REGION_ORDER),
                n,
            ),
        )

    def _within(self, day: date) -> date:
        """A record of the year dated outside it, placed on its nearest day."""
        return min(max(day, self.fy_start), self.fy_end - timedelta(days=1))

    def _school(self, ref) -> _School | None:
        """A school by its id or its School ID (Core plans write either)."""
        if ref is None:
            return None
        ref = str(ref)
        return self.schools.get(ref) or self.schools.get(self._by_code.get(ref, ""))

    def _add(
        self,
        key: str,
        school: _School | None,
        day,
        unit,
        qty: int = 1,
        owner=None,
        *,
        store=None,
    ):
        if day is None or not (self.fy_start <= day < self.fy_end):
            return
        holder = school.owner if school is not None else owner
        (self._events if store is None else store)[key][holder].append((day, unit, qty))

    def _facts(
        self, row, school: _School | None
    ) -> tuple[Facts, date | None, date | None, dict[str, int]]:
        (
            _id,
            activity_type,
            item_code,
            course_code,
            method,
            item_method,
            delivery,
            actual,
            planned,
            scheduled,
            teachers,
            leaders,
            meeting_kind,
            project_id,
        ) = row
        kind = _kind(activity_type)
        if kind == "meeting" and meeting_kind == "training":
            # A cluster meeting held as a Training delivers a catalogue
            # course (owner, 2026-10-06): it is a training.
            kind = "training"
        facts = Facts(
            kind=kind,
            core=school.core if school is not None else None,
            topic=course_code or item_code or "",
            online=(method or item_method) == "online",
            partner=delivery == "partner",
            activity_type=activity_type,
            meeting=meeting_kind or "",
            alumni=bool(project_id) and project_id in self.alumni_projects,
        )
        planned_for = planned or _day(scheduled)
        return (
            facts,
            actual or planned_for,
            planned_for or actual,
            {
                "teachers": teachers or 0,
                "leaders": leaders or 0,
                "": (teachers or 0) + (leaders or 0),
            },
        )

    def _keys_for(self, facts: Facts) -> tuple[str, ...]:
        keys = self._matches.get(facts)
        if keys is None:
            keys = tuple(m.key for m in measures.WORK_MEASURES if m.match(facts))
            self._matches[facts] = keys
        return keys

    def _credit(
        self,
        row,
        school: _School | None,
        *,
        owner=None,
        achieved: bool = True,
        planned: bool = True,
    ) -> None:
        """Work into the plan, and into achievement once completed."""
        facts, done_on, planned_for, headcount = self._facts(row, school)
        activity_id = row[0]
        if school is not None:
            self._unit_regions[activity_id][school.region] += 1
        for key in self._keys_for(facts):
            measure = measures.BY_KEY[key]
            unit = measure.unit
            if unit == measures.SCHOOLS:
                if school is None:
                    continue
                ref, qty = school.pk, 1
            elif unit == measures.PARTICIPANTS:
                ref, qty = activity_id, headcount[measure.people]
            elif unit == measures.SESSIONS:
                ref, qty = activity_id, 1
            else:
                continue
            if achieved:
                self._add(key, school, done_on, ref, qty, owner=owner)
            if planned:
                self._add(
                    key, school, planned_for, ref, qty, owner=owner, store=self._planned
                )

    def _load_work(self) -> None:
        from apps.activities.cluster_attendance import CLUSTER_TRAINING_TYPES
        from apps.activities.models import Activity, ClusterActivityAttendance

        live = Activity.objects.filter(
            deleted_at__isnull=True, fy=self.fy, status__in=PLANNED_STATUSES
        )
        own = live.filter(school_id__isnull=False)
        register = ClusterActivityAttendance.objects.filter(
            Q(invited=True) | Q(attended=True)
        )
        if self.narrowed:
            own = own.filter(school_id__in=list(self.schools))
            register = register.filter(school_id__in=list(self.schools))
        # Work at one school.
        for row in own.values_list("school_id", "status", *_WORK_FIELDS):
            school = self.schools.get(str(row[0]))
            if school is not None:
                self._credit(row[2:], school, achieved=row[1] in ACHIEVED_STATUSES)

        # Cluster sessions: planned for each school invited or attending,
        # achieved for each that attended.
        sessions = CLUSTER_TRAINING_TYPES + CLUSTER_MEETING_TYPES
        registered = set()
        for row in register.filter(
            activity__deleted_at__isnull=True,
            activity__fy=self.fy,
            activity__status__in=PLANNED_STATUSES,
            activity__activity_type__in=sessions,
        ).values_list(
            "school_id",
            "attended",
            "activity__status",
            *(f"activity__{f}" for f in _WORK_FIELDS),
        ):
            registered.add(row[3])
            school = self.schools.get(str(row[0]))
            if school is not None:
                done = row[1] and row[2] in ACHIEVED_STATUSES
                self._credit(row[3:], school, achieved=done)

        # Attendance recorded before the register existed.
        for row in (
            live.filter(activity_type__in=sessions)
            .exclude(attended_school_ids=[])
            .exclude(id__in=registered)
            .values_list("attended_school_ids", "status", *_WORK_FIELDS)
        ):
            for school_id in row[0] or []:
                school = self.schools.get(str(school_id))
                if school is not None:
                    self._credit(row[2:], school, achieved=row[1] in ACHIEVED_STATUSES)

    def _load_unattached_events(self, owners=None) -> None:
        """Work at no school (camps, conferences, a meeting with no register),
        credited to the officer responsible for it. A session with schools on
        its register is planned for those schools; it is achieved here only
        when none of them attended."""
        from apps.activities.cluster_attendance import CLUSTER_TRAINING_TYPES
        from apps.activities.models import Activity, ClusterActivityAttendance

        sessions = CLUSTER_TRAINING_TYPES + CLUSTER_MEETING_TYPES
        rows = ClusterActivityAttendance.objects.filter(
            Q(invited=True) | Q(attended=True),
            activity__fy=self.fy,
            activity__school_id__isnull=True,
        )
        attended = rows.filter(attended=True).values("activity_id")
        registered = set(rows.values_list("activity_id", flat=True).distinct())
        for row in (
            Activity.objects.filter(
                deleted_at__isnull=True,
                fy=self.fy,
                status__in=PLANNED_STATUSES,
                school_id__isnull=True,
            )
            # A cluster session with a legacy attended list is credited to
            # those schools (`_load_work`); any other work is the officer's.
            .exclude(Q(activity_type__in=sessions) & ~Q(attended_school_ids=[]))
            .exclude(id__in=attended)
            .values_list("responsible_staff_id", "status", *_WORK_FIELDS)
        ):
            owner = self.officer_of.get(str(row[0])) if row[0] else None
            if owners is not None and owner not in owners:
                continue
            self._credit(
                row[2:],
                None,
                owner=owner,
                achieved=row[1] in ACHIEVED_STATUSES,
                planned=row[2] not in registered,
            )

    def _load_core_package(self) -> None:
        """A Core school's nth package visit or training: its slots, in date
        order, each counted by the status of the work done in it — planned
        while that work is in the plan, achieved once the officer completes
        it. A slot with no work behind it (filled before work was linked)
        counts by its own status."""
        from apps.activities.models import Activity
        from apps.core_schools.models import CoreActivitySlot
        from apps.core_schools.package_year import DONE_STATUSES

        slots = list(
            CoreActivitySlot.objects.filter(
                core_plan__fy=self.fy,
                activity_type__in=("visit", "training"),
            ).values_list(
                "school_id", "activity_type", "activity_id", "completed_at", "status"
            )
        )
        work = {
            str(pk): (
                status,
                actual or planned or _day(scheduled),
                planned or _day(scheduled) or actual,
            )
            for pk, status, actual, planned, scheduled in Activity.objects.filter(
                deleted_at__isnull=True,
                id__in=[s[2] for s in slots if s[2]],
            ).values_list(
                "id",
                "status",
                "actual_delivery_date",
                "planned_date",
                "scheduled_date",
            )
        }
        done: dict[tuple[str, str], list[date]] = defaultdict(list)
        planned: dict[tuple[str, str], list[date]] = defaultdict(list)
        for school_ref, kind, activity_id, completed_at, slot_status in slots:
            school = self._school(school_ref)
            if school is None:
                continue
            linked = work.get(str(activity_id)) if activity_id else None
            if linked is None:
                if slot_status in DONE_STATUSES and completed_at is not None:
                    done[(school.pk, kind)].append(_day(completed_at))
                    planned[(school.pk, kind)].append(_day(completed_at))
                continue
            status, done_on, planned_for = linked
            if status in ACHIEVED_STATUSES and done_on is not None:
                done[(school.pk, kind)].append(done_on)
            if status in PLANNED_STATUSES and planned_for is not None:
                planned[(school.pk, kind)].append(planned_for)
        for dates, store in ((done, None), (planned, self._planned)):
            for (pk, kind), dated in dates.items():
                school = self.schools[pk]
                # The year's package: a slot dated a little outside the year
                # is placed inside it, so the nth slot stays the nth.
                ordered = sorted(self._within(day) for day in dated)
                for n, day in enumerate(ordered[:4], start=1):
                    self._add(f"core_{kind}_{n}", school, day, school.pk, store=store)

    def _load_recruits(self) -> None:
        """The year's Client-to-Core onboardings, which split a Core school's
        SSA into a baseline (onboarded this year) or a follow-up. A Core
        profile's start year is not one — rollover rewrites it for every
        continuing Core school. Recruitment itself is the Core School
        Orientation (`measures`, "core_recruitment")."""
        from apps.core_schools.models import CoreSchoolOnboarding

        for ref, onboarded in CoreSchoolOnboarding.objects.filter(
            fy=self.fy
        ).values_list("school_id", "onboarded_at"):
            school = self._school(ref)
            if school is not None:
                self.recruits[school.pk] = _day(onboarded)

    def _load_ssa(self) -> None:
        from apps.ssa.models import SsaRecord

        for school_id, when, score in (
            SsaRecord.objects.filter(
                fy=self.fy,
                deleted_at__isnull=True,
                verification_status__in=UPLOADED_STATUSES,
            )
            .order_by("date_of_ssa")
            .values_list("school_id", "date_of_ssa", "average_score")
        ):
            school = self.schools.get(str(school_id))
            if school is None:
                continue
            if score is not None:
                # The year's latest score, pending or confirmed.
                self.ssa_scores[school.pk] = float(score)
            if not school.core:
                key = "ssa_client"
            elif school.pk in self.recruits:
                key = "ssa_core_baseline"
            else:
                key = "ssa_core_followup"
            # A year's SSA counts in its year even when it was dated a little
            # outside it, so it is placed inside the year.
            day = self._within(_day(when))
            self._add(key, school, day, school.pk)
            self._add("ssa_all", school, day, school.pk)

    def _load_evidence(self) -> None:
        from apps.impact.models import (
            DiscipleshipIndicatorRecord,
            LearningAssessmentResult,
        )
        from apps.schools.models import SchoolEnrollmentHistory

        uploaded = {
            "fy": self.fy,
            "deleted_at__isnull": True,
            "verification_status__in": UPLOADED_STATUSES,
        }
        for school_id, observed, groups in DiscipleshipIndicatorRecord.objects.filter(
            **uploaded
        ).values_list("school_id", "observed_on", "discipleship_groups_active"):
            school = self.schools.get(str(school_id))
            if school is None:
                continue
            self._add("dc_data", school, observed, school.pk)
            self._add("metrics", school, observed, school.pk)
            if groups:
                self._add("dc_clubs", school, observed, school.pk)
                family = "dc_clubs_core" if school.core else "dc_clubs_client"
                self._add(family, school, observed, school.pk)
        for school_id, assessed, kind in LearningAssessmentResult.objects.filter(
            **uploaded
        ).values_list("school_id", "assessed_on", "assessment_type"):
            school = self.schools.get(str(school_id))
            if school is None:
                continue
            self._add("metrics", school, assessed, school.pk)
            if kind == "onetest":
                self._add("onetest", school, assessed, school.pk)
            elif kind == "national_exam" and school.core:
                self._add("core_exam_scores", school, assessed, school.pk)
        # Enrolment of the year: the school upload and the profile edit set the
        # school's figure and its date (`last_enrollment_date`) and write no
        # history row; completing an SSA Support writes both. Either counts.
        from apps.schools.models import School

        dated = School.objects.filter(
            deleted_at__isnull=True,
            enrollment__isnull=False,
            last_enrollment_date__gte=self.fy_start,
            last_enrollment_date__lt=self.fy_end,
        )
        if self.narrowed:
            dated = dated.filter(id__in=list(self.schools))
        for school_id, day in dated.values_list("id", "last_enrollment_date"):
            school = self.schools.get(str(school_id))
            if school is not None:
                self._add("enrolment", school, day, school.pk)
                self._add("metrics", school, day, school.pk)
        for school_id, recorded in SchoolEnrollmentHistory.objects.filter(
            fy=self.fy
        ).values_list("school_id", "recorded_at"):
            school = self.schools.get(str(school_id))
            if school is None:
                continue
            day = self._within(_day(recorded))
            self._add("enrolment", school, day, school.pk)
            self._add("metrics", school, day, school.pk)

    def _load_msc(self, owners) -> None:
        from apps.targets.models import MostSignificantChangeStory

        for (
            story_id,
            school_id,
            author,
            day,
        ) in MostSignificantChangeStory.objects.filter(
            status="approved",
            story_date__gte=self.fy_start,
            story_date__lt=self.fy_end,
        ).values_list("id", "school_id", "user_id", "story_date"):
            school = self.schools.get(str(school_id)) if school_id else None
            if school is None:
                author_officer = self.officer_of.get(str(author))
                if school_id or (owners is not None and author_officer not in owners):
                    continue
                self._add("msc", None, day, story_id, owner=author_officer)
            else:
                self._add("msc", school, day, story_id)
                self._unit_regions[story_id][school.region] += 1

    def _load_loans(self) -> None:
        from apps.business_transformation.models import MfiLoan

        for loan_id, school_id, day, edtech in MfiLoan.objects.filter(
            deleted_at__isnull=True,
            status__in=DISBURSED_LOAN_STATUSES,
            disbursement_date__isnull=False,
        ).values_list("id", "school_id", "disbursement_date", "purpose__is_edtech"):
            school = self.schools.get(str(school_id))
            if school is None:
                continue
            self._add("loans", school, day, loan_id)
            self._add(
                "edtech_loans" if edtech else "development_loans", school, day, loan_id
            )

    # ── Reading ─────────────────────────────────────────────────────────────
    def count(self, key: str, owners, start: date, end: date) -> int | None:
        """The measure over [start, end) for these officers (None: everyone,
        schools nobody holds included). None when the records cannot give it."""
        measure = measures.BY_KEY[key]
        if not measure.tracked:
            return None
        if measure.source == "active":
            return self.portfolio(owners, "active", as_of=end)
        if measure.source == "in_clusters":
            return self.portfolio(owners, "clustered", as_of=end)
        return self._tally(self._events, measure, owners, start, end)

    def planned(self, key: str, owners, start: date, end: date) -> int | None:
        """The work planned for [start, end), counted as `count` counts it.
        None for a measure nobody plans: an SSA, an upload, a story, a loan."""
        measure = measures.BY_KEY[key]
        if not measure.tracked or not _plannable(measure):
            return None
        return self._tally(self._planned, measure, owners, start, end)

    def region_of(self, unit) -> str:
        """The region a counted school is in; for a session or a story, the
        region most of the schools it reached are in (by name on a tie), so
        each counts once. "" for work that reached no school."""
        school = self.schools.get(str(unit))
        if school is not None:
            return school.region
        reached = self._unit_regions.get(unit)
        if not reached:
            return ""
        return min(reached, key=lambda region: (-reached[region], region))

    def units(self, key: str, owners, start: date, end: date) -> dict:
        """What a measure counted over [start, end): each school, session or
        record and its quantity, for a figure read by where they are."""
        return self._seen(self._events, measures.BY_KEY[key], owners, start, end)

    @classmethod
    def _tally(cls, store, measure, owners, start: date, end: date) -> int:
        seen = cls._seen(store, measure, owners, start, end)
        if measure.key in measures.PARTICIPANT_KEYS:
            return sum(seen.values())
        return len(seen)

    @staticmethod
    def _seen(store, measure, owners, start: date, end: date) -> dict:
        streams = store.get(measure.key) or store.get(measure.source)
        if not streams:
            return {}
        holders = (
            streams.keys() if owners is None else [o for o in owners if o in streams]
        )
        seen: dict = {}
        for holder in holders:
            events = streams[holder]
            low = bisect_left(events, start, key=_first)
            high = bisect_left(events, end, key=_first)
            for _day_, unit, qty in events[low:high]:
                seen[unit] = qty
        return seen

    def portfolio(self, owners, kind: str = "all", *, as_of: date | None = None) -> int:
        """Schools held: all, active, core, client, clustered, or one of the
        SSA denominators. ``as_of`` reads the portfolio as it stood then."""
        return sum(1 for s in self._held(owners, as_of) if self._is(s, kind, as_of))

    def portfolio_schools(self, owners, kind: str, *, as_of=None) -> list[str]:
        """The schools `portfolio` counts, for a figure read by where they are."""
        return [s.pk for s in self._held(owners, as_of) if self._is(s, kind, as_of)]

    def _held(self, owners, as_of):
        for school in self.schools.values():
            if owners is not None and school.owner not in owners:
                continue
            if as_of is not None and school.start and school.start >= as_of:
                continue
            yield school

    def _is(self, school: _School, kind: str, as_of: date | None = None) -> bool:
        if kind in ("all", "portfolio"):
            return True
        if kind == "active":
            # A school closed after the day asked about was operating then.
            return school.active or bool(
                as_of and school.closed and school.closed >= as_of
            )
        if kind == "core":
            return school.core
        if kind == "client":
            return not school.core
        if kind == "clustered":
            return school.clustered
        if kind == "core_continuing":
            return school.core and school.pk not in self.recruits
        if kind in ("ssa_core", "ssa_client"):
            wanted = school.core is (kind == "ssa_core")
            return wanted and school.pk in self._ssa_schools()
        raise ValueError(kind)

    def _ssa_schools(self) -> set[str]:
        cached = getattr(self, "_ssa_cache", None)
        if cached is None:
            cached = set()
            for key in ("ssa_client", "ssa_core_baseline", "ssa_core_followup"):
                for events in self._events.get(key, {}).values():
                    cached.update(unit for _d, unit, _q in events)
            self._ssa_cache = cached
        return cached

    def ssa_average(self, owners, *, core: bool) -> float | None:
        """The mean of the year's latest SSA scores of these
        officers' Core or client schools; None when none has one."""
        scores = [
            self.ssa_scores[s.pk]
            for s in self._held(owners, None)
            if s.core is core and s.pk in self.ssa_scores
        ]
        return round(sum(scores) / len(scores), 2) if scores else None

    def regions_of(self, owners) -> dict[str, int]:
        """How many of these officers' schools are in each region."""
        tally: dict[str, int] = defaultdict(int)
        for school in self._held(owners, None):
            if school.region:
                tally[school.region] += 1
        return dict(tally)

    def holders(self) -> set[str]:
        """Officers holding at least one school."""
        return {s.owner for s in self.schools.values() if s.owner}


def _first(event) -> date:
    return event[0]


def _plannable(measure) -> bool:
    """Planned work stands behind it: activities, or Core package slots."""
    return bool(measure.match) or measure.source.startswith(
        ("core_visit_", "core_training_")
    )


__all__ = ["Ledger"]
