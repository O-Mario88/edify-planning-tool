from rest_framework.test import APITestCase
from apps.geography.models import Region, District
from apps.schools.models import School
from apps.ssa.models import SsaRecord, SsaScore
from apps.accounts.models import User
from apps.core.exceptions import BadRequest
from apps.ssa import services as ssa_services
from apps.ssa.services import get_ssa_progress_by_fy
from apps.core.fy import get_operational_fy


class SsaSequentialValidationTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala District", region=self.region)
        self.school = School.objects.create(
            school_id="SCH-VAL-99",
            name="Validation Academy",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="not_done",
        )
        self.user = User.objects.create_user(
            email="tester.val@edify.test",
            name="Val Tester",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="pwd",
            is_active=True,
        )
        import os
        os.environ["ENFORCE_SSA_SEQUENCE"] = "true"

    def tearDown(self):
        import os
        if "ENFORCE_SSA_SEQUENCE" in os.environ:
            del os.environ["ENFORCE_SSA_SEQUENCE"]

    def test_current_fy_ssa_blocks_without_previous_fy_ssa(self):
        """Uploading target current FY assessment must fail if previous year is missing."""
        current_fy = get_operational_fy()
        # For current FY (Oct 2025 - Sep 2026 is FY 2026, let's use 2026-06-15)
        # Note: timezone-aware date is passed as isoformat
        data = {
            "schoolId": "SCH-VAL-99",
            "dateOfSsa": "2026-06-15T00:00:00Z",
            "scores": [
                {"intervention": "teaching_and_learning", "score": 8.0},
                {"intervention": "financial_health", "score": 7.0},
                {"intervention": "christlike_behaviour", "score": 9.0},
                {"intervention": "exposure_to_word_of_god", "score": 8.0},
                {"intervention": "government_requirements", "score": 6.0},
                {"intervention": "leadership", "score": 7.0},
                {"intervention": "education_technology", "score": 5.0},
                {"intervention": "learning_environment", "score": 8.0},
            ]
        }

        # Assert BadRequest is raised
        with self.assertRaises(BadRequest) as ctx:
            ssa_services.upload(data, self.user)
        self.assertIn("previous FY", str(ctx.exception))

    def test_current_fy_ssa_succeeds_when_previous_fy_exists(self):
        """Uploading current FY assessment succeeds when the previous year's SSA exists and is confirmed."""
        # 1. Create previous FY SSA (FY 2025, let's use 2025-06-15)
        prev_record = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa="2025-06-15T00:00:00Z",
            fy="2025",
            quarter="Q3",
            average_score=7.0,
            verification_status="confirmed",
            uploaded_by=self.user.user_id,
        )
        for intervention in [
            "teaching_and_learning", "financial_health", "christlike_behaviour",
            "exposure_to_word_of_god", "government_requirements", "leadership",
            "education_technology", "learning_environment"
        ]:
            SsaScore.objects.create(ssa_record=prev_record, intervention=intervention, score=7.0)

        # 2. Upload current FY SSA (FY 2026)
        data = {
            "schoolId": "SCH-VAL-99",
            "dateOfSsa": "2026-06-15T00:00:00Z",
            "scores": [
                {"intervention": "teaching_and_learning", "score": 8.0},
                {"intervention": "financial_health", "score": 7.0},
                {"intervention": "christlike_behaviour", "score": 9.0},
                {"intervention": "exposure_to_word_of_god", "score": 8.0},
                {"intervention": "government_requirements", "score": 6.0},
                {"intervention": "leadership", "score": 7.0},
                {"intervention": "education_technology", "score": 5.0},
                {"intervention": "learning_environment", "score": 8.0},
            ]
        }

        result = ssa_services.upload(data, self.user)
        self.assertIsNotNone(result["id"])
        self.assertEqual(result["fy"], "2026")

        # 3. Verify get_ssa_progress_by_fy tracks correct progression
        progress = get_ssa_progress_by_fy(School.objects.filter(id=self.school.id))
        self.assertEqual(len(progress), 2)
        self.assertEqual(progress[0]["fy"], "2025")
        self.assertEqual(progress[0]["avg_score"], 7.0)
        self.assertEqual(progress[1]["fy"], "2026")
        # Average is (8+7+9+8+6+7+5+8)/8 = 58/8 = 7.25 -> rounds to 7.2 in Python round-to-even
        self.assertEqual(progress[1]["avg_score"], 7.2)


class AttendanceUploadActionTest(APITestCase):
    def setUp(self):
        from apps.clusters.models import Cluster
        from apps.geography.models import Region, District
        self.region = Region.objects.create(name="East Region")
        self.district = District.objects.create(name="Jinja District", region=self.region)
        self.cluster = Cluster.objects.create(
            name="Test Cluster Jinja",
            region=self.region,
            district=self.district,
        )
        self.school1 = School.objects.create(
            school_id="SCH-ATT-1",
            name="Jinja Academy 1",
            region=self.region,
            district=self.district,
        )
        self.school2 = School.objects.create(
            school_id="SCH-ATT-2",
            name="Jinja Academy 2",
            region=self.region,
            district=self.district,
        )
        from apps.clusters.models import SchoolClusterAssignment
        SchoolClusterAssignment.objects.create(school=self.school1, cluster=self.cluster, assigned_by="test-user")
        SchoolClusterAssignment.objects.create(school=self.school2, cluster=self.cluster, assigned_by="test-user")

        from apps.activities.models import Activity
        self.activity = Activity.objects.create(
            activity_type="cluster_meeting",
            cluster=self.cluster,
            fy="2026",
            quarter="Q3",
            status="scheduled",
        )
        self.user = User.objects.create_user(
            email="tester.att@edify.test",
            name="Att Tester",
            roles=["Admin"],
            active_role="Admin",
            password="pwd",
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_attendance_upload_drawer_context(self):
        """Attendance drawer context returns cluster_schools."""
        response = self.client.get(f"/activities/{self.activity.id}/attendance")
        self.assertEqual(response.status_code, 200)
        self.assertIn("cluster_schools", response.context)
        self.assertEqual(len(response.context["cluster_schools"]), 2)

    def test_attendance_upload_action_saves_attended_school_ids(self):
        """Posting to attendance_upload_action saves checked school IDs."""
        post_data = {
            "teachers_attended": 5,
            "leaders_attended": 2,
            "attended_schools": [self.school1.id],
            "notes": "Good session",
        }
        response = self.client.post(f"/activities/{self.activity.id}/attendance/action", post_data, format="multipart")
        self.assertEqual(response.status_code, 302)
        
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "completed")
        self.assertEqual(self.activity.teachers_attended, 5)
        self.assertEqual(self.activity.leaders_attended, 2)
        self.assertEqual(self.activity.attended_school_ids, [self.school1.id])
