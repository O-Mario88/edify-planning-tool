"""The Regional Programme Lead opens Country Oversight and the Country Map.

Their sidebar offered both and the pages refused them (owner, 2026-11-18:
"Give them access"): the regional roles work across every country, and these
two pages are the country's whole picture.
"""

from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import User
from apps.core.permissions import RolePermissionService, can_open_url


class RegionalLeadCountryPagesTest(TestCase):
    def setUp(self):
        self.lead = User.objects.create(
            email="rpl-country-pages@example.org",
            name="Regional Lead",
            roles=["RegionalProgramLead"],
            active_role="RegionalProgramLead",
            status="active",
            is_active=True,
        )

    def test_the_regional_lead_may_open_country_oversight(self):
        self.assertTrue(
            RolePermissionService.can_view_page(self.lead, "country_planning_oversight")
        )
        self.assertTrue(can_open_url(self.lead, "/country-planning-oversight/"))

    def test_the_regional_lead_may_open_the_country_map(self):
        self.assertTrue(RolePermissionService.can_view_page(self.lead, "country_map"))
        self.assertTrue(can_open_url(self.lead, "/country-map/"))

    def test_the_pages_open_for_them(self):
        self.client.force_login(self.lead)
        for path in ("/country-planning-oversight/", "/country-map/"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
