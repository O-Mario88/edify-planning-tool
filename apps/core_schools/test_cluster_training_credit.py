"""A Core School trained in a cluster session fills a package training slot.

Owner, 2026-09-21:

  "The core schools trained through cluster group training or cluster meeting
  should contribute to the core school training packages and should be
  counted as part of the 4 trainings. It should move to core school training
  planned table."

Two moments, and they are different questions:

* **Booked.** The invitation is the commitment, so the slot is taken as soon
  as the session is scheduled — which is what puts the school on the Core
  School Trainings Planned table beside a training booked from the Core
  Schools page.
* **Registered.** Attendance narrows it. A school that was invited and did
  not come gives its slot back, so the four trainings a package counts stay
  the four the school actually took.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.activities.cluster_attendance import confirm_attendance, set_invited_schools
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id
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

    def _session(self, activity_type="cluster_training", status="scheduled"):
        when = date.today() + timedelta(days=10)
        return Activity.objects.create(
            activity_type=activity_type,
            cluster=self.cluster,
            fy=self.fy,
            quarter="Q1",
            status=status,
            planned_date=when,
        )

    def _training_slots(self):
        return CoreActivitySlot.objects.filter(
            core_plan=self.plan, activity_type="training"
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

    def test_a_cluster_meeting_credits_the_package_too(self):
        session = self._session(activity_type="cluster_meeting")
        set_invited_schools(session, [self.core.id])
        self.assertEqual(
            self._training_slots().filter(activity_id=session.id).count(), 1
        )

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

    def test_four_sessions_fill_the_package_and_a_fifth_finds_nothing_open(self):
        sessions = [self._session() for _ in range(5)]
        for session in sessions:
            set_invited_schools(session, [self.core.id])
        filled = self._training_slots().exclude(activity_id=None)
        self.assertEqual(filled.count(), 4, "the package holds four trainings")
        self.assertEqual(sorted(slot.sequence_number for slot in filled), [1, 2, 3, 4])
        # The fifth session still happened; it simply has no slot left to fill.
        self.assertFalse(
            self._training_slots().filter(activity_id=sessions[4].id).exists()
        )

    def test_a_client_school_takes_no_package_slot(self):
        session = self._session()
        set_invited_schools(session, [self.client_school.id])
        self.assertEqual(self._training_slots().exclude(activity_id=None).count(), 0)
