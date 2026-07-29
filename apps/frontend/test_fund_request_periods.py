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
    """Week, month, quarter and financial year, from the same cost lines."""

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

    def _tabs(self, query=""):
        from django.test import RequestFactory

        from apps.frontend.views.budget_views import _build_fund_requests_context

        request = RequestFactory().get("/fund-requests/weekly" + query)
        request.user = self.user
        budgets = _build_fund_requests_context(request)["period_budgets"]
        return {t["key"]: t for t in budgets["tabs"]}, budgets["active"]

    def test_all_four_horizons_are_offered(self):
        tabs, active = self._tabs()
        self.assertEqual(set(tabs), {"week", "month", "quarter", "fy"})
        self.assertEqual(active, "week", "the week moves the money, so it leads")

    def test_only_the_week_carries_a_submit_control(self):
        """Money is disbursed weekly. Approving a quarter would mean nothing."""
        tabs, _ = self._tabs()
        self.assertTrue(tabs["week"]["submits"])
        for key in ("month", "quarter", "fy"):
            with self.subTest(key):
                self.assertFalse(tabs[key]["submits"])

    def test_the_financial_year_carries_what_the_week_does_not(self):
        """The reported symptom: a zero month with a non-zero year behind it."""
        far = _monday(-12)  # earlier in the same FY, outside this week
        self._costed(far, 75_000)
        tabs, _ = self._tabs()
        self.assertEqual(tabs["week"]["total"], 0)
        self.assertEqual(tabs["fy"]["total"], 75_000)

    def test_the_week_totals_only_its_own_week(self):
        self._costed(_monday(0), 30_000)
        self._costed(_monday(1), 50_000)
        tabs, _ = self._tabs()
        self.assertEqual(tabs["week"]["total"], 30_000)
        self.assertEqual(tabs["fy"]["total"], 80_000)

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
        _, active = self._tabs("?period_tab=decade")
        self.assertEqual(active, "week")
