from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.realtime.health import background_automation_health
from apps.realtime.models import ScheduledJobExecution
from apps.realtime.registry import SchedulerHealthService


class CrossProcessSchedulerHealthTests(TestCase):
    @override_settings(ENABLE_BACKGROUND_JOBS=False, IS_PRODUCTION=True)
    def test_web_process_accepts_dedicated_scheduler_execution_evidence(self):
        """Web must keep jobs disabled without declaring the worker absent."""
        with (
            patch.object(
                SchedulerHealthService,
                "is_scheduler_process_alive",
                return_value=True,
            ),
            patch.object(
                SchedulerHealthService,
                "all_jobs_health",
                return_value=[],
            ),
        ):
            checks = background_automation_health()["checks"]

        enabled = next(c for c in checks if c["key"] == "scheduler_enabled")
        heartbeat = next(c for c in checks if c["key"] == "scheduler_heartbeat")
        self.assertEqual(enabled["severity"], "ok")
        self.assertEqual(
            enabled["current_state"], "Dedicated scheduler activity observed"
        )
        self.assertEqual(heartbeat["severity"], "ok")

    @override_settings(ENABLE_BACKGROUND_JOBS=False, IS_PRODUCTION=True)
    def test_production_is_critical_without_worker_execution_evidence(self):
        with patch.object(
            SchedulerHealthService,
            "is_scheduler_process_alive",
            return_value=False,
        ):
            checks = background_automation_health()["checks"]

        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]["key"], "scheduler_enabled")
        self.assertEqual(checks[0]["severity"], "critical")

    def test_twenty_minute_window_covers_fifteen_minute_job_cadence(self):
        ScheduledJobExecution.objects.create(
            job_name="analytics_report_delivery",
            started_at=timezone.now() - timedelta(minutes=16),
            completed_at=timezone.now() - timedelta(minutes=16),
            status="success",
        )

        self.assertTrue(SchedulerHealthService.is_scheduler_process_alive())
        self.assertFalse(
            SchedulerHealthService.is_scheduler_process_alive(stale_after_minutes=10)
        )

    def test_never_run_job_is_healthy_until_its_first_due_time(self):
        ScheduledJobExecution.objects.create(
            job_name="analytics_report_delivery",
            started_at=timezone.now(),
            completed_at=timezone.now(),
            status="success",
        )

        health = SchedulerHealthService.job_health("monthly_work_plan")

        self.assertEqual(health["status"], "scheduled")
        self.assertEqual(health["severity"], "ok")
        self.assertIsNotNone(health["next_due"])

    def test_never_run_job_is_critical_after_its_first_due_time(self):
        ScheduledJobExecution.objects.create(
            job_name="analytics_report_delivery",
            started_at=timezone.now() - timedelta(days=60),
            completed_at=timezone.now() - timedelta(days=60),
            status="success",
        )

        health = SchedulerHealthService.job_health("monthly_work_plan")

        self.assertEqual(health["status"], "never_run")
        self.assertEqual(health["severity"], "critical")
