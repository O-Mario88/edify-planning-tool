from django.test import TestCase
from django.contrib.auth import get_user_model
from apps.accounts.models import StaffProfile
from apps.geography.models import Region, District, SubCounty
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.ssa.models import SsaRecord, SsaScore
from apps.planning.planning_service import PlanningReadinessService

class PlanningReadinessTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(
            id="user-1",
            email="staff@edify.org",
            name="Staff User",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True
        )
        self.staff = StaffProfile.objects.create(
            id="staff-1",
            user=self.user,
            title="CCEO"
        )
        self.region = Region.objects.create(name="Eastern")
        self.district = District.objects.create(name="Jinja", region=self.region)
        self.sub_county = SubCounty.objects.create(name="Town", district=self.district)
        
        # Clustered School
        self.cluster = Cluster.objects.create(
            name="Jinja central",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            status="active"
        )

    def test_readiness_cluster_required(self):
        sub_unclustered = SubCounty.objects.create(name="Remote Area", district=self.district)
        school = School.objects.create(
            school_id="SCH-1",
            name="School One",
            region=self.region,
            district=self.district,
            sub_county=sub_unclustered,
            school_type="client",
            account_owner_id=self.staff.id
        )
        school.cluster_id = None
        school.cluster_status = "unclustered"
        school.save()
        res = PlanningReadinessService.get_school_readiness(school, has_catalogue=True, has_scheduled=False, partner_assignment=None, weakest_area="—")
        self.assertEqual(res["planningReadiness"], "Cluster Required")
        self.assertEqual(res["recommendedAction"], "Add to Cluster")

    def test_readiness_data_cleanup_required(self):
        school = School.objects.create(
            school_id="SCH-2",
            name="School Two",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            cluster_id=self.cluster.id,
            account_owner_id=None
        )
        res = PlanningReadinessService.get_school_readiness(school, has_catalogue=True, has_scheduled=False, partner_assignment=None, weakest_area="—")
        self.assertEqual(res["planningReadiness"], "Data Cleanup Required")
        self.assertIn("Responsible staff", res["recommendedAction"])

    def test_readiness_baseline_required(self):
        school = School.objects.create(
            school_id="SCH-3",
            name="School Three",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            cluster_id=self.cluster.id,
            account_owner_id=self.staff.id
        )
        # Clustered, clean data, but current_fy_ssa_status is not 'done'
        res = PlanningReadinessService.get_school_readiness(school, has_catalogue=True, has_scheduled=False, partner_assignment=None, weakest_area="—")
        self.assertEqual(res["planningReadiness"], "SSA Required")
        self.assertEqual(res["recommendedAction"], "Schedule SSA Visit")

    def test_readiness_ready_for_support(self):
        school = School.objects.create(
            school_id="SCH-4",
            name="School Four",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="client",
            cluster_id=self.cluster.id,
            account_owner_id=self.staff.id,
            current_fy_ssa_status="done"
        )
        # Mock a verified SSA record to give weakest area
        ssa = SsaRecord.objects.create(
            school=school,
            fy="2026",
            date_of_ssa="2026-07-01",
            verification_status="confirmed"
        )
        SsaScore.objects.create(
            ssa_record=ssa,
            intervention="leadership",
            score=4
        )
        SsaScore.objects.create(
            ssa_record=ssa,
            intervention="teaching_learning",
            score=8
        )
        
        res = PlanningReadinessService.get_school_readiness(school, has_catalogue=True, has_scheduled=False, partner_assignment=None, weakest_area="Leadership")
        self.assertEqual(res["planningReadiness"], "Ready for Support")
        self.assertEqual(res["recommendedAction"], "Schedule Leadership-focused Visit")

    def test_baseline_ssa_visit_costing_custom_rate(self):
        from apps.budget.costing import cost_for_activity
        rates = {
            "ssa_visit_rate": 75000,
            "staff_visit_transport_primary": 50000,
            "lunch": 20000
        }
        a = {"activityType": "baseline_ssa_visit", "deliveryType": "staff", "districtType": "primary"}
        cost = cost_for_activity(a, rates)
        self.assertEqual(cost.amount, 75000)
        self.assertEqual(cost.lines[0].key, "ssa_visit_rate")

    def test_core_visit_costing_custom_rate(self):
        from apps.budget.costing import cost_for_activity
        rates = {
            "core_school_visit": 120000,
            "school_visit_cost_per_school": 60000
        }
        a = {"activityType": "core_visit", "deliveryType": "staff", "districtType": "primary"}
        cost = cost_for_activity(a, rates)
        self.assertEqual(cost.amount, 120000)
        self.assertEqual(cost.lines[0].key, "core_school_visit")

    def test_partner_visit_rate_basis_per_school(self):
        from apps.budget.costing import cost_for_activity
        rates = {
            "partner_school_visit_rate": 45000
        }
        a = {"activityType": "school_visit", "deliveryType": "partner"}
        cost = cost_for_activity(a, rates)
        self.assertEqual(cost.amount, 45000)
        self.assertIn("[Rate basis: per school]", cost.lines[0].label)
