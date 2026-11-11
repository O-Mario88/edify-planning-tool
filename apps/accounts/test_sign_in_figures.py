"""The app's sign-in screen shows the same four figures as the web's (owner,
2026-11-11: the app's sign-in is an exact replica of the web sign-in page).

The figures come from the web page's own reckoning
(apps.frontend.views.auth_views._login_stats), so the two can never disagree.
They are public, coarse totals with no school or person in them.
"""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

URL = "/api/auth/sign-in-figures"
FIGURES = {
    "stat_portfolio": "700",
    "stat_schools_reached": "700",
    "stat_schools_visited": "12",
    "stat_schools_trained": "0",
    "stat_ssa_completed": "306",
}


class SignInFiguresTest(TestCase):
    def test_the_figures_are_the_web_sign_in_pages_own(self):
        with patch("apps.accounts.views._login_stats", return_value=FIGURES):
            response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "portfolio": "700",
                "schoolsReached": "700",
                "schoolsVisited": "12",
                "schoolsTrained": "0",
                "ssaCompleted": "306",
            },
        )

    def test_no_sign_in_is_needed_and_the_answer_may_be_cached_briefly(self):
        with patch("apps.accounts.views._login_stats", return_value=FIGURES):
            response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age=300", response["Cache-Control"])

    def test_an_empty_programme_reads_zero(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["schoolsReached"], "0")
