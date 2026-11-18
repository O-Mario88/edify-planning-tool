"""The Analytics Publishing Status page lists failures first.

The model has no ordering, so the page listed records in whatever order the
query plan produced (owner, 2026-11-18: failures first). Failed and
recalculation-required records come first, then pending, then published,
anything else last, the oldest first within each. The Go gateway draws the
page in the same order.
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity, AnalyticsPublishRecord


class AnalyticsPublishingOrderTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="publishing-order@edify.test",
            password="password123",
            name="Publishing Order",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="publishing-order-staff", user=cls.user)
        now = timezone.now()
        # Filed so that table order and the page's order disagree.
        for days, status, message in (
            (1, "published", "Published record"),
            (2, "excluded", "Excluded record"),
            (3, "pending", "Pending record"),
            (4, "recalculation_required", "Newer failure"),
            (9, "failed", "Older failure"),
        ):
            activity = Activity.objects.create(activity_type="visit", status="closed")
            record = AnalyticsPublishRecord.objects.create(
                activity=activity, status=status, error_message=message
            )
            AnalyticsPublishRecord.objects.filter(pk=record.pk).update(
                created_at=now - timedelta(days=days)
            )

    def setUp(self):
        self.client.force_login(self.user)

    def test_failures_come_first_then_pending_then_published(self):
        body = self.client.get("/analytics/publishing").content.decode()

        order = [
            body.index(message)
            for message in (
                "Older failure",
                "Newer failure",
                "Pending record",
                "Published record",
                "Excluded record",
            )
        ]
        self.assertEqual(order, sorted(order))
