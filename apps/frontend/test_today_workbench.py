"""Phase 5: the Today workbench under test.

Pins: field roles get the page and non-field roles do not; the sections
render from real state (honest empty states included); the proposed-week
flow works end-to-end through the page's own POST endpoint; and a foreign
proposal can never be accepted through it.
"""

from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.autopilot.models import ProposedPlan
from apps.geography.models import District, Region, SubCounty
from apps.schools.models import School


def _user(role, email):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="test-password",
        is_active=True,
    )
    staff = StaffProfile.objects.create(user=user, title=role)
    return user, staff


class TodayWorkbenchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cceo, cls.cceo_sp = _user("CCEO", "today-cceo@example.test")
        cls.accountant, _ = _user("Accountant", "today-acct@example.test")
        cls.region = Region.objects.create(name="TW Region")
        cls.district = District.objects.create(name="TW District", region=cls.region)
        cls.sub_county = SubCounty.objects.create(name="TW SC", district=cls.district)
        school = School.objects.create(
            school_id="TW-1",
            name="Today School",
            region=cls.region,
            district=cls.district,
            sub_county=cls.sub_county,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=cls.cceo_sp, school_id=school.id)

    def test_a_field_role_gets_the_workbench(self):
        self.client.force_login(self.cceo)
        response = self.client.get("/today")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your next activity")
        self.assertContains(response, "Exceptions requiring attention")
        self.assertContains(response, "Your proposed week")
        # Honest empty states, never fabricated content.
        self.assertContains(response, "Nothing scheduled for today")

    def test_non_field_roles_never_see_it(self):
        self.client.force_login(self.accountant)
        response = self.client.get("/today")
        self.assertNotEqual(response.status_code, 200)

    def test_prepare_accept_week_end_to_end(self):
        self.client.force_login(self.cceo)
        response = self.client.post(
            "/today/action", {"action": "prepare_week"}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        plan = ProposedPlan.objects.get(staff=self.cceo_sp)
        self.assertContains(response, "Today School")
        self.assertContains(response, "Accept week")

        response = self.client.post(
            "/today/action",
            {"action": "accept_week", "plan": plan.id},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "accepted")

    def test_a_foreign_proposal_cannot_be_accepted_here(self):
        other, other_sp = _user("CCEO", "today-other@example.test")
        from apps.autopilot.services import generate_week_proposal

        school = School.objects.create(
            school_id="TW-2",
            name="Other School",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=other_sp, school_id=school.id)
        plan = generate_week_proposal(other_sp)
        self.client.force_login(self.cceo)
        response = self.client.post(
            "/today/action", {"action": "accept_week", "plan": plan.id}
        )
        self.assertEqual(response.status_code, 403)
        plan.refresh_from_db()
        self.assertEqual(plan.status, "proposed")

    def test_todo_rows_surface_with_their_real_keys(self):
        # The seam that silently breaks: todo_service rows carry action_url/
        # description/priority/status_key. A real planned activity must
        # surface as a linked row, not an empty shell.
        from datetime import date as date_cls

        from apps.activities.models import Activity
        from apps.schools.models import School

        school = School.objects.get(school_id="TW-1")
        Activity.objects.create(
            activity_type="school_visit",
            status="planned",
            planned_date=date_cls.today(),
            fy="2027",
            school=school,
            responsible_staff_id=self.cceo_sp.id,
        )
        self.client.force_login(self.cceo)
        response = self.client.get("/today")
        self.assertEqual(response.status_code, 200)
        waiting = response.context["waiting"]
        exceptions = response.context["exceptions"]
        rows = list(waiting) + list(exceptions)
        self.assertTrue(rows, "a planned activity must produce a To-Do row")
        for row in rows:
            self.assertIn("title", row)
            self.assertIn("action_url", row)
            self.assertContains(response, row["action_url"])

    def test_the_sidebar_offers_today_to_field_roles_only(self):
        from apps.core.navigation import build_sidebar_for_user

        cceo_items = [
            item["label"]
            for section in build_sidebar_for_user(self.cceo, "/today")
            for item in section["items"]
        ]
        self.assertIn("Today", cceo_items)
        accountant_items = [
            item["label"]
            for section in build_sidebar_for_user(self.accountant, "/dashboard")
            for item in section["items"]
        ]
        self.assertNotIn("Today", accountant_items)
