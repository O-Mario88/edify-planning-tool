from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.activities.models import Activity
from apps.core.enums import ActivityType
from apps.core.rbac import EdifyRole


class EvidenceCenterContractTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="admin-evidence@example.org",
            name="Evidence Admin",
            roles=[EdifyRole.ADMIN.value],
            active_role=EdifyRole.ADMIN.value,
            password="testpassword",
        )
        self.activity = Activity.objects.create(
            activity_type=ActivityType.SCHOOL_VISIT.value,
            fy="2026",
            quarter="Q1",
            status="completed",
            evidence_status="none",
            responsible_staff_id=self.user.id,
        )
        self.client.login(email=self.user.email, password="testpassword")

    def test_pending_tab_renders_named_nonempty_action(self):
        response = self.client.get(reverse("frontend:evidence_center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Upload evidence")
        self.assertContains(
            response, f'hx-get="/activities/{self.activity.id}/evidence"'
        )
        self.assertNotContains(response, 'hx-get=""')

    def test_tabs_are_url_addressable_and_htmx_returns_workspace(self):
        response = self.client.get(
            reverse("frontend:evidence_center") + "?tab=verified",
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<!DOCTYPE html>")
        self.assertContains(response, 'id="evidence-workspace"')
        self.assertContains(response, 'aria-selected="true"')
