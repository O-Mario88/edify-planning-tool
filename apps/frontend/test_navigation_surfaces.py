from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.navigation import build_sidebar_for_user


class AdminNavigationSurfaceSmokeTest(TestCase):
    """Every destination exposed in the Admin sidebar must resolve safely."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="navigation-admin@edify.org",
            password="password123",
            name="Navigation Admin",
            roles=["Admin"],
            active_role="Admin",
        )
        StaffProfile.objects.create(
            user=self.user,
            title="Platform Administrator",
            department="Administration",
            country="Uganda",
            onboarding_state="active",
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_every_visible_sidebar_destination_resolves(self):
        urls = {
            item["url"]
            for section in build_sidebar_for_user(self.user, "/")
            for item in section["items"]
        }
        self.assertGreaterEqual(len(urls), 40)

        for url in sorted(urls):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(
                    response.status_code,
                    (200, 301, 302),
                    f"Sidebar destination {url} returned {response.status_code}",
                )

    def test_major_filter_surfaces_accept_real_interaction_state(self):
        """High-traffic filter/search/tab surfaces must render with non-default
        query state instead of only passing their empty initial page."""
        surfaces = (
            (
                "/schools",
                {"tab": "unclustered", "q": "no-match", "per_page": "25"},
            ),
            (
                "/planning",
                {
                    "tab": "core",
                    "q": "no-match",
                    "planning_readiness": "locked",
                    "per_page": "20",
                },
            ),
            (
                "/my-plan",
                {
                    "period": "month",
                    "activity_type": "school_visit",
                    "status": "completed",
                },
            ),
            (
                "/messages",
                {"tab": "unread", "q": "no-match", "sort": "oldest"},
            ),
            (
                "/analytics/",
                {"fy": "2026", "quarter": "Q4", "school_type": "core"},
            ),
            (
                "/projects/planning",
                {"q": "no-match", "tab": "baseline", "quarter": "Q4"},
            ),
            (
                "/projects/my-plan",
                {"q": "no-match", "period": "month", "quarter": "Q4"},
            ),
            (
                "/projects/analytics",
                {"q": "no-match", "fy": "2026"},
            ),
            (
                "/ssa",
                {"q": "no-match", "fy": "2026", "quarter": "Q4"},
            ),
            (
                "/clusters",
                {"q": "no-match", "status": "active"},
            ),
            (
                "/debriefs",
                {"q": "no-match", "range_days": "30", "risk_level": "critical"},
            ),
        )

        for url, params in surfaces:
            with self.subTest(url=url):
                response = self.client.get(url, params)
                self.assertEqual(
                    response.status_code,
                    200,
                    f"Filtered surface {url} returned {response.status_code}",
                )
