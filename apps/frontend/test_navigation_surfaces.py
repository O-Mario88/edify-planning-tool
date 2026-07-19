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

    def test_no_sidebar_page_renders_template_artifacts(self):
        """No page may show template plumbing or a raw Python value as copy.

        These defects render fine, return 200 and pass every other test --
        the template is valid, it just prints the wrong thing. Only reading
        the page catches them, which is how a four-line ``{# #}`` comment
        ended up displayed as a paragraph above the My Team table and how
        ``(0 acts) None Avg`` reached the analytics regional panel.

        Only patterns that are always a defect are checked. A bare "None" is
        left out on purpose: it is legitimate copy in a filter option, so
        asserting on it would make this test fail for a correct page.
        """
        import re

        # Template syntax that survived to the response is never intentional.
        artifacts = {
            "unrendered {% %} tag": re.compile(r"\{%"),
            "unrendered {{ }} variable": re.compile(r"\{\{"),
            "leaked {# #} comment": re.compile(r"\{#"),
            "JavaScript NaN": re.compile(r"\bNaN\b"),
            "JavaScript undefined": re.compile(r"\bundefined\b"),
        }
        strip = re.compile(
            r"<(script|style|noscript)\b.*?</\1>", re.DOTALL | re.IGNORECASE
        )
        tags = re.compile(r"<[^>]+>")

        urls = {
            item["url"]
            for section in build_sidebar_for_user(self.user, "/")
            for item in section["items"]
        }

        offenders = []
        for url in sorted(urls):
            response = self.client.get(url)
            if response.status_code != 200:
                continue
            body = response.content.decode("utf-8", errors="ignore")
            visible = tags.sub(" ", strip.sub(" ", body))
            for label, pattern in artifacts.items():
                if pattern.search(visible):
                    offenders.append(f"{url}: {label}")

        self.assertEqual(
            offenders,
            [],
            f"Pages rendering template plumbing as visible copy: {offenders}",
        )
