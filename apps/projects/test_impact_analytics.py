from datetime import datetime, timezone

from django.test import TestCase

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.core.enums import (
    ActivityStatus,
    ActivityType,
    EvidenceStatus,
    SsaIntervention,
    VerificationStatus,
)
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.projects.impact_service import get_analytics
from apps.projects.models import Project, ProjectCategory, ProjectSchoolAssignment
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore


class SpecialProjectImpactAnalyticsTest(TestCase):
    fy = "2026"

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            email="impact-admin@example.org",
            name="Impact Admin",
            password="testing-only",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
        )
        cls.region = Region.objects.create(name="Impact North")
        cls.district = District.objects.create(
            name="Impact District", region=cls.region
        )
        cls.project = Project.objects.create(
            code="SP-IMPACT-TEST",
            name="Leadership Lift",
            category=ProjectCategory.INTERVENTION_SPECIFIC,
            intervention=SsaIntervention.LEADERSHIP,
        )

        cls.assigned_schools = []
        for index in range(3):
            school = cls._school(index, assigned=True)
            cls.assigned_schools.append(school)
            cls._ssa_pair(school)
            cls._delivered_activity(school, teachers=10)

        # A project stamp alone must never expand the assigned School Directory
        # cohort or its reach/attendance metrics.
        cls.unassigned_school = cls._school(99, assigned=False)
        cls._ssa_pair(cls.unassigned_school)
        cls._delivered_activity(cls.unassigned_school, teachers=99)

    @classmethod
    def _school(cls, index, *, assigned):
        school = School.objects.create(
            school_id=f"IMPACT-{index:03d}",
            name=f"Impact School {index}",
            region=cls.region,
            district=cls.district,
            enrollment=100,
        )
        if assigned:
            ProjectSchoolAssignment.objects.create(
                project=cls.project,
                school=school,
                assigned_by=cls.admin.id,
            )
        return school

    @classmethod
    def _ssa_pair(cls, school):
        baseline = SsaRecord.objects.create(
            school=school,
            date_of_ssa=datetime(2025, 9, 15, tzinfo=timezone.utc),
            fy="2025",
            quarter="Q4",
            verification_status=VerificationStatus.CONFIRMED,
            uploaded_by=cls.admin.id,
        )
        latest = SsaRecord.objects.create(
            school=school,
            date_of_ssa=datetime(2026, 7, 15, tzinfo=timezone.utc),
            fy=cls.fy,
            quarter="Q4",
            verification_status=VerificationStatus.CONFIRMED,
            uploaded_by=cls.admin.id,
        )
        for record, leadership, financial in (
            (baseline, 4.0, 8.0),
            (latest, 6.0, 2.0),
        ):
            SsaScore.objects.create(
                ssa_record=record,
                intervention=SsaIntervention.LEADERSHIP,
                score=leadership,
            )
            SsaScore.objects.create(
                ssa_record=record,
                intervention=SsaIntervention.FINANCIAL_HEALTH,
                score=financial,
            )

    @classmethod
    def _delivered_activity(cls, school, *, teachers):
        return Activity.objects.create(
            activity_type=ActivityType.PROJECT_ACTIVITY,
            school=school,
            project_id=cls.project.id,
            fy=cls.fy,
            fiscal_year=cls.fy,
            quarter="Q4",
            planned_date=datetime(2026, 7, 10).date(),
            focus_intervention=SsaIntervention.LEADERSHIP,
            status=ActivityStatus.IA_VERIFIED,
            evidence_status=EvidenceStatus.ACCEPTED,
            ia_verification_status=VerificationStatus.CONFIRMED,
            teachers_attended=teachers,
            leaders_attended=1,
        )

    def test_impact_is_exact_to_assigned_schools_and_associated_intervention(self):
        analytics = get_analytics(self.admin, {"fy": self.fy})

        self.assertEqual(len(analytics["matrix"]), 1)
        project = analytics["matrix"][0]
        self.assertEqual(project["schools_assigned"], 3)
        self.assertEqual(project["schools_supported"], 3)
        self.assertEqual(project["measurable_schools"], 3)
        self.assertEqual(project["baseline_avg"], 4.0)
        self.assertEqual(project["latest_avg"], 6.0)
        self.assertEqual(project["delta"], 2.0)
        self.assertEqual(project["classification"], "Great Impact")

        self.assertEqual(
            [row["code"] for row in analytics["interventions"]],
            [SsaIntervention.LEADERSHIP],
        )
        self.assertEqual(analytics["interventions"][0]["delta"], 2.0)
        self.assertEqual(analytics["data_quality"]["verified_activities"], 3)
        self.assertEqual(analytics["donor_snapshot"]["teachers"], 30)
        self.assertEqual(analytics["donor_snapshot"]["students"], 300)

    def test_filters_and_downloads_preserve_the_impact_scope(self):
        great = get_analytics(
            self.admin,
            {
                "fy": self.fy,
                "intervention": SsaIntervention.LEADERSHIP,
                "impact_status": "great",
            },
        )
        self.assertEqual([row["name"] for row in great["matrix"]], ["Leadership Lift"])

        unrelated = get_analytics(
            self.admin,
            {"fy": self.fy, "intervention": SsaIntervention.FINANCIAL_HEALTH},
        )
        self.assertTrue(unrelated["has_projects"])
        self.assertFalse(unrelated["has_results"])

        self.client.force_login(self.admin)
        page = self.client.get("/projects/analytics", {"fy": self.fy})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Special Project Analytics")
        self.assertContains(page, "Leadership Lift")
        self.assertContains(page, "Observed association")

        partial = self.client.get(
            "/projects/analytics",
            {"fy": self.fy, "impact_status": "great"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(partial.status_code, 200)
        self.assertContains(partial, "Leadership Lift")
        self.assertNotContains(partial, "<!doctype html>")

        export = self.client.get(
            "/projects/analytics", {"fy": self.fy, "export": "csv"}
        )
        self.assertEqual(export.status_code, 200)
        self.assertEqual(export["Content-Type"], "text/csv")
        self.assertIn("Leadership Lift", export.content.decode())

        snapshot = self.client.get(
            "/projects/analytics", {"fy": self.fy, "export": "snapshot"}
        )
        self.assertEqual(snapshot.status_code, 200)
        self.assertIn("Data provenance", snapshot.content.decode())
