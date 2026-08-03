"""The fund-request page's four budget horizons, and who may submit which.

Reported: the page named April in July, showed no monthly, quarterly or annual
budget, and did not fetch costs for the period.

The month label was never the bug. `_scoped_base_querysets` matched activities
on `responsible_staff_id=user.user_id` alone, but `activities.services.create`
stamps the StaffProfile CUID by preference -- so the account this was found on
saw 13 of its 213 activities. The page then opened on "the newest scheduled
activity it can see", which was April, and the budgets behind it were empty
because the cost lines were invisible too.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.geography.models import District, Region
from apps.schools.models import School


def _monday(offset: int = 0) -> date:
    today = date.today()
    return today - timedelta(days=today.weekday()) + timedelta(weeks=offset)


class ScopeSeesBothIdentitySpacesTest(TestCase):
    """The defect: work stamped with a StaffProfile id was invisible."""

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="FR Region")
        cls.district = District.objects.create(name="FR District", region=cls.region)
        cls.school = School.objects.create(
            school_id="SCH-FR-1",
            name="FR Primary",
            region=cls.region,
            district=cls.district,
        )
        cls.user = User.objects.create(
            id="fr-cceo",
            email="fr-cceo@edify.org",
            name="FR CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        cls.staff = StaffProfile.objects.create(
            id="fr-cceo-sp", user=cls.user, title="CCEO"
        )

    def _activity(self, owner_id, when):
        return Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(when),
            school=self.school,
            responsible_staff_id=owner_id,
            planned_date=when,
            scheduled_date=when,
        )

    def _visible_activity_count(self):
        """What the page's own scoping can see, through the shared base
        querysets the whole fund-requests page is built from."""
        from django.test import RequestFactory

        from apps.frontend.views.budget_views import _scoped_base_querysets

        request = RequestFactory().get("/fund-requests/weekly")
        request.user = self.user
        return _scoped_base_querysets(request, get_operational_fy())[
            "activities_qs"
        ].count()

    def test_work_stamped_with_the_staff_profile_id_is_visible(self):
        self._activity(self.staff.id, _monday(1))
        self.assertEqual(self._visible_activity_count(), 1)

    def test_work_stamped_with_the_user_id_is_still_visible(self):
        """The identity the page already handled must not regress."""
        self._activity(self.user.id, _monday(1))
        self.assertEqual(self._visible_activity_count(), 1)

    def test_both_are_counted_together(self):
        self._activity(self.staff.id, _monday(1))
        self._activity(self.user.id, _monday(2))
        self.assertEqual(self._visible_activity_count(), 2)

    def test_another_persons_work_is_not(self):
        other = User.objects.create(
            id="fr-other",
            email="fr-other@edify.org",
            name="Other",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        self._activity(other.id, _monday(1))
        self.assertEqual(self._visible_activity_count(), 0)


class FourPeriodBudgetTest(TestCase):
    """Week, month, quarter and FY, all from the canonical budget builder.

    The card first computed its own sums from budget_qs. Those could disagree
    with the My Budget page over quarter boundaries and scope -- a PL's
    hand-computed FY read the whole team while the budget page read their own
    plan. Everything now comes from budget_workspace, so the card and the page
    it summarises cannot argue.
    """

    @classmethod
    def setUpTestData(cls):
        cls.region = Region.objects.create(name="FR2 Region")
        cls.district = District.objects.create(name="FR2 District", region=cls.region)
        cls.school = School.objects.create(
            school_id="SCH-FR2-1",
            name="FR2 Primary",
            region=cls.region,
            district=cls.district,
        )
        cls.user = User.objects.create(
            id="fr2-cceo",
            email="fr2-cceo@edify.org",
            name="FR2 CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        StaffProfile.objects.create(id="fr2-sp", user=cls.user, title="CCEO")

    def _costed(self, when, amount):
        activity = Activity.objects.create(
            activity_type="school_visit",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(when),
            school=self.school,
            responsible_staff_id=self.user.id,
            planned_date=when,
            scheduled_date=when,
        )
        ActivityScheduleCostLine.objects.create(
            activity=activity,
            responsible_user=self.user.id,
            planned_date=when,
            week_start_date=when - timedelta(days=when.weekday()),
            fiscal_year=activity.fy,
            month=when.month,
            description="Transport",
            unit_cost=amount,
            quantity=1,
            amount=amount,
        )

    def _budgets(self, query=""):
        from django.test import RequestFactory

        from apps.frontend.views.budget_views import _build_fund_requests_context

        request = RequestFactory().get("/fund-requests/weekly" + query)
        request.user = self.user
        return _build_fund_requests_context(request)["period_budgets"]

    def test_all_four_horizons_are_offered(self):
        budgets = self._budgets()
        self.assertEqual(
            [t["key"] for t in budgets["tabs"]], ["week", "month", "quarter", "fy"]
        )
        self.assertEqual(
            budgets["active"], "week", "the week moves the money, so it leads"
        )

    def test_only_the_week_carries_a_submit_control(self):
        """Money is disbursed weekly. Approving a quarter would mean nothing."""
        tabs = {t["key"]: t for t in self._budgets()["tabs"]}
        self.assertTrue(tabs["week"]["submits"])
        for key in ("month", "quarter", "fy"):
            with self.subTest(key):
                self.assertFalse(tabs[key]["submits"])

    def test_the_totals_come_from_the_canonical_builder(self):
        """The card must agree with the budget page, so it asks the same
        service the budget page asks."""
        self._costed(_monday(0), 30_000)
        card = self._budgets()
        from apps.budget.services import budget_workspace

        page = budget_workspace(
            self.user, {"period": "week", "date": _monday(0).isoformat()}
        )
        self.assertEqual(card["total"], page["total"])

    def test_the_fy_carries_what_the_week_does_not(self):
        """The reported symptom: a zero week with a non-zero year behind it.

        The week is pinned explicitly. With no week chosen the page anchors on
        the newest scheduled activity -- so with only the 12-week-old activity
        in the fixture it would (correctly) open on that old week and show its
        money, which is the page working, not the symptom.
        """
        self._costed(_monday(-12), 75_000)
        week = self._budgets(f"?week={_monday(0).isoformat()}")
        fy = self._budgets("?period_tab=fy")
        self.assertEqual(week["total"], 0)
        self.assertEqual(fy["total"], 75_000)

    def test_with_no_week_chosen_the_page_opens_where_the_work_is(self):
        """The anchoring rule itself -- and the regression this whole page had:
        deriving that week from the raw UTC date put a local-midnight Monday
        activity into the previous week, so the page opened one week early
        with an empty budget."""
        self._costed(_monday(-12), 75_000)
        week = self._budgets()
        self.assertEqual(week["total"], 75_000)

    def test_the_breakdown_groups_travel_with_the_card(self):
        """The uniform format: the card renders the same group tables the
        budget page does, from the same rows."""
        self._costed(_monday(0), 30_000)
        budgets = self._budgets()
        self.assertTrue(budgets["groups"])
        group = budgets["groups"][0]
        for key in ("label", "table_kind", "rows", "total", "staff_total"):
            with self.subTest(key):
                self.assertIn(key, group)

    def test_an_empty_period_says_so_rather_than_hiding(self):
        budgets = self._budgets()
        self.assertEqual(budgets["groups"], [])
        self.assertTrue(budgets["empty_title"])

    def test_switching_horizon_keeps_the_other_filters(self):
        from django.test import RequestFactory

        from apps.frontend.views.budget_views import _build_fund_requests_context

        request = RequestFactory().get(
            "/fund-requests/weekly?district=d-1&period_tab=fy"
        )
        request.user = self.user
        query = _build_fund_requests_context(request)["period_tab_query"]
        self.assertIn("district=d-1", query)
        self.assertNotIn("period_tab", query)

    def test_an_unknown_horizon_falls_back_to_the_week(self):
        self.assertEqual(self._budgets("?period_tab=decade")["active"], "week")


class ProgrammeAdminBudgetClassificationTest(TestCase):
    """A catalogue Admin item must stay Admin across every finance surface."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            id="programme-admin-pl",
            email="programme-admin-pl@edify.org",
            name="Programme Admin PL",
            roles=["Program Lead"],
            active_role="Program Lead",
            is_active=True,
        )
        StaffProfile.objects.create(
            id="programme-admin-pl-sp", user=cls.user, title="Program Lead"
        )
        cls.when = _monday(0) + timedelta(days=2)
        cls.activity = Activity.objects.create(
            activity_type="partner_activity",
            activity_name_snapshot="Partner Meetings Admin budget",
            programme_activity_type="admin",
            programme_delivery_mode="admin",
            planning_source="manual_work_plan",
            activity_context_type="organization",
            delivery_type="staff",
            status="scheduled",
            fy=get_operational_fy(cls.when),
            responsible_staff_id=cls.user.id,
            planned_date=cls.when,
            scheduled_date=cls.when,
            venue="Production QA venue",
            activity_purpose_text="Verify budget taxonomy",
            expected_participants=1,
            planned_school_count=1,
            est_cost_cents=40_000,
        )
        cls.line = ActivityScheduleCostLine.objects.create(
            activity=cls.activity,
            responsible_user=cls.user.id,
            planned_date=cls.when,
            week_start_date=_monday(0),
            fiscal_year=cls.activity.fy,
            month=cls.when.month,
            label="Partner/project lump sum",
            description="Partner/project lump sum",
            cost_setting_key="partner_visit_lump_sum",
            line_item_type="lump_sum",
            unit_cost=40_000,
            quantity=1,
            amount=40_000,
        )

        from apps.fund_requests.weekly_service import generate_weekly_fund_request

        generate_weekly_fund_request(cls.user.id, _monday(0).isoformat())

    def _context(self):
        from django.test import RequestFactory

        from apps.frontend.views.budget_views import _build_fund_requests_context

        query = (
            f"?fy={self.activity.fy}&month={self.when:%B}"
            f"&week={_monday(0).isoformat()}"
        )
        request = RequestFactory().get("/fund-requests/weekly" + query)
        request.user = self.user
        return _build_fund_requests_context(request)

    def test_weekly_request_keeps_the_admin_source_and_catalogue_title(self):
        context = self._context()
        self.assertEqual(context["weekly_total"], 40_000)
        self.assertEqual(len(context["weekly_lines"]), 1)
        self.assertEqual(context["weekly_lines"][0]["source"], "Admin Budget")
        self.assertEqual(len(context["source_activities"]), 1)
        self.assertEqual(
            context["source_activities"][0]["title"],
            "Partner Meetings Admin budget",
        )
        self.assertEqual(
            context["source_activities"][0]["location"], "Production QA venue"
        )

    def test_monthly_summary_and_budget_table_keep_admin_out_of_visits(self):
        context = self._context()
        self.assertEqual(context["monthly_totals_by_type"]["admin"], 40_000)
        self.assertEqual(context["monthly_totals_by_type"]["visits"], 0)
        self.assertEqual(context["period_budgets"]["total"], 40_000)
        self.assertEqual(context["period_budgets"]["groups"][0]["label"], "Admin")
        self.assertEqual(context["period_budgets"]["groups"][0]["table_kind"], "admin")

    def test_monthly_request_uses_admin_category_and_catalogue_title(self):
        from apps.fund_requests.monthly_request_service import get_monthly_request

        context = get_monthly_request(
            self.user, {"fy": self.activity.fy, "month": self.when.month}
        )
        self.assertEqual(context["shown_total"], 40_000)
        self.assertEqual(context["cost_groups"][0]["label"], "Admin Budget")
        self.assertEqual(
            context["cost_groups"][0]["rows"][0]["activity"],
            "Partner Meetings Admin budget",
        )


class TwoColumnLayoutTest(TestCase):
    """The 70/30 canvas split must hold structurally, not just textually.

    The layout shipped broken while every string check passed: the grid class,
    both column classes and the right panel were all present in the page, but
    an orphaned </div> (left behind when the old period strip was removed from
    the monthly preview) closed the grid early, so the right panel rendered
    OUTSIDE it, full-width below. Classes in the page prove nothing about
    where the tree puts them -- this parses the tree.
    """

    @classmethod
    def setUpTestData(cls):
        from apps.accounts.models import StaffProfile, User

        cls.user = User.objects.create(
            id="layout-cceo",
            email="layout-cceo@edify.org",
            name="Layout CCEO",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        StaffProfile.objects.create(id="layout-sp", user=cls.user, title="CCEO")

    def test_both_columns_are_direct_children_of_the_grid(self):
        from html.parser import HTMLParser

        from django.test import Client

        client = Client()
        client.force_login(self.user)
        body = client.get("/fund-requests/weekly").content.decode()

        class Walk(HTMLParser):
            def __init__(self):
                super().__init__()
                self.depth = 0
                self.grid_depth = None
                self.events = []

            def handle_starttag(self, tag, attrs):
                if tag != "div":
                    return
                self.depth += 1
                cls = dict(attrs).get("class", "") or ""
                if "lg:grid-cols-10" in cls:
                    self.grid_depth = self.depth
                elif self.grid_depth is not None and (
                    "lg:col-span-7" in cls or "lg:col-span-3" in cls
                ):
                    span = "7" if "lg:col-span-7" in cls else "3"
                    self.events.append((span, self.depth - self.grid_depth))

            def handle_endtag(self, tag):
                if tag != "div":
                    return
                if self.grid_depth is not None and self.depth == self.grid_depth:
                    self.grid_depth = None
                self.depth -= 1

        walker = Walk()
        walker.feed(body)
        self.assertEqual(
            walker.events,
            [("7", 1), ("3", 1)],
            "both panels must sit at grid+1; anything else means an unbalanced "
            f"div has re-flattened the layout (saw {walker.events})",
        )

    def test_the_monthly_summary_spans_the_full_width(self):
        """The five summary tiles fill a full row like the KPI strip above.

        Inside the left 70% column they filled the column exactly, and the
        shorter right column had already ended beside them -- which read as a
        row stopping 70% of the way across."""
        from django.test import Client

        client = Client()
        client.force_login(self.user)
        body = client.get("/fund-requests/weekly").content.decode()

        grid_open = body.index("lg:grid-cols-10")
        preview = body.index('id="fund-requests-monthly-preview"')
        # The preview must open AFTER the grid has closed: walk the grid to
        # its close and compare positions.
        import re

        start = body.rindex("<div", 0, grid_open)
        depth = 0
        for match in re.finditer(r"<div\b|</div>", body[start:]):
            depth += 1 if match.group(0) == "<div" else -1
            if depth == 0:
                grid_close = start + match.end()
                break
        self.assertGreater(
            preview,
            grid_close,
            "the monthly summary is inside the two-column grid again",
        )

    def test_the_monthly_preview_is_balanced(self):
        """The partial that carried the orphan. Textual balance is a weaker
        check than the tree walk above, but it points at the file itself."""
        from pathlib import Path

        from django.conf import settings

        source = (
            Path(settings.BASE_DIR)
            / "templates/partials/fund_requests/monthly_preview.html"
        ).read_text()
        self.assertEqual(source.count("<div"), source.count("</div>"))
