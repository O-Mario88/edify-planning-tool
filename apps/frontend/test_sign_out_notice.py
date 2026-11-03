"""Signing out says so on the sign-in page, and only there (partner audit,
2026-11-03).

Sign-out queued "Logged out successfully." in Django's messages, but the
sign-in screens render no messages, so it waited and appeared after the next
sign-in beside "Welcome back". It now rides the sign-in flow's own one-shot
notice (auth_views._flash).
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.rbac import EdifyRole

SIGNED_OUT = "Logged out successfully."
PASSWORD = "Secret-1!"


class TheSignOutNoticeIsShownOnTheSignInPage(TestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="out@notice.test",
            name="Olive Officer",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            is_active=True,
        )
        self.user.set_password(PASSWORD)
        self.user.save()
        StaffProfile.objects.create(user=self.user, title="CCEO")

    def test_the_sign_in_page_says_you_signed_out(self):
        self.client.force_login(self.user)
        response = self.client.post("/logout", follow=True)
        self.assertEqual(response.redirect_chain[-1][0], "/login")
        self.assertContains(response, SIGNED_OUT)

    def test_the_next_sign_in_does_not_repeat_it(self):
        self.client.force_login(self.user)
        self.client.post("/logout")
        response = self.client.post(
            "/login", {"email": self.user.email, "password": PASSWORD}, follow=True
        )
        self.assertContains(response, "Welcome back")
        self.assertNotContains(response, SIGNED_OUT)
