from datetime import datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from apps.accounts.models import StaffProfile
from apps.geography.models import Region, District, SubCounty
from apps.schools.models import School
from apps.clusters.models import Cluster
from apps.ssa.models import SsaRecord, SsaScore
from apps.planning.planning_service import (
    PlanningReadinessService,
    PlanningDashboardService,
)
from apps.core_schools.models import CorePlan, CoreActivitySlot


class PlanningReadinessTestCase(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(
            id="user-1",
            email="staff@edify.org",
            name="Staff User",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self.staff = StaffProfile.objects.create(
            id="staff-1", user=self.user, title="CCEO"
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
            status="active",
        )

    def test_readiness_cluster_required(self):
        sub_unclustered = SubCounty.objects.create(
            name="Remote Area", district=self.district
        )
        school = School.objects.create(
            school_id="SCH-1",
            name="School One",
            region=self.region,
            district=self.district,
            sub_county=sub_unclustered,
            school_type="client",
            account_owner_id=self.staff.id,
        )
        school.cluster_id = None
        school.cluster_status = "unclustered"
        school.save()
        res = PlanningReadinessService.get_school_readiness(
            school,
            has_catalogue=True,
            has_scheduled=False,
            partner_assignment=None,
            weakest_area="—",
        )
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
            account_owner_id=None,
        )
        res = PlanningReadinessService.get_school_readiness(
            school,
            has_catalogue=True,
            has_scheduled=False,
            partner_assignment=None,
            weakest_area="—",
        )
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
            account_owner_id=self.staff.id,
        )
        # Clustered, clean data, but current_fy_ssa_status is not 'done'
        res = PlanningReadinessService.get_school_readiness(
            school,
            has_catalogue=True,
            has_scheduled=False,
            partner_assignment=None,
            weakest_area="—",
        )
        self.assertEqual(res["planningReadiness"], "SSA Required")
        self.assertEqual(res["recommendedAction"], "Complete SSA")

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
            current_fy_ssa_status="done",
        )
        # Mock a verified SSA record to give weakest area
        ssa = SsaRecord.objects.create(
            school=school,
            fy="2026",
            # The production importer normalizes this to an aware timestamp;
            # keep the direct model-fixture path equally realistic.
            date_of_ssa=timezone.make_aware(
                datetime(2026, 7, 1), timezone.get_current_timezone()
            ),
            verification_status="confirmed",
        )
        SsaScore.objects.create(ssa_record=ssa, intervention="leadership", score=4)
        SsaScore.objects.create(
            ssa_record=ssa, intervention="teaching_learning", score=8
        )

        res = PlanningReadinessService.get_school_readiness(
            school,
            has_catalogue=True,
            has_scheduled=False,
            partner_assignment=None,
            weakest_area="Leadership",
        )
        self.assertEqual(res["planningReadiness"], "Ready for Support")
        self.assertEqual(
            res["recommendedAction"], "Recommend Staff (Visit/training support)"
        )

    def test_baseline_ssa_visit_costing_custom_rate(self):
        from apps.budget.costing import cost_for_activity

        rates = {
            "ssa_visit_rate": 75000,
            "staff_visit_transport_primary": 50000,
            "lunch": 20000,
        }
        a = {
            "activityType": "baseline_ssa_visit",
            "deliveryType": "staff",
            "districtType": "primary",
        }
        cost = cost_for_activity(a, rates)
        self.assertEqual(cost.amount, 75000)
        self.assertEqual(cost.lines[0].key, "ssa_visit_rate")

    def test_core_visit_costing_custom_rate(self):
        from apps.budget.costing import cost_for_activity

        rates = {"core_school_visit": 120000, "school_visit_cost_per_school": 60000}
        a = {
            "activityType": "core_visit",
            "deliveryType": "staff",
            "districtType": "primary",
        }
        cost = cost_for_activity(a, rates)
        self.assertEqual(cost.amount, 120000)
        self.assertEqual(cost.lines[0].key, "core_school_visit")

    def test_partner_visit_rate_basis_per_school(self):
        from apps.budget.costing import cost_for_activity

        rates = {"partner_school_visit_rate": 45000}
        a = {"activityType": "school_visit", "deliveryType": "partner"}
        cost = cost_for_activity(a, rates)
        self.assertEqual(cost.amount, 45000)
        self.assertIn("[Rate basis: per school]", cost.lines[0].label)


class CoreSummarySecondRoundPendingTestCase(TestCase):
    """core_summary's second_visit_pending/second_training_pending must be a
    real count off CoreActivitySlot (the 2nd-sequence slot on the school's
    Core Plan), not a fabricated offset of the 1st-round pending count."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create(
            id="user-cd",
            email="cd@edify.org",
            name="CD User",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        self.region = Region.objects.create(name="Eastern")
        self.district = District.objects.create(name="Jinja", region=self.region)
        self.sub_county = SubCounty.objects.create(name="Town", district=self.district)

    def _make_core_school(self, school_id):
        return School.objects.create(
            school_id=school_id,
            name=f"Core School {school_id}",
            region=self.region,
            district=self.district,
            sub_county=self.sub_county,
            school_type="core",
        )

    def test_second_visit_pending_counts_real_incomplete_slots_only(self):
        # School A: 2nd visit slot still pending -> should count.
        school_a = self._make_core_school("CORE-A")
        plan_a = CorePlan.objects.create(
            id="cplan-a", school_id=school_a.school_id, fy="2026"
        )
        CoreActivitySlot.objects.create(
            id="cslot-a-v1",
            core_plan=plan_a,
            school_id=school_a.school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=1,
            status="completed",
        )
        CoreActivitySlot.objects.create(
            id="cslot-a-v2",
            core_plan=plan_a,
            school_id=school_a.school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=2,
            status="Planned",
        )

        # School B: 2nd visit slot already done -> should NOT count.
        school_b = self._make_core_school("CORE-B")
        plan_b = CorePlan.objects.create(
            id="cplan-b", school_id=school_b.school_id, fy="2026"
        )
        CoreActivitySlot.objects.create(
            id="cslot-b-v2",
            core_plan=plan_b,
            school_id=school_b.school_id,
            intervention="leadership",
            activity_type="visit",
            sequence_number=2,
            status="ia_verified",
        )

        # School C: core school with no Core Plan at all -> honest zero, not
        # counted (no fabricated offset applied).
        self._make_core_school("CORE-C")

        data = PlanningDashboardService.get_dashboard_data(
            self.user, {"fy": "2026", "tab": "core"}
        )
        core_summary = data["core_summary"]

        self.assertEqual(core_summary["second_visit_pending"], 1)
        # Confirm it is NOT the old fabricated heuristic
        # (max(0, first_visit_pending - 15)), which would have been 0 here
        # since first_visit_pending is well under 15.
        self.assertLess(core_summary["first_visit_pending"], 15)
        self.assertEqual(core_summary["second_training_pending"], 0)
