"""An invited user's first login must be a funnel, never a loop.

A new user once arrived with two obligations at once: a forced password change
(must_change_password=True) and the mandatory first-login agreements (the
safeguarding policy and the Apostles' Creed, once published). Each was enforced
by its own middleware, and each middleware exempted its own page but not the
other's, so the first login bounced

    /change-password -> /policy-agreement -> /change-password -> ...

until the browser gave up with ERR_TOO_MANY_REDIRECTS.

The owner removed the blocking policy gate on 2026-09-14. The password change
is now the only obligation that redirects: once it is done, the person goes
straight to their work, whatever policy is still unanswered. These tests walk
the whole journey the way a browser would, with cycle detection, so any future
pair of competing redirects fails here instead of at the login screen.
"""

from __future__ import annotations

from apps.documents.tests import DocumentTestBase


MAX_HOPS = 8
FRESH_PASSWORD = "Invited-then-changed-99!"
POLICY_HOPS = ("/policy-agreement", "/documents/")


class FirstLoginFunnelTest(DocumentTestBase):
    def setUp(self):
        super().setUp()
        document, version = self._policy(title="Funnel Safeguarding Policy")
        self._publish(document, version)
        self.cceo.must_change_password = True
        self.cceo.set_password("fresh-invite-password-1!")
        self.cceo.save()

    def _follow(self, response):
        """Follow redirects with cycle detection; return (final, trail)."""
        trail = []
        while response.status_code in (301, 302) and len(trail) < MAX_HOPS:
            target = response.headers["Location"]
            self.assertNotIn(
                target,
                trail,
                "redirect cycle — two gates are bouncing each other's pages: "
                + " -> ".join(trail + [target]),
            )
            trail.append(target)
            response = self.client.get(target)
        self.assertLess(
            len(trail), MAX_HOPS, "redirect chain never settled: " + " -> ".join(trail)
        )
        return response, trail

    def test_the_whole_first_login_settles_without_a_cycle(self):
        response = self.client.post(
            "/login",
            {"email": self.cceo.email, "password": "fresh-invite-password-1!"},
        )
        response, trail = self._follow(response)

        # Credentials first: the funnel presents the password change and
        # actually renders it.
        self.assertEqual(response.status_code, 200)
        self.assertIn("/change-password", trail)

        # Then work: completing the password change does not detour through
        # the policy pages, even with a blocking policy unanswered.
        response = self.client.post(
            "/change-password",
            {"new_password": FRESH_PASSWORD, "confirm_password": FRESH_PASSWORD},
        )
        response, trail = self._follow(response)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            any(hop.startswith(POLICY_HOPS) for hop in trail),
            f"the password change led into the policy pages: {trail}",
        )
        self.cceo.refresh_from_db()
        self.assertFalse(self.cceo.must_change_password)

    def test_the_password_page_is_reachable_with_a_policy_unanswered(self):
        """GET /change-password renders rather than redirecting elsewhere."""
        self.client.force_login(self.cceo)
        response = self.client.get("/change-password")
        self.assertEqual(response.status_code, 200)

    def test_an_unanswered_policy_does_not_withhold_the_dashboard(self):
        """The blocking gate is gone (owner, 2026-09-14)."""
        self.cceo.must_change_password = False
        self.cceo.save(update_fields=["must_change_password"])
        self.client.force_login(self.cceo)

        response = self.client.get("/dashboard")
        response, trail = self._follow(response)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            any(hop.startswith(POLICY_HOPS) for hop in trail),
            f"an unanswered policy still redirected the dashboard: {trail}",
        )
