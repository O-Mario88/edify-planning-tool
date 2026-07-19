"""Budget aggregation tests — monthly/quarterly/FY totals = activity lines + admin.

Verifies the finance-aggregation layer sums persisted budget lines + CD admin
items correctly (the spec's reconciliation rule). Isolated test DB only.
"""

from __future__ import annotations


from django.test import TestCase

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.models import CostSetting
from apps.budget.costing_service import apply_to_activity
from apps.budget.services import (
    board,
    budget_workspace,
    fy_budget,
    monthly_budget,
    quarterly_budget,
)
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
        CostSetting.objects.create(
            key="staff_visit_transport_primary", label="Transport", unit_cost=15000
        )
        CostSetting.objects.create(key="lunch", label="Lunch", unit_cost=8000)
        self.school = School.objects.create(
            school_id="AGG-SCH",
            name="Agg Primary",
            region=self.region,
            district=self.district,
            current_fy_ssa_status="done",
            planning_readiness="ready",
        )
        self.fy = get_operational_fy()

    def _schedule_visit(self, month: int, week: int = 1) -> Activity:
        """Create + cost a visit through the central CostingService.

        A real `scheduled_date` is required — apply_to_activity() derives
        activity.month/.quarter/.fy/.planned_date from it (the reliable
        fields the aggregation layer reads), not from the legacy
        planned_month/planned_week fields set below, which are only ever
        populated when a caller happens to pass them explicitly and don't
        drive any real aggregation."""
        from apps.core.fy import get_month_date_range

        # FY months 1-3 = Q1, 4-6 = Q2, 7-9 = Q3, 10-12 = Q4.
        quarter = {
            1: "Q1",
            2: "Q1",
            3: "Q1",
            4: "Q2",
            5: "Q2",
            6: "Q2",
            7: "Q3",
            8: "Q3",
            9: "Q3",
            10: "Q4",
            11: "Q4",
            12: "Q4",
        }[month]
        month_start, _ = get_month_date_range(self.fy, month)
        a = Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT.value,
            school=self.school,
            fy=self.fy,
            quarter=quarter,
            planned_month=month,
            planned_week=week,
            scheduled_date=month_start,
            est_cost_cents=0,
            cost_missing=False,
        )
        apply_to_activity(
            a,
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "districtType": "primary",
                "fy": self.fy,
            },
        )
        a.refresh_from_db()
        return a

    def test_monthly_budget_equals_activity_lines_plus_admin(self):
        visit = self._schedule_visit(month=1)  # October (FY month 1)
        line_sum = sum(l.amount for l in visit.schedule_cost_lines.all())

        # CD adds an admin budget line for the same month.
        mwp = MonthlyWorkPlanBudget.objects.create(
            fy=self.fy,
            month_key=f"{int(self.fy) - 1}-10",
            program_total=0,
            admin_total=0,
            total_amount=0,
        )
        cd = User.objects.create_user(
            email="cd@agg.test",
            name="Cd",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="x",
            is_active=True,
        )
        cd_staff = StaffProfile.objects.create(user=cd, title="CD")
        # add_admin_line reads principal.user_id — wrap in a tiny stub.
        principal_stub = type("P", (), {"user_id": cd.id})()
        add_admin_line(
            mwp.id,
            {
                "costCategory": "rent",
                "description": "Office",
                "unitCost": 200000,
                "quantity": 1,
            },
            principal_stub,
        )
        admin_total = AdminBudgetLine.objects.get(monthly_budget=mwp).total_cost

        result = monthly_budget({"fy": self.fy, "month": 1})
        self.assertEqual(result["programTotal"], line_sum)
        self.assertEqual(result["adminTotal"], admin_total)
        self.assertEqual(result["total"], line_sum + admin_total)

    def test_fy_budget_aggregates_all_periods_and_breaks_down(self):
        v1 = self._schedule_visit(month=1, week=1)
        v2 = self._schedule_visit(month=4, week=2)  # different quarter (Q2)
        fy_total_lines = sum(l.amount for l in v1.schedule_cost_lines.all()) + sum(
            l.amount for l in v2.schedule_cost_lines.all()
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

    def test_monthly_budget_counts_activity_with_no_planned_month_field(self):
        """activity.planned_month is a legacy field only populated when a
        caller happens to pass plannedMonth explicitly — real activities
        scheduled without it (the common case) must still be counted, since
        the aggregation reads the reliable schedule-time month instead."""
        from apps.core.fy import get_month_date_range

        month_start, _ = get_month_date_range(self.fy, 1)  # October
        visit = Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT.value,
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            scheduled_date=month_start,
            est_cost_cents=0,
            cost_missing=False,
        )
        apply_to_activity(
            visit,
            {
                "activityType": "school_visit",
                "deliveryType": "staff",
                "districtType": "primary",
                "fy": self.fy,
            },
        )
        visit.refresh_from_db()
        self.assertIsNone(visit.planned_month)
        line_sum = sum(l.amount for l in visit.schedule_cost_lines.all())

        result = monthly_budget({"fy": self.fy, "month": 1})
        self.assertEqual(result["programTotal"], line_sum)

    def test_board_excludes_cancelled_and_unscheduled_partner_activities(self):
        """A cancelled activity's stale cost lines, and a partner activity
        that was only assigned (never actually scheduled), must not inflate
        the live Monthly Budget board totals."""
        good = self._schedule_visit(month=1)
        good_amount = sum(l.amount for l in good.schedule_cost_lines.all())

        cancelled = self._schedule_visit(month=1)
        cancelled.status = "cancelled"
        cancelled.save(update_fields=["status"])

        unscheduled_partner = Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT.value,
            school=self.school,
            fy=self.fy,
            quarter="Q1",
            delivery_type="partner",
            assigned_partner_id="partner-1",
            est_cost_cents=999_000,
            cost_missing=False,
        )
        ActivityScheduleCostLine.objects.create(
            activity=unscheduled_partner,
            cost_setting_key="partner_visit_lump_sum",
            label="Partner visit",
            unit_cost=999_000,
            quantity=1,
            amount=999_000,
            fiscal_year=self.fy,
        )

        cd = User.objects.create_user(
            email="cd-board@agg.test",
            name="Cd Board",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="x",
            is_active=True,
        )
        result = board(cd, {"fy": self.fy})
        self.assertEqual(result["summary"]["fiscalYear"], good_amount)

    def test_budget_workspace_groups_costs_by_period_and_includes_cd_admin_plan(self):
        """My Budget uses actual cost lines, with CD admin costs only at their
        honest monthly-or-larger planning level (never an invented weekly split)."""
        from apps.core.fy import get_month_date_range

        visit = self._schedule_visit(month=10)  # July in FY 2026.
        program_amount = sum(line.amount for line in visit.schedule_cost_lines.all())
        month_start, _ = get_month_date_range(self.fy, 10)
        cd = User.objects.create_user(
            email="cd-workspace@agg.test",
            name="CD Workspace",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="x",
            is_active=True,
        )
        month_budget = MonthlyWorkPlanBudget.objects.create(
            country_id="Uganda",
            fy=self.fy,
            month_key=f"{month_start.year}-{month_start.month:02d}",
        )
        AdminBudgetLine.objects.create(
            monthly_budget=month_budget,
            cost_category="coordination",
            description="District coordination meeting",
            quantity=1,
            unit_cost=80_000,
            total_cost=80_000,
            created_by_user_id=cd.id,
        )

        month_workspace = budget_workspace(
            cd,
            {
                "fy": self.fy,
                "date": month_start.date().isoformat(),
                "period": "month",
            },
        )
        self.assertEqual(len(month_workspace["comparison"]), 4)
        self.assertEqual(month_workspace["program_total"], program_amount)
        self.assertEqual(month_workspace["admin_total"], 80_000)
        self.assertEqual(month_workspace["total"], program_amount + 80_000)
        self.assertIn(
            "Country Admin Plan",
            [group["label"] for group in month_workspace["groups"]],
        )

        week_workspace = budget_workspace(
            cd,
            {
                "fy": self.fy,
                "date": month_start.date().isoformat(),
                "period": "week",
            },
        )
        self.assertEqual(week_workspace["admin_total"], 0)
        self.assertTrue(week_workspace["admin_weekly_note"])

    def test_budget_workspace_uses_activity_specific_training_and_meeting_columns(self):
        """Training and meeting budgets use their costed headcount rather than
        showing the generic one-person school-visit fallback."""
        from apps.core.fy import get_month_date_range

        month_start, _ = get_month_date_range(self.fy, 10)  # July in FY 2026.
        cd = User.objects.create_user(
            email="cd-activity-tables@agg.test",
            name="CD Activity Tables",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="x",
            is_active=True,
        )
        training = Activity.objects.create(
            activity_type=ActivityType.CLUSTER_TRAINING.value,
            fy=self.fy,
            quarter="Q4",
            scheduled_date=month_start,
            status="scheduled",
        )
        meeting = Activity.objects.create(
            activity_type=ActivityType.CLUSTER_MEETING.value,
            fy=self.fy,
            quarter="Q4",
            scheduled_date=month_start,
            status="scheduled",
        )
        ActivityScheduleCostLine.objects.bulk_create(
            [
                ActivityScheduleCostLine(
                    activity=training,
                    cost_setting_key="group_training_participant_meal_cost_per_head",
                    label="Meals",
                    unit_cost=10_000,
                    quantity=18,
                    amount=180_000,
                    line_item_type="participant_meals",
                    planned_date=month_start.date(),
                    fiscal_year=self.fy,
                ),
                ActivityScheduleCostLine(
                    activity=meeting,
                    cost_setting_key="cluster_meeting_participant_meal_cost_per_head",
                    label="Cluster meeting participant meals",
                    unit_cost=8_000,
                    quantity=12,
                    amount=96_000,
                    line_item_type="cluster_meeting_participant_meals",
                    planned_date=month_start.date(),
                    fiscal_year=self.fy,
                ),
            ]
        )

        workspace = budget_workspace(
            cd,
            {
                "fy": self.fy,
                "date": month_start.date().isoformat(),
                "period": "month",
            },
        )
        groups = {group["label"]: group for group in workspace["groups"]}
        self.assertEqual(groups["Cluster Training"]["table_kind"], "training")
        self.assertEqual(groups["Cluster Training"]["rows"][0]["activity_count"], 1)
        self.assertEqual(groups["Cluster Training"]["rows"][0]["people"], 18)
        self.assertEqual(groups["Cluster Meeting"]["table_kind"], "meeting")
        self.assertEqual(groups["Cluster Meeting"]["rows"][0]["people"], 12)

    def test_program_lead_budget_tabs_separate_personal_and_team_costs(self):
        """A PL's personal ledger is private while Team Budget is a true
        consolidation of the PL and every supervised staff member."""
        from apps.core.fy import get_month_date_range

        staff_user = User.objects.create_user(
            email="team-cceo@agg.test",
            name="Team CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        staff_profile = StaffProfile.objects.create(user=staff_user, title="CCEO")
        pl_user = User.objects.create_user(
            email="team-pl@agg.test",
            name="Team PL",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            password="x",
            is_active=True,
        )
        pl_profile = StaffProfile.objects.create(user=pl_user, title="Program Lead")
        StaffSupervisorAssignment.objects.create(
            supervisor=pl_profile,
            supervisee=staff_profile,
        )
        staff_visit = self._schedule_visit(month=10)
        staff_lines = list(staff_visit.schedule_cost_lines.all())
        ActivityScheduleCostLine.objects.filter(activity=staff_visit).update(
            responsible_user=staff_user.id
        )
        pl_visit = self._schedule_visit(month=10)
        pl_lines = list(pl_visit.schedule_cost_lines.all())
        ActivityScheduleCostLine.objects.filter(activity=pl_visit).update(
            responsible_user=pl_user.id
        )
        month_start, _ = get_month_date_range(self.fy, 10)

        personal_workspace = budget_workspace(
            pl_user,
            {
                "fy": self.fy,
                "date": month_start.date().isoformat(),
                "period": "month",
            },
        )
        self.assertEqual(personal_workspace["budget_scope"], "my")
        self.assertEqual(
            personal_workspace["total"], sum(line.amount for line in pl_lines)
        )
        self.assertEqual(personal_workspace["team_summary"], [])

        team_workspace = budget_workspace(
            pl_user,
            {
                "fy": self.fy,
                "date": month_start.date().isoformat(),
                "period": "month",
                "budget_scope": "team",
            },
        )
        self.assertEqual(team_workspace["budget_scope"], "team")
        self.assertEqual(
            team_workspace["total"],
            sum(line.amount for line in staff_lines)
            + sum(line.amount for line in pl_lines),
        )
        self.assertEqual(
            team_workspace["team_summary"],
            [
                {
                    "name": "Team CCEO",
                    "activity_count": 1,
                    "total": sum(line.amount for line in staff_lines),
                },
                {
                    "name": "Team PL",
                    "activity_count": 1,
                    "total": sum(line.amount for line in pl_lines),
                },
            ],
        )
        team_rows = team_workspace["groups"][0]["rows"]
        self.assertTrue(all(row["owners"] == "Team CCEO, Team PL" for row in team_rows))
