"""An invited user's first login must be a funnel, never a loop.

A new user arrives with two obligations at once: a forced password change
(must_change_password=True) and the mandatory first-login agreements (the
safeguarding policy and the Apostles' Creed, once published). Each is enforced
by its own middleware, and each middleware exempted its own page but not the
other's: ForcePasswordChangeMiddleware allowed only /change-password, and the
policy gate's "/password" prefix does not match "/change-password". So the
first login bounced

    /change-password -> /policy-agreement -> /change-password -> ...

until the browser gave up with ERR_TOO_MANY_REDIRECTS. Nobody invited after
the agreements were installed could sign in at all — reported as "users cannot
login, it goes off at the change password and safeguarding policy".

The resolution is an ordering, not an exception: credentials first (the policy
gate exempts /change-password), then the agreements. These tests walk the whole
journey the way a browser would, with cycle detection, so any future pair of
competing gates fails here instead of at the login screen.
"""

from __future__ import annotations

from apps.documents.tests import DocumentTestBase


MAX_HOPS = 8
FRESH_PASSWORD = "Invited-then-changed-99!"


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

        # Credentials first: the funnel must present the password change and
        # actually render it, with the policy gate standing aside.
        self.assertEqual(response.status_code, 200)
        self.assertIn("/change-password", trail)

        # Then the agreements: completing the password change hands over to
        # the policy flow rather than back to the password page.
        response = self.client.post(
            "/change-password",
            {"new_password": FRESH_PASSWORD, "confirm_password": FRESH_PASSWORD},
        )
        response, trail = self._follow(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(hop.startswith(("/policy-agreement", "/documents/")) for hop in trail),
            f"expected the policy flow after the password change, got: {trail}",
        )
        self.cceo.refresh_from_db()
        self.assertFalse(self.cceo.must_change_password)

    def test_the_password_page_is_reachable_while_the_policy_gate_is_armed(self):
        """The precise deadlock: both obligations at once, GET /change-password
        must render rather than redirect into the policy flow."""
        self.client.force_login(self.cceo)
        response = self.client.get("/change-password")
        self.assertEqual(response.status_code, 200)

    def test_the_policy_gate_still_holds_after_the_password_is_changed(self):
        """Exempting /change-password must not have widened the gate."""
        self.cceo.must_change_password = False
        self.cceo.save(update_fields=["must_change_password"])
        self.client.force_login(self.cceo)

        response = self.client.get("/dashboard")
        response, trail = self._follow(response)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            any(hop.startswith(("/policy-agreement", "/documents/")) for hop in trail),
            f"the agreements must still gate the application: {trail}",
        )
