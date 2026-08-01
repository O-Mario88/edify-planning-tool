"""Self-service profile editing.

A person owns their own name and phone number. Everything else on the account
is either the identity the platform authenticates against, or authority granted
by somebody else -- so the write path is an allow-list, and these tests exist
mostly to prove what it refuses.
"""

from __future__ import annotations

from django.test import Client, TestCase

from apps.accounts.models import User


class ProfileSelfServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            id="profile-self-cceo",
            email="profile-self@edify.org",
            name="Original Name",
            phone="+256700000000",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )
        cls.other = User.objects.create(
            id="profile-self-other",
            email="profile-other@edify.org",
            name="Somebody Else",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
            status="active",
        )

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.user)

    def _post(self, **fields):
        """Post the whole form, as a browser would. Both fields default to the
        stored values, so a test that names one is changing only that one --
        omitting phone would legitimately clear it."""
        data = {"name": "Original Name", "phone": "+256700000000"}
        data.update(fields)
        return self.client.post("/profile", data)

    def test_the_page_renders_the_editable_fields(self):
        """The POST tests would all still pass with a broken template, since
        they never render the form they are meant to be submitting."""
        page = self.client.get("/profile")
        body = page.content.decode()

        self.assertEqual(page.status_code, 200)
        self.assertIn('name="name"', body)
        self.assertIn('name="phone"', body)
        self.assertIn("csrfmiddlewaretoken", body)
        # Granted fields stay read-only: no input should offer to edit them.
        self.assertNotIn('name="email"', body)
        self.assertNotIn('name="roles"', body)

    def test_a_user_can_change_their_own_name_and_phone(self):
        response = self._post(name="Updated Name", phone="+256781234567")

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Updated Name")
        self.assertEqual(self.user.phone, "+256781234567")

    def test_clearing_the_phone_stores_null_not_an_empty_string(self):
        """Otherwise "no phone" reads as a set value everywhere downstream."""
        self._post(phone="")

        self.user.refresh_from_db()
        self.assertIsNone(self.user.phone)

    def test_an_empty_name_is_refused(self):
        self._post(name="   ")

        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Original Name")

    def test_an_over_long_name_is_refused(self):
        self._post(name="x" * 256)

        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Original Name")

    def test_an_over_long_phone_is_refused(self):
        self._post(phone="9" * 65)

        self.user.refresh_from_db()
        self.assertEqual(self.user.phone, "+256700000000")

    def test_the_form_cannot_grant_its_owner_a_role(self):
        """The obvious privilege escalation: post the field and see if it sticks."""
        self._post(roles=["Admin"], active_role="Admin")

        self.user.refresh_from_db()
        self.assertEqual(self.user.roles, ["CCEO"])
        self.assertEqual(self.user.active_role, "CCEO")

    def test_the_form_cannot_change_the_login_identity(self):
        self._post(email="attacker@evil.test")

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "profile-self@edify.org")

    def test_the_form_cannot_reactivate_or_unlock_the_account(self):
        User.objects.filter(id=self.user.id).update(
            is_active=False, status="disabled", lockout_escalated=True
        )

        self._post(is_active=True, status="active", lockout_escalated=False)

        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)
        self.assertEqual(self.user.status, "disabled")
        self.assertTrue(self.user.lockout_escalated)

    def test_the_form_edits_only_the_signed_in_account(self):
        """There is no user id in the request, so the only record reachable is
        request.user -- this pins that, rather than trusting it stays true."""
        self._post(name="Renamed", id=self.other.id, user_id=self.other.id)

        self.other.refresh_from_db()
        self.assertEqual(self.other.name, "Somebody Else")

    def test_an_anonymous_post_changes_nothing(self):
        Client().post("/profile", {"name": "Anonymous Edit"})

        self.user.refresh_from_db()
        self.assertEqual(self.user.name, "Original Name")

    def test_a_real_change_is_audited(self):
        from apps.audit.models import AuditLog

        self._post(name="Audited Name")

        row = AuditLog.objects.filter(action="user.profile_self_updated").first()
        self.assertIsNotNone(row)
        self.assertEqual(row.actor_id, self.user.id)
        self.assertEqual(row.payload["fields"], ["name"])
        # The values themselves stay on the User row rather than being copied
        # into an append-only table that cannot be corrected.
        self.assertNotIn("Audited Name", str(row.payload))

    def test_saving_an_unchanged_form_writes_no_audit_row(self):
        from apps.audit.models import AuditLog

        self._post(phone="+256700000000")

        self.assertFalse(
            AuditLog.objects.filter(action="user.profile_self_updated").exists()
        )
