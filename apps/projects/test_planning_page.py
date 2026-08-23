from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.core.enums import ActivityStatus, SsaIntervention
from apps.core.fy import get_operational_fy, get_quarter_for_date
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore

from .models import Project, ProjectSchoolAssignment
from .planning_service import get_planning


class SpecialProjectPlanningPageTests(TestCase):
    def setUp(self):
        self.fy = get_operational_fy()
        self.quarter = get_quarter_for_date()
        self.admin = User.objects.create_user(
            email="project-planning-admin@example.org",
            name="Planning Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="test-password",
        )
        self.staff = StaffProfile.objects.create(user=self.admin, title="Project Lead")
        self.region = Region.objects.create(name="Project Planning Region")
        self.district = District.objects.create(
            name="Project Planning District", region=self.region
        )
        self.school = School.objects.create(
            school_id="SPP-001",
            name="Lakeview Project School",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="done",
            planning_readiness="ready_for_support_planning",
        )
        self.unassigned_school = School.objects.create(
            school_id="SPP-002",
            name="Not in a Project",
            region=self.region,
            district=self.district,
        )
        self.project_a = Project.objects.create(
            name="Reading Excellence Initiative",
            category="pilot",
            manager_staff_id=self.staff.id,
        )
        self.project_b = Project.objects.create(
            name="Leadership Growth Project",
            category="intervention_specific",
            manager_staff_id=self.staff.id,
        )
        self.assignment_a = ProjectSchoolAssignment.objects.create(
            project=self.project_a, school=self.school
        )
        self.assignment_b = ProjectSchoolAssignment.objects.create(
            project=self.project_b, school=self.school
        )
        self.ssa = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.now(),
            fy=self.fy,
            quarter=self.quarter,
            average_score=4.7,
            uploaded_by=self.admin.id,
            verification_status="confirmed",
        )
        SsaScore.objects.create(
            ssa_record=self.ssa,
            intervention=SsaIntervention.LEARNING_ENVIRONMENT,
            score=3.8,
        )
        self.activity = Activity.objects.create(
            activity_type="school_visit",
            school=self.school,
            project_id=self.project_a.id,
            fy=self.fy,
            quarter=self.quarter,
            planned_date=timezone.localdate(),
            status=ActivityStatus.SCHEDULED,
            responsible_staff_id=self.staff.id,
            activity_purpose_text="Reading project coaching",
        )
        self.client.force_login(self.admin)

    def test_school_directory_project_assignment_is_the_only_intake(self):
        response = self.client.get("/projects/planning")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Lakeview Project School")
        self.assertNotContains(response, "Not in a Project")
        self.assertContains(response, "School Directory intake")

    def test_readiness_is_specific_to_each_school_project_pair(self):
        context = get_planning(
            self.admin, {"fy": self.fy, "quarter": self.quarter, "per_page": 25}
        )
        rows = {row["project_id"]: row for row in context["rows"]}
        self.assertEqual(rows[self.project_a.id]["bucket"], "scheduled")
        self.assertEqual(rows[self.project_b.id]["bucket"], "ready")
        self.assertEqual(rows[self.project_b.id]["weakest"], "Learning Environment")
        self.assertEqual(rows[self.project_b.id]["average"], 4.7)

    def test_kpi_strip_keeps_six_distinct_planning_signals(self):
        context = get_planning(
            self.admin, {"fy": self.fy, "quarter": self.quarter, "per_page": 25}
        )
        labels = [item["label"] for item in context["kpis"]]

        self.assertEqual(len(labels), 6)
        self.assertEqual(
            labels,
            [
                "Total Project Schools",
                "SSA Score Required",
                "Scheduled This Week",
                "Planning Completion",
                "High-Risk Project Schools",
                "Schools Requiring Follow-up",
            ],
        )
        self.assertNotIn("Assigned to Partner", labels)
        self.assertNotIn("Schools in Active Projects", labels)

    def test_filters_htmx_and_export_use_the_same_scoped_dataset(self):
        filtered = self.client.get(f"/projects/planning?project={self.project_b.id}")
        self.assertEqual(filtered.status_code, 200)
        self.assertContains(filtered, "Leadership Growth Project")
        self.assertNotContains(filtered, "Reading project coaching")

        htmx = self.client.get("/projects/planning?tab=ready", HTTP_HX_REQUEST="true")
        self.assertEqual(htmx.status_code, 200)
        self.assertNotContains(htmx, "<!DOCTYPE html>")
        self.assertContains(htmx, "Ready for Support")

        export = self.client.get(
            f"/projects/planning?project={self.project_b.id}&export=csv"
        )
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export["Content-Type"], "text/csv")
        self.assertIn("Lakeview Project School", export.content.decode())
        self.assertNotIn("Reading Excellence Initiative", export.content.decode())

    def test_admin_does_not_bulk_schedule_project_work(self):
        """Planning is the owner's, on Special Projects as everywhere else.

        Admin used to be allowed here. It creates real dated visits whose
        responsible staff is derived from the school, so the work lands on a
        field officer's plan without that person choosing it — the reason
        scheduling joined the reserved authorities in
        apps/core/tests/test_admin_platform_boundary.py. Reading the planning
        page is unaffected; the test below still pins that.
        """
        schedule = self.client.get(
            f"/projects/planning/bulk-schedule?assignments={self.assignment_a.id}"
        )
        self.assertEqual(schedule.status_code, 403)
        self.assertIn("does not schedule field work", schedule.content.decode())

    def test_admin_still_reads_the_project_planning_page(self):
        page = self.client.get("/projects/planning")
        self.assertEqual(page.status_code, 200)
