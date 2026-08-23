"""The cluster drawer invites schools by name, and scheduling records it.

The count that multiplies into the budget is derived from the ticks, so the
figure and the list cannot disagree — and completion opens with the register
already filled in rather than blank, which is why cluster-delivered work never
reached the schools that sat in the room.
"""

from __future__ import annotations

import re

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.clusters.models import Cluster
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School

BACKEND = "apps.accounts.auth_backend.LockoutEnforcingModelBackend"


class ClusterInviteDrawerTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(
            name="Dist", region=self.region, district_type="primary"
        )
        self.cluster = Cluster.objects.create(
            name="Cluster One", district=self.district, region=self.region
        )
        self.user = User.objects.create_user(
            email="cceo-inv@t.org",
            name="CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(
            user=self.user, title=EdifyRole.CCEO.value
        )
        self.schools = [self._school(n) for n in ("Alpha", "Beta", "Gamma")]
        self.client = Client()
        self.client.force_login(self.user, backend=BACKEND)

    def _school(self, name):
        school = School.objects.create(
            school_id=f"S-{name}",
            name=f"School {name}",
            region=self.region,
            district=self.district,
            cluster_id=self.cluster.id,
            cluster_status="clustered",
            enrollment=100,
        )
        StaffSchoolAssignment.objects.create(staff=self.staff, school_id=school.id)
        return school

    def _drawer(self, action):
        return self.client.get(
            f"/planning/schedule-modal?cluster_id={self.cluster.id}&action={action}"
        )

    def test_a_training_drawer_lists_every_member_school_with_a_checkbox(self):
        body = self._drawer("training").content.decode()

        self.assertEqual(body.count('name="invited_school_ids"'), len(self.schools))
        for school in self.schools:
            self.assertIn(school.name, body)
            self.assertIn(school.id, body)

    def test_a_meeting_drawer_gets_the_same_list(self):
        # Meetings were exempt: the block was gated off entirely, so a meeting
        # invited the whole cluster by definition. Schools miss meetings for
        # the same reasons they miss trainings.
        body = self._drawer("meeting").content.decode()

        self.assertEqual(body.count('name="invited_school_ids"'), len(self.schools))

    def test_every_school_starts_ticked(self):
        # Which is what the number it replaces defaulted to. Counted on the
        # invite inputs specifically — the drawer has other checkboxes.
        body = self._drawer("training").content.decode()

        ticked = re.findall(r'name="invited_school_ids"[^>]*?\bchecked\b', body, re.S)
        self.assertEqual(len(ticked), len(self.schools))

    def test_the_drawer_offers_select_all_rather_than_three_clicks(self):
        body = self._drawer("training").content.decode()

        self.assertIn("toggleAll()", body)
        self.assertIn("syncInvited()", body)

    def test_the_typed_school_count_is_gone(self):
        body = self._drawer("training").content.decode()

        self.assertNotIn('name="schools_invited"', body)
