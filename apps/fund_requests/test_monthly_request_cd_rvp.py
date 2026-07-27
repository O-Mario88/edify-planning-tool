"""Tests for Country Director and RVP Monthly Request workflow & weekly breakdown."""

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.fund_requests import monthly_request_service as service


class MonthlyRequestCdRvpTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.cd_user = User.objects.create(
            id="cd-monthly-1",
            email="cd@edify.org",
            name="Country Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            is_active=True,
        )
        self.rvp_user = User.objects.create(
            id="rvp-monthly-1",
            email="rvp@edify.org",
            name="Regional VP",
            roles=["RegionalVicePresident"],
            active_role="RegionalVicePresident",
            is_active=True,
        )

    def test_cd_monthly_request_fetches_country_budget_with_weekly_groups(self):
        res = service.get_monthly_request(self.cd_user, {"fy": "2026", "month": "10"})
        self.assertTrue(res.get("is_country_request"))
        self.assertEqual(res.get("role"), "CountryDirector")
        self.assertTrue(res.get("can_submit_to_rvp"))
        self.assertEqual(res.get("submit_rvp_label"), "Send to RVP for Approval")

        weekly_groups = res.get("weekly_groups", [])
        self.assertGreaterEqual(len(weekly_groups), 4)
        self.assertEqual(weekly_groups[0]["week_key"], "Week 1")
        self.assertEqual(weekly_groups[1]["week_key"], "Week 2")
        self.assertEqual(weekly_groups[2]["week_key"], "Week 3")
        self.assertEqual(weekly_groups[3]["week_key"], "Week 4")

    def test_submit_to_rvp_action(self):
        res = service.submit_to_rvp(self.cd_user, "2026", 10)
        self.assertEqual(res.status, "submitted_to_rvp")

        cd_res = service.get_monthly_request(
            self.cd_user, {"fy": "2026", "month": "10"}
        )
        self.assertEqual(cd_res.get("request_state"), "submitted_to_rvp")
        self.assertFalse(cd_res.get("can_submit_to_rvp"))
