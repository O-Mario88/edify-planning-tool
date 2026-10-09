"""Accounts are the Admin's; a partner splits its schools among its team.

Owner, 2026-10-09: "Admin cant add new users is is bringing a blury screen and
nothing else. Also admin cant configure partner login like setting and
resetting password. can you fix it. Admin should have set up and configure
every account. Remove users from CD role and restrict it to admin. the Action
button should include configure option so that the admin can set up the
account, reset passwords for all users and partners. Partners can onboard
their team members. Partner can assign schools assigend to them to the rest of
their team members so that the the system can track who supported which
schools." Then: "can you reduce the drawer size to match the system drawer"
and "Add deactivate option too for active users and activate for inactive
users".
"""

from __future__ import annotations

from django.contrib.auth import authenticate, get_user_model
from django.test import TestCase, override_settings

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.permissions import RolePermissionService, has_permission
from apps.core.rbac import EdifyRole, Permission
from apps.geography.models import District, Region
from apps.partners import profile_lists, school_team
from apps.partners.models import (
    Partner,
    PartnerAssignment,
    PartnerMember,
    PartnerSchoolMember,
)
from apps.partners.services import (
    add_member,
    configure_partner_user,
    may_manage_partner_users,
    partner_user_administrators,
)
from apps.schools.models import School

User = get_user_model()
PASSWORD = "StrongPassphrase!23"
NEW_PASSWORD = "Fresh-Passphrase!48"


def _user(email: str, role: str, *, staff: bool = True, name=None):
    user = User.objects.create_user(
        email=email,
        name=name or email.split("@")[0].title(),
        roles=[role],
        active_role=role,
        password=PASSWORD,
    )
    if staff:
        StaffProfile.objects.create(user=user, country="Uganda", title=role)
    return user


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class AccountsAreTheAdminsTests(TestCase):
    def setUp(self):
        self.admin = _user("aa-admin@edify.test", EdifyRole.ADMIN.value)
        self.cd = _user("aa-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        self.hr = _user("aa-hr@edify.test", EdifyRole.HUMAN_RESOURCES.value)
        self.cceo = _user("aa-cceo@edify.test", EdifyRole.CCEO.value, name="Nick Field")
        self.login = _user(
            "aa-grace@literacy.test",
            EdifyRole.PARTNER_ADMIN.value,
            staff=False,
            name="Grace Nakato",
        )
        self.org = Partner.objects.create(name="Literacy Works", user=self.login)
        self.bare = Partner.objects.create(name="No Login Org")

    # ── Who holds accounts ───────────────────────────────────────────────
    def test_only_the_admin_holds_user_management(self):
        self.assertTrue(has_permission(self.admin, Permission.USER_MANAGE.value))
        for other in (self.cd, self.hr, self.cceo):
            self.assertFalse(has_permission(other, Permission.USER_MANAGE.value))
            self.assertFalse(RolePermissionService.can_view_page(other, "users"))
            self.assertFalse(RolePermissionService.can_manage_users(other))
        self.assertTrue(RolePermissionService.can_view_page(self.admin, "users"))

    def test_the_country_director_cannot_open_the_users_page(self):
        self.client.force_login(self.cd)
        self.assertNotEqual(self.client.get("/admin-panel/users").status_code, 200)
        self.assertNotEqual(
            self.client.get(f"/admin-panel/users/{self.cceo.id}").status_code, 200
        )
        self.client.post(
            f"/admin-panel/users/{self.cceo.id}",
            {"action": "reset_password", "new_password": NEW_PASSWORD},
        )
        self.assertIsNone(authenticate(email=self.cceo.email, password=NEW_PASSWORD))

    def test_partner_logins_are_the_admins_alone(self):
        self.assertTrue(may_manage_partner_users(self.admin))
        self.assertFalse(may_manage_partner_users(self.cd))
        with self.assertRaises(Forbidden):
            configure_partner_user(
                self.bare.id, {"mode": "invite", "email": "x@org.test"}, self.cd
            )
        self.assertEqual([u.id for u in partner_user_administrators()], [self.admin.id])

    # ── Add User ─────────────────────────────────────────────────────────
    def test_add_user_opens_in_the_platform_drawer(self):
        self.client.force_login(self.admin)
        page = self.client.get("/admin-panel/users").content.decode()
        self.assertIn('hx-get="/admin-panel/users?drawer=add"', page)
        # The page-local dialog whose dimming layer covered it is gone.
        self.assertNotIn("showAddModal", page)
        self.assertNotIn("Provision New System User", page)
        drawer = self.client.get("/admin-panel/users?drawer=add").content.decode()
        self.assertIn("data-add-user-form", drawer)
        self.assertIn("drawer-surface", drawer)
        self.assertNotIn("<html", drawer)

    def test_the_drawer_form_creates_the_account(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            "/admin-panel/users",
            {
                "action": "create",
                "name": "New Officer",
                "email": "aa-new@edify.test",
                "role": "CCEO",
                "password": NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 302)
        created = User.objects.get(email="aa-new@edify.test")
        self.assertTrue(created.is_active)
        self.assertTrue(created.must_change_password)

    # ── The Actions menu of every account ────────────────────────────────
    def test_every_account_row_offers_configure_and_reset_password(self):
        self.client.force_login(self.admin)
        page = self.client.get("/admin-panel/users").content.decode()
        for account in (self.cceo, self.cd, self.login):
            self.assertIn(
                f'href="/admin-panel/users/{account.id}" '
                f'aria-label="Configure the account of {account.name}"',
                page,
            )
            self.assertIn(
                f'hx-get="/admin-panel/users/{account.id}?drawer=password"', page
            )
        # The organisation's row reaches the same two.
        self.assertIn('aria-label="Reset the password of Literacy Works"', page)
        self.assertIn('aria-label="Configure the login of No Login Org"', page)

    def test_an_active_account_offers_deactivate_and_an_inactive_one_activate(self):
        self.client.force_login(self.admin)
        page = self.client.get("/admin-panel/users").content.decode()
        self.assertIn(f'aria-label="Deactivate {self.cceo.name}"', page)
        self.assertNotIn(f'aria-label="Activate {self.cceo.name}"', page)
        # Nobody deactivates the account they are signed in with.
        self.assertNotIn(f'aria-label="Deactivate {self.admin.name}"', page)

        response = self.client.post(
            f"/admin-panel/users/{self.cceo.id}",
            {"action": "deactivate", "next": "users"},
        )
        self.assertRedirects(
            response, "/admin-panel/users", fetch_redirect_response=False
        )
        self.cceo.refresh_from_db()
        self.assertFalse(self.cceo.is_active)

        page = self.client.get("/admin-panel/users").content.decode()
        self.assertIn(f'aria-label="Activate {self.cceo.name}"', page)
        self.assertNotIn(f'aria-label="Deactivate {self.cceo.name}"', page)
        self.client.post(
            f"/admin-panel/users/{self.cceo.id}",
            {"action": "activate", "next": "users"},
        )
        self.cceo.refresh_from_db()
        self.assertTrue(self.cceo.is_active)

    def test_reset_password_from_the_row_for_staff_and_for_a_partner(self):
        self.client.force_login(self.admin)
        for account in (self.cceo, self.login):
            drawer = self.client.get(
                f"/admin-panel/users/{account.id}?drawer=password"
            ).content.decode()
            self.assertIn("data-reset-password-form", drawer)
            self.assertIn(account.name, drawer)
            response = self.client.post(
                f"/admin-panel/users/{account.id}",
                {
                    "action": "reset_password",
                    "new_password": NEW_PASSWORD,
                    "next": "users",
                },
            )
            self.assertRedirects(
                response, "/admin-panel/users", fetch_redirect_response=False
            )
            account.refresh_from_db()
            self.assertTrue(account.check_password(NEW_PASSWORD))
            self.assertTrue(account.must_change_password)

    def test_a_partner_login_can_be_created_with_a_first_password(self):
        self.client.force_login(self.admin)
        drawer = self.client.get(
            f"/partners/{self.bare.id}/user-setup", HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn('name="password"', drawer)
        self.client.post(
            f"/partners/{self.bare.id}/user-setup",
            {
                "mode": "invite",
                "email": "aa-lead@nologin.test",
                "login_name": "Lead Person",
                "password": NEW_PASSWORD,
            },
            HTTP_HX_REQUEST="true",
        )
        self.bare.refresh_from_db()
        account = self.bare.user
        self.assertEqual(account.email, "aa-lead@nologin.test")
        self.assertTrue(account.is_active)
        self.assertTrue(account.check_password(NEW_PASSWORD))
        self.assertTrue(account.must_change_password)


@override_settings(ALLOWED_HOSTS=["testserver", "localhost"])
class PartnerSplitsItsSchoolsTests(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="ST Region")
        self.district = District.objects.create(
            name="ST District", region=self.region, district_type="primary"
        )
        self.login = _user(
            "st-grace@literacy.test",
            EdifyRole.PARTNER_ADMIN.value,
            staff=False,
            name="Grace Nakato",
        )
        self.partner = Partner.objects.create(
            name="Literacy Works", active_status=True, user=self.login
        )
        self.other_login = _user(
            "st-other@other.test", EdifyRole.PARTNER_ADMIN.value, staff=False
        )
        self.other = Partner.objects.create(
            name="Other Org", active_status=True, user=self.other_login
        )
        self.admin = _user("st-admin@edify.test", EdifyRole.ADMIN.value)
        self.cceo = _user("st-cceo@edify.test", EdifyRole.CCEO.value)
        self.peter = PartnerMember.objects.create(
            partner=self.partner, name="Peter Okello", role="staff"
        )
        self.mary = PartnerMember.objects.create(
            partner=self.partner, name="Mary Akello", role="volunteer"
        )
        self.schools = [self._school(code) for code in ("A", "B", "C")]
        for school in self.schools:
            PartnerAssignment.objects.create(
                school=school, partner=self.partner, status="assigned"
            )
        # Not this organisation's: handed to another, and taken back.
        self.strange = self._school("X")
        PartnerAssignment.objects.create(
            school=self.strange, partner=self.other, status="assigned"
        )
        self.released = self._school("R")
        PartnerAssignment.objects.create(
            school=self.released,
            partner=self.partner,
            status=PartnerAssignment.RELEASED_STATUSES[0],
        )

    def _school(self, code: str):
        return School.objects.create(
            school_id=f"ST-{code}",
            name=f"ST School {code}",
            region=self.region,
            district=self.district,
        )

    def _ids(self, *indexes):
        return [self.schools[i].id for i in indexes]

    def test_a_partner_onboards_its_own_team_member(self):
        member = add_member(
            self.partner.id, {"name": "New Person", "role": "staff"}, self.login
        )
        self.assertEqual(member.partner_id, self.partner.id)
        with self.assertRaises(Forbidden):
            add_member(self.other.id, {"name": "Intruder"}, self.login)

    def test_the_partner_gives_its_schools_to_a_team_member(self):
        result = school_team.set_member_schools(
            self.partner.id, self.peter.id, self._ids(0, 1), self.login
        )
        self.assertEqual(result["schools"], 2)
        self.assertEqual(
            {
                sid: member.name
                for sid, member in school_team.members_by_school(self.partner).items()
            },
            {self.schools[0].id: "Peter Okello", self.schools[1].id: "Peter Okello"},
        )
        self.assertEqual(school_team.school_counts(self.partner), {self.peter.id: 2})
        self.assertTrue(
            AuditLog.objects.filter(
                action="partner.school_team_member_set", subject_id=self.partner.id
            ).exists()
        )

    def test_a_school_moves_between_members_and_an_unticked_one_is_cleared(self):
        school_team.set_member_schools(
            self.partner.id, self.peter.id, self._ids(0, 1), self.login
        )
        # Mary takes B (Peter's) and C; Peter keeps A.
        school_team.set_member_schools(
            self.partner.id, self.mary.id, self._ids(1, 2), self.login
        )
        self.assertEqual(
            school_team.school_counts(self.partner),
            {self.peter.id: 1, self.mary.id: 2},
        )
        # Peter's list saved with nothing ticked: A goes back to nobody.
        school_team.set_member_schools(self.partner.id, self.peter.id, [], self.login)
        self.assertEqual(school_team.school_counts(self.partner), {self.mary.id: 2})
        self.assertEqual(
            PartnerSchoolMember.objects.filter(partner=self.partner).count(), 2
        )

    def test_only_schools_the_organisation_holds_can_be_given(self):
        for stranger in (self.strange, self.released):
            with self.assertRaises(BadRequest):
                school_team.set_member_schools(
                    self.partner.id, self.peter.id, [stranger.id], self.login
                )
        self.assertFalse(PartnerSchoolMember.objects.exists())

    def test_only_the_organisation_or_the_admin_makes_the_split(self):
        for outsider in (self.cceo, self.other_login):
            with self.assertRaises(Forbidden):
                school_team.set_member_schools(
                    self.partner.id, self.peter.id, self._ids(0), outsider
                )
        school_team.set_member_schools(
            self.partner.id, self.peter.id, self._ids(0), self.admin
        )
        self.assertEqual(
            school_team.member_for(self.partner, self.schools[0].id), "Peter Okello"
        )

    def test_unfinished_work_that_names_nobody_takes_the_members_name(self):
        unnamed = Activity.objects.create(
            school=self.schools[0],
            assigned_partner_id=self.partner.id,
            delivery_type="partner",
            activity_type="school_visit",
            status="scheduled",
        )
        named = Activity.objects.create(
            school=self.schools[0],
            assigned_partner_id=self.partner.id,
            delivery_type="partner",
            activity_type="school_visit",
            status="scheduled",
            delivery_contact_name="Mary Akello",
        )
        school_team.set_member_schools(
            self.partner.id, self.peter.id, self._ids(0), self.login
        )
        unnamed.refresh_from_db()
        named.refresh_from_db()
        self.assertEqual(unnamed.delivery_contact_name, "Peter Okello")
        self.assertEqual(named.delivery_contact_name, "Mary Akello")

    def test_the_profile_shows_who_looks_after_each_school(self):
        school_team.set_member_schools(
            self.partner.id, self.peter.id, self._ids(0), self.login
        )
        rows = {r["school"].id: r for r in profile_lists.visit_schools(self.partner)}
        self.assertEqual(rows[self.schools[0].id]["team_member"], "Peter Okello")
        self.assertEqual(rows[self.schools[1].id]["team_member"], "")

        self.client.force_login(self.login)
        page = self.client.get(f"/partners/{self.partner.id}").content.decode()
        self.assertIn("Team Member", page)
        self.assertIn(f'data-member-schools="{self.peter.id}">1<', page)
        self.assertIn('aria-label="Assign schools to Peter Okello"', page)

    def test_the_drawer_lists_the_held_schools_and_saves_the_ticked_ones(self):
        school_team.set_member_schools(
            self.partner.id, self.mary.id, self._ids(2), self.login
        )
        self.client.force_login(self.login)
        url = f"/partners/{self.partner.id}/members/{self.peter.id}/schools"
        drawer = self.client.get(url, HTTP_HX_REQUEST="true").content.decode()
        for school in self.schools:
            self.assertIn(school.name, drawer)
        self.assertNotIn(self.strange.name, drawer)
        self.assertNotIn(self.released.name, drawer)
        self.assertIn("now with Mary Akello", drawer)

        response = self.client.post(
            url, {"school_ids": self._ids(0, 2)}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response["HX-Redirect"], f"/partners/{self.partner.id}")
        self.assertEqual(school_team.school_counts(self.partner), {self.peter.id: 2})

    def test_an_officer_cannot_open_or_save_the_split(self):
        self.client.force_login(self.cceo)
        url = f"/partners/{self.partner.id}/members/{self.peter.id}/schools"
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(
            self.client.post(url, {"school_ids": self._ids(0)}).status_code, 403
        )
        self.assertFalse(PartnerSchoolMember.objects.exists())
