"""The RVP's view of the country budget names what they are looking at.

`monthly_request_view` hands CD/RVP/Admin straight to `country_budget_view`, so
the RVP's sidebar carried two entries -- "Monthly Request" and "Monthly Fund
Request" -- that opened the very same page, and neither said "Country Budget".

The Country Director assembles that page and submits it *as* a Monthly Fund
Request; the RVP is the person it is submitted to, and what they are approving
is the country's budget for the month. So the label follows the reader. The CD's
own naming is deliberate and pinned by test_cd_budget_workspaces.py.
"""

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.navigation import build_sidebar_for_user
from apps.monthly_work_plan.models import MonthlyWorkPlanBudget


def _sidebar_items(user, path="/budgets/overview"):
    return [
        item
        for section in build_sidebar_for_user(user, path)
        for item in section["items"]
    ]


class RvpCountryBudgetNamingTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.rvp = User.objects.create_user(
            email="rvp-country-budget@edify.test",
            name="Regional Vice President",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            password="x",
            is_active=True,
        )
        self.cd = User.objects.create_user(
            email="cd-country-budget@edify.test",
            name="Country Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )

    # ── Sidebar ──────────────────────────────────────────────────────────────
    def test_rvp_sidebar_calls_it_budget(self):
        labels = [i["label"] for i in _sidebar_items(self.rvp)]
        self.assertIn("Budget", labels)
        self.assertNotIn("Monthly Fund Request", labels)

    def test_rvp_sidebar_offers_one_route_to_that_page(self):
        """Two links to one destination is a duplicate, not a choice."""
        items = _sidebar_items(self.rvp)
        to_budget = [
            i
            for i in items
            if i["url"]
            in ("/budgets/overview", "/country-budget/", "/accounts/monthly-request/")
        ]
        self.assertEqual(
            [i["url"] for i in to_budget],
            ["/budgets/overview"],
            f"expected one country-budget link, got {[(i['label'], i['url']) for i in to_budget]}",
        )

    def test_rvp_no_longer_sees_the_monthly_request_entry(self):
        urls = [i["url"] for i in _sidebar_items(self.rvp)]
        self.assertNotIn("/accounts/monthly-request/", urls)

    def test_the_country_director_uses_the_same_budget_page(self):
        labels = [i["label"] for i in _sidebar_items(self.cd)]
        self.assertIn("Budget", labels)
        self.assertNotIn("Country Budget", labels)

    # ── Page titles ──────────────────────────────────────────────────────────
    def test_the_page_titles_itself_for_the_rvp(self):
        self.client.force_login(self.rvp)
        response = self.client.get("/budgets/overview?fy=2026&month=7")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["workspace_title"], "General Budget")
        self.assertContains(response, "Monthly Budget")
        self.assertContains(response, "Quarterly Budget")
        self.assertContains(response, "Annual Budget")

    def test_the_page_keeps_its_cd_title(self):
        self.client.force_login(self.cd)
        response = self.client.get("/budgets/overview?fy=2026&month=7")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["workspace_title"], "General Budget")

    def test_the_legacy_monthly_request_deep_link_still_works_for_the_rvp(self):
        """The route stays authorized -- only the sidebar entry was removed."""
        self.client.force_login(self.rvp)
        response = self.client.get("/accounts/monthly-request/?fy=2026&month=7")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/budgets/overview", response.url)

    def test_submitted_budget_history_is_titled_for_the_reader(self):
        self.client.force_login(self.rvp)
        response = self.client.get("/country-budget/history?fy=2026")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["workspace_title"], "Country Budget")


class RvpCountryBudgetDataTest(TestCase):
    """The figures the RVP approves must come from the country's own rows."""

    def setUp(self):
        User = get_user_model()
        self.rvp = User.objects.create_user(
            email="rvp-budget-data@edify.test",
            name="Regional Vice President",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            password="x",
            is_active=True,
        )
        self.cd = User.objects.create_user(
            email="cd-budget-data@edify.test",
            name="Sarah Okello",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password="x",
            is_active=True,
        )
        # A CCEO's scheduled, costed work — the RVP is approving the country
        # envelope, so somebody else's activity must be inside it.
        self.cceo = User.objects.create_user(
            email="cceo-budget-data@edify.test",
            name="Field Officer",
            roles=["CCEO"],
            active_role="CCEO",
            password="x",
            is_active=True,
        )
        activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy="2026",
            planned_date=date(2026, 4, 10),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 10, 9, 0)),
            responsible_staff_id=self.cceo.id,
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
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
            responsible_user=self.cceo.id,
        )
        # A cancelled activity must not reach the envelope.
        cancelled = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="cancelled",
            fy="2026",
            planned_date=date(2026, 4, 11),
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 4, 11, 9, 0)),
            responsible_staff_id=self.cceo.id,
        )
        ActivityScheduleCostLine.objects.create(
            activity=cancelled,
            cost_setting_key="primary_transport_per_day",
            label="Cancelled transport",
            unit_cost=999_000,
            quantity=1,
            amount=999_000,
            planned_date=date(2026, 4, 11),
            month=4,
            fiscal_year="2026",
            catalogue_id="catalogue-1",
            catalogue_version=1,
            responsible_user=self.cceo.id,
        )

    def test_the_rvp_sees_the_whole_country_not_only_their_own_work(self):
        self.client.force_login(self.rvp)
        response = self.client.get(
            "/budgets/overview?fy=2026&date=2026-04-01&period=month"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["budget_scope"], "country")
        self.assertEqual(response.context["program_total"], 60_000)

    def test_cancelled_work_is_not_in_the_envelope(self):
        self.client.force_login(self.rvp)
        response = self.client.get(
            "/budgets/overview?fy=2026&date=2026-04-01&period=month"
        )

        self.assertNotContains(response, "Cancelled transport")
        self.assertNotEqual(response.context["program_total"], 1_059_000)

    def test_submitted_budgets_name_the_person_who_submitted_them(self):
        """The list rendered the raw stored id, so the RVP approving a country
        budget could not see who had sent it."""
        MonthlyWorkPlanBudget.objects.create(
            country_id="Uganda",
            month_key="2026-04",
            fy="2026",
            status="submitted_to_rvp",
            total_amount=60_000,
            submitted_by_user_id=self.cd.id,
            submitted_at=timezone.now(),
        )
        self.client.force_login(self.rvp)
        response = self.client.get("/country-budget/history?fy=2026")

        self.assertEqual(response.status_code, 200)
        rows = response.context["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["submitted_by_name"], "Sarah Okello")
        self.assertContains(response, "Sarah Okello")
        self.assertNotContains(response, self.cd.id)

    def test_an_unresolvable_submitter_falls_back_to_the_id(self):
        """Better a raw id than a blank cell on a page money is approved from."""
        MonthlyWorkPlanBudget.objects.create(
            country_id="Uganda",
            month_key="2026-05",
            fy="2026",
            status="submitted_to_rvp",
            total_amount=1_000,
            submitted_by_user_id="ghost-user-id",
            submitted_at=timezone.now(),
        )
        self.client.force_login(self.rvp)
        response = self.client.get("/country-budget/history?fy=2026")

        row = next(r for r in response.context["rows"] if r["month_key"] == "2026-05")
        self.assertIsNone(row["submitted_by_name"])
        self.assertContains(response, "ghost-user-id")
