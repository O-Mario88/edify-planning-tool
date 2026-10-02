"""Handing a Core school's partner half over (owner, 2026-10-02).

"make sure the PLs and CCEOs can assign the remaining packages to the partner
through either in-school training, follow up, or project." Asked, the owner
kept the Programme Lead read-only at an officer's school: the officer assigns,
the Lead asks them to.

Two things stood in an officer's way. The Core Schools doors asked for this
year's package exactly, and a school whose new-year package had not been made
yet was refused; and the hand-over drawers offered no way through a project.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.core_schools.models import CorePlan, cplan_id
from apps.core_schools.package_split import PARTNER, VISIT, package_split
from apps.core_schools.services import create_package_slots
from apps.frontend.views.core_schools_views import _locked_core_plan
from apps.frontend.views.planning_views import project_handover_routes
from apps.geography.models import District, Region
from apps.partners.models import Partner, PartnerAssignment
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School


def _person(email, name, role):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        is_active=True,
        status="active",
    )
    return user, StaffProfile.objects.create(user=user, title=name, country="Uganda")


class _Fixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.last_fy = str(int(cls.fy) - 1)
        region = Region.objects.create(name="Route Region")
        district = District.objects.create(name="Route District", region=region)
        cls.cceo_user, cls.cceo = _person(
            "cceo@route.test", "Officer", EdifyRole.CCEO.value
        )
        cls.school = School.objects.create(
            school_id="ROUTE-1",
            name="Route Core Primary",
            region=region,
            district=district,
            school_type="core",
            account_owner_id=cls.cceo.id,
            account_owner_status="matched",
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo, school_id=cls.school.id)
        # Last year's package, and none made for this year yet.
        cls.plan = CorePlan.objects.create(
            id=cplan_id("ROUTE-1", fy=cls.last_fy),
            school_id="ROUTE-1",
            fy=cls.last_fy,
            status="Active",
        )
        create_package_slots(cls.plan, "ROUTE-1", ["leadership"])
        cls.partner = Partner.objects.create(name="Route Partner", active_status=True)


class LivePackageTest(_Fixture):
    def test_the_doors_book_into_the_package_the_school_has(self):
        self.assertFalse(
            CorePlan.objects.filter(school_id="ROUTE-1", fy=self.fy).exists()
        )
        self.assertEqual(_locked_core_plan("ROUTE-1").id, self.plan.id)

    def test_this_years_package_wins_once_it_exists(self):
        this_year = CorePlan.objects.create(
            id=cplan_id("ROUTE-1", fy=self.fy),
            school_id="ROUTE-1",
            fy=self.fy,
            status="Active",
        )
        self.assertEqual(_locked_core_plan("ROUTE-1").id, this_year.id)

    def test_a_school_with_no_package_has_none(self):
        self.assertIsNone(_locked_core_plan("NO-SUCH-SCHOOL"))

    def test_an_officer_hands_a_visit_over_without_this_years_package(self):
        self.client.force_login(self.cceo_user)
        response = self.client.post(
            "/core-schools/assign-partner/action",
            {
                "school_id": "ROUTE-1",
                "partner_id": self.partner.id,
                "purpose_of_visit": "ssa_support",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200, response.content)
        handover = PartnerAssignment.objects.get(school=self.school)
        self.assertEqual(handover.partner_id, self.partner.id)
        self.assertEqual(package_split(self.school).used(VISIT, PARTNER), 1)


class ProjectRouteTest(_Fixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.project = Project.objects.create(
            name="Route Project",
            category="pilot",
            status="active",
            intervention="leadership",
        )
        cls.closed = Project.objects.create(
            name="Closed Project",
            category="pilot",
            status="closed",
            intervention="leadership",
        )
        cls.enrolment = ProjectSchoolAssignment.objects.create(
            project=cls.project, school=cls.school
        )
        ProjectSchoolAssignment.objects.create(project=cls.closed, school=cls.school)

    def test_the_schools_open_projects_are_the_routes(self):
        routes = project_handover_routes(self.cceo_user, self.school)
        self.assertEqual(
            routes,
            [{"assignment_id": self.enrolment.id, "project_name": "Route Project"}],
        )

    def test_no_school_no_routes(self):
        self.assertEqual(project_handover_routes(self.cceo_user, None), [])

    def test_the_core_drawer_offers_the_project(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            "/core-schools/assign-partner", {"school_id": "ROUTE-1"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Or assign through a project")
        self.assertContains(
            response,
            f"/projects/planning/bulk-partner?assignments={self.enrolment.id}",
        )
        self.assertNotContains(response, "Closed Project")

    def test_the_planning_drawer_offers_it_too(self):
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            "/planning/assign-partner-modal", {"school_id": self.school.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-project-handover")

    def test_a_school_in_no_project_shows_no_route(self):
        ProjectSchoolAssignment.objects.all().delete()
        self.client.force_login(self.cceo_user)
        response = self.client.get(
            "/core-schools/assign-partner", {"school_id": "ROUTE-1"}
        )
        self.assertNotContains(response, "Or assign through a project")


class LeadStaysReadOnlyTest(_Fixture):
    """Owner, 2026-10-02: "PL should have read only access to CCEO schools
    and planned activities"."""

    def test_a_lead_cannot_hand_an_officers_school_over(self):
        from apps.accounts.models import StaffSupervisorAssignment

        lead_user, lead = _person(
            "lead@route.test", "Lead", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        StaffSupervisorAssignment.objects.create(supervisee=self.cceo, supervisor=lead)
        self.client.force_login(lead_user)
        drawer = self.client.get(
            "/core-schools/assign-partner",
            {"school_id": "ROUTE-1"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(drawer.status_code, 403)
        response = self.client.post(
            "/core-schools/assign-partner/action",
            {
                "school_id": "ROUTE-1",
                "partner_id": self.partner.id,
                "purpose_of_visit": "ssa_support",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PartnerAssignment.objects.exists())
