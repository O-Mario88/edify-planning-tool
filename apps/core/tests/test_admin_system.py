from __future__ import annotations

from django.test import TestCase

from apps.accounts.models import Permission, RolePermission, User, StaffProfile
from apps.core.rbac import EdifyRole
from apps.geography.models import Region, District
from apps.notifications.models import Notification
from apps.schools.models import School, UploadBatch


class AdminSystemTestCase(TestCase):
    """Verifies that all 12 priority admin routes render correctly and process actions."""

    def setUp(self):
        # Create administrative user
        self.admin_user = User.objects.create_user(
            email="admin@example.test",
            password="adminpassword123",
            name="Admin User",
            active_role=EdifyRole.ADMIN.value,
        )
        self.client.login(email="admin@example.test", password="adminpassword123")

        # Create basic lookup models
        self.region = Region.objects.create(name="Central Region")
        self.district = District.objects.create(name="Kampala", region=self.region)

        # Create standard user CCEO and profile
        self.cceo_user = User.objects.create_user(
            email="cceo@example.test",
            password="cceopassword123",
            name="CCEO User",
            active_role=EdifyRole.CCEO.value,
        )
        self.cceo_profile = StaffProfile.objects.create(
            user=self.cceo_user, title="CCEO"
        )

        # Create school pending staff matching
        self.school = School.objects.create(
            school_id="SCH-999",
            name="Smoke Test School",
            region=self.region,
            district=self.district,
            account_owner_status="pending",
            account_owner_name_raw="CCEO User",
        )

        # Create notification log
        self.notification = Notification.objects.create(
            recipient_id=self.admin_user.id,
            title="System Alert Test",
            body="Smoke check body details",
            status="unread",
        )

        # Create upload batch
        self.batch = UploadBatch.objects.create(
            uploaded_by=self.admin_user.id,
            file_name="schools_july.xlsx",
            upload_type="schools",
            total_rows=10,
            status="completed",
        )

        # Roles & Permissions Matrix reads real RolePermission rows (no longer
        # a hardcoded role list) — the demo `seed` command populates this in
        # dev/prod, but the test DB only runs migrations, so a role grant must
        # be seeded here for the matrix to have anything to render.
        perm = Permission.objects.create(
            key="dashboard.view", description="View dashboard"
        )
        RolePermission.objects.create(role="CCEO", permission=perm)

    def test_admin_dashboard_renders(self):
        response = self.client.get("/admin-panel")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Admin Dashboard")
        self.assertContains(response, "User Directory Health")

    def test_user_management_renders(self):
        response = self.client.get("/admin-panel/users")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "User Management")
        self.assertContains(response, "admin@example.test")

    def test_roles_permissions_renders(self):
        response = self.client.get("/admin-panel/roles-permissions")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Roles & Permissions Matrix")
        self.assertContains(response, "CCEO")

    def test_staff_setup_queue_renders_and_matches(self):
        response = self.client.get("/admin-panel/staff-setup-queue")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Staff Setup Queue")
        self.assertContains(response, "Smoke Test School")

        # Perform match post action
        post_data = {
            "school_id": self.school.id,
            "staff_id": self.cceo_profile.id,
            "action": "match",
        }
        post_response = self.client.post("/admin-panel/staff-setup-queue", post_data)
        self.assertEqual(post_response.status_code, 302)  # redirect back
        self.school.refresh_from_db()
        self.assertEqual(self.school.account_owner_status, "matched")
        self.assertEqual(self.school.account_owner_id, str(self.cceo_profile.id))

    def test_school_upload_history_renders_and_rollbacks(self):
        response = self.client.get("/admin-panel/school-upload-history")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "School Upload History")
        self.assertContains(response, "schools_july.xlsx")

        # Perform rollback post action
        post_data = {"rollback_id": self.batch.id}
        post_response = self.client.post(
            "/admin-panel/school-upload-history", post_data
        )
        self.assertEqual(post_response.status_code, 302)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, "failed")

    def test_data_quality_center_renders(self):
        response = self.client.get("/admin-panel/data-quality-center")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Quality Center")
        self.assertContains(response, "Clean Schools")
        self.assertContains(response, "Duplicate Risk")

    def test_workflow_rules_renders_and_toggles(self):
        response = self.client.get("/admin-panel/workflow-rules")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Workflow & Automation Rules")
        self.assertContains(response, "School must be clustered before planning")

        # This page is intentionally read-only — no WorkflowRule model exists;
        # the rules above are enforced in code, not toggleable DB rows (a fake
        # toggle used to flash success without persisting anything, and has
        # been removed). A POST here is simply unhandled, not a state change.
        post_data = {"rule_key": "clustered_before_planning"}
        post_response = self.client.post("/admin-panel/workflow-rules", post_data)
        self.assertEqual(post_response.status_code, 200)

    def test_page_access_matrix_renders(self):
        response = self.client.get("/admin-panel/page-access-matrix")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page & Feature Access Matrix")
        # The matrix is built by walking the real URL config for
        # @require_page_permission-wrapped views — "dashboard" is always
        # discovered since /dashboard carries that decorator.
        self.assertContains(response, "Dashboard")

    def test_region_district_setup_renders_and_adds(self):
        response = self.client.get("/admin-panel/region-district-setup")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Geographical Location Setup")
        self.assertContains(response, "Central Region")

        # Add new district
        post_data = {"district_name": "Wakiso", "region_id": self.region.id}
        post_response = self.client.post(
            "/admin-panel/region-district-setup", post_data
        )
        self.assertEqual(post_response.status_code, 302)
        self.assertTrue(District.objects.filter(name="Wakiso").exists())

    def test_notifications_mgmt_renders_and_resends(self):
        response = self.client.get("/admin-panel/notifications-mgmt")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Notification & Alert Logs")
        self.assertContains(response, "System Alert Test")

        # This page is intentionally read-only — apps.notifications has no
        # send/resend/dispatch service, so the fake "resend" action (which
        # used to flash success without sending anything) has been removed.
        # A POST here is simply unhandled, not a state change.
        post_data = {"resend_id": self.notification.id}
        post_response = self.client.post("/admin-panel/notifications-mgmt", post_data)
        self.assertEqual(post_response.status_code, 200)
