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
class GroupTrainingsCountInThePackageTest(_YearFixture):
    """Owner, 2026-10-02: the package's trainings "should include both
    in-school training and group trainings planned through clusters"."""

    def test_a_group_training_fills_a_slot_on_its_deliverers_half(self):
        self._session(date(2026, 10, 20))
        # A meeting is not a training.
        self._session(date(2026, 10, 27), "cluster_meeting")
        self._session(
            date(2026, 11, 3), delivery_type="partner", status="partner_scheduled"
        )
        slots = self._slots("2027", "training")
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2"])
        self.assertEqual([slot.owner for slot in slots[:2]], ["staff", "partner"])
        split = package_split(self.school, "2027")
        self.assertEqual(
            (split.used(TRAINING, STAFF), split.used(TRAINING, PARTNER)), (1, 1)
        )

    def test_two_group_trainings_are_staffs_two_and_the_rest_is_the_partners(self):
        self._session(date(2026, 10, 20))
        self._session(date(2026, 10, 27))
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2"])
        with self.assertRaisesMessage(BadRequest, "2 staff core trainings"):
            assert_side_open(self.school, TRAINING, STAFF, fy="2027")
        # The other two are the Partner's to be assigned.
        assert_side_open(self.school, TRAINING, PARTNER, fy="2027")
        # A third staff session is the school's training all the same, in no
        # slot: the package does not read 3 of 4 by staff.
        third = self._session(date(2026, 11, 10))
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2"])
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=third.id).exists())

    def test_in_school_and_group_trainings_share_staffs_two(self):
        self._work("in_school_training", date(2026, 10, 14))
        self._session(date(2026, 10, 20))
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2"])
        late = self._session(date(2026, 10, 27))
        self.assertFalse(CoreActivitySlot.objects.filter(activity_id=late.id).exists())
        split = package_split(self.school, "2027")
        self.assertEqual(split.used(TRAINING, STAFF), 2)

    def test_a_meeting_saved_again_gives_back_a_slot_it_held(self):
        meeting = self._session(date(2026, 10, 20), "cluster_meeting")
        plan = ensure_core_plan(self.school, "2027")
        CoreActivitySlot.objects.filter(
            core_plan=plan, activity_type="training", sequence_number=1
        ).update(activity_id=meeting.id, status="scheduled", owner="staff")
        meeting.save()
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
            ClusterActivityAttendance,
            School,
            from_fy="2027",
            out=lines.append,
            **kwargs,
        )
        return report, lines

    def test_a_dry_run_reports_and_writes_nothing(self):
        report, lines = self._refile(write=False)
        self.assertEqual(len(report["moved"]), 2)
        # The two meetings; the two group trainings are staff's two.
        self.assertEqual(len(report["released"]), 2)
        self.assertEqual(report["credited"], [])
        self.assertEqual(self._taken("2026", "visit"), ["V1", "V2"])
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2", "T3", "T4"])
        self.assertTrue(any("FY2026 V1 -> " in line for line in lines))

    def test_visits_move_to_their_year_and_meetings_leave_the_package(self):
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
        # The two group trainings are staff's two; the slots the meetings
        # held are open again, for the two assigned to a Partner.
        trainings = self._slots("2027", "training")
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2"])
        self.assertEqual(
            [slot.activity_id for slot in trainings[:2]],
            [session.id for session in self.sessions[:2]],
        )
        self.assertTrue(all(package_year.is_open(s.status) for s in trainings[2:]))
        self.assertEqual(len(report["moved"]), 2)
        self.assertEqual(len(report["released"]), 2)
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
            (split.used(VISIT, STAFF), split.used(TRAINING, STAFF)), (2, 2)
        )
        self.assertTrue(split.is_open(TRAINING, PARTNER))

    def test_running_it_twice_changes_nothing_more(self):
        self._refile()
        report, _lines = self._refile()
        self.assertEqual(
            (report["moved"], report["released"], report["credited"]), ([], [], [])
        )

    def _group_training(self, day, *, delivery="staff", fy="2027", invited=True):
        session = Activity.objects.create(
            activity_type="cluster_training",
            cluster=self.cluster,
            fy=fy,
            planned_date=day,
            status="partner_scheduled" if delivery == "partner" else "scheduled",
            delivery_type=delivery,
        )
        # Written as an import or an older release left them: no credit pass.
        ClusterActivityAttendance.objects.create(
            activity=session, school=self.school, invited=invited
        )
        return session

    def _hold(self, plan, sequence, session, owner="staff"):
        CoreActivitySlot.objects.filter(
            core_plan=plan, activity_type="training", sequence_number=sequence
        ).update(
            activity_id=session.id,
            status="scheduled",
            owner=owner,
            scheduled_for=session.planned_date.isoformat(),
        )

    def test_a_third_staff_group_training_gives_its_slot_back(self):
        """Staff plan two trainings; the other two are the Partner's."""
        # In the slot a meeting holds now: T3, earlier than staff's second.
        early = self._group_training(date(2026, 10, 6))
        self._hold(self.new_plan, 3, early)
        report, lines = self._refile()
        linked = [
            s.activity_id for s in self._slots("2027", "training") if s.activity_id
        ]
        # Earliest first: the 6 and 20 October sessions; 24 November's is on
        # the school's history, in no slot.
        self.assertEqual(linked, [early.id, self.sessions[0].id])
        self.assertTrue(any("staff half already has its 2" in line for line in lines))
        self.assertEqual(package_split(self.school, "2027").used(TRAINING, STAFF), 2)
        self.assertEqual(report["unplaced"], [])

    def test_a_partners_group_training_takes_the_partners_half(self):
        theirs = self._group_training(date(2026, 11, 3), delivery="partner")
        report, _lines = self._refile()
        slots = self._slots("2027", "training")
        self.assertEqual(self._taken("2027", "training"), ["T1", "T2", "T3"])
        self.assertEqual(
            [(slot.activity_id, slot.owner) for slot in slots[:3]],
            [
                (self.sessions[0].id, "staff"),
                (theirs.id, "partner"),
                (self.sessions[1].id, "staff"),
            ],
        )
        self.assertEqual([c["activity"] for c in report["credited"]], [theirs.id])
        split = package_split(self.school, "2027")
        self.assertEqual(
            (split.used(TRAINING, STAFF), split.used(TRAINING, PARTNER)), (2, 1)
        )

    def test_a_group_training_in_last_years_package_moves_to_its_own(self):
        # Planned in September for October: booked into the FY2026 package.
        for session in self.sessions[:2]:
            session.delete()
        CoreActivitySlot.objects.filter(
            core_plan=self.new_plan, activity_type="training", sequence_number__lte=2
        ).update(activity_id=None, status="Planned", owner="unassigned")
        misfiled = self._group_training(date(2026, 10, 13))
        self._hold(self.old_plan, 1, misfiled)
        self._refile()
        self.assertEqual(self._taken("2026", "training"), [])
        slots = self._slots("2027", "training")
        self.assertEqual(self._taken("2027", "training"), ["T1"])
        self.assertEqual(
            (slots[0].activity_id, slots[0].owner, slots[0].scheduled_for),
            (misfiled.id, "staff", "2026-10-13"),
        )

    def test_a_school_off_the_list_and_a_cancelled_session_hold_nothing(self):
        uninvited = self._group_training(date(2026, 10, 6), invited=False)
        cancelled = self._group_training(date(2026, 10, 7))
        Activity.objects.filter(id=cancelled.id).update(status="cancelled")
        # In the slots the two meetings hold.
        self._hold(self.new_plan, 3, uninvited)
        self._hold(self.new_plan, 4, cancelled)
        self._refile()
        linked = [
            s.activity_id for s in self._slots("2027", "training") if s.activity_id
        ]
        self.assertEqual(linked, [session.id for session in self.sessions[:2]])

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
