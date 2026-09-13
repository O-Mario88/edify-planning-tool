""" "Trained" means one thing (Programme Lead alignment, 2026-09-13).

A school trained at a verified cluster session carries an attendance row, not
the activity's school FK. The urgent-attention resolver asked only the FK, so
the same school read "No Training" on the dashboard card and Team Oversight
while its profile and the analytics tile counted it trained. Both now ask
`trained_school_ids`, in bulk.
"""

from __future__ import annotations

from datetime import date

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.planning.urgent_attention import resolve_urgent_issue, support_facts
from apps.schools.models import School
from apps.ssa.models import SsaRecord

FY = "2026"


class TrainedFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Trained Region")
        cls.district = District.objects.create(
            name="Trained District", region=cls.region
        )
        cls.cceo = User.objects.create(
            email="trained-cceo@t.test",
            name="Trained Officer",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        cls.sp = StaffProfile.objects.create(user=cls.cceo, title="CCEO")
        cls.cluster = Cluster.objects.create(
            name="Trained Cluster",
            region=cls.region,
            district=cls.district,
            responsible_staff_id=cls.sp.id,
        )

    def _school(self, ref):
        school = School.objects.create(
            school_id=ref,
            name=f"School {ref}",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=self.sp, school_id=school.id)
        return school

    def _verified_ssa(self, school):
        SsaRecord.objects.create(
            school=school,
            fy=FY,
            date_of_ssa=timezone.now(),
            average_score=6.5,
            verification_status="confirmed",
        )

    def _verified_visit(self, school):
        Activity.objects.create(
            school=school,
            activity_type="school_visit",
            status="ia_verified",
            fy=FY,
            quarter="Q3",
            responsible_staff_id=self.sp.id,
        )

    def _cluster_session(self, school, activity_type="cluster_training"):
        session = Activity.objects.create(
            cluster=self.cluster,
            activity_type=activity_type,
            status="ia_verified",
            fy=FY,
            quarter="Q3",
            planned_date=date(2026, 5, 4),
            responsible_staff_id=self.sp.id,
        )
        ClusterActivityAttendance.objects.create(
            activity=session, school=school, invited=True, attended=True
        )
        return session


class ClusterTrainingCountsTest(TrainedFixture):
    def test_a_school_trained_at_a_cluster_session_is_trained(self):
        school = self._school("TR-1")
        self._verified_ssa(school)
        self._verified_visit(school)
        self._cluster_session(school)

        facts = support_facts([school.id], FY)
        issue = resolve_urgent_issue(school, FY, [], facts=facts)

        self.assertIn(school.id, facts["trained"])
        self.assertNotIn(issue["key"], ("no_training", "no_visit_or_training"))

    def test_the_resolver_answers_the_same_without_precomputed_facts(self):
        school = self._school("TR-2")
        self._verified_ssa(school)
        self._verified_visit(school)
        self._cluster_session(school)

        self.assertEqual(
            resolve_urgent_issue(school, FY, [])["key"],
            resolve_urgent_issue(school, FY, [], facts=support_facts([school.id], FY))[
                "key"
            ],
        )

    def test_a_cluster_meeting_is_not_a_training(self):
        school = self._school("TR-3")
        self._verified_ssa(school)
        self._verified_visit(school)
        self._cluster_session(school, activity_type="cluster_meeting")

        self.assertEqual(resolve_urgent_issue(school, FY, [])["key"], "no_training")

    def test_an_unverified_cluster_session_does_not_train(self):
        school = self._school("TR-4")
        self._verified_ssa(school)
        self._verified_visit(school)
        session = self._cluster_session(school)
        Activity.objects.filter(id=session.id).update(status="submitted_to_pl")

        self.assertEqual(resolve_urgent_issue(school, FY, [])["key"], "no_training")


class SupportFactsCostTest(TrainedFixture):
    def test_the_facts_cost_the_same_for_three_schools_or_twelve(self):
        schools = [self._school(f"TC-{i}") for i in range(12)]
        for school in schools:
            self._verified_ssa(school)
            self._cluster_session(school)

        with CaptureQueriesContext(connection) as few:
            support_facts([s.id for s in schools[:3]], FY)
        with CaptureQueriesContext(connection) as many:
            support_facts([s.id for s in schools], FY)

        self.assertEqual(len(few.captured_queries), len(many.captured_queries))
        self.assertLessEqual(len(many.captured_queries), 5)
