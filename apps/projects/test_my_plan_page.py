from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.geography.models import District, Region
from apps.partners.models import Partner
from apps.schools.models import School

from .models import Project, ProjectSchoolAssignment


class SpecialProjectMyPlanPageTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()
        self.fy = get_operational_fy(self.today)
        self.quarter = get_quarter_for_date(self.today)
        self.region = Region.objects.create(name="Project Plan Region")
        self.district = District.objects.create(
            name="Project Plan District", region=self.region
        )
        self.school_a = School.objects.create(
            school_id="SP-PLAN-A",
            name="Coordinator A School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        self.school_b = School.objects.create(
            school_id="SP-PLAN-B",
            name="Coordinator B School",
            region=self.region,
            district=self.district,
            school_type="client",
        )
        self.user_a = User.objects.create_user(
            email="project-plan-a@example.org",
            name="Coordinator A",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
        )
        self.user_b = User.objects.create_user(
            email="project-plan-b@example.org",
            name="Coordinator B",
            roles=["ProjectCoordinator"],
            active_role="ProjectCoordinator",
        )
        self.staff_a = StaffProfile.objects.create(
            user=self.user_a, title="Project Coordinator"
        )
        self.staff_b = StaffProfile.objects.create(
            user=self.user_b, title="Project Coordinator"
        )
        self.project_a = Project.objects.create(
            name="Project Alpha",
            code="SP-PLAN-ALPHA",
            category="pilot",
            manager_staff_id=self.staff_a.id,
        )
        self.project_b = Project.objects.create(
            name="Project Beta",
            code="SP-PLAN-BETA",
            category="pilot",
            manager_staff_id=self.staff_b.id,
        )
        ProjectSchoolAssignment.objects.create(
            project=self.project_a, school=self.school_a
        )
        ProjectSchoolAssignment.objects.create(
            project=self.project_b, school=self.school_b
        )
        self.partner = Partner.objects.create(name="Project Delivery Partner")
        self.staff_activity = self._activity(
            project=self.project_a,
            school=self.school_a,
            responsible_staff_id=self.staff_a.id,
        )
        self.partner_activity = self._activity(
            project=self.project_a,
            school=self.school_a,
            delivery_type="partner",
            assigned_partner_id=self.partner.id,
            status="assigned_to_partner",
        )
        self.other_activity = self._activity(
            project=self.project_b,
            school=self.school_b,
            responsible_staff_id=self.staff_b.id,
        )

    def _activity(self, *, project, school, **overrides):
        values = {
            "activity_type": "school_visit",
            "school": school,
            "project_id": project.id,
            "fy": self.fy,
            "fiscal_year": self.fy,
            "quarter": self.quarter,
            "month": self.today.month,
            "planned_month": self.today.month,
            "planned_week": min(5, (self.today.day - 1) // 7 + 1),
            "planned_date": self.today,
            "status": "scheduled",
            "delivery_type": "staff",
            "activity_purpose_text": "Instructional support",
        }
        values.update(overrides)
        return Activity.objects.create(**values)

    def test_page_is_project_manager_scoped_and_partner_work_is_read_only(self):
        self.client.force_login(self.user_a)
        response = self.client.get("/projects/my-plan")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Coordinator A School")
        self.assertNotContains(response, "Coordinator B School")
        self.assertContains(response, "Project Delivery Partner")
        partner_rows = response.context["partner_activities"]
        self.assertEqual(len(partner_rows), 1)
        self.assertTrue(partner_rows[0]["readonly"])
        self.assertEqual(partner_rows[0]["action"]["text"], "View details")

    def test_period_filter_htmx_and_csv_use_the_same_scoped_feed(self):
        future = self.today + timedelta(days=40)
        self._activity(
            project=self.project_a,
            school=self.school_a,
            responsible_staff_id=self.staff_a.id,
            planned_date=future,
            planned_month=future.month,
            month=future.month,
            quarter=get_quarter_for_date(future),
        )
        self.client.force_login(self.user_a)
        response = self.client.get(
            f"/projects/my-plan?period=week&week={(self.today - timedelta(days=self.today.weekday())).isoformat()}",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "partials/projects/my_plan_workspace.html")
        self.assertContains(response, "sp-plan-filters")

        export = self.client.get("/projects/my-plan?export=csv")
        body = export.content.decode()
        self.assertEqual(export.status_code, 200)
        self.assertIn("Coordinator A School", body)
        self.assertNotIn("Coordinator B School", body)

    def test_special_project_calendar_preserves_project_scope(self):
        self.client.force_login(self.user_a)
        response = self.client.get(
            f"/calendar?project_scope=special&month={self.today.month}&year={self.today.year}"
        )
        self.assertEqual(response.status_code, 200)
        activities = list(response.context["activities"])
        self.assertIn(self.staff_activity, activities)
        self.assertIn(self.partner_activity, activities)
        self.assertNotIn(self.other_activity, activities)
