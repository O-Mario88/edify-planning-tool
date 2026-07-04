from django.test import TestCase
from django.utils import timezone
from apps.accounts.models import User, StaffProfile
from apps.core.rbac import EdifyRole
from apps.schools.models import School
from apps.schools.services import set_type
from apps.core_schools.models import CorePlan, CoreSchoolProfile
from apps.core_schools.champion_services import ChampionEligibilityService
from apps.ssa.models import SsaRecord, SsaScore
from apps.geography.models import Region, District, SubCounty
from apps.activities.models import Activity

class ChampionProposalEngineTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Champ Region")
        self.district = District.objects.create(name="Champ District", region=self.region)
        self.sub_county = SubCounty.objects.create(name="Champ SubCounty", district=self.district)

        self.user = User.objects.create_user(
            email="admin@core.test", name="Admin User",
            roles=[EdifyRole.ADMIN.value], active_role=EdifyRole.ADMIN.value,
            password="pwd", is_active=True
        )
        self.staff = StaffProfile.objects.create(user=self.user, title="Admin")
        
        self.school = School.objects.create(
            school_id="SCH-CHAMP-001", name="Champ Academy",
            region=self.region, district=self.district, sub_county=self.sub_county,
            school_type="client", enrollment=250
        )

    def test_champion_graduation_flow(self):
        # 1. Promote school to Core
        set_type(self.user, self.school.school_id, "core")
        
        profile = CoreSchoolProfile.objects.filter(school_id=self.school.school_id).first()
        self.assertIsNotNone(profile)
        self.assertEqual(profile.champion_status, "Not Eligible")
        
        # 2. Add Baseline SSA (low scores: avg 6.0)
        baseline = SsaRecord.objects.create(
            school=self.school, date_of_ssa="2025-07-10", fy="2026", quarter="Q1", verification_status="confirmed",
            average_score=6.0
        )
        interventions = [
            "teaching_and_learning", "financial_health", "christlike_behaviour", "exposure_to_word_of_god",
            "government_requirements", "leadership", "education_technology", "learning_environment"
        ]
        for idx, item in enumerate(interventions):
            SsaScore.objects.create(ssa_record=baseline, intervention=item, score=6.0)
        
        # Ineligible because package is not complete & latest SSA is < 8.0
        res = ChampionEligibilityService.calculate_score(self.school)
        self.assertFalse(res["eligible"])
        
        # 3. Add High Post SSA (avg 8.5, lowest 7.0)
        followup = SsaRecord.objects.create(
            school=self.school, date_of_ssa="2026-06-10", fy="2026", quarter="Q4", verification_status="confirmed",
            average_score=8.75
        )
        for idx, item in enumerate(interventions):
            # Lowest is 7.0, others are 9.0 -> average is 8.75
            score = 7.0 if idx == 0 else 9.0
            SsaScore.objects.create(ssa_record=followup, intervention=item, score=score)

        # Still ineligible because package slots are not closed (0/8 completed)
        res = ChampionEligibilityService.calculate_score(self.school)
        self.assertFalse(res["eligible"])
        self.assertEqual(res["completed_slots"], 0)

        # 4. Mock package completion by marking slots as Closed / Completed
        plan = CorePlan.objects.get(school_id=self.school.school_id)
        for slot in plan.slots.all():
            slot.status = "Closed"
            slot.save()
            
        # Re-evaluate: Now should be fully eligible for Graduation!
        res = ChampionEligibilityService.calculate_score(self.school)
        self.assertTrue(res["eligible"])
        self.assertGreaterEqual(res["score"], 80.0)
        
        # 5. Evaluate all should list candidate
        candidates = ChampionEligibilityService.evaluate_all()
        self.assertTrue(any(c["school"].school_id == self.school.school_id for c in candidates))
        
        # 6. Approve Graduation
        # Create a mock activity to satisfy audit logger dependency
        Activity.objects.create(
            school=self.school, activity_type="core_visit", fy="2026", status="closed",
            scheduled_date=timezone.now(), salesforce_activity_id="SF-ACT-999"
        )
        
        success = ChampionEligibilityService.approve(self.school.school_id, self.user.user_id)
        self.assertTrue(success)
        
        self.school.refresh_from_db()
        profile.refresh_from_db()
        self.assertEqual(self.school.school_type, "champion")
        self.assertEqual(profile.champion_status, "Champion")
