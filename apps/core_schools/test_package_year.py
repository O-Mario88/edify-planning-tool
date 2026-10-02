"""A Core package's work is the work dated in its year, split two and two.

Owner, 2026-10-02: "Core School page are not fetching the number of visits.
People have planned first visit and second visits but they are not showing in
V1, V2, V3, V4 but the trainings are showing but also inflated numbers. The
staff are only supposed to plan for two visits and two trainings but it is
showing all the 4. The other two visits and trainings are supposed to be
assigned."

Replayed here as it happened: in September, with FY2026 running and each Core
school holding only its FY2026 package, staff plan October's work.
"""

from __future__ import annotations

from datetime import date

from django.test import TestCase
from freezegun import freeze_time

from apps.activities.cluster_attendance import set_invited_schools
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.exceptions import BadRequest
from apps.core_schools import package_year
from apps.core_schools.core_planning_services import CoreSchoolsService
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id
from apps.core_schools.package_split import (
    PARTNER,
    STAFF,
    TRAINING,
    VISIT,
    assert_side_open,
    package_split,
)
from apps.core_schools.services import create_package_slots, ensure_core_plan
from apps.core_schools.visit_routing import core_plan_for_visit
from apps.activities.models import ClusterActivityAttendance
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School

SEPTEMBER = "2026-09-22T10:00:00"
OCTOBER = "2026-10-02T10:00:00"


class _YearFixture(TestCase):
    """One Core school in a cluster, holding its FY2026 package and no other."""

    def setUp(self):
        self.region = Region.objects.create(name="Year Region")
        self.district = District.objects.create(
            name="Year District", region=self.region
        )
        self.sub_county = SubCounty.objects.create(
            name="Year SC", district=self.district
        )
        self.cluster = Cluster.objects.create(
            name="Year Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
            status="active",
        )
        self.school = self._school("YEAR-1")
        self.old_plan = CorePlan.objects.create(
            id=cplan_id("YEAR-1", fy="2026"),
            school_id="YEAR-1",
            fy="2026",
            status="Active",
            baseline_average=6.5,
            interventions=["leadership"],
        )
        create_package_slots(self.old_plan, "YEAR-1", ["leadership"])

    def _school(self, code, school_type="core"):
        school = School.objects.create(
            school_id=code,
            name=f"School {code}",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type=school_type,
        )
        School.objects.filter(id=school.id).update(
            cluster_id=self.cluster.id, cluster_status="clustered"
        )
        school.refresh_from_db()
        return school

    def _work(self, activity_type, day, *, fy="2027", **fields):
        """Saved the way every door saves one, with its commit hooks run."""
        with self.captureOnCommitCallbacks(execute=True):
            return Activity.objects.create(
                activity_type=activity_type,
                school=self.school,
                fy=fy,
                quarter="Q1",
                planned_date=day,
                status=fields.pop("status", "scheduled"),
                delivery_type=fields.pop("delivery_type", "staff"),
                **fields,
            )

    def _session(self, day, activity_type="cluster_training", **fields):
        session = Activity.objects.create(
            activity_type=activity_type,
            cluster=self.cluster,
            fy="2027",
            quarter="Q1",
            planned_date=day,
            status=fields.pop("status", "scheduled"),
            delivery_type=fields.pop("delivery_type", "staff"),
            **fields,
        )
        set_invited_schools(session, [self.school.id])
        return session

    def _slots(self, fy, kind):
        return list(
            CoreActivitySlot.objects.filter(
                core_plan__school_id="YEAR-1", core_plan__fy=fy, activity_type=kind
            ).order_by("sequence_number")
        )

    def _taken(self, fy, kind):
        return [
            f"{kind[0].upper()}{slot.sequence_number}"
            for slot in self._slots(fy, kind)
            if slot.activity_id
        ]


@freeze_time(SEPTEMBER)
class OctoberWorkPlannedInSeptemberTest(_YearFixture):
    def test_a_visit_goes_to_the_package_of_the_year_it_is_dated_in(self):
        first = self._work("school_visit", date(2026, 10, 13))
        second = self._work("training_follow_up_visit", date(2026, 11, 17))
        self.assertEqual(self._taken("2027", "visit"), ["V1", "V2"])
        self.assertEqual(self._taken("2026", "visit"), [])
        slots = self._slots("2027", "visit")
        self.assertEqual(
            [slot.activity_id for slot in slots[:2]], [first.id, second.id]
        )

    def test_the_year_s_package_is_made_from_the_one_the_school_has(self):
        plan = ensure_core_plan(self.school, "2027")
        self.assertEqual((plan.fy, plan.status), ("2027", "Active"))
        self.assertEqual(plan.baseline_average, 6.5)
        self.assertEqual(plan.interventions, ["leadership"])
        # One assessment, four visits, four trainings, as every package.
        self.assertEqual(plan.slots.count(), 9)
        # Asked again, it is the same package.
        self.assertEqual(ensure_core_plan(self.school, "2027").id, plan.id)

    def test_the_planning_door_books_into_the_dated_year(self):
        october = core_plan_for_visit(self.school, scheduled_date=date(2026, 10, 13))
        this_month = core_plan_for_visit(self.school, scheduled_date=date(2026, 9, 25))
        self.assertEqual((october.fy, this_month.fy), ("2027", "2026"))

    def test_a_school_that_never_had_a_package_gets_none_this_way(self):
        newcomer = self._school("YEAR-NEW")
        self.assertIsNone(ensure_core_plan(newcomer, "2027"))
        client = self._school("YEAR-CLIENT", school_type="client")
        self.assertIsNone(ensure_core_plan(client, "2027"))

    def test_each_year_s_split_counts_its_own_work(self):
        self._work("school_visit", date(2026, 9, 28), fy="2026")
        self._work("follow_up_visit", date(2026, 10, 13))
        self._work("training_follow_up_visit", date(2026, 11, 17))
        this_year = package_split(self.school, "2026")
        next_year = package_split(self.school, "2027")
        self.assertEqual(this_year.used(VISIT, STAFF), 1)
        self.assertEqual(next_year.used(VISIT, STAFF), 2)
        # A third staff visit next year is the Partner's; this year has room.
        with self.assertRaisesMessage(BadRequest, "2 staff core visits"):
            assert_side_open(self.school, VISIT, STAFF, fy="2027")
        assert_side_open(self.school, VISIT, STAFF, fy="2026")
        assert_side_open(self.school, VISIT, PARTNER, fy="2027")


@freeze_time(OCTOBER)
class ClusterSessionsAreOutsideThePackageTest(_YearFixture):
    """Owner, 2026-10-02: "They should be separate" — outside the package."""

    def test_a_session_fills_no_training_slot_and_is_on_neither_half(self):
        self._session(date(2026, 10, 20))
        self._session(date(2026, 10, 27), "cluster_meeting")
        self._session(
            date(2026, 11, 3), delivery_type="partner", status="partner_scheduled"
        )
        self.assertEqual(self._taken("2027", "training"), [])
        split = package_split(self.school, "2027")
        self.assertEqual(
            (split.used(TRAINING, STAFF), split.used(TRAINING, PARTNER)), (0, 0)
        )

    def test_the_four_trainings_are_in_school_two_and_two(self):
        self._session(date(2026, 10, 20))
        self._session(date(2026, 10, 27))
        self._work("in_school_training", date(2026, 10, 14))
        self._work("in_school_training", date(2026, 10, 21))
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2"])
        with self.assertRaisesMessage(BadRequest, "2 staff core trainings"):
            assert_side_open(self.school, TRAINING, STAFF, fy="2027")
        # The other two are the Partner's to be assigned.
        assert_side_open(self.school, TRAINING, PARTNER, fy="2027")

    def test_a_session_saved_again_gives_back_a_slot_it_held(self):
        session = self._session(date(2026, 10, 20))
        plan = ensure_core_plan(self.school, "2027")
        CoreActivitySlot.objects.filter(
            core_plan=plan, activity_type="training", sequence_number=1
        ).update(activity_id=session.id, status="scheduled", owner="staff")
        session.save()
        self.assertEqual(self._taken("2027", "training"), [])


@freeze_time(OCTOBER)
class DataCollectionIsOutsideThePackageTest(_YearFixture):
    """Owner, 2026-10-02: "the only visits that count are in-school visits
    and Training Follow Up visits"; data collection is allowed on every
    school whatever visits it has."""

    def test_a_data_collection_visit_takes_no_slot_and_no_half(self):
        self._work(
            "school_visit_ssa_collection",
            date(2026, 10, 13),
            purpose_type="ssa_support",
        )
        self._work("core_visit", date(2026, 10, 14), purpose_type="ssa_support")
        self.assertEqual(self._taken("2027", "visit"), [])
        self.assertEqual(package_split(self.school, "2027").used(VISIT, STAFF), 0)

    def test_it_is_allowed_when_staff_have_their_two_visits(self):
        from apps.planning.visit_gate import (
            SSA_POOL,
            assert_staff_may_schedule_visit,
        )

        self._work("training_follow_up_visit", date(2026, 10, 13))
        self._work("training_follow_up_visit", date(2026, 11, 17))
        with self.assertRaisesMessage(BadRequest, "Staff core visits complete"):
            assert_staff_may_schedule_visit(self.school, "2027")
        assert_staff_may_schedule_visit(self.school, "2027", pool=SSA_POOL)


@freeze_time(OCTOBER)
class RefileTest(_YearFixture):
    """What the deploy migration does to the links already written."""

    def setUp(self):
        super().setUp()
        self.new_plan = ensure_core_plan(self.school, "2027")
        # As September left it: October's two visits in the FY2026 package.
        self.visits = []
        for sequence, day in ((1, date(2026, 10, 13)), (2, date(2026, 11, 17))):
            visit = Activity.objects.create(
                activity_type="core_visit",
                school=self.school,
                fy="2027",
                planned_date=day,
                status="scheduled",
                delivery_type="staff",
            )
            CoreActivitySlot.objects.filter(
                core_plan=self.old_plan, activity_type="visit", sequence_number=sequence
            ).update(
                activity_id=visit.id,
                status="scheduled",
                owner="staff",
                scheduled_for=day.isoformat(),
            )
            self.visits.append(visit)
        # And four staff sessions in all four FY2027 training slots.
        self.sessions = []
        for sequence, (day, kind) in enumerate(
            (
                (date(2026, 10, 20), "cluster_training"),
                (date(2026, 11, 24), "cluster_training"),
                (date(2026, 10, 27), "cluster_meeting"),
                (date(2026, 12, 8), "cluster_meeting"),
            ),
            start=1,
        ):
            session = Activity.objects.create(
                activity_type=kind,
                cluster=self.cluster,
                fy="2027",
                planned_date=day,
                status="scheduled",
                delivery_type="staff",
            )
            ClusterActivityAttendance.objects.create(
                activity=session, school=self.school, invited=True
            )
            CoreActivitySlot.objects.filter(
                core_plan=self.new_plan,
                activity_type="training",
                sequence_number=sequence,
            ).update(
                activity_id=session.id,
                status="scheduled",
                owner="staff",
                scheduled_for=day.isoformat(),
            )
            self.sessions.append(session)

    def _refile(self, **kwargs):
        lines = []
        report = package_year.refile(
            CorePlan,
            CoreActivitySlot,
            Activity,
            from_fy="2027",
            out=lines.append,
            **kwargs,
        )
        return report, lines

    def test_a_dry_run_reports_and_writes_nothing(self):
        report, lines = self._refile(write=False)
        self.assertEqual(len(report["moved"]), 2)
        self.assertEqual(len(report["released"]), 4)
        self.assertEqual(self._taken("2026", "visit"), ["V1", "V2"])
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2", "T3", "T4"])
        self.assertTrue(any("FY2026 V1 -> " in line for line in lines))

    def test_visits_move_to_their_year_and_sessions_leave_the_package(self):
        before = list(
            Activity.objects.order_by("id").values_list(
                "id", "status", "fy", "planned_date"
            )
        )
        report, _lines = self._refile()
        self.assertEqual(self._taken("2026", "visit"), [])
        self.assertEqual(self._taken("2027", "visit"), ["V1", "V2"])
        visits = self._slots("2027", "visit")
        self.assertEqual(
            [slot.activity_id for slot in visits[:2]], [v.id for v in self.visits]
        )
        self.assertEqual(visits[0].status, "scheduled")
        self.assertEqual(visits[0].scheduled_for, "2026-10-13")
        # Every training slot is open again: for two in-school trainings by
        # staff and two assigned to a Partner.
        trainings = self._slots("2027", "training")
        self.assertEqual(self._taken("2027", "training"), [])
        self.assertTrue(all(package_year.is_open(s.status) for s in trainings))
        self.assertEqual(len(report["moved"]), 2)
        self.assertEqual(len(report["released"]), 4)
        # No activity was touched.
        self.assertEqual(
            before,
            list(
                Activity.objects.order_by("id").values_list(
                    "id", "status", "fy", "planned_date"
                )
            ),
        )
        split = package_split(self.school, "2027")
        self.assertEqual(
            (split.used(VISIT, STAFF), split.used(TRAINING, STAFF)), (2, 0)
        )

    def test_running_it_twice_changes_nothing_more(self):
        self._refile()
        report, _lines = self._refile()
        self.assertEqual((report["moved"], report["released"]), ([], []))

    def test_a_data_collection_visit_gives_its_slot_back_and_the_rest_close_up(self):
        # V1 a data collection visit, V2 a follow up, both in FY2027.
        plan = self.new_plan
        days = (date(2026, 10, 6), date(2026, 10, 9))
        kinds = (("core_visit", "ssa_support"), ("core_visit", "training_follow_up"))
        made = []
        for sequence, (day, (kind, purpose)) in enumerate(zip(days, kinds), start=1):
            visit = Activity.objects.create(
                activity_type=kind,
                purpose_type=purpose,
                school=self.school,
                fy="2027",
                planned_date=day,
                status="scheduled",
                delivery_type="staff",
            )
            CoreActivitySlot.objects.filter(
                core_plan=plan, activity_type="visit", sequence_number=sequence
            ).update(
                activity_id=visit.id,
                status="scheduled",
                owner="staff",
                scheduled_for=day.isoformat(),
            )
            made.append(visit)
        self._refile()
        visits = self._slots("2027", "visit")
        linked = [slot.activity_id for slot in visits if slot.activity_id]
        self.assertNotIn(made[0].id, linked)
        # The follow up and the two moved from FY2026, earliest first.
        self.assertEqual(linked, [made[1].id, *(v.id for v in self.visits)])
        self.assertEqual(self._taken("2027", "visit"), ["V1", "V2", "V3"])


@freeze_time(OCTOBER)
class TheNewYearsPageTest(_YearFixture):
    def test_an_onboarded_school_gets_its_package_without_a_new_assessment(self):
        schools = School.objects.filter(id=self.school.id)
        self.assertEqual(CoreSchoolsService.carry_packages_forward(schools, "2027"), 1)
        self.assertTrue(CorePlan.objects.filter(school_id="YEAR-1", fy="2027").exists())
        # Nothing to do the second time, and no package for a year that passed.
        self.assertEqual(CoreSchoolsService.carry_packages_forward(schools, "2027"), 0)
        self.assertEqual(CoreSchoolsService.carry_packages_forward(schools, "2025"), 0)
        self.assertFalse(
            CorePlan.objects.filter(school_id="YEAR-1", fy="2025").exists()
        )
