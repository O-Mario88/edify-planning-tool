"""Navigation and admin hygiene for the Country Director.

The CD's mobile bar asked for a `country_budget` item nobody registered and
silently dropped it (the sidebar keeps the platform's one 'Budget' label); the Cost Catalogue was locked to the current year; the
Users page listed every user in every country, unpaginated, and offered an
Admin role the service refuses (owner, 2026-09-03).
"""

from __future__ import annotations

from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.core.rbac import EdifyRole
from apps.partners.models import Partner

User = get_user_model()


def _person(email, name, role, country="Uganda"):
    u = User.objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=u, title=role, country=country)
    return u


class CdNavigationHygieneTest(TestCase):
    def test_the_cd_budget_entry_reaches_the_phone(self):
        from apps.core.navigation import (
            build_mobile_nav_for_user,
            build_sidebar_for_user,
        )

        cd = SimpleNamespace(is_authenticated=True, active_role="CD")
        labels = {
            i["label"]: i["url"]
            for g in build_sidebar_for_user(cd, "/")
            for i in g["items"]
        }
        self.assertEqual(labels.get("Budget"), "/budget")
        mobile = build_mobile_nav_for_user(cd, "/")
        self.assertIn("/budget", {i["url"] for i in mobile})


class CostSettingsFiscalYearTest(TestCase):
    def test_the_cd_can_open_another_years_rate_card(self):
        cd = _person("hyg-cd@t.org", "Hyg CD", EdifyRole.COUNTRY_DIRECTOR.value)
        self.client.force_login(cd)
        response = self.client.get("/cost-settings?fy=2025")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "FY2025 approved cost items")
        self.assertContains(response, 'id="cost-settings-fy"')
        response = self.client.get("/cost-settings?fy=nonsense")
        self.assertEqual(response.status_code, 200)


class UsersPageScopeTest(TestCase):
    def setUp(self):
        self.cd = _person("usr-cd@t.org", "Usr CD", EdifyRole.COUNTRY_DIRECTOR.value)
        for i in range(12):
            _person(f"usr-{i}@t.org", f"Usr Local {i:02d}", EdifyRole.CCEO.value)
        _person("usr-abroad@t.org", "Usr Abroad", EdifyRole.CCEO.value, country="Kenya")

    def test_the_cd_sees_their_country_paginated_and_cannot_grant_admin(self):
        from apps.core.pagination import TABLE_PAGE_SIZE

        self.client.force_login(self.cd)
        response = self.client.get("/admin-panel/users")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Usr Abroad")
        self.assertEqual(len(response.context["users_pager"]["rows"]), TABLE_PAGE_SIZE)
        page_two = self.client.get("/admin-panel/users?page=2")
        self.assertEqual(page_two.status_code, 200)
        self.assertNotIn("Admin", response.context["available_roles"])

    def test_partner_summary_uses_the_directory_presentation_status(self):
        Partner.objects.create(name="Active partner", active_status=True)
        Partner.objects.create(name="Inactive partner", active_status=False)

        self.client.force_login(self.cd)
        response = self.client.get("/admin-panel/users")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_partner_count"], 1)
