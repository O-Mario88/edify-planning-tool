"""A school with no district on record must not take a page down.

Production, 2026-10-06: My Plan answered 500 for a CCEO —
``'NoneType' object has no attribute 'name'`` at ``a.school.district.name``.
The upload keeps a school whose district name it cannot match: the typed text
is stored and the district, region and sub-county links are left empty
(``schools.upload_service``). Scheduling such a school put a row on My Plan
that the page could not print.

The seed has no such school, so nothing caught it. Every page that printed
``school.district.name`` or ``school.region.name`` unguarded is opened here
with one.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.schools.models import School

User = get_user_model()


class SchoolWithoutDistrictTest(TestCase):
    def setUp(self):
        self.cceo = User.objects.create(
            id="nd-cceo",
            email="nd-cceo@edify.org",
            name="ND Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(
            id="nd-cceo-sp", user=self.cceo, title="CCEO", country="Uganda"
        )
        self.admin = User.objects.create(
            id="nd-admin",
            email="nd-admin@edify.org",
            name="ND Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        # As the upload leaves it: the typed district kept, no link made.
        self.school = School.objects.create(
            school_id="ND-1",
            name="Kyabazinga Memorial Primary",
            uploaded_district_text="Bugweri Central",
            account_owner_id=self.profile.id,
        )
        self.core_school = School.objects.create(
            school_id="ND-2",
            name="Namutumba Parents Primary",
            school_type="core",
            uploaded_district_text="Bugweri Central",
            account_owner_id=self.profile.id,
        )
        for school in (self.school, self.core_school):
            StaffSchoolAssignment.objects.create(
                staff=self.profile, school_id=school.id
            )
        today = date.today()
        self.visit = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            responsible_staff_id=self.profile.id,
            delivery_type="staff",
            status="scheduled",
            planned_date=today,
            fy=get_operational_fy(),
            quarter=get_quarter_for_date(today),
        )

    def _get(self, user, path):
        client = Client()
        client.force_login(user)
        return client.get(path)

    def test_my_plan_opens_and_lists_the_school(self):
        response = self._get(self.cceo, "/my-plan")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kyabazinga Memorial Primary")

    def test_a_core_card_prints_a_dash_and_no_search_link_for_the_district(self):
        """The Core cards link a district to a school search; a school with
        none must read as a dash, not as a link to a search for a word."""
        Activity.objects.filter(id=self.visit.id).update(school=self.core_school)
        response = self._get(self.cceo, "/my-plan")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Namutumba Parents Primary")
        self.assertNotContains(response, "/schools?q=Unknown")

    def test_my_plan_opens_for_every_period(self):
        for period in ("week", "month", "quarter", "year"):
            with self.subTest(period=period):
                response = self._get(self.cceo, f"/my-plan?period={period}")
                self.assertEqual(response.status_code, 200)

    def test_core_schools_list_opens_and_lists_the_school(self):
        response = self._get(self.cceo, "/core-schools")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Namutumba Parents Primary")

    def test_project_planning_opens_and_lists_the_school(self):
        project = Project.objects.create(
            name="No District Project",
            category="pilot",
            manager_staff_id=self.profile.id,
        )
        ProjectSchoolAssignment.objects.create(project=project, school=self.school)
        response = self._get(self.admin, "/projects/planning")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Kyabazinga Memorial Primary")

    def test_planning_bulk_export_writes_the_school(self):
        client = Client()
        client.force_login(self.cceo)
        response = client.post(
            "/planning/bulk-action",
            {"action": "export", "school_ids": [self.school.school_id]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("ND-1,Kyabazinga Memorial Primary,—", response.content.decode())
