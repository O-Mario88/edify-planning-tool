from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import User
from apps.core.rbac import EdifyRole

from .models import AnalyticsReportSchedule
from .report_delivery import deliver_due_schedules


class AnalyticsReportDeliveryTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="director@example.org",
            name="Director",
            roles=[EdifyRole.COUNTRY_DIRECTOR.value],
            active_role=EdifyRole.COUNTRY_DIRECTOR.value,
            password="testpassword",
        )
        self.schedule = AnalyticsReportSchedule.objects.create(
            user=self.user,
            frequency="weekly",
            categories=["targets"],
            next_run_at=timezone.now(),
        )

    @patch("apps.analytics.report_delivery.workflow_message")
    @patch(
        "apps.analytics.report_delivery.AnalyticsDashboardService.get_analytics_data"
    )
    def test_due_schedule_sends_scoped_inbox_digest_and_advances_next_run(
        self, analytics_data, workflow_message
    ):
        analytics_data.return_value = {
            "kpi_strip_items": [
                {
                    "label": "Overall Target Achievement",
                    "value": "82%",
                    "helper": "vs last period",
                },
                {"label": "SSA Average", "value": "7.4", "helper": "confirmed"},
            ]
        }
        workflow_message.return_value = object()
        before = self.schedule.next_run_at

        self.assertEqual(deliver_due_schedules(), 1)

        self.schedule.refresh_from_db()
        self.assertGreater(self.schedule.next_run_at, before)
        self.assertIsNotNone(self.schedule.last_delivered_at)
        payload = workflow_message.call_args.kwargs
        self.assertEqual(payload["recipient_ids"], [str(self.user.id)])
        self.assertIn("Overall Target Achievement: 82%", payload["body"])
        self.assertNotIn("SSA Average", payload["body"])
