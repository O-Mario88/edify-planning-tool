"""Three CCEO routes nothing else fetched: /actions/mine, /priorities, /extra-work.

The route crawl proves none of them 500s for any role; it cannot say whether
the page a CCEO gets is the page they were promised, or that the roles kept
off it are actually kept off. This is the minimum that does: each page
renders (200) with its own title as a CCEO, and each gate refuses a role
outside its page permission set.

The refusal is asserted over HTMX. `render_access_denied` answers a plain
page GET with a flash and a redirect to /dashboard, and only an HX-Request
(or a URL that reads as an action) with a 403 -- so a plain GET would prove
the redirect and not the gate.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import StaffProfile, User


def _person(key, role):
    user = User.objects.create_user(
        email=f"routes-{key}@edify.org",
        name=f"Routes {key}",
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role, country="Uganda")
    return user


class CceoRouteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cceo = _person("cceo", "CCEO")
        cls.accountant = _person("accountant", "Accountant")
        cls.partner = _person("partner", "PartnerFieldOfficer")

    def _page(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def _denied(self, user, url):
        self.client.force_login(user)
        return self.client.get(url, HTTP_HX_REQUEST="true")

    # ── /actions/mine ────────────────────────────────────────────────────────

    def test_my_actions_renders_for_a_cceo(self):
        response = self._page(self.cceo, "/actions/mine")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>My Actions — Edify</title>", html=True)

    def test_my_actions_requires_a_login(self):
        """`my_actions` is open to every role (anyone can be handed an
        action), so there is no role to refuse; the gate that exists is the
        login one."""
        response = self.client.get("/actions/mine")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login"))

    # ── /priorities ──────────────────────────────────────────────────────────

    def test_priorities_renders_for_a_cceo(self):
        response = self._page(self.cceo, "/priorities")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Priorities · Edify</title>", html=True)

    def test_priorities_refuses_an_accountant(self):
        self.assertEqual(self._denied(self.accountant, "/priorities").status_code, 403)

    # ── /extra-work ──────────────────────────────────────────────────────────

    def test_extra_work_renders_for_a_cceo(self):
        response = self._page(self.cceo, "/extra-work")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<title>Extra Work · Edify</title>", html=True)

    def test_extra_work_refuses_a_partner_field_officer(self):
        self.assertEqual(self._denied(self.partner, "/extra-work").status_code, 403)
