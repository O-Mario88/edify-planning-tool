from django.test import TestCase


class LaunchPageTest(TestCase):
    def test_root_shows_the_branded_launch_screen_before_login(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "pages/auth/launch.html")
        self.assertContains(response, 'data-launch-screen')
        self.assertContains(response, 'data-login-url="/login"')
        self.assertContains(response, "Preparing your workspace")
        self.assertContains(response, "launch.css")
        self.assertContains(response, "launch.js")
