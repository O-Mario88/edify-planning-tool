"""Budget aggregation tests — monthly/quarterly/FY totals = activity lines + admin.

Verifies the finance-aggregation layer sums persisted budget lines + CD admin
items correctly (the spec's reconciliation rule). Isolated test DB only.
"""
from __future__ import annotations


from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity
from apps.budget.models import CostSetting
from apps.budget.costing_service import apply_to_activity
from apps.budget.services import fy_budget, monthly_budget, quarterly_budget
from apps.core.enums import ActivityType
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.monthly_work_plan.models import AdminBudgetLine, MonthlyWorkPlanBudget
from apps.monthly_work_plan.services import add_admin_line
from apps.schools.models import School


class BudgetAggregationTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="Agg Region")
        self.district = District.objects.create(name="Agg District", region=self.region)
        CostSetting.objects.create(key="staff_visit_transport_primary", label="Transport", unit_cost=15000)
        CostSetting.objects.create(key="lunch", label="Lunch", unit_cost=8000)
        self.school = School.objects.create(
            school_id="AGG-SCH", name="Agg Primary", region=self.region, district=self.district,
            current_fy_ssa_status="done", planning_readiness="ready",
        )
        self.fy = get_operational_fy()

    def _schedule_visit(self, month: int, week: int = 1) -> Activity:
        """Create + cost a visit through the central CostingService."""
        # FY months 1-3 = Q1, 4-6 = Q2, 7-9 = Q3, 10-12 = Q4.
        quarter = {1: "Q1", 2: "Q1", 3: "Q1", 4: "Q2", 5: "Q2", 6: "Q2",
                   7: "Q3", 8: "Q3", 9: "Q3", 10: "Q4", 11: "Q4", 12: "Q4"}[month]
        a = Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT.value, school=self.school,
            fy=self.fy, quarter=quarter, planned_month=month, planned_week=week,
            est_cost_cents=0, cost_missing=False,
        )
        apply_to_activity(a, {
            "activityType": "school_visit", "deliveryType": "staff",
            "districtType": "primary", "fy": self.fy,
        })
        a.refresh_from_db()
        return a

    def test_monthly_budget_equals_activity_lines_plus_admin(self):
        visit = self._schedule_visit(month=1)  # October (FY month 1)
        line_sum = sum(l.amount for l in visit.schedule_cost_lines.all())

        # CD adds an admin budget line for the same month.
        mwp = MonthlyWorkPlanBudget.objects.create(
            fy=self.fy, month_key=f"{int(self.fy) - 1}-10", program_total=0, admin_total=0, total_amount=0,
        )
        cd = User.objects.create_user(
            email="cd@agg.test", name="Cd", roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value, password="x", is_active=True,
        )
        cd_staff = StaffProfile.objects.create(user=cd, title="CD")
        # add_admin_line reads principal.user_id — wrap in a tiny stub.
        principal_stub = type("P", (), {"user_id": cd.id})()
        add_admin_line(mwp.id, {"costCategory": "rent", "description": "Office", "unitCost": 200000, "quantity": 1}, principal_stub)
        admin_total = AdminBudgetLine.objects.get(monthly_budget=mwp).total_cost

        result = monthly_budget({"fy": self.fy, "month": 1})
        self.assertEqual(result["programTotal"], line_sum)
        self.assertEqual(result["adminTotal"], admin_total)
        self.assertEqual(result["total"], line_sum + admin_total)

    def test_fy_budget_aggregates_all_periods_and_breaks_down(self):
        v1 = self._schedule_visit(month=1, week=1)
        v2 = self._schedule_visit(month=4, week=2)  # different quarter (Q2)
        fy_total_lines = (
            sum(l.amount for l in v1.schedule_cost_lines.all())
            + sum(l.amount for l in v2.schedule_cost_lines.all())
        )

        result = fy_budget({"fy": self.fy})
        self.assertEqual(result["programTotal"], fy_total_lines)
        self.assertEqual(result["total"], fy_total_lines)  # no admin items here
        self.assertEqual(result["activityCount"], 2)
        # by-quarter breakdown sums to the program total.
        self.assertEqual(sum(result["byQuarter"].values()), fy_total_lines)
        # by-activity-type breakdown.
        self.assertIn("school_visit", result["byActivityType"])

    def test_quarterly_budget_filters_by_quarter(self):
        # Q1 = FY months 1,2,3 (Oct,Nov,Dec).
        v_q1 = self._schedule_visit(month=1)
        _v_other = self._schedule_visit(month=5)  # Q2 — must NOT appear in Q1.
        q1_lines = sum(l.amount for l in v_q1.schedule_cost_lines.all())

        result = quarterly_budget({"fy": self.fy, "quarter": "Q1"})
        self.assertEqual(result["programTotal"], q1_lines)
        self.assertEqual(result["quarter"], "Q1")

    def test_activity_total_equals_line_sum(self):
        """The activity's est_cost_cents must equal the sum of its budget lines —
        the reconciliation rule System Health enforces."""
        visit = self._schedule_visit(month=2)
        line_sum = sum(l.amount for l in visit.schedule_cost_lines.all())
        self.assertEqual(visit.est_cost_cents, line_sum)
