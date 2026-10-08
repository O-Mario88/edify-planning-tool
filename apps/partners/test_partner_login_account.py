"""A partner's login is configured like a member of staff's (owner,
2026-10-08: "make sure admin can configure partner account, reset password
just like the staff. rightnow it cannot be configured").

A member of staff's row on User Management has a Configure button that opens
their account: details, status, unlock, a password set for them. An
organisation's row had a drawer that linked or invited a login and nothing
else, so once a partner had an account there was no way from the organisation
to reset its password. The account page existed and was reachable only by
finding the right person's name in the staff list below.

Now the organisation's row, its profile and that drawer all open the login's
account page, and the page fits an account that is not a member of staff.
"""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase, override_settings

from apps.accounts.models import StaffProfile
from apps.admin_users.services import delete_user
from apps.audit.models import AuditLog
from apps.core.rbac import EdifyRole
from apps.partners.models import Partner, PartnerUserSetupStatus
from apps.partners.services import (
    is_partner_login,
    login_organisation,
    partner_login,
)

User = get_user_model()
PASSWORD = "StrongPassphrase!23"
NEW_PASSWORD = "Fresh-Passphrase!48"


def _user(email: str, role: str, *, country: str | None = None, name=None) -> User:
    user = User.objects.create_user(
        email=email,
        name=name or email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password=PASSWORD,
    )
    if country:
        StaffProfile.objects.create(user=user, country=country, title=role)
    return user


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class PartnerLoginAccountTests(TestCase):
    def setUp(self):
        self.admin = _user("pla-admin@edify.test", EdifyRole.ADMIN.value)
        self.cd = _user(
            "pla-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value, country="Uganda"
        )
        self.hr = _user(
            "pla-hr@edify.test", EdifyRole.HUMAN_RESOURCES.value, country="Uganda"
        )
        # A linked login has no People record: it was never a member of staff.
        self.login = _user(
            "grace@literacy.test", EdifyRole.PARTNER_ADMIN.value, name="Grace Nakato"
        )
        self.org = Partner.objects.create(
            name="Literacy Works",
            user=self.login,
            user_setup_status=PartnerUserSetupStatus.CONFIGURED,
        )
        self.bare = Partner.objects.create(name="No Login Org")
        self.account_url = f"/admin-panel/users/{self.login.id}"

    # ── Reaching the account from the organisation ───────────────────────
    def test_the_organisations_row_opens_its_logins_account(self):
        self.client.force_login(self.admin)
        page = self.client.get("/admin-panel/users").content.decode()
        self.assertIn(
            f'href="{self.account_url}" aria-label="Configure the login of '
            'Literacy Works"',
            page,
        )
        self.assertIn('aria-label="Change the login of Literacy Works"', page)
        # An organisation with no login has nothing to configure yet.
        self.assertIn('aria-label="Set up login for No Login Org"', page)
        self.assertNotIn("Configure the login of No Login Org", page)

    def test_the_staff_list_says_whose_login_a_partner_account_is(self):
        """It carries a person's name; the directory lists organisations."""
        self.client.force_login(self.admin)
        page = self.client.get("/admin-panel/users?q=grace").content.decode()
        self.assertIn("Grace Nakato", page)
        self.assertIn('title="Partner login for Literacy Works"', page)
        staff = self.client.get("/admin-panel/users?q=pla-cd").content.decode()
        self.assertNotIn("data-partner-login-of", staff)

    def test_the_organisations_profile_opens_it_too(self):
        self.client.force_login(self.admin)
        page = self.client.get(f"/partners/{self.org.id}").content.decode()
        self.assertIn(f'href="{self.account_url}"', page)
        self.assertIn("Configure login", page)
        bare = self.client.get(f"/partners/{self.bare.id}").content.decode()
        self.assertIn("Set up login", bare)
        self.assertNotIn("Configure login", bare)

    def test_the_drawer_points_at_the_account_for_everything_else(self):
        self.client.force_login(self.admin)
        drawer = self.client.get(
            f"/partners/{self.org.id}/user-setup", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn("Change the login of Literacy Works", drawer)
        self.assertIn(f'href="{self.account_url}"', drawer)
        self.assertIn("configure this login", drawer)
        bare = self.client.get(
            f"/partners/{self.bare.id}/user-setup", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn("Set up login for No Login Org", bare)
        self.assertNotIn("configure this login", bare)

    def test_a_login_just_linked_or_invited_opens_on_its_account(self):
        self.client.force_login(self.admin)
        other = _user("field@nologinorg.test", EdifyRole.PARTNER_FIELD_OFFICER.value)
        linked = self.client.post(
            f"/partners/{self.bare.id}/user-setup",
            {"mode": "link", "email": other.email},
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(
            f'window.location.href = "/admin-panel/users/{other.id}"',
            linked.content.decode(),
        )

        third = Partner.objects.create(name="Invited Org")
        invited = self.client.post(
            f"/partners/{third.id}/user-setup",
            {"mode": "invite", "email": "new@invited.test", "login_name": "New One"},
            HTTP_HX_REQUEST="true",
        )
        account = User.objects.get(email="new@invited.test")
        self.assertIn(
            f'window.location.href = "/admin-panel/users/{account.id}"',
            invited.content.decode(),
        )

    def test_no_login_required_goes_back_to_the_directory(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            f"/partners/{self.bare.id}/user-setup",
            {"mode": "not_required"},
            HTTP_HX_REQUEST="true",
        )
        self.assertIn(
            'window.location.href = "/admin-panel/users"', response.content.decode()
        )

    # ── The account page, for an account that is not staff ───────────────
    def test_the_page_says_whose_login_it_is_and_drops_the_staff_parts(self):
        self.client.force_login(self.admin)
        page = self.client.get(self.account_url)
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn("Partner login for", body)
        self.assertIn(f'href="/partners/{self.org.id}"', body)
        self.assertIn("Reset Password", body)
        self.assertIn("Account Lifecycle", body)
        self.assertNotIn("Primary District Assignment", body)
        self.assertNotIn("People Managed", body)

    def test_only_the_partner_roles_are_offered(self):
        self.client.force_login(self.admin)
        page = self.client.get(self.account_url)
        self.assertEqual(
            sorted(page.context["available_roles"]),
            sorted(
                [
                    EdifyRole.PARTNER_ADMIN.value,
                    EdifyRole.PARTNER_FIELD_OFFICER.value,
                ]
            ),
        )

    def test_a_staff_account_keeps_the_whole_page(self):
        self.client.force_login(self.admin)
        page = self.client.get(f"/admin-panel/users/{self.cd.id}")
        body = page.content.decode()
        self.assertNotIn("data-partner-login", body)
        self.assertIn("Primary District Assignment", body)
        self.assertIn(EdifyRole.CCEO.value, page.context["available_roles"])

    def test_a_partner_account_with_no_organisation_says_so(self):
        loose = _user("loose@partner.test", EdifyRole.PARTNER_FIELD_OFFICER.value)
        self.client.force_login(self.admin)
        body = self.client.get(f"/admin-panel/users/{loose.id}").content.decode()
        self.assertIn("not the login of any organisation yet", body)

    # ── Configuring it ───────────────────────────────────────────────────
    def test_the_admin_resets_its_password(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self.account_url,
            {"action": "reset_password", "new_password": NEW_PASSWORD},
        )
        self.assertRedirects(response, self.account_url, fetch_redirect_response=False)
        self.login.refresh_from_db()
        self.assertTrue(self.login.must_change_password)
        self.assertTrue(self.login.check_password(NEW_PASSWORD))
        self.assertIsNotNone(
            authenticate(None, email=self.login.email, password=NEW_PASSWORD)
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.password_reset_direct",
                subject_id=self.login.id,
                actor_id=self.admin.id,
            ).exists()
        )

    def test_an_invited_login_is_given_a_password_and_can_sign_in(self):
        """The invitation email never arrived: the Admin sets a password, as
        for a member of staff, and the account is live."""
        self.client.force_login(self.admin)
        org = Partner.objects.create(name="Waiting Org")
        self.client.post(
            f"/partners/{org.id}/user-setup",
            {"mode": "invite", "email": "wait@waiting.test", "login_name": "Wait"},
            HTTP_HX_REQUEST="true",
        )
        account = User.objects.get(email="wait@waiting.test")
        self.assertEqual(account.status, "pending_invited")
        self.assertIsNone(authenticate(None, email=account.email, password=PASSWORD))

        self.client.post(
            f"/admin-panel/users/{account.id}",
            {"action": "reset_password", "new_password": NEW_PASSWORD},
        )
        account.refresh_from_db()
        self.assertEqual(account.status, "active")
        self.assertTrue(account.is_active)
        self.assertIsNotNone(
            authenticate(None, email=account.email, password=NEW_PASSWORD)
        )

    def test_the_admin_deactivates_and_reactivates_it(self):
        self.client.force_login(self.admin)
        self.client.post(self.account_url, {"action": "deactivate"})
        self.login.refresh_from_db()
        self.assertFalse(self.login.is_active)
        self.client.post(self.account_url, {"action": "activate"})
        self.login.refresh_from_db()
        self.assertTrue(self.login.is_active)

    def test_saving_its_details_does_not_make_it_a_member_of_staff(self):
        """The staff form's save gave every account a People record and
        cleared its districts. A partner's login has neither."""
        self.client.force_login(self.admin)
        response = self.client.post(
            self.account_url,
            {
                "action": "edit",
                "name": "Grace N. Nakato",
                "email": "grace.nakato@literacy.test",
                "phone": "+256700000001",
                "role": EdifyRole.PARTNER_FIELD_OFFICER.value,
            },
        )
        self.assertRedirects(response, self.account_url, fetch_redirect_response=False)
        self.login.refresh_from_db()
        self.assertEqual(self.login.name, "Grace N. Nakato")
        self.assertEqual(self.login.email, "grace.nakato@literacy.test")
        self.assertEqual(self.login.active_role, EdifyRole.PARTNER_FIELD_OFFICER.value)
        self.assertFalse(StaffProfile.objects.filter(user=self.login).exists())
        # Still the organisation's login under its new name and role.
        self.assertEqual(login_organisation(self.login), self.org)

    def test_saving_a_staff_account_still_keeps_its_people_record(self):
        self.client.force_login(self.admin)
        cceo = _user("pla-cceo@edify.test", EdifyRole.CCEO.value)
        self.client.post(
            f"/admin-panel/users/{cceo.id}",
            {
                "action": "edit",
                "name": "Pla Cceo",
                "email": cceo.email,
                "phone": "",
                "role": EdifyRole.CCEO.value,
            },
        )
        self.assertTrue(StaffProfile.objects.filter(user=cceo).exists())

    # ── Who reaches it ───────────────────────────────────────────────────
    def test_the_country_director_reaches_a_login_with_no_people_record(self):
        """Reach is by the country on a People record, and a linked partner
        login has none: the Country Director set the login up and was then
        told it did not exist."""
        self.client.force_login(self.cd)
        self.assertEqual(self.client.get(self.account_url).status_code, 200)
        self.client.post(
            self.account_url,
            {"action": "reset_password", "new_password": NEW_PASSWORD},
        )
        self.login.refresh_from_db()
        self.assertTrue(self.login.check_password(NEW_PASSWORD))

    def test_someone_who_does_not_set_up_partner_logins_does_not(self):
        """HR holds the Users page for staff; partner logins are the Admin's
        and the Country Director's (owner, 2026-09-15)."""
        self.client.force_login(self.hr)
        self.assertEqual(self.client.get(self.account_url).status_code, 404)
        response = self.client.post(
            self.account_url,
            {"action": "reset_password", "new_password": NEW_PASSWORD},
        )
        self.assertEqual(response.status_code, 404)
        self.login.refresh_from_db()
        self.assertTrue(self.login.check_password(PASSWORD))

    def test_staff_out_of_reach_stay_out_of_reach(self):
        """The partner rule widens nothing for staff accounts."""
        elsewhere = _user("pla-kenya@edify.test", EdifyRole.CCEO.value, country="Kenya")
        self.client.force_login(self.cd)
        self.assertEqual(
            self.client.get(f"/admin-panel/users/{elsewhere.id}").status_code, 404
        )

    # ── A deleted login ──────────────────────────────────────────────────
    def test_deleting_the_login_leaves_the_organisation_without_one(self):
        delete_user(self.login.id, self.admin)
        self.org.refresh_from_db()
        self.assertIsNone(self.org.user_id)
        self.assertEqual(self.org.user_setup_status, PartnerUserSetupStatus.PENDING)
        row = AuditLog.objects.get(
            action="admin.user_deleted", subject_id=self.login.id
        )
        self.assertEqual(row.payload["partnerLoginOf"], [self.org.id])

        self.client.force_login(self.admin)
        page = self.client.get("/admin-panel/users").content.decode()
        self.assertIn('aria-label="Set up login for Literacy Works"', page)
        self.assertNotIn("Configure the login of Literacy Works", page)

    def test_deleting_a_member_of_staff_touches_no_organisation(self):
        cceo = _user("pla-gone@edify.test", EdifyRole.CCEO.value)
        delete_user(cceo.id, self.admin)
        self.org.refresh_from_db()
        self.assertEqual(self.org.user_id, self.login.id)
        row = AuditLog.objects.get(action="admin.user_deleted", subject_id=cceo.id)
        self.assertNotIn("partnerLoginOf", row.payload)

    # ── The helpers the pages read ───────────────────────────────────────
    def test_what_counts_as_a_partner_login(self):
        self.assertTrue(is_partner_login(self.login))
        self.assertFalse(is_partner_login(self.cd))
        self.assertFalse(is_partner_login(self.admin))
        self.assertEqual(partner_login(self.org), self.login)
        self.assertIsNone(partner_login(self.bare))
        self.assertIsNone(login_organisation(self.cd))
