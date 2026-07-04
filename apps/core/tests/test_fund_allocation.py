"""Unit and integration tests for consolidated fund allocation.

Verifies CD Monthly Admin budget allocation, grouping, and rendering within the finance
allocation context.
"""
from __future__ import annotations

import datetime
from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import CostSetting
from apps.budget.costing_service import apply_to_activity
from apps.core.enums import ActivityType
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.monthly_work_plan.models import MonthlyWorkPlanBudget, MonthlyWorkPlanBudgetStatus
from apps.monthly_work_plan.services import add_admin_line
from apps.schools.models import School
from apps.budget.admin_budget_service import AdminBudgetAllocationService
from apps.budget.allocation_service import MonthlyFundAllocationService

class FundAllocationTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Allocation Region")
        self.district = District.objects.create(name="Allocation District", region=self.region)
        CostSetting.objects.create(key="staff_visit_transport_primary", label="Transport", unit_cost=15000)
        CostSetting.objects.create(key="lunch", label="Lunch", unit_cost=8000)
        self.school = School.objects.create(
            school_id="ALLOC-SCH", name="Alloc School", region=self.region, district=self.district,
            current_fy_ssa_status="done", planning_readiness="ready",
        )
        self.fy = get_operational_fy()
        
        # Create users
        self.accountant = User.objects.create_user(
            email="accountant@agg.test", name="Moses Accountant", roles=[EdifyRole.PROGRAM_ACCOUNTANT.value],
            active_role=EdifyRole.PROGRAM_ACCOUNTANT.value, password="x", is_active=True,
        )
        self.staff_user = User.objects.create_user(
            email="cceo@agg.test", name="Paul Staff", roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value, password="x", is_active=True,
        )
        self.staff_profile = StaffProfile.objects.create(
            user=self.staff_user, title="CCEO", primary_district_id=self.district.id
        )
        
        # CD user
        self.cd_user = User.objects.create_user(
            email="cd@agg.test", name="Sarah CD", roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value, password="x", is_active=True,
        )
        
    def _schedule_visit(self, month: int, user_id: str) -> Activity:
        quarter = "Q1" if month <= 3 else "Q2"
        # Determine date in April 2026 or appropriate month
        dt = datetime.datetime(2026, month, 15, 10, 0, tzinfo=datetime.timezone.utc)
        
        a = Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT.value, school=self.school,
            fy=self.fy, quarter=quarter, planned_month=month, planned_week=1,
            scheduled_date=dt, est_cost_cents=0, cost_missing=False,
        )
        apply_to_activity(a, {
            "activityType": "school_visit", "deliveryType": "staff",
            "districtType": "primary", "fy": self.fy,
        })
        a.refresh_from_db()
        
        # Assign responsible user on cost lines
        ActivityScheduleCostLine.objects.filter(activity=a).update(responsible_user=user_id)
        return a

    def test_admin_budget_allocation_service(self):
        # 1. No budget plan scenario
        res_empty = AdminBudgetAllocationService.get_admin_budget_allocation(4, self.fy)
        self.assertFalse(res_empty["exists"])
        self.assertEqual(res_empty["planned_total"], 0)
        self.assertEqual(res_empty["total"], 0)

        # 2. Draft plan scenario
        mwp = MonthlyWorkPlanBudget.objects.create(
            fy=self.fy, month_key="2026-04", status=MonthlyWorkPlanBudgetStatus.DRAFT_GENERATED.value,
            program_total=0, admin_total=0, total_amount=0
        )
        principal_stub = type("P", (), {"user_id": self.cd_user.id})()
        add_admin_line(mwp.id, {"costCategory": "rent", "description": "Office rent", "unitCost": 200000, "quantity": 1}, principal_stub)
        
        res_draft = AdminBudgetAllocationService.get_admin_budget_allocation(4, self.fy)
        self.assertTrue(res_draft["exists"])
        self.assertFalse(res_draft["approved"])
        self.assertEqual(res_draft["planned_total"], 200000)
        # Draft is excluded from disbursed total allocation
        self.assertEqual(res_draft["allocated_total"], 0)
        self.assertEqual(res_draft["total"], 0)
        
        # 3. Approved plan scenario
        mwp.status = MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP.value
        mwp.save()
        
        res_approved = AdminBudgetAllocationService.get_admin_budget_allocation(4, self.fy)
        self.assertTrue(res_approved["approved"])
        self.assertEqual(res_approved["planned_total"], 200000)
        self.assertEqual(res_approved["allocated_total"], 200000)
        self.assertEqual(res_approved["total"], 200000)
        self.assertEqual(len(res_approved["lines"]), 1)
        self.assertEqual(res_approved["lines"][0]["description"], "Office rent")

    def test_monthly_fund_allocation_consolidation(self):
        # Schedule activity for Paul Staff
        self._schedule_visit(month=4, user_id=self.staff_user.id)
        
        # Create approved admin plan
        mwp = MonthlyWorkPlanBudget.objects.create(
            fy=self.fy, month_key="2026-04", status=MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP.value,
            program_total=0, admin_total=0, total_amount=0
        )
        principal_stub = type("P", (), {"user_id": self.cd_user.id})()
        add_admin_line(mwp.id, {"costCategory": "rent", "description": "Office rent", "unitCost": 500000, "quantity": 1}, principal_stub)

        # Call service
        res = MonthlyFundAllocationService.get_monthly_allocation(month_num=4, fy=self.fy)
        
        # Check rows contain CCEOs + CD Admin Budget
        self.assertEqual(len(res["rows"]), 2)  # Paul Staff + CD Admin Budget
        
        admin_row = next(r for r in res["rows"] if r["user_id"] == "cd_admin_budget")
        self.assertEqual(admin_row["admin_budget"]["total"], 500000)
        self.assertEqual(admin_row["total_allocation"], 500000)
        
        staff_row = next(r for r in res["rows"] if r["user_id"] == self.staff_user.id)
        self.assertEqual(staff_row["staff_visits"]["count"], 1)
        self.assertGreater(staff_row["staff_visits"]["total"], 0)
        
        # Check grand totals
        self.assertEqual(res["grand_totals"]["admin_budget"]["total"], 500000)
        self.assertGreater(res["grand_totals"]["total_allocation"], 500000)

    def test_views_response_and_drawers(self):
        # Login accountant
        self.client.force_login(self.accountant)
        
        # Create admin plan
        MonthlyWorkPlanBudget.objects.create(
            fy=self.fy, month_key="2026-04", status=MonthlyWorkPlanBudgetStatus.APPROVED_BY_RVP.value,
            program_total=0, admin_total=0, total_amount=0
        )
        
        # Page load
        resp = self.client.get(reverse("frontend:fund_allocation"), {"month": "April", "fy": self.fy})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Consolidated Fund Allocation")
        
        # Admin budget drilldown partial
        resp_drill = self.client.get(reverse("frontend:admin_budget_drilldown"), {"month": "April", "fy": self.fy})
        self.assertEqual(resp_drill.status_code, 200)
        self.assertContains(resp_drill, "Admin Budget Breakdown")
        
        # Export drawer partial
        resp_exp = self.client.get(reverse("frontend:export_drawer"), {"month": "April", "fy": self.fy})
        self.assertEqual(resp_exp.status_code, 200)
        self.assertContains(resp_exp, "Export Consolidated Allocation")
