"""Training is aimed at any SSA intervention (owner, 2026-09-30).

"can you also lift restrictions on scheduling training based on SSA. you can
leave the users to select any SSA intervention. Currently it is hiding the SSA
intervention the school or cluster is perfroming well in."

The cluster drawer listed only the courses for the cluster's weakest
interventions and posted the course's own intervention from a hidden field;
its meeting listed only the recommended interventions. Both sat behind a
"Show all" step. The fixture's cluster is strong in Christlike Behaviour and
weak in Leadership, so a drawer that still hid the strong one would fail here.

Owner, 2026-10-06, narrowing that for trainings: a training is scheduled
under the SSA intervention the Training Catalogue links it to, shown
read-only and taken from the catalogue again on save. What is pinned here
still holds beside that rule: no training is hidden by the cluster's scores,
no hidden field posts an intervention, and the list of all eight is what a
planner is given for a training the catalogue maps to any SSA intervention,
for a cluster meeting, and for a partner hand-over. That the linked
intervention wins is pinned in apps.planning.test_training_ceilings.
"""

from __future__ import annotations

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.clusters.models import Cluster
from apps.core.enums import SsaIntervention
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"
STRONG = "christlike_behaviour"
WEAK = "leadership"


class _Fixture(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Any Region")
        self.district = District.objects.create(
            name="Any District", region=self.region, district_type="primary"
        )
        self.cluster = Cluster.objects.create(
            name="Any Cluster", district=self.district, region=self.region
        )
        self.user = User.objects.create_user(
            email="cceo-any@t.org",
            name="Any CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(
            user=self.user, title=EdifyRole.CCEO.value
        )
        self.school = School.objects.create(
            school_id="S-ANY",
            name="Any Primary",
            region=self.region,
            district=self.district,
            cluster_id=self.cluster.id,
            cluster_status="clustered",
            school_type="client",
            enrollment=100,
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=self.school.id)
        record = SsaRecord.objects.create(
            school=self.school,
            fy=get_operational_fy(),
            quarter="Q1",
            average_score=6.0,
            verification_status="confirmed",
            date_of_ssa=timezone.now(),
            uploaded_by=self.user.id,
            verified_at=timezone.now(),
        )
        SsaScore.objects.create(ssa_record=record, intervention=STRONG, score=9.5)
        SsaScore.objects.create(ssa_record=record, intervention=WEAK, score=2.5)
        self.client = Client()
        self.client.force_login(self.user, backend=BACKEND)

    def _cluster_drawer(self, action):
        response = self.client.get(
            f"/planning/schedule-modal?cluster_id={self.cluster.id}&action={action}"
        )
        self.assertEqual(response.status_code, 200)
        return response


class ClusterTrainingOffersEveryInterventionTest(_Fixture):
    def test_the_training_has_a_visible_intervention_select_of_all_eight(self):
        body = self._cluster_drawer("training").content.decode()
        select = body.split('id="cluster_training_focus_intervention"', 1)[1].split(
            "</select>", 1
        )[0]
        for code in SsaIntervention.values:
            with self.subTest(code=code):
                self.assertIn(f'<option value="{code}">', select)
        self.assertNotIn('type="hidden" name="focus_intervention"', body)

    def test_no_training_is_hidden_behind_show_all(self):
        response = self._cluster_drawer("training")
        body = response.content.decode()
        self.assertNotIn("training_show_all", body)
        self.assertNotIn("addressesPriority ||", body)
        # Every governed course is in the list the drawer renders, including
        # the ones for an intervention the cluster is strong in.
        from apps.activity_catalogue.availability import (
            CLUSTER,
            training_activity_options,
        )

        offered = {o["id"] for o in response.context["training_activity_options"]}
        everything = {
            o["id"]
            for o in training_activity_options(
                planning_context=CLUSTER, cluster=self.cluster
            )
        }
        self.assertEqual(offered, everything)


class ClusterMeetingOffersEveryInterventionTest(_Fixture):
    def test_the_strong_intervention_is_listed_and_the_weak_one_preselected(self):
        body = self._cluster_drawer("meeting").content.decode()
        select = body.split('id="meeting_focus_intervention"', 1)[1].split(
            "</select>", 1
        )[0]
        self.assertIn(f'<option value="{STRONG}">', select)
        self.assertIn(f'<option value="{WEAK}" selected>', select)
        for code in SsaIntervention.values:
            with self.subTest(code=code):
                self.assertIn(f'value="{code}"', select)
        self.assertNotIn("meeting_show_all", body)


class PartnerTrainingHandoverOffersEveryInterventionTest(_Fixture):
    def test_the_in_school_training_handover_names_any_intervention(self):
        response = self.client.get(
            f"/planning/assign-partner-modal?school_id={self.school.id}"
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        select = body.split('id="partner_training_focus_intervention"', 1)[1].split(
            "</select>", 1
        )[0]
        for code in SsaIntervention.values:
            with self.subTest(code=code):
                self.assertIn(f'<option value="{code}">', select)
