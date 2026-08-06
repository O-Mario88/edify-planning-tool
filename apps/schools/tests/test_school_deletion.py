"""Admin school-deletion guard rails.

Deletion is cleanup, never a shortcut around live workflow state: in-flight
activities and unsettled advances block it, history survives the tombstone,
and School.save() side effects (cluster reassignment, data-quality rows)
must not fire — the service writes the tombstone via queryset update().
"""

from __future__ import annotations

from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.audit.models import AuditLog
from apps.core.exceptions import BadRequest, NotFoundError
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import AdvanceRequest
from apps.geography.models import District, Region
from apps.schools.models import School
from apps.schools.services import delete_school
from apps.ssa.models import SsaRecord


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


class SchoolDeletionTest(TestCase):
    def setUp(self):
        self.admin = _user("sdel-admin@edify.test", EdifyRole.ADMIN.value)
        self.cd = _user("sdel-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        region = Region.objects.create(name="Delete Region")
        self.district = District.objects.create(name="Delete District", region=region)
        self.school = School.objects.create(
            school_id="SDEL-1",
            name="Deletable P/S",
            region=region,
            district=self.district,
        )

    def _activity(self, status: str, sf_id: str = "") -> Activity:
        return Activity.objects.create(
            school=self.school,
            activity_type="school_visit",
            status=status,
            planned_date=timezone.now().date() - timedelta(days=10),
            fy="2026",
            salesforce_activity_id=sf_id,
        )

    def test_admin_deletes_school_history_retained(self):
        record = SsaRecord.objects.create(
            school=self.school,
            fy="2026",
            quarter="Q1",
            date_of_ssa=timezone.now(),
            verification_status="confirmed",
        )
        self._activity("closed", sf_id="SV-123")

        delete_school("SDEL-1", self.admin)

        self.school.refresh_from_db()
        self.assertIsNotNone(self.school.deleted_at)
        # History survives the tombstone.
        record.refresh_from_db()
        self.assertIsNone(record.deleted_at)
        # Audit row written.
        row = AuditLog.objects.filter(
            action="admin.school_deleted", subject_id=self.school.id
        ).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.actor_id, self.admin.id)

    def test_non_admin_blocked(self):
        with self.assertRaises(BadRequest):
            delete_school("SDEL-1", self.cd)
        self.school.refresh_from_db()
        self.assertIsNone(self.school.deleted_at)

    def test_in_flight_activity_blocks_deletion(self):
        self._activity("scheduled")
        with self.assertRaises(BadRequest) as ctx:
            delete_school("SDEL-1", self.admin)
        self.assertIn("in flight", str(ctx.exception.detail))
        self.school.refresh_from_db()
        self.assertIsNone(self.school.deleted_at)

    def test_unsettled_advance_blocks_deletion(self):
        activity = self._activity("closed", sf_id="SV-999")
        line = ActivityScheduleCostLine.objects.create(
            activity=activity,
            school=self.school,
            cost_setting_key="transport",
            label="Transport",
            line_item_type="transport",
            unit_cost=80_000,
            quantity=1,
            amount=80_000,
        )
        AdvanceRequest.objects.create(
            activity=activity,
            budget_line=line,
            fy="2026",
            quarter="Q1",
            amount=80_000,
            status="disbursed",
            disbursed_amount=80_000,
        )
        with self.assertRaises(BadRequest) as ctx:
            delete_school("SDEL-1", self.admin)
        self.assertIn("not yet accounted", str(ctx.exception.detail))
        self.school.refresh_from_db()
        self.assertIsNone(self.school.deleted_at)

    def test_double_delete_is_not_found(self):
        delete_school("SDEL-1", self.admin)
        with self.assertRaises(NotFoundError):
            delete_school("SDEL-1", self.admin)


class SchoolDeletionPageTest(TestCase):
    def setUp(self):
        self.admin = _user("sdelp-admin@edify.test", EdifyRole.ADMIN.value)
        self.cd = _user("sdelp-cd@edify.test", EdifyRole.COUNTRY_DIRECTOR.value)
        region = Region.objects.create(name="Page Delete Region")
        district = District.objects.create(name="Page Delete District", region=region)
        self.school = School.objects.create(
            school_id="SDEL-P1",
            name="Page Deletable P/S",
            region=region,
            district=district,
        )

    def test_admin_sees_danger_zone_and_deletes(self):
        client = Client()
        client.force_login(self.admin)
        page = client.get("/schools/SDEL-P1")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Danger Zone")

        response = client.post("/schools/SDEL-P1/delete")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("/schools"))
        self.school.refresh_from_db()
        self.assertIsNotNone(self.school.deleted_at)

        # Gone from the directory and the detail page.
        self.assertNotContains(client.get("/schools"), "SDEL-P1")

    def test_cd_sees_no_danger_zone_and_cannot_delete(self):
        client = Client()
        client.force_login(self.cd)
        page = client.get("/schools/SDEL-P1")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Danger Zone")

        response = client.post("/schools/SDEL-P1/delete", follow=True)
        self.school.refresh_from_db()
        self.assertIsNone(self.school.deleted_at)
        self.assertContains(response, "Only an Admin can delete schools")

    def test_get_on_delete_url_redirects_without_deleting(self):
        client = Client()
        client.force_login(self.admin)
        response = client.get("/schools/SDEL-P1/delete")
        self.assertEqual(response.status_code, 302)
        self.school.refresh_from_db()
        self.assertIsNone(self.school.deleted_at)
