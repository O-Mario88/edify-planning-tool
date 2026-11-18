"""A page the feed does not draw says so, apart from one the reader may not
open.

The feed draws its native pages only. A page of the web that the reader may
open but the feed does not draw used to be answered 404, like a page refused
to the reader, so the new web app showed "This page could not be found" for a
page that exists and is the reader's. It is answered 501 now, which the gateway
reads as "not moved yet" and the web app opens in the existing web.
"""

from __future__ import annotations

from django.test import TestCase
from django.urls import resolve

from apps.accounts.models import User
from apps.mobile_feed.views import LATER_PARTS, NATIVE_PAGES, read_page


class PageNotMovedFeedTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create(
            email="not-moved-admin@example.org",
            name="Not Moved Admin",
            roles=["Admin"],
            active_role="Admin",
            status="active",
            is_active=True,
        )

    def test_a_web_page_the_feed_does_not_draw_is_not_moved_yet(self):
        self.assertNotIn(resolve("/messages").url_name, NATIVE_PAGES | LATER_PARTS)

        status, body = read_page(self.admin, "/messages", {})

        self.assertEqual(status, 501)
        self.assertEqual(body["error"], "This page has not moved here yet.")

    def test_a_page_the_reader_may_not_open_is_still_not_found(self):
        partner = User.objects.create(
            email="not-moved-partner@example.org",
            name="Not Moved Partner",
            roles=["PartnerFieldOfficer"],
            active_role="PartnerFieldOfficer",
            status="active",
            is_active=True,
        )

        status, _ = read_page(partner, "/admin-panel/users", {})

        self.assertEqual(status, 404)

    def test_a_path_that_is_no_page_is_not_found(self):
        status, _ = read_page(self.admin, "/no-such-page-anywhere", {})

        self.assertEqual(status, 404)
