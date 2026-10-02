"""A cluster session is outside a Core School's package.

Owner, 2026-10-02, asked whether a cluster training or meeting counts as one
of a Core package's trainings: "They should be separate" — outside the
package. The package's four trainings are in-school trainings, two by staff
and two assigned to a Partner.

From 2026-09-21 until then a session took the next open training slot at
every Core school it invited, with no limit, so two group trainings and two
meetings read "4/4 trainings" with the Partner's half never assigned. These
tests pin the new rule and the hand-back of slots held from before.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.activities.cluster_attendance import confirm_attendance, set_invited_schools
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.core_schools import cluster_credit
from apps.core_schools.models import CoreActivitySlot, CorePlan, cplan_id
from apps.core_schools.services import create_package_slots
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


class ClusterSessionsFillNoPackageSlotTest(TestCase):
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

    def _all_open(self) -> bool:
        return self._training_slots().filter(status="Planned").count() == 4

    def test_a_booked_training_or_meeting_takes_no_slot(self):
        for kind in ("cluster_training", "cluster_meeting"):
            session = self._session(activity_type=kind)
            set_invited_schools(session, [self.core.id, self.client_school.id])
            self.assertFalse(
                self._training_slots().filter(activity_id=session.id).exists(), kind
            )
        self.assertTrue(self._all_open())

    def test_a_session_the_school_attended_takes_none_either(self):
        session = self._session()
        set_invited_schools(session, [self.core.id, self.client_school.id])
        session.status = "completed"
        session.save()
        confirm_attendance(session, [self.core.id, self.client_school.id])
        self.assertTrue(self._all_open())

    def test_however_many_sessions_the_package_stays_the_in_school_four(self):
        for _ in range(5):
            set_invited_schools(self._session(), [self.core.id])
        self.assertTrue(self._all_open())

    def test_a_slot_held_from_before_is_given_back_on_the_next_save(self):
        session = self._session()
        set_invited_schools(session, [self.core.id])
        slot = self._training_slots().first()
        CoreActivitySlot.objects.filter(id=slot.id).update(
            activity_id=session.id, status="scheduled", owner="staff"
        )
        session.save()
        slot.refresh_from_db()
        self.assertIsNone(slot.activity_id)
        self.assertEqual((slot.status, slot.owner), ("Planned", "unassigned"))

    def test_the_session_still_says_which_schools_it_counts_for(self):
        """Training coverage and follow-ups still read the register."""
        session = self._session()
        set_invited_schools(session, [self.core.id, self.client_school.id])
        self.assertEqual(
            cluster_credit.credited_school_ids(session),
            {self.core.id, self.client_school.id},
        )
        session.status = "completed"
        session.save()
        confirm_attendance(session, [self.client_school.id])
        self.assertEqual(
            cluster_credit.credited_school_ids(session), {self.client_school.id}
        )
