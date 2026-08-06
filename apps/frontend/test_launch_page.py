from django.contrib.auth import get_user_model
from django.test import TestCase


class RootRouteTest(TestCase):
    def test_root_renders_login_directly_for_anonymous_users(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/auth/login.html")
        self.assertContains(response, "Access workspace")
        self.assertNotContains(response, "Preparing your workspace")

    def test_root_sends_authenticated_users_to_dashboard(self):
        user = get_user_model().objects.create_user(
            email="root-route@example.com",
            password="Strong-password-123!",
            name="Root Route",
        )
        self.client.force_login(user)

        response = self.client.get("/")

        self.assertRedirects(response, "/dashboard", fetch_redirect_response=False)
