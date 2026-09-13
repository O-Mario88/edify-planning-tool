"""Delivery correctness on the directory pages (Programme Lead alignment, 2026-09-13).

• /schools, /clusters and /core-schools opened on a literal "2026" and
  accepted any year typed into the URL; they open on the operational year
  now and fall back to it for a year the platform does not offer.
• Coverage listed every cluster in the deployment beside school counts that
  were already scoped, and counted three hand-picked visit types as reach.
• The Closed Schools archive listed every closure in the deployment.
• The unrouted completed-activities view is gone.
"""

from __future__ import annotations

from datetime import date

from django.test import Client, TestCase

from apps.accounts.models import (
    StaffProfile,
    StaffSchoolAssignment,
    StaffSupervisorAssignment,
    User,
)
from apps.activities.models import Activity
from apps.clusters.models import Cluster
from apps.core.fy import fy_options, get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools import lifecycle_service
from apps.schools.lifecycle_models import ClosureReason, ClosureType
from apps.schools.models import School

EXPLANATION = "The owner confirmed the school stopped operating at the end of term."


def _person(email, name, role, country="Uganda"):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    return user, StaffProfile.objects.create(user=user, title=name, country=country)


class DirectoryFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.uganda = Region.objects.create(name="Dir Central", country="Uganda")
        cls.kenya = Region.objects.create(name="Dir Rift", country="Kenya")
        cls.district = District.objects.create(name="Dir Wakiso", region=cls.uganda)
        cls.kenya_district = District.objects.create(
            name="Dir Nakuru", region=cls.kenya
        )
        cls.pl_user, cls.pl = _person(
            "dir-pl@t.test", "Dir Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.cceo_user, cls.cceo = _person(
            "dir-cceo@t.test", "Dir Grace", EdifyRole.CCEO
        )
        cls.other_user, cls.other = _person(
            "dir-other@t.test", "Dir Stranger", EdifyRole.CCEO
        )
        cls.cd_user, cls.cd = _person(
            "dir-cd@t.test", "Dir Director", EdifyRole.COUNTRY_DIRECTOR
        )
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)
        cls.school = cls._school("DIR-1", "Dir Alpha", cls.cceo)
        cls.other_school = cls._school("DIR-2", "Dir Beta", cls.other)

    @classmethod
    def _school(cls, ref, name, owner, district=None):
        school = School.objects.create(
            school_id=ref,
            name=name,
            region=(district or cls.district).region,
            district=district or cls.district,
            enrollment=200,
            account_owner_id=owner.id,
            account_owner_name_raw=owner.title,
        )
        StaffSchoolAssignment.objects.create(staff=owner, school_id=school.id)
        return school

    def as_user(self, user) -> Client:
        client = Client()
        client.force_login(user)
        return client


class FiscalYearDefaultsTest(DirectoryFixture):
    PAGES = ("/schools", "/clusters", "/core-schools")

    def test_each_page_opens_on_the_operational_year(self):
        client = self.as_user(self.cceo_user)
        for url in self.PAGES:
            with self.subTest(url=url):
                response = client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["selected_fy"], get_operational_fy())

    def test_a_year_the_platform_does_not_offer_falls_back(self):
        client = self.as_user(self.cceo_user)
        for url in self.PAGES:
            with self.subTest(url=url):
                response = client.get(url, {"fy": "1999"})
                self.assertEqual(response.context["selected_fy"], get_operational_fy())

    def test_an_offered_year_is_kept_and_every_offered_year_is_listed(self):
        chosen = fy_options()[0]
        client = self.as_user(self.cceo_user)
        for url in self.PAGES:
            with self.subTest(url=url):
                response = client.get(url, {"fy": chosen})
                self.assertEqual(response.context["selected_fy"], chosen)
                for option in fy_options():
                    self.assertContains(response, f'<option value="{option}"')


class CoverageScopeTest(DirectoryFixture):
    def test_the_cluster_table_lists_the_readers_country_only(self):
        Cluster.objects.create(
            name="Dir Uganda Cluster", region=self.uganda, district=self.district
        )
        Cluster.objects.create(
            name="Dir Kenya Cluster", region=self.kenya, district=self.kenya_district
        )

        response = self.as_user(self.cd_user).get("/coverage")

        names = {cluster.name for cluster in response.context["clusters"]}
        self.assertIn("Dir Uganda Cluster", names)
        self.assertNotIn("Dir Kenya Cluster", names)

    def test_every_visit_type_counts_as_reach(self):
        fy = get_operational_fy()
        Activity.objects.create(
            activity_type="core_visit",
            status="ia_verified",
            school=self.school,
            fy=fy,
            planned_date=date.today(),
            responsible_staff_id=self.cceo.id,
        )
        Activity.objects.create(
            activity_type="in_school_training",
            status="ia_verified",
            school=self.other_school,
            fy=fy,
            planned_date=date.today(),
            responsible_staff_id=self.other.id,
        )

        response = self.as_user(self.cd_user).get("/coverage", {"fy": fy})

        # The core visit reaches its school; a training is not a visit.
        self.assertEqual(response.context["visited"], 1)


class ClosedArchiveScopeTest(DirectoryFixture):
    def _close(self, school, closer):
        lifecycle_service.close_school(
            school.id,
            {
                "closure_type": ClosureType.PERMANENT,
                "reason_category": ClosureReason.FINANCIAL,
                "reason": EXPLANATION,
                "effective_date": date.today(),
            },
            closer,
        )

    def test_each_reader_sees_the_closures_in_their_own_scope(self):
        self._close(self.school, self.cceo_user)
        self._close(self.other_school, self.other_user)

        def archive(user):
            return self.as_user(user).get("/schools/closed").content.decode()

        officer = archive(self.cceo_user)
        self.assertIn("Dir Alpha", officer)
        self.assertNotIn("Dir Beta", officer)

        lead = archive(self.pl_user)
        self.assertIn("Dir Alpha", lead)
        self.assertNotIn("Dir Beta", lead)

        director = archive(self.cd_user)
        self.assertIn("Dir Alpha", director)
        self.assertIn("Dir Beta", director)

    def test_the_archive_totals_count_the_readers_closures(self):
        self._close(self.school, self.cceo_user)
        self._close(self.other_school, self.other_user)

        response = self.as_user(self.cceo_user).get("/schools/closed")

        self.assertEqual(response.context["closed_count"], 1)
        self.assertEqual(response.context["enrollment_removed"], 200)


class DeadViewRemovedTest(TestCase):
    def test_the_unrouted_completed_activities_view_is_gone(self):
        from apps.frontend.views import extended_views

        self.assertFalse(hasattr(extended_views, "completed_activities_view"))


class ReportsLinkFollowsAccessTest(TestCase):
    """District delivery gaps offers "View reports" only to readers of /reports.

    The Programme Lead lost `reports` (unscoped counts) on 2026-09-13; the
    analytics view hands the partial `can_open_reports` from the page rule.
    """

    def test_the_link_is_drawn_only_when_the_reader_may_open_reports(self):
        from django.template.loader import render_to_string

        template = "partials/analytics/target_by_district.html"
        self.assertIn(
            'href="/reports"', render_to_string(template, {"can_open_reports": True})
        )
        self.assertNotIn(
            'href="/reports"', render_to_string(template, {"can_open_reports": False})
        )

    def test_the_programme_lead_may_not_open_reports(self):
        from apps.core.permissions import RolePermissionService

        pl_user, _pl = _person(
            "dir-reports-pl@t.test", "Reports Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        self.assertFalse(RolePermissionService.can_view_page(pl_user, "reports"))
