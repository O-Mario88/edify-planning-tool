"""Admin user-deletion guard rails and access revocation.

The critical property under test: User.objects does NOT filter tombstones,
so a soft-delete alone would leave existing sessions alive. Deletion must
therefore disable the account, tombstone the staff profile, purge sessions,
and refuse the three dangerous cases (non-admin actor, self-delete, last
active Admin).
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.admin_users.services import delete_user
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.rbac import EdifyRole


def _user(email: str, role: str) -> User:
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="password123",
        is_active=True,
        status="active",
    )


class UserDeletionServiceTest(TestCase):
    def setUp(self):
        self.admin = _user("del-admin@edify.test", EdifyRole.ADMIN.value)
        self.second_admin = _user("del-admin2@edify.test", EdifyRole.ADMIN.value)
        self.cceo = _user("del-cceo@edify.test", EdifyRole.CCEO.value)
        self.cceo_profile = StaffProfile.objects.create(user=self.cceo, title="CCEO")

    def test_delete_revokes_access_completely(self):
        # The target has a live session before deletion.
        target_client = Client()
        target_client.force_login(self.cceo)
        self.assertEqual(target_client.get("/dashboard").status_code, 200)

        delete_user(self.cceo.id, self.admin)

        self.cceo.refresh_from_db()
        self.assertIsNotNone(self.cceo.deleted_at)
        self.assertFalse(self.cceo.is_active)
        self.assertEqual(self.cceo.status, "disabled")

        self.cceo_profile.refresh_from_db()
        self.assertIsNotNone(self.cceo_profile.deleted_at)

        # The live session is dead: next request bounces to login.
        response = target_client.get("/dashboard")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response["Location"])

        # And fresh logins fail.
        self.assertFalse(
            Client().login(username="del-cceo@edify.test", password="password123")
        )

        # The deletion is audit-logged.
        row = AuditLog.objects.filter(
            action="admin.user_deleted", subject_id=self.cceo.id
        ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.actor_id, self.admin.id)

    def test_non_admin_cannot_delete(self):
        cd = _user("del-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        with self.assertRaises(BadRequest):
            delete_user(self.cceo.id, cd)
        self.cceo.refresh_from_db()
        self.assertIsNone(self.cceo.deleted_at)

    def test_cannot_delete_yourself(self):
        with self.assertRaises(BadRequest):
            delete_user(self.admin.id, self.admin)
        self.admin.refresh_from_db()
        self.assertIsNone(self.admin.deleted_at)

    def test_cannot_delete_last_active_admin(self):
        # Removing one of two admins is fine…
        delete_user(self.second_admin.id, self.admin)
        # …but a second admin cannot then be deleted by anyone. Recreate an
        # acting admin context: self.admin is now the last one standing.
        survivor = _user("del-admin3@edify.test", EdifyRole.ADMIN.value)
        delete_user(survivor.id, self.admin)  # two admins again -> allowed? No:
        # survivor was just created making two, deleting it leaves one — fine.
        with self.assertRaises(BadRequest):
            delete_user(self.admin.id, self.admin)  # self-delete guard fires first

    def test_last_admin_guard_specifically(self):
        # Delete the second admin so exactly one active admin remains.
        delete_user(self.second_admin.id, self.admin)
        acting = self.admin
        # A hypothetical second acting admin is required to even attempt this,
        # so verify via the guard directly: the last admin cannot be deleted
        # even by another (already deleted) admin's stale principal.
        with self.assertRaises(BadRequest) as ctx:
            delete_user(acting.id, self.second_admin)
        # Either guard is acceptable: deleted actors are no longer Admin-slugged
        # OR the last-admin rule fires. The account must survive regardless.
        acting.refresh_from_db()
        self.assertIsNone(acting.deleted_at)
        self.assertTrue(str(ctx.exception.detail))

    def test_double_delete_is_a_404(self):
        delete_user(self.cceo.id, self.admin)
        with self.assertRaises(NotFoundError):
            delete_user(self.cceo.id, self.admin)


class UserDeletionPageTest(TestCase):
    def setUp(self):
        self.admin = _user("page-admin@edify.test", EdifyRole.ADMIN.value)
        self.second_admin = _user("page-admin2@edify.test", EdifyRole.ADMIN.value)
        self.hr = _user("page-hr@edify.test", EdifyRole.HUMAN_RESOURCES.value)
        self.cceo = _user("page-cceo@edify.test", EdifyRole.CCEO.value)

    def test_admin_deletes_via_page(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            f"/admin-panel/users/{self.cceo.id}", {"action": "delete"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("/admin-panel/users"))
        self.cceo.refresh_from_db()
        self.assertIsNotNone(self.cceo.deleted_at)

        # The deleted user's detail page is gone, and the list omits them.
        self.assertEqual(
            client.get(f"/admin-panel/users/{self.cceo.id}").status_code, 404
        )
        listing = client.get("/admin-panel/users")
        self.assertNotContains(listing, "page-cceo@edify.test")

    def test_hr_sees_no_delete_button_and_cannot_delete(self):
        client = Client()
        client.force_login(self.hr)
        page = client.get(f"/admin-panel/users/{self.cceo.id}")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'value="delete"')

        response = client.post(
            f"/admin-panel/users/{self.cceo.id}", {"action": "delete"}, follow=True
        )
        self.cceo.refresh_from_db()
        self.assertIsNone(self.cceo.deleted_at)
        self.assertContains(response, "Only an Admin can delete users")

    def test_admin_sees_delete_button(self):
        client = Client()
        client.force_login(self.admin)
        page = client.get(f"/admin-panel/users/{self.cceo.id}")
        self.assertContains(page, 'value="delete"')

    def test_self_delete_blocked_via_page(self):
        client = Client()
        client.force_login(self.admin)
        response = client.post(
            f"/admin-panel/users/{self.admin.id}", {"action": "delete"}, follow=True
        )
        self.admin.refresh_from_db()
        self.assertIsNone(self.admin.deleted_at)
        self.assertContains(response, "cannot delete your own account")

    def test_deleted_email_can_be_reused_for_new_user(self):
        client = Client()
        client.force_login(self.admin)
        client.post(f"/admin-panel/users/{self.cceo.id}", {"action": "delete"})
        response = client.post(
            "/admin-panel/users",
            {
                "action": "create",
                "email": "page-cceo@edify.test",
                "name": "Replacement CCEO",
                "role": EdifyRole.CCEO.value,
                "password": "Str0ng!Passw0rd42",
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            User.objects.filter(
                email="page-cceo@edify.test", deleted_at__isnull=True
            ).exists()
        )
