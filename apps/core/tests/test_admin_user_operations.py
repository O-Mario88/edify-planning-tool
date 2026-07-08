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
        # 1. Create a new user from Admin panel
        url = reverse("frontend:admin_users")
        create_data = {
            "action": "create",
            "name": "New Staff Member",
            "email": "newstaff@edify.test",
            "phone": "+256111111",
            "role": EdifyRole.CCEO.value,
            "primary_district": self.district.id,
        }
        res = self.client.post(url, create_data)
        self.assertEqual(res.status_code, 302)

        # Verify created
        user = User.objects.get(email="newstaff@edify.test")
        self.assertEqual(user.name, "New Staff Member")
        self.assertEqual(user.active_role, EdifyRole.CCEO.value)
        self.assertFalse(user.is_active)

        # Verify StaffProfile created
        sp = StaffProfile.objects.get(user=user)
        self.assertEqual(sp.primary_district_id, self.district.id)

        # 2. Edit user via detail view POST edit action
        detail_url = reverse("frontend:admin_user_detail", kwargs={"user_id": user.id})
        edit_data = {
            "action": "edit",
            "name": "Updated Staff Name",
            "email": "updatedstaff@edify.test",
            "phone": "+256222222",
            "role": EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        }
        res = self.client.post(detail_url, edit_data)
        self.assertEqual(res.status_code, 302)

        user.refresh_from_db()
        self.assertEqual(user.name, "Updated Staff Name")
        self.assertEqual(user.email, "updatedstaff@edify.test")
        self.assertEqual(user.active_role, EdifyRole.COUNTRY_PROGRAM_LEAD.value)

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
