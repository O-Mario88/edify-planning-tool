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
        self.sub_county = SubCounty.objects.create(name="SubCounty A", district=self.district)

        # Setup administrative users
        self.admin = User.objects.create_user(
            email="admin@edify.test", name="Admin User",
            roles=[EdifyRole.ADMIN.value], active_role=EdifyRole.ADMIN.value,
            password="pwd", is_active=True
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
        geo_links = list(StaffGeographyAssignment.objects.filter(staff=sp).values_list("district_id", flat=True))
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
        geo_links_updated = list(StaffGeographyAssignment.objects.filter(staff=sp).values_list("district_id", flat=True))
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
        Row = namedtuple("Row", [
            "school_id", "name", "school_type", "district_name", "sub_county_name",
            "enrollment", "phone", "contact_person", "address", "director_name",
            "headteacher_name", "account_owner_name", "raw_data"
        ])
        
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
            account_owner_name="Grace Mwesigwa", # Unmatched CCEO
            raw_data={"last_enrollment_date": "2026-01-01"}
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
            staff_profile_id=None
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
        api_geo_links = list(StaffGeographyAssignment.objects.filter(staff=api_sp).values_list("district_id", flat=True))
        self.assertIn(self.district.id, api_geo_links)
        self.assertIn(self.district_2.id, api_geo_links)

    def test_account_lockout_after_failed_logins(self):
        """Test that 10 failed login attempts lock the account and notify admins."""
        from apps.notifications.models import Notification
        from django.conf import settings

        # Create a target user who will be locked out
        target = User.objects.create_user(
            email="lockme@edify.test", name="Lock Target",
            roles=[EdifyRole.CCEO.value], active_role=EdifyRole.CCEO.value,
            password="CorrectPassword1!", is_active=True, status="active"
        )

        # Log out admin first
        self.client.logout()

        max_attempts = getattr(settings, "AUTH_MAX_FAILED_LOGINS", 10)

        # Attempt wrong password max_attempts times
        for i in range(max_attempts):
            res = self.client.post("/login", {"email": "lockme@edify.test", "password": "WrongPassword"})
            self.assertEqual(res.status_code, 200)  # stays on login page

        # Verify the account is locked
        target.refresh_from_db()
        self.assertIsNotNone(target.locked_until)

        # Verify admin notification was created
        admin_notifications = Notification.objects.filter(
            recipient_id=self.admin.id,
            source_event_type="account_lockout",
        )
        self.assertTrue(admin_notifications.exists())
        self.assertIn("Account Locked", admin_notifications.first().title)

        # Verify login is blocked even with correct password
        res = self.client.post("/login", {"email": "lockme@edify.test", "password": "CorrectPassword1!"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "locked")

    def test_admin_password_reset_and_unlock(self):
        """Test that admin can reset a user's password and unlock an account."""
        from django.utils import timezone
        from datetime import timedelta

        # Create a user
        target = User.objects.create_user(
            email="resetme@edify.test", name="Reset Target",
            roles=[EdifyRole.CCEO.value], active_role=EdifyRole.CCEO.value,
            password="OldPassword1!", is_active=True, status="active"
        )

        detail_url = reverse("frontend:admin_user_detail", kwargs={"user_id": target.id})

        # Admin resets password
        res = self.client.post(detail_url, {
            "action": "reset_password",
            "new_password": "NewAdminSet1!",
        })
        self.assertEqual(res.status_code, 302)

        target.refresh_from_db()
        self.assertTrue(target.check_password("NewAdminSet1!"))
        self.assertTrue(target.must_change_password)
        self.assertEqual(target.failed_login_count, 0)
        self.assertIsNone(target.locked_until)

        # Simulate lockout
        target.locked_until = timezone.now() + timedelta(days=36500)
        target.save(update_fields=["locked_until"])

        # Admin unlocks
        res = self.client.post(detail_url, {"action": "unlock"})
        self.assertEqual(res.status_code, 302)

        target.refresh_from_db()
        self.assertIsNone(target.locked_until)
        self.assertEqual(target.failed_login_count, 0)

    def test_force_change_password_flow(self):
        """Test that a user with must_change_password=True is forced to change password."""
        # Create user with must_change_password=True
        target = User.objects.create_user(
            email="changeme@edify.test", name="Change Me",
            roles=[EdifyRole.CCEO.value], active_role=EdifyRole.CCEO.value,
            password="TempPassword1!", is_active=True, status="active",
            must_change_password=True,
        )

        # Log out admin, log in as target
        self.client.logout()
        res = self.client.post("/login", {"email": "changeme@edify.test", "password": "TempPassword1!"})
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
        res = self.client.post("/change-password", {
            "new_password": "NewPassword1!",
            "confirm_password": "DifferentPassword1!",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "do not match")

        # Submit weak password
        res = self.client.post("/change-password", {
            "new_password": "123",
            "confirm_password": "123",
        })
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "at least 8 characters")

        # Submit valid password
        res = self.client.post("/change-password", {
            "new_password": "MyNewSecurePass1!",
            "confirm_password": "MyNewSecurePass1!",
        })
        self.assertEqual(res.status_code, 302)
        self.assertIn("/dashboard", res.url)

        target.refresh_from_db()
        self.assertFalse(target.must_change_password)
        self.assertTrue(target.check_password("MyNewSecurePass1!"))

    def test_create_user_without_password_fails(self):
        """Password is now required — creating without one should fail."""
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
        self.assertFalse(User.objects.filter(email="nopwd@edify.test").exists())
