"""The web app reads a page as a desktop browser draws it.

The page feed was built for the phone app, so it read every page as a phone
draws it: To-Do opened as the phone's "Action queue" with its "Do next" card,
and the desktop page's own header and parts never reached the new web app.
The web app now asks for the desktop reading (the feed's ``_desktop=1``);
the phone app's reading is unchanged.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import User
from apps.mobile_feed.views import read_page


class DesktopReadingFeedTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create(
            email="desktop-admin@example.org",
            name="Desktop Admin",
            roles=["Admin"],
            active_role="Admin",
            status="active",
            is_active=True,
        )

    def test_to_do_on_a_desktop_is_the_desktop_page(self):
        status, body = read_page(self.admin, "/todos", {}, desktop=True)

        self.assertEqual(status, 200)
        self.assertEqual(
            (body["header"]["eyebrow"], body["header"]["title"]), ("My Work", "To-Do")
        )

    def test_to_do_on_a_phone_is_still_the_phones_action_queue(self):
        status, body = read_page(self.admin, "/todos", {})

        self.assertEqual(status, 200)
        self.assertEqual(body["header"]["title"], "Action queue")
