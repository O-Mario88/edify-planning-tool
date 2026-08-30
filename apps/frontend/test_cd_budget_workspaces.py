from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.navigation import build_sidebar_for_user
from apps.monthly_work_plan.models import AdminBudgetLine, MonthlyWorkPlanBudget


class CountryDirectorBudgetWorkspaceTest(TestCase):
    def setUp(self):
        self.cd = get_user_model().objects.create_user(
            email="cd-budget-workspaces@edify.test",
            name="Country Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        self.activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy="2026",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            responsible_staff_id=self.cd.id,
        )
        ActivityScheduleCostLine.objects.create(
            activity=self.activity,
            cost_setting_key="primary_transport_per_day",
            label="Primary transport",
            unit_cost=60_000,
            quantity=1,
            amount=60_000,
            planned_date=date(2026, 4, 10),
            month=4,
            fiscal_year="2026",
            catalogue_id="catalogue-1",
            catalogue_version=1,
            responsible_user=self.cd.id,
        )
        monthly_budget, _ = MonthlyWorkPlanBudget.objects.get_or_create(
            country_id="Uganda",
            month_key="2026-04",
            defaults={"fy": "2026"},
        )
        AdminBudgetLine.objects.create(
            monthly_budget=monthly_budget,
            cost_category="operations",
            description="Office internet",
            quantity=1,
            unit_cost=25_000,
            total_cost=25_000,
            created_by_user_id=self.cd.id,
        )
        self.client.force_login(self.cd)

    def test_cd_navigation_uses_one_budget_label(self):
        items = [
            item
            for section in build_sidebar_for_user(self.cd, "/budgets/monthly")
            for item in section["items"]
        ]
        labels = [item["label"] for item in items]
        urls = [item["url"] for item in items]
        self.assertIn("Budget", labels)
        self.assertEqual(labels.count("Budget"), 1)
        self.assertIn("Weekly Advance Request", labels)
        self.assertNotIn("General Budget", labels)
        self.assertNotIn("Admin Budget", labels)
        self.assertNotIn("Country Budget", labels)
        self.assertNotIn("My Budget", labels)
        self.assertNotIn("/budgets/monthly", urls)

    def test_retired_monthly_budget_redirects_cd_to_unified_budget(self):
        response = self.client.get(
            "/budgets/monthly?fy=2026&date=2026-04-01&period=month"
        )

        self.assertRedirects(
            response,
            "/budgets/overview?period=month",
            fetch_redirect_response=False,
        )

    def test_country_budget_inherits_workspace_and_uses_planned_activities(self):
        response = self.client.get(
            "/budgets/overview?fy=2026&date=2026-04-01&period=month"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/budgets/monthly.html")
        self.assertEqual(response.context["workspace_title"], "General Budget")
        self.assertEqual(response.context["budget_scope"], "country")
        self.assertEqual(response.context["program_total"], 60_000)
        # The CD's administrative plan now rolls into the Monthly Fund Request
        # as its own "Country Admin Plan" category.
        self.assertEqual(response.context["admin_total"], 25_000)
        self.assertEqual(response.context["total"], 85_000)
        self.assertContains(response, "Monthly Budget")
        self.assertContains(response, "Quarterly Budget")
        self.assertContains(response, "Annual Budget")
        self.assertContains(response, "Primary transport")
        self.assertContains(response, "Office internet")

    def test_cd_can_add_an_item_from_the_admin_budget_workspace(self):
        monthly_budget = MonthlyWorkPlanBudget.objects.get(
            country_id="Uganda",
            month_key="2026-04",
        )

        response = self.client.post(
            "/country-budget/action",
            {
                "action": "add_admin_line",
                "budget_id": monthly_budget.id,
                "fy": "2026",
                "month": "4",
                "description": "Office utilities",
                "cost_category": "operations",
                "quantity": "2",
                "unit_cost": "15000",
                "justification": "Monthly operations",
            },
        )

        self.assertRedirects(
            response,
            "/budgets/overview?fy=2026&date=2026-04-01&period=month&budget_scope=country",
            fetch_redirect_response=False,
        )
        self.assertTrue(
            AdminBudgetLine.objects.filter(
                monthly_budget=monthly_budget,
                description="Office utilities",
                total_cost=30_000,
            ).exists()
        )

    def test_send_to_rvp_advances_to_the_following_month_in_the_same_fy(self):
        monthly_budget = MonthlyWorkPlanBudget.objects.get(
            country_id="Uganda",
            month_key="2026-04",
        )

        response = self.client.post(
            "/country-budget/action",
            {
                "action": "send_to_rvp",
                "budget_id": monthly_budget.id,
                "fy": "2026",
                "month": "4",
            },
        )

        # April → May, same FY (calendar year 2026 for month 5).
        self.assertRedirects(
            response,
            "/budgets/overview?fy=2026&date=2026-05-01&period=month&budget_scope=country",
            fetch_redirect_response=False,
        )

    def test_send_to_rvp_in_september_clamps_within_the_same_fy(self):
        sep_budget, _ = MonthlyWorkPlanBudget.objects.get_or_create(
            country_id="Uganda",
            month_key="2026-09",
            defaults={"fy": "2026"},
        )

        response = self.client.post(
            "/country-budget/action",
            {
                "action": "send_to_rvp",
                "budget_id": sep_budget.id,
                "fy": "2026",
                "month": "9",
            },
        )

        # September is the last month of an Edify FY (Oct→Sep), so the view
        # clamps to September instead of crossing into October / a new FY.
        self.assertRedirects(
            response,
            "/budgets/overview?fy=2026&date=2026-09-01&period=month&budget_scope=country",
            fetch_redirect_response=False,
        )

    def test_active_workspace_links_to_submitted_budgets_history(self):
        response = self.client.get(
            "/budgets/overview?fy=2026&date=2026-04-01&period=month"
        )
        self.assertContains(response, "/country-budget/history?fy=2026")
        self.assertContains(response, "Submitted budgets")

    def test_submitted_month_appears_in_history_and_renders_detail(self):
        monthly_budget = MonthlyWorkPlanBudget.objects.get(
            country_id="Uganda", month_key="2026-04"
        )
        # Submit April so it moves into the history list.
        self.client.post(
            "/country-budget/action",
            {
                "action": "send_to_rvp",
                "budget_id": monthly_budget.id,
                "fy": "2026",
                "month": "4",
            },
        )

        history = self.client.get("/country-budget/history?fy=2026")
        self.assertEqual(history.status_code, 200)
        self.assertTemplateUsed(history, "pages/finance/country_budget_history.html")
        self.assertContains(history, "April")
        self.assertContains(history, "v1")

        # The detail view renders the frozen snapshot.
        detail = self.client.get(f"/country-budget/history/{monthly_budget.id}")
        self.assertEqual(detail.status_code, 200)
        self.assertTemplateUsed(detail, "pages/finance/country_budget_submission.html")
        self.assertContains(detail, "Submitted budget · immutable")
        self.assertContains(detail, "Primary transport")
