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
