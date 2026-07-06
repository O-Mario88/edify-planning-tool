from django.utils import timezone
from apps.geography.models import Region, District
from apps.schools.models import School, UnmatchedSSARecord
from apps.activities.models import Activity
from apps.ssa.models import SsaRecord
from apps.accounts.models import User
from rest_framework.test import APITestCase

class SsaLifecycleTest(APITestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Central")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.school = School.objects.create(
            school_id="10099",
            name="Lifecycle Academy",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="not_done",
        )
        self.user = User.objects.create_user(
            email="tester@edify.test",
            name="Tester",
            roles=["ImpactAssessment"],
            active_role="ImpactAssessment",
            password="x",
            is_active=True,
        )
        self.client.force_login(self.user)

    def test_dynamic_ssa_readiness_states(self):
        # Case 1: No SsaRecord and no scheduled activity -> No SSA
        self.assertEqual(self.school.ssa_readiness_state, "No SSA")

        # Case 2: Scheduled activity with ssa_collection_expected
        act = Activity.objects.create(
            activity_type="baseline_ssa_visit",
            school=self.school,
            fy="2026/2027",
            quarter="Q1",
            ssa_collection_expected=True,
            status="scheduled",
        )
        self.assertEqual(self.school.ssa_readiness_state, "Scheduled for Collection")

        # Case 3: SsaRecord exists but in pending verification status
        act.delete()
        rec = SsaRecord.objects.create(
            school=self.school,
            date_of_ssa=timezone.now(),
            fy="2026/2027",
            quarter="Q1",
            average_score=6.5,
            uploaded_by="tester",
            verification_status="pending",
        )
        self.assertEqual(self.school.ssa_readiness_state, "Pending IA Verification")

        # Case 4: SsaRecord is verified
        from apps.core.fy import get_operational_fy
        rec.verification_status = "confirmed"
        rec.fy = get_operational_fy()
        rec.save()
        self.assertEqual(self.school.ssa_readiness_state, "Verified")

        # Case 5: SsaRecord expired (belongs to previous FY)
        rec.fy = "2025/2026"
        rec.save()
        self.assertEqual(self.school.ssa_readiness_state, "Expired / Needs Refresh")

    def test_unmatched_ssa_queue_actions(self):
        # Create an unmatched record
        rec = UnmatchedSSARecord.objects.create(
            school_id="99999",
            school_name_raw="Raw School Name",
            district_raw="Kampala",
            date_of_ssa="2026-07-01",
            scores={
                "teaching_environment": 7.0,
                "financial_health": 8.0,
                "christian_ethos": 6.5,
                "leadership_and_governance": 7.5,
                "safe_school_environment": 6.0,
                "community_engagement": 8.0,
                "wash_and_infrastructure": 7.0,
                "special_needs_and_inclusion": 6.5
            },
            reason="School not found",
            status="pending"
        )
        
        # Test creation of school from unmatched row via frontend view route url
        response = self.client.post("/ssa/unmatched", {
            "record_id": rec.id,
            "action": "create_school"
        }, format="multipart")
        self.assertEqual(response.status_code, 302)
        
        # Verify school created by numeric ID extraction
        new_school = School.objects.get(school_id="99999")
        self.assertEqual(new_school.name, "Raw School Name")
        self.assertEqual(SsaRecord.objects.filter(school=new_school).count(), 1)
