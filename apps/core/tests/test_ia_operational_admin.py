"""Impact Assessment works with the Admin's operational reach (owner,
2026-11-02), except User Management and System Settings.

Pinned here:

  1. IA holds every permission the Admin holds, less user management and the
     system keys, and keeps its own verification and target authorities. The
     set is derived, so a permission the Admin gains later reaches IA too.
  2. IA opens every page the Admin opens except the user-management and
     system-settings pages — by direct URL and through the API alike.
  3. No other role's permissions moved.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.core.navigation import (
    IA_ADMIN_ONLY_PAGES,
    PAGE_PERMISSIONS,
    ROLE_EXCLUSIVE_PAGES,
)
from apps.core.permissions import RolePermissionService
from apps.core.rbac import (
    IA_EXCLUDED_ADMIN_PERMISSIONS,
    ROLE_PERMISSIONS,
    EdifyRole,
    Permission,
    holds_operational_admin,
    permissions_for_role,
)


def _user(email: str, role: EdifyRole) -> User:
    user = User.objects.create(
        email=email,
        name=email.split("@")[0],
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    StaffProfile.objects.create(user=user, title=user.name, country="Uganda")
    return user


class TheMatrix(TestCase):
    def test_ia_holds_every_admin_permission_but_users_and_system(self):
        ia = set(permissions_for_role(EdifyRole.IMPACT_ASSESSMENT))
        admin = set(permissions_for_role(EdifyRole.ADMIN))
        excluded = {p.value for p in IA_EXCLUDED_ADMIN_PERMISSIONS}
        self.assertEqual(admin - ia, excluded)

    def test_ia_keeps_its_own_authorities(self):
        ia = set(permissions_for_role(EdifyRole.IMPACT_ASSESSMENT))
        for key in (
            Permission.IA_VERIFY,
            Permission.MILESTONES_DEFINE,
            Permission.ACTIVITY_BULK_COMPLETE,
        ):
            self.assertIn(key.value, ia)

    def test_money_approvals_the_admin_never_held_do_not_arrive(self):
        ia = set(permissions_for_role(EdifyRole.IMPACT_ASSESSMENT))
        for key in (Permission.PAYMENT_ACT, Permission.BUDGET_APPROVE):
            self.assertNotIn(key.value, ia)

    def test_user_management_and_system_settings_are_named(self):
        self.assertEqual(
            IA_EXCLUDED_ADMIN_PERMISSIONS,
            {
                Permission.USER_MANAGE,
                Permission.PARTNER_USER_MANAGE,
                Permission.SYSTEM_ADMIN,
                Permission.PLANNING_RECALC,
                Permission.COST_SETTINGS_MANAGE,
                Permission.ACTIVITY_CATALOGUE_MANAGE,
            },
        )

    def test_the_helper_names_admin_and_ia_only(self):
        self.assertTrue(holds_operational_admin(EdifyRole.ADMIN.value))
        self.assertTrue(holds_operational_admin(EdifyRole.IMPACT_ASSESSMENT.value))
        for role in EdifyRole:
            if role not in (EdifyRole.ADMIN, EdifyRole.IMPACT_ASSESSMENT):
                self.assertFalse(holds_operational_admin(role.value), role)

    def test_other_roles_are_unchanged_by_the_rule(self):
        # The derivation adds to IA alone; every other role keeps its own list.
        for role, grants in ROLE_PERMISSIONS.items():
            if role in (EdifyRole.ADMIN, EdifyRole.IMPACT_ASSESSMENT):
                continue
            self.assertNotIn(Permission.ACTIVITY_BULK_COMPLETE, grants, role)
        cd = set(permissions_for_role(EdifyRole.COUNTRY_DIRECTOR))
        self.assertNotIn(Permission.USER_MANAGE.value, cd)


class ThePages(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ia = _user("ops-ia@t.test", EdifyRole.IMPACT_ASSESSMENT)
        cls.cceo = _user("ops-cceo@t.test", EdifyRole.CCEO)

    def test_ia_opens_every_admin_page_but_users_and_settings(self):
        for page in PAGE_PERMISSIONS:
            if page in ROLE_EXCLUSIVE_PAGES:
                continue
            expected = page not in IA_ADMIN_ONLY_PAGES
            with self.subTest(page=page):
                self.assertEqual(
                    RolePermissionService.can_view_page(self.ia, page), expected
                )

    def test_a_page_added_later_is_open_to_ia(self):
        self.assertTrue(RolePermissionService.can_view_page(self.ia, "future_page"))
        self.assertFalse(RolePermissionService.can_view_page(self.cceo, "future_page"))

    def _client(self):
        client = Client()
        client.force_login(self.ia)
        return client

    def test_users_and_system_settings_refuse_ia_by_direct_url(self):
        client = self._client()
        for url in (
            "/admin-panel",
            "/admin-panel/users",
            f"/admin-panel/users/{self.cceo.id}",
            "/admin-panel/roles-permissions",
            "/admin-panel/page-access-matrix",
            "/admin-panel/workflow-rules",
            "/admin-panel/region-district-setup",
            "/admin-panel/notifications-mgmt",
            "/system-health",
            "/admin-ops/support",
            "/admin-ops/maintenance",
        ):
            with self.subTest(url=url):
                self.assertNotEqual(client.get(url).status_code, 200)

    def test_users_and_system_settings_refuse_ia_through_the_api(self):
        client = self._client()
        for url in ("/api/admin/users", "/api/security/health", "/api/system-health"):
            with self.subTest(url=url):
                self.assertIn(client.get(url).status_code, (401, 403))

    def test_operational_pages_once_closed_to_ia_now_open(self):
        client = self._client()
        for url in ("/admin-ops/team-plans", "/admin-panel/audit-log"):
            with self.subTest(url=url):
                self.assertEqual(client.get(url).status_code, 200)


class TheRecords(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ia = _user("rec-ia@t.test", EdifyRole.IMPACT_ASSESSMENT)

    def test_ia_creates_what_the_admin_creates_except_accounts(self):
        for kind in ("activity", "cluster", "partner"):
            self.assertTrue(RolePermissionService.can_create(self.ia, kind), kind)
        self.assertFalse(RolePermissionService.can_create(self.ia, "user"))

    def test_ia_never_manages_users(self):
        self.assertFalse(RolePermissionService.can_manage_users(self.ia))
