from django.test import TestCase
from django.urls import reverse
from apps.accounts.models import User, StaffProfile, UserStatus, StaffSetupCandidate
from apps.core.rbac import EdifyRole
from apps.geography.models import Region, District, SubCounty


class AdminUserOperationsTest(TestCase):
    def setUp(self):
        # Setup geography
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)
        self.district_2 = District.objects.create(name="Wakiso", region=self.region)
        self.sub_county = SubCounty.objects.create(
            name="SubCounty A", district=self.district
        )

        # Setup administrative users
        self.admin = User.objects.create_user(
            email="admin@edify.test",
            name="Admin User",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="pwd",
            is_active=True,
        )
        self.client.force_login(self.admin)

    def test_admin_user_management_views_and_actions(self):
        # 1. Create a new user from Admin panel (password is now required)
        url = reverse("frontend:admin_users")
        create_data = {
            "action": "create",
            "name": "New Staff Member",
            "email": "newstaff@edify.test",
            "phone": "+256111111",
            "role": EdifyRole.CCEO.value,
            "primary_district": self.district.id,
            "additional_districts": [self.district_2.id],
            "password": "StrongPassword1!",
        }
        res = self.client.post(url, create_data)
        self.assertEqual(res.status_code, 302)

        # Verify created — user is active and must_change_password is True
        user = User.objects.get(email="newstaff@edify.test")
        self.assertEqual(user.name, "New Staff Member")
        self.assertEqual(user.active_role, EdifyRole.CCEO.value)
        self.assertTrue(user.is_active)
        self.assertTrue(user.must_change_password)
        self.assertTrue(user.check_password("StrongPassword1!"))

        # Verify StaffProfile and geography links created
        sp = StaffProfile.objects.get(user=user)
        self.assertEqual(sp.primary_district_id, self.district.id)
        from apps.accounts.models import StaffGeographyAssignment

        geo_links = list(
            StaffGeographyAssignment.objects.filter(staff=sp).values_list(
                "district_id", flat=True
            )
        )
        self.assertIn(self.district.id, geo_links)
        self.assertIn(self.district_2.id, geo_links)

        # 2. Edit user via detail view POST edit action
        detail_url = reverse("frontend:admin_user_detail", kwargs={"user_id": user.id})
        edit_data = {
            "action": "edit",
            "name": "Updated Staff Name",
            "email": "updatedstaff@edify.test",
            "phone": "+256222222",
            "role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            "primary_district": self.district_2.id,
            "additional_districts": [self.district.id],
        }
        res = self.client.post(detail_url, edit_data)
        self.assertEqual(res.status_code, 302)

        user.refresh_from_db()
        self.assertEqual(user.name, "Updated Staff Name")
        self.assertEqual(user.email, "updatedstaff@edify.test")
        self.assertEqual(user.active_role, EdifyRole.COUNTRY_PROGRAM_LEAD.value)

        sp.refresh_from_db()
        self.assertEqual(sp.primary_district_id, self.district_2.id)
        geo_links_updated = list(
            StaffGeographyAssignment.objects.filter(staff=sp).values_list(
                "district_id", flat=True
            )
        )
        self.assertIn(self.district.id, geo_links_updated)
        self.assertIn(self.district_2.id, geo_links_updated)

        # 3. Deactivate user
        res = self.client.post(detail_url, {"action": "deactivate"})
        self.assertEqual(res.status_code, 302)
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertEqual(user.status, "disabled")

        # 4. Activate user
        res = self.client.post(detail_url, {"action": "activate"})
        self.assertEqual(res.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.status, "active")

        # 5. Invite User (sends mailer & sets pending status)
        res = self.client.post(detail_url, {"action": "invite"})
        self.assertEqual(res.status_code, 302)
        user.refresh_from_db()
        self.assertEqual(user.status, "pending_invited")

        # 6. Soft-delete user
        res = self.client.post(detail_url, {"action": "delete"})
        self.assertEqual(res.status_code, 302)
        # Verify user is soft-deleted (deleted_at is set)
        user_deleted = User.all_objects.get(id=user.id)
        self.assertIsNotNone(user_deleted.deleted_at)

    def test_auto_create_user_from_school_upload(self):
        # Mock school csv file row structure
        # Salesforce account owner is a new, unmatched name
        from collections import namedtuple

        Row = namedtuple(
            "Row",
            [
                "school_id",
                "name",
                "school_type",
                "district_name",
                "sub_county_name",
                "enrollment",
                "phone",
                "contact_person",
                "address",
                "director_name",
                "headteacher_name",
                "account_owner_name",
                "raw_data",
            ],
        )

        row = Row(
            school_id="SCH-NEW-99",
            name="New Upload School",
            school_type="Client",
            district_name="Kampala",
            sub_county_name="SubCounty A",
            enrollment=120,
            phone="0777...",
            contact_person="Director Person",
            address="Kampala Road",
            director_name="Director",
            headteacher_name="Headteacher",
            account_owner_name="Grace Mwesigwa",  # Unmatched CCEO
            raw_data={"last_enrollment_date": "2026-01-01"},
        )

        from apps.schools.upload_service import _auto_create_user_from_upload

        # Verify user automatically created
        profile_id = _auto_create_user_from_upload("Grace Mwesigwa")
        self.assertIsNotNone(profile_id)

        user = User.objects.get(name="Grace Mwesigwa")
        self.assertEqual(user.status, UserStatus.PENDING_INVITED)
        self.assertFalse(user.is_active)
        self.assertTrue(user.email.startswith("pending.grace.mwesigwa"))

        # Verify StaffSetupCandidate was queued
        candidate = StaffSetupCandidate.objects.get(normalized_name="grace mwesigwa")
        self.assertEqual(candidate.matched_user_id, user.id)

    def test_create_user_with_temporary_password(self):
        # Test creation with valid temporary password from front-end admin view
        url = reverse("frontend:admin_users")
        create_data = {
            "action": "create",
            "name": "Temp Pwd Staff",
            "email": "temppwd@edify.test",
            "phone": "+256333333",
            "role": EdifyRole.CCEO.value,
            "primary_district": self.district.id,
            "password": "TemporaryPassword123!",
        }
        res = self.client.post(url, create_data)
        self.assertEqual(res.status_code, 302)

        # Verify user created and active
        user = User.objects.get(email="temppwd@edify.test")
        self.assertEqual(user.name, "Temp Pwd Staff")
        self.assertTrue(user.is_active)
        self.assertEqual(user.status, "active")
        self.assertIsNotNone(user.password_set_at)
        self.assertTrue(user.check_password("TemporaryPassword123!"))

        # Test creation with invalid temporary password (too weak)
        weak_data = {
            "action": "create",
            "name": "Weak Pwd Staff",
            "email": "weakpwd@edify.test",
            "phone": "+256444444",
            "role": EdifyRole.CCEO.value,
            "primary_district": self.district.id,
            "password": "123",
        }
        res_weak = self.client.post(url, weak_data)
        self.assertEqual(res_weak.status_code, 302)
        # Verify user was NOT created
        self.assertFalse(User.objects.filter(email="weakpwd@edify.test").exists())

        # Test service layer API creation directly
        from apps.admin_users import services
        from apps.accounts.jwt import AuthPrincipal

        principal = AuthPrincipal(
            user=self.admin,
            user_id=self.admin.id,
            email=self.admin.email,
            name=self.admin.name,
            roles=self.admin.roles,
            active_role=self.admin.active_role,
            staff_profile_id=None,
        )

        api_data = {
            "name": "API Temp Pwd Staff",
            "email": "api_temppwd@edify.test",
            "phone": "+256555555",
            "role": EdifyRole.CCEO.value,
            "primaryDistrictId": self.district.id,
            "additionalDistrictIds": [self.district_2.id],
            "password": "API_TemporaryPassword123!",
        }
        res_api = services.create(api_data, principal)
        self.assertIsNone(res_api["inviteToken"])

        api_user = User.objects.get(email="api_temppwd@edify.test")
        self.assertEqual(api_user.name, "API Temp Pwd Staff")
        self.assertTrue(api_user.is_active)
        self.assertEqual(api_user.status, "active")
        self.assertTrue(api_user.check_password("API_TemporaryPassword123!"))

        # Verify multiple districts mapped via service
        api_sp = StaffProfile.objects.get(user=api_user)
        self.assertEqual(api_sp.primary_district_id, self.district.id)
        from apps.accounts.models import StaffGeographyAssignment

        api_geo_links = list(
            StaffGeographyAssignment.objects.filter(staff=api_sp).values_list(
                "district_id", flat=True
            )
        )
        self.assertIn(self.district.id, api_geo_links)
        self.assertIn(self.district_2.id, api_geo_links)

    def test_account_lockout_after_failed_logins(self):
        """N failed login attempts trigger a TEMPORARY lock (the "safer
        enterprise default" — Issue 3 of the audit: no permanent lock from a
        single burst, no admin notification for an ordinary first lock
        cycle). See test_repeated_lockout_cycles_escalate_and_notify_admin
        for the escalation path, which IS still admin-notified."""
        from django.conf import settings

        # Create a target user who will be locked out
        target = User.objects.create_user(
            email="lockme@edify.test",
            name="Lock Target",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="CorrectPassword1!",
            is_active=True,
            status="active",
        )

        # Log out admin first
        self.client.logout()

        max_attempts = getattr(settings, "AUTH_MAX_FAILED_LOGINS", 10)

        # Attempt wrong password max_attempts times
        for i in range(max_attempts):
            res = self.client.post(
                "/login", {"email": "lockme@edify.test", "password": "WrongPassword"}
            )
            self.assertEqual(res.status_code, 200)  # stays on login page

        # Verify the account is temporarily locked (auto-expiring, not
        # escalated) — a single burst never triggers a permanent lock.
        target.refresh_from_db()
        self.assertIsNotNone(target.locked_until)
        self.assertFalse(target.lockout_escalated)
        self.assertEqual(target.lockout_cycle_count, 1)

        # Verify login is blocked even with correct password while locked —
        # SEC-02: the public response must be the SAME generic message a
        # wrong password or unknown email gets, not a "locked" disclosure.
        res = self.client.post(
            "/login", {"email": "lockme@edify.test", "password": "CorrectPassword1!"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Invalid email or password")
        self.assertNotContains(res, "locked")

        from apps.audit.models import AuditLog

        self.assertTrue(
            AuditLog.objects.filter(
                action="auth.login_failed", reason="account_locked"
            ).exists()
        )

    def test_repeated_lockout_cycles_escalate_and_notify_admin(self):
        """AUTH_LOCKOUT_ESCALATION_COUNT separate lock cycles within the
        escalation window escalate to admin-required unlock AND notify
        admins — the behavior the old "permanent lock on first burst"
        implementation used to apply to every single lockout."""
        from apps.accounts.lockout_service import AuthenticationLockoutService
        from apps.notifications.models import Notification
        from django.conf import settings
        from django.utils import timezone
        from datetime import timedelta

        target = User.objects.create_user(
            email="repeat-lock@edify.test",
            name="Repeat Lock Target",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="CorrectPassword1!",
            is_active=True,
            status="active",
        )

        escalation_count = getattr(settings, "AUTH_LOCKOUT_ESCALATION_COUNT", 3)
        max_attempts = getattr(settings, "AUTH_MAX_FAILED_LOGINS", 10)

        for cycle in range(escalation_count):
            for _ in range(max_attempts):
                AuthenticationLockoutService.record_failed_attempt(target.id)
            target.refresh_from_db()
            if cycle < escalation_count - 1:
                self.assertFalse(
                    target.lockout_escalated,
                    f"escalated too early at cycle {cycle + 1}",
                )
                # Simulate the temporary lock having expired so the next
                # cycle's attempts are actually evaluated (not just
                # rejected pre-password-check).
                target.locked_until = timezone.now() - timedelta(minutes=1)
                target.save(update_fields=["locked_until"])

        target.refresh_from_db()
        self.assertTrue(target.lockout_escalated)
        self.assertIsNone(target.locked_until)
        self.assertEqual(target.lockout_cycle_count, escalation_count)

        admin_notifications = Notification.objects.filter(
            recipient_id=self.admin.id,
            source_event_type="account_lockout",
        )
        self.assertTrue(admin_notifications.exists())

    def test_admin_password_reset_and_unlock(self):
        """Test that admin can reset a user's password and unlock an account."""
        # Create a user
        target = User.objects.create_user(
            email="resetme@edify.test",
            name="Reset Target",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="OldPassword1!",
            is_active=True,
            status="active",
        )

        detail_url = reverse(
            "frontend:admin_user_detail", kwargs={"user_id": target.id}
        )

        # Admin resets password
        res = self.client.post(
            detail_url,
            {
                "action": "reset_password",
                "new_password": "NewAdminSet1!",
            },
        )
        self.assertEqual(res.status_code, 302)

        target.refresh_from_db()
        self.assertTrue(target.check_password("NewAdminSet1!"))
        self.assertTrue(target.must_change_password)
        self.assertEqual(target.failed_login_count, 0)
        self.assertIsNone(target.locked_until)

        # Simulate an escalated lockout (admin-required unlock).
        target.lockout_escalated = True
        target.lockout_cycle_count = 3
        target.locked_until = None
        target.save(
            update_fields=["lockout_escalated", "lockout_cycle_count", "locked_until"]
        )

        # Admin unlocks
        res = self.client.post(detail_url, {"action": "unlock"})
        self.assertEqual(res.status_code, 302)

        target.refresh_from_db()
        self.assertIsNone(target.locked_until)
        self.assertEqual(target.failed_login_count, 0)
        self.assertFalse(target.lockout_escalated)
        self.assertEqual(target.lockout_cycle_count, 0)

    def test_admin_manual_lock(self):
        """An admin can explicitly lock an account (e.g. a suspected
        compromise) without waiting for failed-login attempts to trigger
        it — this always escalates immediately (admin-required unlock),
        never a mere temporary lock."""
        target = User.objects.create_user(
            email="manuallock@edify.test",
            name="Manual Lock Target",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="Password1!",
            is_active=True,
            status="active",
        )
        detail_url = reverse(
            "frontend:admin_user_detail", kwargs={"user_id": target.id}
        )

        res = self.client.post(
            detail_url, {"action": "lock", "reason": "Suspected compromised credential"}
        )
        self.assertEqual(res.status_code, 302)

        target.refresh_from_db()
        self.assertTrue(target.lockout_escalated)

        # Login must be blocked even with the correct password while
        # manually locked — SEC-02: same generic public response as any
        # other rejection, not a "locked" disclosure.
        self.client.logout()
        res = self.client.post(
            "/login", {"email": "manuallock@edify.test", "password": "Password1!"}
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Invalid email or password")
        self.assertNotContains(res, "locked")

    def test_force_change_password_flow(self):
        """Test that a user with must_change_password=True is forced to change password."""
        # Create user with must_change_password=True
        target = User.objects.create_user(
            email="changeme@edify.test",
            name="Change Me",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="TempPassword1!",
            is_active=True,
            status="active",
            must_change_password=True,
        )

        # Log out admin, log in as target
        self.client.logout()
        res = self.client.post(
            "/login", {"email": "changeme@edify.test", "password": "TempPassword1!"}
        )
        # Should redirect to /change-password, not /dashboard
        self.assertEqual(res.status_code, 302)
        self.assertIn("/change-password", res.url)

        # Try to access dashboard — middleware should redirect to /change-password
        res = self.client.get("/dashboard")
        self.assertEqual(res.status_code, 302)
        self.assertIn("/change-password", res.url)

        # GET the change password page
        res = self.client.get("/change-password")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Password Change Required")

        # Submit mismatched passwords
        res = self.client.post(
            "/change-password",
            {
                "new_password": "NewPassword1!",
                "confirm_password": "DifferentPassword1!",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "do not match")

        # Submit weak password
        res = self.client.post(
            "/change-password",
            {
                "new_password": "123",
                "confirm_password": "123",
            },
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "at least 8 characters")

        # Submit valid password
        res = self.client.post(
            "/change-password",
            {
                "new_password": "MyNewSecurePass1!",
                "confirm_password": "MyNewSecurePass1!",
            },
        )
        self.assertEqual(res.status_code, 302)
        self.assertIn("/dashboard", res.url)

        target.refresh_from_db()
        self.assertFalse(target.must_change_password)
        self.assertTrue(target.check_password("MyNewSecurePass1!"))

    def test_create_user_without_password_sends_an_invitation(self):
        """No password means the new user sets their own.

        This page used to REQUIRE a provisioner-chosen plaintext password,
        which made the canonical service's tokenised invitation path
        unreachable from the only surface anyone uses — so whoever created the
        account knew the credential. Omitting the password is now the safer
        path, not an error.
        """
        from apps.accounts.models import UserInvitation

        url = reverse("frontend:admin_users")
        create_data = {
            "action": "create",
            "name": "No Pwd Staff",
            "email": "nopwd@edify.test",
            "phone": "+256999999",
            "role": EdifyRole.CCEO.value,
            "primary_district": self.district.id,
        }
        res = self.client.post(url, create_data)
        self.assertEqual(res.status_code, 302)
        user = User.objects.filter(email="nopwd@edify.test").first()
        self.assertIsNotNone(user)
        self.assertEqual(user.status, "pending_invited")
        self.assertFalse(user.is_active)
        self.assertTrue(UserInvitation.objects.filter(user=user).exists())


class UpdateUserPrivilegeEscalationTest(TestCase):
    """A HumanResources or CountryDirector principal holds USER_MANAGE (the
    same permission that gates user creation/editing) but must never be able
    to grant themselves or anyone else the unrestricted Admin role, or touch
    an existing Admin's account at all — closing a real self/lateral
    privilege-escalation hole found by audit (update_user() previously had
    none of delete_user()'s guard rails)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="admin2@edify.test",
            name="Admin User",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="pwd",
            is_active=True,
        )
        self.hr = User.objects.create_user(
            email="hr@edify.test",
            name="HR User",
            roles=[EdifyRole.HUMAN_RESOURCES.value],
            active_role=EdifyRole.HUMAN_RESOURCES.value,
            password="pwd",
            is_active=True,
        )
        self.cd = User.objects.create_user(
            email="cd@edify.test",
            name="CD User",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="pwd",
            is_active=True,
        )
        self.staffer = User.objects.create_user(
            email="staffer@edify.test",
            name="Ordinary Staffer",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="pwd",
            is_active=True,
        )

    def test_hr_cannot_self_promote_to_admin(self):
        from apps.admin_users.services import update_user
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest) as ctx:
            update_user(self.hr.id, {"role": EdifyRole.ADMIN.value}, self.hr)
        self.assertIn("own role", str(ctx.exception.detail))
        self.hr.refresh_from_db()
        self.assertEqual(self.hr.active_role, EdifyRole.HUMAN_RESOURCES.value)

    def test_cd_cannot_grant_admin_role_to_another_user(self):
        from apps.admin_users.services import update_user
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest) as ctx:
            update_user(self.staffer.id, {"role": EdifyRole.ADMIN.value}, self.cd)
        self.assertIn("Only an Admin can grant", str(ctx.exception.detail))
        self.staffer.refresh_from_db()
        self.assertEqual(self.staffer.active_role, EdifyRole.CCEO.value)

    def test_hr_cannot_edit_an_existing_admin_account(self):
        """Blocks the email-change + forgot-password takeover vector, not
        just direct role escalation."""
        from apps.admin_users.services import update_user
        from apps.core.exceptions import BadRequest

        with self.assertRaises(BadRequest) as ctx:
            update_user(self.admin.id, {"email": "hijacked@edify.test"}, self.hr)
        self.assertIn("Only an Admin", str(ctx.exception.detail))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.email, "admin2@edify.test")

    def test_admin_can_still_grant_admin_role_and_edit_admins(self):
        from apps.admin_users.services import update_user

        update_user(self.staffer.id, {"role": EdifyRole.ADMIN.value}, self.admin)
        self.staffer.refresh_from_db()
        self.assertEqual(self.staffer.active_role, EdifyRole.ADMIN.value)

        update_user(self.admin.id, {"name": "Renamed Admin"}, self.admin)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.name, "Renamed Admin")

    def test_hr_can_still_perform_routine_non_admin_role_change(self):
        """The fix must not block HR/CD's legitimate day-to-day staff role
        management — only the Admin-role and self-role escalation vectors."""
        from apps.admin_users.services import update_user

        update_user(
            self.staffer.id, {"role": EdifyRole.COUNTRY_PROGRAM_LEAD.value}, self.hr
        )
        self.staffer.refresh_from_db()
        self.assertEqual(self.staffer.active_role, EdifyRole.COUNTRY_PROGRAM_LEAD.value)

    def test_frontend_edit_action_enforces_same_guard(self):
        self.client.force_login(self.hr)
        detail_url = reverse(
            "frontend:admin_user_detail", kwargs={"user_id": self.staffer.id}
        )
        res = self.client.post(
            detail_url,
            {
                "action": "edit",
                "name": self.staffer.name,
                "email": self.staffer.email,
                "role": EdifyRole.ADMIN.value,
            },
        )
        self.assertEqual(res.status_code, 302)
        self.staffer.refresh_from_db()
        self.assertEqual(self.staffer.active_role, EdifyRole.CCEO.value)


class AccountLifecycleAuditTest(TestCase):
    """Every account-lifecycle transition must enter the tamper-evident
    audit chain — audit found create/suspend/disable/reactivate/invite were
    all silently missing it (only delete_user() was audited)."""

    def setUp(self):
        self.admin = User.objects.create_user(
            email="audit-admin@edify.test",
            name="Audit Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="pwd",
            is_active=True,
        )
        self.target = User.objects.create_user(
            email="audit-target@edify.test",
            name="Audit Target",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="pwd",
            is_active=True,
        )

    def test_create_suspend_disable_reactivate_are_all_audited(self):
        from apps.admin_users.services import create, suspend, disable, reactivate
        from apps.audit.models import AuditLog

        result = create(
            {
                "email": "newperson@edify.test",
                "name": "New Person",
                "role": EdifyRole.CCEO.value,
                "password": "StrongPassword1!",
            },
            self.admin,
        )
        new_user_id = result["user"]["id"]
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.user_created", subject_id=new_user_id
            ).exists()
        )

        suspend(self.target.id, self.admin)
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.user_suspended", subject_id=self.target.id
            ).exists()
        )

        disable(self.target.id, self.admin)
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.user_disabled", subject_id=self.target.id
            ).exists()
        )
        # Disabling must also revoke live refresh tokens (SEC-03 hygiene).
        from apps.accounts.models import RefreshToken
        from apps.accounts.jwt import issue_token_pair

        tokens = issue_token_pair(self.target.id, self.target.active_role)
        from apps.core.security import hash_token

        disable(self.target.id, self.admin)
        rt = RefreshToken.objects.filter(
            token_hash=hash_token(tokens["refreshToken"])
        ).first()
        if rt:
            self.assertIsNotNone(rt.revoked_at)

        reactivate(self.target.id, self.admin)
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.user_active", subject_id=self.target.id
            ).exists()
        )

    def test_invite_resend_and_revoke_are_audited(self):
        from apps.admin_users.services import resend_invite, revoke_invite
        from apps.audit.models import AuditLog

        resend_invite(self.target.id, self.admin)
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.invite_resent", subject_id=self.target.id
            ).exists()
        )

        revoke_invite(self.target.id, self.admin)
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.invite_revoked", subject_id=self.target.id
            ).exists()
        )

    def test_invite_accepted_is_audited(self):
        from apps.accounts.auth_services import set_password
        from apps.admin_users.services import _create_invitation
        from apps.audit.models import AuditLog

        token = _create_invitation(self.target.id, self.admin.id)
        set_password(token, "BrandNewPassword1!", "BrandNewPassword1!")
        self.assertTrue(
            AuditLog.objects.filter(
                action="auth.invite_accepted", subject_id=self.target.id
            ).exists()
        )

    def test_supervisor_reassignment_is_audited(self):
        from apps.accounts.supervisor_service import assign_supervisor
        from apps.audit.models import AuditLog

        supervisee_profile = StaffProfile.objects.create(
            user=self.target, title=EdifyRole.CCEO.value
        )
        supervisor_user = User.objects.create_user(
            email="pl-supervisor@edify.test",
            name="PL Supervisor",
            roles=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value,
            password="pwd",
            is_active=True,
        )
        supervisor_profile = StaffProfile.objects.create(
            user=supervisor_user, title=EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        assign_supervisor(
            supervisee_profile.id, {"supervisorId": supervisor_profile.id}, self.admin
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="admin.supervisor_reassigned", subject_id=supervisee_profile.id
            ).exists()
        )
