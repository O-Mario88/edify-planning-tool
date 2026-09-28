"""Planned and completed activities on every profile (owner, 2026-09-28).

"can you add list of planned and completed activities on every profile
(Cluster, school, organization...) with the action button to complete, view
activity, reschedule and cancel activities."

What is pinned here: the Planned / Completed split, the school's invited
cluster sessions counting on its profile, the actions following the server's
own execution rules (a supervisor reads a CCEO's work and does not run it),
and the section on each profile page.
"""

from __future__ import annotations

import datetime

from django.test import RequestFactory, TestCase
from django.utils import timezone

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities import profile_activities as profile_acts
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

PASSWORD = "pw-profile-acts-1"


class ProfileActivitiesFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="Profile Region")
        cls.district = District.objects.create(
            name="Profile District", region=cls.region, district_type="primary"
        )
        cls.cceo = User.objects.create_user(
            email="profile-cceo@edify.org",
            name="Profile CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            password=PASSWORD,
            is_active=True,
        )
        cls.cceo_staff = StaffProfile.objects.create(
            user=cls.cceo, staff_number="ST-PROFILE-CCEO", country="Uganda"
        )
        cls.pl = User.objects.create_user(
            email="profile-pl@edify.org",
            name="Profile PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            password=PASSWORD,
            is_active=True,
        )
        cls.pl_staff = StaffProfile.objects.create(
            user=cls.pl, staff_number="ST-PROFILE-PL", country="Uganda"
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=cls.pl_staff, supervisee=cls.cceo_staff
        )
        cls.cluster = Cluster.objects.create(
            name="Profile Cluster",
            region=cls.region,
            district=cls.district,
            responsible_staff_id=cls.cceo_staff.id,
        )
        cls.school = School.objects.create(
            school_id="PROFILE-001",
            name="Profile School",
            region=cls.region,
            district=cls.district,
            school_type="client",
            account_owner_id=cls.cceo_staff.id,
            cluster_id=cls.cluster.id,
            cluster_status="clustered",
        )
        cls.other = School.objects.create(
            school_id="PROFILE-002",
            name="Profile Neighbour",
            region=cls.region,
            district=cls.district,
            school_type="client",
            account_owner_id=cls.cceo_staff.id,
        )
        for school in (cls.school, cls.other):
            StaffSchoolAssignment.objects.create(
                staff=cls.cceo_staff, school_id=school.id
            )
        cls.partner = Partner.objects.create(name="Profile Partner")

    def setUp(self):
        today = timezone.localdate()
        self.fy = get_operational_fy()
        self.planned = self._activity(
            school=self.school, status="scheduled", day=today + datetime.timedelta(5)
        )
        self.overdue = self._activity(
            school=self.school, status="scheduled", day=today - datetime.timedelta(3)
        )
        self.delivered = self._activity(
            school=self.school,
            status="submitted_to_pl",
            day=today - datetime.timedelta(10),
        )
        self.verified = self._activity(
            school=self.school, status="ia_verified", day=today - datetime.timedelta(20)
        )
        self.cancelled = self._activity(
            school=self.school, status="cancelled", day=today + datetime.timedelta(2)
        )
        self.session = self._activity(
            cluster=self.cluster,
            activity_type="cluster_meeting",
            status="scheduled",
            day=today + datetime.timedelta(7),
        )
        ClusterActivityAttendance.objects.create(
            activity=self.session, school=self.school, invited=True
        )
        self.partner_work = self._activity(
            school=self.other,
            status="partner_scheduled",
            day=today + datetime.timedelta(9),
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
        )

    def _activity(self, *, day, status, activity_type="school_visit", **fields):
        return Activity.objects.create(
            activity_type=activity_type,
            status=status,
            fy=get_operational_fy(day),
            planned_date=day,
            responsible_staff_id=str(self.cceo_staff.id),
            **fields,
        )

    def _read(self, user, queryset, **params):
        request = RequestFactory().get("/", params)
        request.user = user
        return profile_acts.profile_activities(request, queryset, param="t")


class PlannedAndCompletedSplit(ProfileActivitiesFixture):
    def test_the_school_splits_open_from_delivered_work(self):
        acts = self._read(self.cceo, profile_acts.for_school(self.school))

        planned = {row.id for row in acts.planned["rows"]}
        completed = {row.id for row in acts.completed["rows"]}
        self.assertEqual(planned, {self.planned.id, self.overdue.id, self.session.id})
        self.assertEqual(completed, {self.delivered.id, self.verified.id})
        self.assertNotIn(self.cancelled.id, planned | completed)
        self.assertEqual(acts.overdue, 1)

    def test_an_invited_cluster_session_is_on_the_school_but_not_its_neighbour(self):
        on_school = profile_acts.for_school(self.school).values_list("id", flat=True)
        on_neighbour = profile_acts.for_school(self.other).values_list("id", flat=True)
        self.assertIn(self.session.id, on_school)
        self.assertNotIn(self.session.id, on_neighbour)

    def test_planned_work_is_oldest_first_and_overdue_reads_so(self):
        acts = self._read(self.cceo, profile_acts.for_school(self.school))

        first = acts.planned["rows"][0]
        self.assertEqual(first.id, self.overdue.id)
        self.assertEqual((first.status_label, first.status_tone), ("Overdue", "danger"))

    def test_delivered_work_reads_as_its_reviewer_holds_it(self):
        acts = self._read(self.cceo, profile_acts.for_school(self.school))

        labels = {row.id: row.status_label for row in acts.completed["rows"]}
        self.assertEqual(labels[self.delivered.id], "PL Pending")
        self.assertEqual(labels[self.verified.id], "Complete")

    def test_the_cluster_holds_its_sessions_and_its_member_schools_work(self):
        ids = set(profile_acts.for_cluster(self.cluster).values_list("id", flat=True))
        self.assertIn(self.session.id, ids)
        self.assertIn(self.planned.id, ids)
        self.assertNotIn(self.partner_work.id, ids)

    def test_the_partner_holds_the_work_it_delivers(self):
        ids = set(
            profile_acts.for_partner(self.partner.id).values_list("id", flat=True)
        )
        self.assertEqual(ids, {self.partner_work.id})

    def test_the_chosen_tab_is_kept(self):
        acts = self._read(
            self.cceo, profile_acts.for_school(self.school), t_tab="completed"
        )
        self.assertEqual(acts.active_tab, "completed")


class ActionsFollowTheExecutionRules(ProfileActivitiesFixture):
    def _row(self, user, activity, queryset):
        acts = self._read(user, queryset)
        rows = list(acts.planned["rows"]) + list(acts.completed["rows"])
        return next(row for row in rows if row.id == activity.id)

    def test_the_owner_may_complete_reschedule_and_cancel_open_work(self):
        row = self._row(self.cceo, self.planned, profile_acts.for_school(self.school))
        self.assertTrue(row.may_complete and row.may_reschedule and row.may_cancel)

    def test_a_supervisor_reads_the_team_s_work_without_running_it(self):
        row = self._row(self.pl, self.planned, profile_acts.for_school(self.school))
        self.assertTrue(row.may_view)
        self.assertFalse(row.may_complete or row.may_reschedule or row.may_cancel)

    def test_delivered_work_is_not_moved_or_cancelled(self):
        row = self._row(self.cceo, self.delivered, profile_acts.for_school(self.school))
        self.assertFalse(row.may_reschedule or row.may_cancel or row.may_complete)

    def test_partner_work_is_viewed_here_and_run_by_the_partner(self):
        row = self._row(
            self.cceo, self.partner_work, profile_acts.for_partner(self.partner.id)
        )
        self.assertFalse(row.has_owner_actions)
        self.assertEqual(row.executor, "Profile Partner")


class EveryProfileShowsTheSection(ProfileActivitiesFixture):
    def test_school_cluster_partner_and_district_profiles_render_it(self):
        self.assertTrue(self.client.login(email=self.cceo.email, password=PASSWORD))
        for url, param in (
            (f"/schools/{self.school.school_id}", "school_acts"),
            (f"/clusters/{self.cluster.id}", "cluster_acts"),
            (f"/partners/{self.partner.id}", "partner_acts"),
            (f"/districts/{self.district.id}", "district_acts"),
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                body = response.content.decode()
                self.assertIn(f'data-profile-activities="{param}"', body)
                self.assertIn("View activity", body)

    def test_the_owner_s_menu_carries_the_three_doors(self):
        self.assertTrue(self.client.login(email=self.cceo.email, password=PASSWORD))
        body = self.client.get(f"/schools/{self.school.school_id}").content.decode()
        for door in ("complete-drawer", "reschedule-drawer", "cancel-drawer"):
            self.assertIn(f"/my-plan/{self.planned.id}/{door}", body)

    def test_the_supervisor_s_menu_has_no_doors_it_would_be_refused(self):
        self.assertTrue(self.client.login(email=self.pl.email, password=PASSWORD))
        response = self.client.get(f"/staff/{self.cceo.id}")
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn(f"/my-plan/{self.planned.id}", body)
        self.assertNotIn(f"/my-plan/{self.planned.id}/cancel-drawer", body)
