"""A group training planned through a cluster fills a Core package slot.

Owner, 2026-09-21: "The core schools trained through cluster group training
... should contribute to the core school training packages and should be
counted as part of the 4 trainings. It should move to core school training
planned table." And, 2026-10-02: the package's trainings "should include both
in-school training and group trainings planned through clusters. So if a core
school is part of a group training, it should be counted in the core
package."

Two moments, and they are different questions:

* **Booked.** The invitation is the commitment, so the slot is taken as soon
  as the session is scheduled — which is what puts the school on the Core
  School Trainings Planned table beside a training booked from the Core
  Schools page.
* **Registered.** Attendance narrows it. A school that was invited and did
  not come gives its slot back, so the four trainings a package counts stay
  the four the school actually took.

And the split (owner, 2026-10-02: "The staff are only supposed to plan for
two visits and two trainings but it is showing all the 4"): a group training
is on the half of whoever delivers it and takes a slot while that half has
room. A cluster meeting is not a training and takes none.
"""

from __future__ import annotations

import threading
from datetime import date, timedelta
from unittest.mock import patch

from django.db import connections
from django.test import TestCase, TransactionTestCase

from apps.activities.cluster_attendance import confirm_attendance, set_invited_schools
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.core_schools import cluster_credit
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id
from apps.core_schools.package_split import PARTNER, STAFF, TRAINING, package_split
from apps.core_schools.services import create_package_slots
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class ClusterTrainingCreditsThePackageTest(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        self.region = Region.objects.create(name="CTC Region")
        self.district = District.objects.create(name="CTC District", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="CTC SC", district=self.district
        )
        self.cluster = Cluster.objects.create(
            name="CTC Cluster",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            cluster_type="mixed",
            status="active",
        )
        self.core = self._school("CTC-CORE", school_type="core")
        self.client_school = self._school("CTC-CLIENT")
        self.plan = CorePlan.objects.create(
            id=cplan_id("CTC-CORE", fy=self.fy),
            school_id="CTC-CORE",
            fy=self.fy,
            status="Active",
        )
        create_package_slots(self.plan, "CTC-CORE", ["leadership"])

    def _school(self, code, school_type="client"):
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

    def _session(self, activity_type="cluster_training", status="scheduled", **more):
        when = date.today() + timedelta(days=10)
        return Activity.objects.create(
            **{
                "activity_type": activity_type,
                "cluster": self.cluster,
                "fy": self.fy,
                "quarter": "Q1",
                "status": status,
                "planned_date": when,
                **more,
            }
        )

    def _partner_session(self):
        return self._session(status="partner_scheduled", delivery_type="partner")

    def _training_slots(self, plan=None):
        return CoreActivitySlot.objects.filter(
            core_plan=plan or self.plan, activity_type="training"
        ).order_by("sequence_number")

    def test_the_slot_is_taken_when_the_session_is_scheduled(self):
        session = self._session()
        set_invited_schools(session, [self.core.id, self.client_school.id])
        taken = self._training_slots().filter(activity_id=session.id)
        self.assertEqual(taken.count(), 1, "one slot, not four")
        slot = taken.first()
        self.assertEqual(slot.sequence_number, 1)
        self.assertEqual(slot.status, "scheduled")
        # The column is a CharField; the day it carries is the plan's day.
        self.assertEqual(str(slot.scheduled_for)[:10], session.planned_date.isoformat())

    def test_a_cluster_meeting_is_not_a_training_and_takes_no_slot(self):
        for activity_type in ("cluster_meeting", "cluster_meeting_ssa_review"):
            with self.subTest(activity_type=activity_type):
                session = self._session(activity_type=activity_type)
                set_invited_schools(session, [self.core.id])
                self.assertFalse(
                    self._training_slots().filter(activity_id=session.id).exists()
                )
        self.assertEqual(self._training_slots().filter(status="Planned").count(), 4)

    def test_a_slot_a_meeting_held_from_before_is_given_back_on_its_next_save(self):
        meeting = self._session(activity_type="cluster_meeting")
        set_invited_schools(meeting, [self.core.id])
        slot = self._training_slots().first()
        slot.activity_id = meeting.id
        slot.status = "scheduled"
        slot.owner = "staff"
        slot.save()
        meeting.save()
        slot.refresh_from_db()
        self.assertEqual((slot.activity_id, slot.status), (None, "Planned"))

    def test_unticking_the_school_gives_the_slot_back(self):
        session = self._session()
        set_invited_schools(session, [self.core.id, self.client_school.id])
        set_invited_schools(session, [self.client_school.id])
        self.assertEqual(
            self._training_slots().filter(activity_id=session.id).count(), 0
        )
        self.assertEqual(self._training_slots().filter(status="Planned").count(), 4)

    def test_a_school_that_did_not_come_gives_its_slot_back(self):
        session = self._session()
        set_invited_schools(session, [self.core.id, self.client_school.id])
        session.status = "completed"
        session.save()
        confirm_attendance(session, [self.client_school.id])
        self.assertEqual(
            self._training_slots().filter(activity_id=session.id).count(),
            0,
            "the package counts trainings the school took, not ones it missed",
        )

    def test_a_school_that_came_keeps_its_slot(self):
        session = self._session()
        set_invited_schools(session, [self.core.id, self.client_school.id])
        session.status = "completed"
        session.save()
        confirm_attendance(session, [self.core.id, self.client_school.id])
        self.assertEqual(
            self._training_slots().filter(activity_id=session.id).count(), 1
        )

    def test_a_cancelled_session_releases_the_slot(self):
        session = self._session()
        set_invited_schools(session, [self.core.id])
        session.status = "cancelled"
        session.save()
        self.assertEqual(
            self._training_slots().filter(activity_id=session.id).count(), 0
        )

    def test_staff_sessions_fill_staffs_two_and_a_third_takes_no_slot(self):
        """ "The staff are only supposed to plan for two visits and two
        trainings but it is showing all the 4." """
        sessions = [self._session() for _ in range(3)]
        for session in sessions:
            set_invited_schools(session, [self.core.id])
        filled = self._training_slots().exclude(activity_id=None)
        self.assertEqual(
            [(slot.sequence_number, slot.owner) for slot in filled],
            [(1, "staff"), (2, "staff")],
        )
        # The third session still happens; it is on the school's history and
        # fills no slot. The Partner's two stay open to be assigned.
        self.assertFalse(
            self._training_slots().filter(activity_id=sessions[2].id).exists()
        )
        split = package_split(self.core, self.fy)
        self.assertEqual(
            (split.used(TRAINING, STAFF), split.used(TRAINING, PARTNER)), (2, 0)
        )
        self.assertFalse(split.is_open(TRAINING, STAFF))
        self.assertTrue(split.is_open(TRAINING, PARTNER))

    def test_a_session_a_partner_delivers_is_on_the_partners_half(self):
        for session in (self._session(), self._session()):
            set_invited_schools(session, [self.core.id])
        partner_sessions = [self._partner_session() for _ in range(3)]
        for session in partner_sessions:
            set_invited_schools(session, [self.core.id])
        filled = self._training_slots().exclude(activity_id=None)
        self.assertEqual(
            [(slot.sequence_number, slot.owner) for slot in filled],
            [(1, "staff"), (2, "staff"), (3, "partner"), (4, "partner")],
        )
        self.assertFalse(
            self._training_slots().filter(activity_id=partner_sessions[2].id).exists()
        )
        split = package_split(self.core, self.fy)
        self.assertEqual(
            (split.used(TRAINING, STAFF), split.used(TRAINING, PARTNER)), (2, 2)
        )

    def test_staffs_own_in_school_trainings_leave_a_session_no_staff_slot(self):
        for offset in (3, 5):
            Activity.objects.create(
                activity_type="in_school_training",
                purpose_type="in_school_training",
                school=self.core,
                fy=self.fy,
                quarter="Q1",
                status="scheduled",
                planned_date=date.today() + timedelta(days=offset),
            )
        session = self._session()
        set_invited_schools(session, [self.core.id])
        self.assertFalse(self._training_slots().filter(activity_id=session.id).exists())
        # A Partner's session still has the Partner's half to go to.
        partner_session = self._partner_session()
        set_invited_schools(partner_session, [self.core.id])
        self.assertEqual(
            self._training_slots().get(activity_id=partner_session.id).owner, "partner"
        )

    def test_a_session_handed_to_a_partner_moves_to_the_partners_half(self):
        session = self._session()
        set_invited_schools(session, [self.core.id])
        self.assertEqual(
            self._training_slots().get(activity_id=session.id).owner, "staff"
        )
        session.delivery_type = "partner"
        session.status = "partner_scheduled"
        session.save()
        self.assertEqual(
            self._training_slots().get(activity_id=session.id).owner, "partner"
        )
        split = package_split(self.core, self.fy)
        self.assertEqual(
            (split.used(TRAINING, STAFF), split.used(TRAINING, PARTNER)), (0, 1)
        )

    def test_a_session_dated_next_year_fills_next_years_package(self):
        """Work is filed in the package of the year it is planned for."""
        next_fy = str(int(self.fy) + 1)
        session = self._session(fy=next_fy)
        set_invited_schools(session, [self.core.id])
        self.assertFalse(self._training_slots().filter(activity_id=session.id).exists())
        next_plan = CorePlan.objects.get(school_id="CTC-CORE", fy=next_fy)
        self.assertEqual(
            self._training_slots(next_plan).filter(activity_id=session.id).count(), 1
        )

    def test_a_client_school_takes_no_package_slot(self):
        session = self._session()
        set_invited_schools(session, [self.client_school.id])
        self.assertEqual(self._training_slots().exclude(activity_id=None).count(), 0)


class SimultaneousSessionSavesTest(TransactionTestCase):
    """Every save of a cluster session runs the credit pass. Two saves at once
    (a double-click, the officer and the planner on one session) both read the
    school as unlinked before either took the slot lock."""

    reset_sequences = False

    def setUp(self):
        fy = get_operational_fy()
        region = Region.objects.create(name="Race CTC Region")
        district = District.objects.create(name="Race CTC District", region=region)
        sub_county = SubCounty.objects.create(name="Race CTC SC", district=district)
        cluster = Cluster.objects.create(
            name="Race CTC Cluster",
            region=region,
            district=district,
            sub_county=sub_county,
            cluster_type="mixed",
            status="active",
        )
        core = School.objects.create(
            school_id="RACE-CORE",
            name="Race Core",
            region=region,
            district=district,
            sub_county=sub_county,
            school_type="core",
        )
        School.objects.filter(id=core.id).update(
            cluster_id=cluster.id, cluster_status="clustered"
        )
        self.plan = CorePlan.objects.create(
            id=cplan_id("RACE-CORE", fy=fy),
            school_id="RACE-CORE",
            fy=fy,
            status="Active",
        )
        create_package_slots(self.plan, "RACE-CORE", ["leadership"])
        self.session = Activity.objects.create(
            activity_type="cluster_training",
            cluster=cluster,
            fy=fy,
            quarter="Q1",
            status="scheduled",
            planned_date=date.today() + timedelta(days=10),
        )
        # Invited, no slot taken yet: where a school stands when it became a
        # Core School, or got its plan, after the session was booked.
        ClusterActivityAttendance.objects.create(
            activity=self.session, school_id=core.id, invited=True
        )

    def test_two_simultaneous_saves_credit_one_slot(self):
        workers = 2
        both_have_read = threading.Barrier(workers)
        credited = cluster_credit.credited_school_ids
        past_the_read: list[str] = []
        failures: list[str] = []

        def read_then_wait(activity):
            schools = credited(activity)
            both_have_read.wait(timeout=10)
            past_the_read.append(activity.pk)
            return schools

        def save():
            try:
                Activity.objects.get(pk=self.session.pk).save()
            except Exception as exc:  # pragma: no cover - the assertion reports it
                failures.append(repr(exc))
            finally:
                for db_connection in connections.all():
                    db_connection.close()

        with patch.object(
            cluster_credit, "credited_school_ids", side_effect=read_then_wait
        ):
            threads = [threading.Thread(target=save) for _ in range(workers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        self.assertEqual(failures, [])
        self.assertEqual(len(past_the_read), workers)
        self.assertEqual(
            CoreActivitySlot.objects.filter(
                core_plan=self.plan,
                activity_type="training",
                activity_id=self.session.id,
            ).count(),
            1,
        )
