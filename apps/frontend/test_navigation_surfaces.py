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

