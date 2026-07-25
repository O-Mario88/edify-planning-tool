"""A redirect target built from a request value must stay on this site.

Views interpolate ids and query values into redirect paths. The router usually
constrains those values, but the guard has to hold regardless of what the
router happens to allow today — an open redirect on an authenticated app is a
credible phishing primitive precisely because the link really does come from
this domain.
"""

from __future__ import annotations

from django.test import TestCase

from apps.core.redirects import DEFAULT_FALLBACK, is_local_path, local_redirect

OFF_SITE = (
    "//evil.example/login",
    "https://evil.example",
    "http://evil.example",
    "javascript:alert(1)",
    "\\\\evil.example",
    "/\\evil.example",
    "",
    None,
)

ON_SITE = (
    "/dashboard",
    "/my-plan/cmr123",
    "/decisions?fy=2026",
    "/messages?thread=abc#latest",
)


class LocalPathTest(TestCase):
    def test_paths_on_this_site_are_allowed(self):
        for target in ON_SITE:
            with self.subTest(target=target):
                self.assertTrue(is_local_path(target))

    def test_anything_naming_another_host_is_refused(self):
        for target in OFF_SITE:
            with self.subTest(target=target):
                self.assertFalse(is_local_path(target))


class LocalRedirectTest(TestCase):
    def test_a_local_target_is_honoured(self):
        self.assertEqual(local_redirect("/my-plan/abc")["Location"], "/my-plan/abc")

    def test_an_off_site_target_lands_on_the_fallback(self):
        for target in OFF_SITE:
            with self.subTest(target=target):
                self.assertEqual(local_redirect(target)["Location"], DEFAULT_FALLBACK)

    def test_the_fallback_is_configurable(self):
        self.assertEqual(
            local_redirect("//evil.example", fallback="/my-plan")["Location"],
            "/my-plan",
        )

    def test_a_target_submitted_whole_by_a_form_cannot_leave_the_site(self):
        """The shape that was actually exploitable. Two views took their
        destination straight out of the POST body — a phishing link that
        genuinely departs from the real Edify domain, on a route the victim is
        already signed in to."""
        for target in ("https://evil.example/login", "//evil.example"):
            with self.subTest(target=target):
                self.assertEqual(
                    local_redirect(target, fallback="/debriefs")["Location"],
                    "/debriefs",
                )

    def test_an_id_interpolated_after_a_literal_prefix_stays_on_site(self):
        """A value with a leading slash makes "/my-plan//evil.example", which
        a browser reads as a path, not a host — so it is allowed through. Only
        a target that is itself protocol-relative is a redirect off-site, and
        the guard is what tells the two apart."""
        self.assertEqual(
            local_redirect("/my-plan//evil.example")["Location"],
            "/my-plan//evil.example",
        )
