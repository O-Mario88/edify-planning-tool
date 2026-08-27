"""A job that stops must reach somebody without them opening a page.

SchedulerHealthService computed all of this correctly and was read by two
things: the System Health page, and a CLI command no deploy config invokes.
`docs/runbooks.md` names the consequence — "a scheduler that can stop without
anyone noticing until a job is stale needs its own liveness signal".

What these tests hold is the push, the deduplication, and the recovery. The
deduplication matters as much as the alert: a job broken for a week runs this
watchdog forty-eight times a day, and a notice per run is how people learn to
stop reading notices.
"""

from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.notifications.models import Notification
from apps.realtime.jobs import SCHEDULER_JOB_UNHEALTHY, _do_scheduler_watchdog

User = get_user_model()


def _health(job_name: str, severity: str, status: str) -> dict:
    return {
        "job_name": job_name,
        "severity": severity,
        "status": status,
        "last_successful": None,
        "failure_count": 2 if severity == "critical" else 0,
        "last_error": "boom" if status == "failed" else None,
    }


class SchedulerWatchdogTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            email="watchdog-admin@edify.test",
            name="Watchdog Admin",
            roles=["Admin"],
            active_role="Admin",
            password="password123",
            is_active=True,
        )

    def _run(self, healths):
        with mock.patch(
            "apps.realtime.registry.SchedulerHealthService.all_jobs_health",
            return_value=healths,
        ):
            return _do_scheduler_watchdog()

    def _open_notices(self, job_name="outbox_drain"):
        return Notification.objects.filter(
            source_event_type=SCHEDULER_JOB_UNHEALTHY,
            context_type="scheduled_job",
            context_id=job_name,
            resolved_at__isnull=True,
        )

    def test_a_failed_job_reaches_an_admin(self):
        raised = self._run([_health("outbox_drain", "critical", "failed")])
        self.assertEqual(raised, 1)
        notice = self._open_notices().first()
        self.assertIsNotNone(notice, "a failed background job notified nobody")
        self.assertEqual(notice.recipient_id, self.admin.id)
        self.assertIn("outbox_drain", notice.title)

    def test_an_overdue_job_reaches_an_admin_at_a_lower_priority(self):
        self._run([_health("daily_digest", "high", "overdue")])
        notice = self._open_notices("daily_digest").first()
        self.assertIsNotNone(notice)
        self.assertEqual(
            notice.priority,
            "normal",
            "late is not the same as failed; starting at urgent leaves the "
            "escalation sweep nowhere to go",
        )

    def test_a_healthy_job_notifies_nobody(self):
        self.assertEqual(self._run([_health("outbox_drain", "ok", "healthy")]), 0)
        self.assertFalse(Notification.objects.exists())

    def test_a_job_broken_for_a_week_does_not_add_a_notice_every_run(self):
        broken = [_health("outbox_drain", "critical", "failed")]
        for _ in range(5):
            self._run(broken)
        self.assertEqual(
            self._open_notices().count(),
            1,
            "the watchdog stacked a notice per run — forty-eight a day for one "
            "broken job is how a queue stops being read",
        )

    def test_recovery_closes_the_notice(self):
        self._run([_health("outbox_drain", "critical", "failed")])
        self.assertEqual(self._open_notices().count(), 1)

        self._run([_health("outbox_drain", "ok", "healthy")])
        self.assertEqual(
            self._open_notices().count(),
            0,
            "the job recovered and its notice stayed open — a notice that "
            "outlives its condition is what taught people to ignore them",
        )

    def test_no_admin_is_logged_rather_than_swallowed(self):
        User.objects.filter(id=self.admin.id).delete()
        with self.assertLogs("edify.jobs", level="ERROR") as logs:
            self._run([_health("outbox_drain", "critical", "failed")])
        self.assertIn("no active Admin", "\n".join(logs.output))

    def test_it_is_registered_with_a_runnable_function(self):
        """A registry entry with no function stops the whole scheduler booting."""
        from apps.realtime.registry import JOB_REGISTRY

        self.assertIn("scheduler_watchdog", {spec.name for spec in JOB_REGISTRY})

        import apps.realtime.jobs as jobs_module

        self.assertTrue(callable(jobs_module.scheduler_watchdog_job))
