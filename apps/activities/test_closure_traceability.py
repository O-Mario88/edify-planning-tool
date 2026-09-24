"""One closure, followed from the browser's request to every record it leaves.

The traceability chain the 2026-09-24 audit asked to be proven for one
critical journey: browser action → HTTP request (correlation id) → permission
→ service → database write → audit event → notification → analytics state →
timeline. Close & Lock was chosen because the same audit found its form dead
(D-01), so this is also the proof that the repaired control does the whole
job.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.accounts.models import StaffProfile
from apps.activities.models import (
    Activity,
    ActivityTimelineEvent,
    AnalyticsPublishRecord,
)
from apps.audit.models import AuditLog
from apps.evidence.models import EvidenceRecord
from apps.geography.models import District, Region
from apps.notifications.models import Notification
from apps.schools.models import School

TRACE = "trace-closure-2026-09-24"


class ClosureJourneyTraceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_user(
            email="trace-admin@edify.test",
            password="password123",
            name="Trace Admin",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="trace-admin-staff", user=cls.admin)
        cls.officer = User.objects.create_user(
            email="trace-cceo@edify.test",
            password="password123",
            name="Trace Officer",
            roles=["CCEO"],
            active_role="CCEO",
            is_active=True,
        )
        region = Region.objects.create(name="Trace Region")
        district = District.objects.create(name="Trace District", region=region)
        school = School.objects.create(
            school_id="TRACE-1", name="Trace School", region=region, district=district
        )
        # Executed, evidenced, SF ID entered, IA verified, no money moved:
        # everything closure requires.
        cls.activity = Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status="ia_verified",
            salesforce_activity_id="SF-TRACE-1",
            responsible_staff_id=cls.officer.id,
            planned_date=date(2026, 7, 2),
        )
        EvidenceRecord.objects.create(
            activity=cls.activity, kind="visit_form", uri="t.pdf", uploaded_by="x"
        )

    def test_the_close_action_is_traceable_end_to_end(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            f"/activities/{self.activity.id}/closure/close",
            HTTP_X_CORRELATION_ID=TRACE,
        )

        # HTTP: the repaired form's action runs and returns to the workspace,
        # echoing the correlation id the browser sent.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], f"/activities/{self.activity.id}/closure/"
        )
        self.assertEqual(response.headers.get("X-Correlation-Id"), TRACE)

        # Service and database: the activity is closed and locked.
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "closed")

        # Analytics: published only because every requirement was met.
        self.assertEqual(
            AnalyticsPublishRecord.objects.get(activity=self.activity).status,
            "published",
        )

        # Audit: the tamper-evident entry carries the request's correlation id
        # and the acting user.
        entry = AuditLog.objects.get(
            action="activity.closed", subject_id=self.activity.id
        )
        self.assertEqual(entry.correlation_id, TRACE)
        self.assertEqual(entry.actor_id, self.admin.user_id)

        # Timeline and notification: the owner hears about it.
        self.assertTrue(
            ActivityTimelineEvent.objects.filter(activity=self.activity).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                recipient_id=self.officer.id,
                context_type="Activity",
                context_id=self.activity.id,
            ).exists()
        )

    def test_a_refused_close_leaves_no_trace_of_success(self):
        self.activity.status = "completed"  # IA has not verified
        self.activity.save()
        self.client.force_login(self.admin)
        response = self.client.post(
            f"/activities/{self.activity.id}/closure/close",
            HTTP_X_CORRELATION_ID=TRACE,
        )
        self.assertEqual(response.status_code, 302)
        self.activity.refresh_from_db()
        self.assertEqual(self.activity.status, "completed")
        self.assertFalse(
            AuditLog.objects.filter(
                action="activity.closed", subject_id=self.activity.id
            ).exists()
        )
        self.assertFalse(
            AnalyticsPublishRecord.objects.filter(
                activity=self.activity, status="published"
            ).exists()
        )
