from __future__ import annotations

from rest_framework.test import APITestCase

from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School


class SchoolDetailAndAssignmentOptionsTest(APITestCase):
    def setUp(self):
        # Create standard geo hierarchy
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Mukono", region=self.region)

        # Create user / planner context
        self.user = User.objects.create_user(
            email="planner@test.edify.org",
            name="Cceo Planner",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="password",
            is_active=True,
        )
        self.profile = StaffProfile.objects.create(
            user=self.user, title="CCEO", id="STF-001"
        )

        # Create a school with no staff assignment
        self.school = School.objects.create(
            school_id="SCH-999",
            name="Unassigned School",
            region=self.region,
            district=self.district,
            school_type="client",
        )

    def test_assignment_options_for_unassigned_school(self):
        """GET /api/assignment/options returns correct payload with options and assignments: [] when no assignment exists."""
        from apps.accounts.jwt import issue_access_token

        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {issue_access_token(self.user.id, self.user.active_role)}"
        )

        response = self.client.get(
            f"/api/assignment/options?schoolId={self.school.school_id}"
        )
        self.assertEqual(response.status_code, 200)

        data = response.json()
        self.assertEqual(data["schoolId"], self.school.school_id)
        self.assertIn("options", data)
        self.assertIn("capacity", data)
        self.assertEqual(data["assignments"], [])
