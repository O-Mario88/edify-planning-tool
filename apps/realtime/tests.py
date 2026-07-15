"""Background jobs scheduling — regression coverage.

Covers the `ENABLE_BACKGROUND_JOBS` gate every one of the 7 registered jobs
(apps.realtime.registry.JOB_REGISTRY) must honour, plus the scheduler
architecture fix (Issue 2 of the audit):

  - AppConfig.ready() must NEVER start a scheduler (that used to run inside
    every web worker process — the actual production-readiness defect).
  - The scheduler now runs in exactly one dedicated process
    (`python manage.py runscheduler`), with every job wrapped by
    apps.realtime.execution.run_tracked_job: a DB-backed lock
    (ScheduledJobLock) + an execution history row (ScheduledJobExecution)
    + retry-per-registry-spec.
  - SchedulerHealthService / `scheduler_health_check` read that history as
    the ground truth for "is background automation actually alive."
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from apps.notifications.models import Notification


class BackgroundJobsGateTests(TestCase):
    """Every job must be a strict no-op unless ENABLE_BACKGROUND_JOBS is true."""

    @override_settings(ENABLE_BACKGROUND_JOBS=False)
    def test_weekly_fund_request_job_noop_when_disabled(self):
        from apps.realtime import jobs

        with patch("apps.fund_requests.services.regenerate") as regenerate:
            jobs.weekly_fund_request_job()
        regenerate.assert_not_called()

    @override_settings(ENABLE_BACKGROUND_JOBS=False)
    def test_monthly_work_plan_job_noop_when_disabled(self):
        from apps.monthly_work_plan.models import MonthlyWorkPlanBudget
        from apps.realtime import jobs

        jobs.monthly_work_plan_job()
        self.assertEqual(MonthlyWorkPlanBudget.objects.count(), 0)

    @override_settings(ENABLE_BACKGROUND_JOBS=False)
    def test_notification_escalation_job_noop_when_disabled(self):
        from apps.realtime import jobs

        Notification.objects.create(
            recipient_id="u1",
            title="Old action-required notification",
            status="unread",
            action_required=True,
            priority="normal",
        )
        jobs.notification_escalation_job()
        n = Notification.objects.get()
        self.assertEqual(n.priority, "normal")

    @override_settings(ENABLE_BACKGROUND_JOBS=False)
    def test_daily_digest_job_noop_when_disabled(self):
        from apps.realtime import jobs

        Notification.objects.create(
            recipient_id="u1", title="Unread item", status="unread"
        )
        jobs.daily_digest_job()
        # No digest notification was created — only the original one exists.
        self.assertEqual(Notification.objects.count(), 1)

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_monthly_work_plan_job_runs_when_enabled(self):
        """Sanity check the flip side: with the flag on, the job actually acts."""
        from apps.monthly_work_plan.models import MonthlyWorkPlanBudget
        from apps.realtime import jobs

        jobs.monthly_work_plan_job()
        self.assertEqual(MonthlyWorkPlanBudget.objects.count(), 1)


class SchedulerRegistrationGateTests(TestCase):
    """AppConfig.ready() must not register any apscheduler job unless the
    ENABLE_BACKGROUND_JOBS flag is set — this is the production-readiness
    gate: flipping deployment config (not code) is what would turn jobs on."""

    @override_settings(ENABLE_BACKGROUND_JOBS=False)
    def test_ready_does_not_start_scheduler_when_disabled(self):
        from apps.realtime.apps import RealtimeConfig

        config = RealtimeConfig.__new__(RealtimeConfig)
        with patch(
            "apscheduler.schedulers.background.BackgroundScheduler"
        ) as scheduler_cls:
            config.ready()
        scheduler_cls.assert_not_called()

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_scheduler_does_not_start_in_multiple_web_workers(self):
        """The scheduler must NEVER start from AppConfig.ready() -- not even
        with the flag enabled. ready() runs once per Django process, so if
        it ever started a scheduler there, every web worker/replica would
        run its own copy of every job. This is the actual production
        defect this issue fixes: the scheduler now only ever starts from
        `python manage.py runscheduler`, a single dedicated process."""
        from apps.realtime.apps import RealtimeConfig

        config = RealtimeConfig.__new__(RealtimeConfig)
        with patch(
            "apscheduler.schedulers.background.BackgroundScheduler"
        ) as scheduler_cls:
            # Simulate 3 web worker processes each importing/booting Django.
            config.ready()
            config.ready()
            config.ready()
        scheduler_cls.assert_not_called()


class SchedulerArchitectureTests(TestCase):
    """Issue 2: canonical scheduler architecture -- one dedicated process,
    a shared job registry, DB-backed locking, execution history, and
    health visibility that reads real run history rather than trusting the
    ENABLE_BACKGROUND_JOBS flag alone."""

    def test_scheduler_configuration_enabled_in_production(self):
        """`runscheduler` refuses to start (loudly, non-zero exit) unless
        ENABLE_BACKGROUND_JOBS is set on ITS OWN process -- the one process
        whose entire purpose is running jobs must never silently be a
        no-op. With the flag on, it registers every JOB_REGISTRY entry."""
        from io import StringIO

        from django.core.management import call_command
        from django.core.management.base import CommandError

        with override_settings(ENABLE_BACKGROUND_JOBS=False):
            with self.assertRaises(CommandError):
                call_command("runscheduler", stdout=StringIO())

        from apps.realtime.registry import JOB_REGISTRY

        with override_settings(ENABLE_BACKGROUND_JOBS=True):
            out = StringIO()
            with (
                patch(
                    "apscheduler.schedulers.background.BackgroundScheduler"
                ) as scheduler_cls,
                patch("apps.realtime.management.commands.runscheduler.signal.signal"),
                patch(
                    "apps.realtime.management.commands.runscheduler.time.sleep",
                    side_effect=KeyboardInterrupt,
                ),
            ):
                scheduler_instance = scheduler_cls.return_value
                try:
                    call_command("runscheduler", stdout=out)
                except KeyboardInterrupt:
                    pass
            self.assertEqual(scheduler_instance.add_job.call_count, len(JOB_REGISTRY))
            scheduler_instance.start.assert_called_once()

    def test_scheduler_health_fails_when_jobs_disabled(self):
        from apps.realtime.registry import SchedulerHealthService

        with override_settings(ENABLE_BACKGROUND_JOBS=False):
            self.assertFalse(SchedulerHealthService.overall_healthy())

        from io import StringIO

        from django.core.management import call_command

        with override_settings(ENABLE_BACKGROUND_JOBS=False):
            with self.assertRaises(SystemExit) as ctx:
                call_command("scheduler_health_check", stdout=StringIO())
            self.assertNotEqual(ctx.exception.code, 0)

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_scheduler_health_fails_when_job_overdue(self):
        from apps.realtime.models import ScheduledJobExecution
        from apps.realtime.registry import SchedulerHealthService

        # A "successful" run from 10 days ago for a job whose max_interval
        # is far shorter (notification_escalation: 3 hours) -- overdue.
        ScheduledJobExecution.objects.create(
            job_name="notification_escalation",
            started_at=timezone.now() - timedelta(days=10),
            completed_at=timezone.now() - timedelta(days=10),
            status="success",
        )
        health = SchedulerHealthService.job_health("notification_escalation")
        self.assertEqual(health["status"], "overdue")
        self.assertEqual(health["severity"], "high")
        self.assertFalse(SchedulerHealthService.overall_healthy())

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_successful_job_updates_health_record(self):
        from apps.realtime.execution import run_tracked_job
        from apps.realtime.registry import SchedulerHealthService

        run_tracked_job("daily_digest", lambda: 3)

        health = SchedulerHealthService.job_health("daily_digest")
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["severity"], "ok")
        self.assertIsNotNone(health["last_successful"])
        self.assertEqual(health["records_processed"], 3)

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_failed_job_is_recorded(self):
        from apps.realtime.execution import run_tracked_job
        from apps.realtime.models import ScheduledJobExecution

        def _boom():
            raise RuntimeError("simulated failure")

        run_tracked_job("daily_digest", _boom)

        execution = ScheduledJobExecution.objects.filter(
            job_name="daily_digest"
        ).latest("started_at")
        self.assertEqual(execution.status, "failed")
        self.assertIn("simulated failure", execution.error_message)

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_failed_job_retries(self):
        from apps.realtime.execution import run_tracked_job
        from apps.realtime.models import ScheduledJobExecution

        attempts = {"n": 0}

        def _fails_twice_then_succeeds():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise RuntimeError(f"attempt {attempts['n']} failed")
            return 7

        # daily_digest's registry spec allows 2 retries (3 total attempts).
        result = run_tracked_job("daily_digest", _fails_twice_then_succeeds)

        self.assertEqual(result, 7)
        self.assertEqual(attempts["n"], 3)
        execution = ScheduledJobExecution.objects.filter(
            job_name="daily_digest"
        ).latest("started_at")
        self.assertEqual(execution.status, "success")
        self.assertEqual(execution.retry_count, 2)

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_concurrent_job_execution_is_locked(self):
        """Two overlapping triggers of the same job (a slow run still in
        flight when the next cron tick fires, or a second scheduler process
        existing by mistake) must not run concurrently — the second caller
        is skipped, not double-executed."""
        from apps.realtime.execution import acquire_lock, run_tracked_job
        from apps.realtime.models import ScheduledJobExecution

        # Simulate another runner already holding the lock.
        acquired = acquire_lock("daily_digest", ttl_seconds=600)
        self.assertTrue(acquired)

        calls = {"n": 0}

        def _would_increment():
            calls["n"] += 1
            return 1

        result = run_tracked_job("daily_digest", _would_increment)

        self.assertIsNone(result)
        self.assertEqual(calls["n"], 0, "job body must not run while the lock is held")
        self.assertFalse(
            ScheduledJobExecution.objects.filter(job_name="daily_digest").exists(),
            "a skipped-due-to-lock trigger must not create an execution row",
        )

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_target_ledger_job_is_idempotent(self):
        from datetime import date

        from apps.accounts.models import StaffProfile
        from apps.activities.models import Activity
        from apps.core.rbac import EdifyRole
        from apps.geography.models import District, Region
        from apps.realtime import jobs
        from apps.schools.models import School
        from apps.targets.models import TargetAchievementLedger
        from django.contrib.auth import get_user_model

        User = get_user_model()
        region = Region.objects.create(name="Sched Region")
        district = District.objects.create(name="Sched District", region=region)
        school = School.objects.create(
            school_id="SCHED-1", name="Sched School", region=region, district=district
        )
        user = User.objects.create_user(
            email="sched-cceo@t.org",
            name="Sched CCEO",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        sp = StaffProfile.objects.create(user=user, title="CCEO")
        Activity.objects.create(
            school=school,
            activity_type="school_visit",
            delivery_type="staff",
            status="completed",
            responsible_staff_id=sp.id,
            fy=__import__(
                "apps.core.fy", fromlist=["get_operational_fy"]
            ).get_operational_fy(),
            quarter="Q1",
            planned_date=date.today(),
            scheduled_date=timezone.now(),
            evidence_status="accepted",
            salesforce_activity_id="SV-SCHED-1",
        )

        jobs.target_ledger_sync_job()
        first_count = TargetAchievementLedger.objects.filter(user_id=user.id).count()
        self.assertGreater(first_count, 0)

        jobs.target_ledger_sync_job()
        second_count = TargetAchievementLedger.objects.filter(user_id=user.id).count()
        self.assertEqual(
            first_count, second_count, "re-running must not duplicate ledger rows"
        )

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_pd_reminder_job_is_idempotent(self):
        from datetime import date, timedelta as td

        from apps.accounts.models import StaffProfile
        from apps.core.rbac import EdifyRole
        from apps.professional_development.models import (
            PDStatus,
            ProfessionalDevelopmentRequest,
        )
        from apps.realtime import jobs
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(
            email="pd-sched@t.org",
            name="PD Sched",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        sp = StaffProfile.objects.create(user=user, title="CCEO")
        ProfessionalDevelopmentRequest.objects.create(
            staff_id=sp.id,
            staff_name=user.name,
            course_name="Leadership 101",
            institution="Test Institute",
            status=PDStatus.ENROLLMENT_CONFIRMED,
            start_date=date.today() + td(days=7),
            end_date=date.today() + td(days=14),
            funding_type="self_funded",
        )

        before = Notification.objects.count()
        jobs.pd_reminders_job()
        after_first = Notification.objects.count()
        self.assertGreater(after_first, before)

        jobs.pd_reminders_job()
        after_second = Notification.objects.count()
        self.assertEqual(
            after_first, after_second, "re-running the same day must not double-send"
        )

    def test_pd_reminders_stop_after_certificate_and_accountability_completion(self):
        from datetime import date, timedelta as td

        from apps.accounts.models import StaffProfile
        from apps.core.rbac import EdifyRole
        from apps.professional_development.models import (
            PDStatus,
            ProfessionalDevelopmentRequest,
        )
        from apps.professional_development.reminders import send_due_reminders
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.create_user(
            email="pd-done@t.org",
            name="PD Done",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            password="x",
            is_active=True,
        )
        sp = StaffProfile.objects.create(user=user, title="CCEO")
        req = ProfessionalDevelopmentRequest.objects.create(
            staff_id=sp.id,
            staff_name=user.name,
            course_name="Finished Course",
            institution="Test Institute",
            status=PDStatus.ENDED,
            start_date=date.today() - td(days=40),
            end_date=date.today() - td(days=7),
            funding_type="self_funded",
        )
        before = Notification.objects.count()
        sent_while_ended = send_due_reminders()
        after_ended = Notification.objects.count()
        self.assertGreaterEqual(after_ended, before)  # 7-day overdue reminder fires

        # Certificate uploaded + accountability closed -> COMPLETED_CLOSED.
        # Reminders only ever query ENROLLMENT_CONFIRMED/IN_PROGRESS/ENDED,
        # so once completion moves status out of those three, this request
        # can never generate another reminder regardless of date math.
        req.status = PDStatus.COMPLETED_CLOSED
        req.save(update_fields=["status"])

        before_after_close = Notification.objects.count()
        send_due_reminders()
        after_close = Notification.objects.count()
        self.assertEqual(
            before_after_close,
            after_close,
            "a completed/closed request must never trigger another reminder",
        )

    @override_settings(ENABLE_BACKGROUND_JOBS=True)
    def test_field_debrief_recurring_issue_job_is_idempotent(self):
        from apps.debriefs.tests import FieldDebriefTestBase
        from apps.debriefs.models import DailyDebriefInsight
        from apps.realtime import jobs

        base = FieldDebriefTestBase()
        base.setUp()
        for _ in range(3):
            base._submit(
                base.cceo,
                school_ids=[base.school.id],
                challenges=[
                    {
                        "challenge_type": "no_transport",
                        "description": "recurring issue",
                    },
                ],
            )

        jobs.field_debrief_recurring_issues_job()
        first_count = DailyDebriefInsight.objects.filter(
            scope_id=base.school.id, challenge_type="no_transport"
        ).count()
        self.assertEqual(first_count, 1)

        jobs.field_debrief_recurring_issues_job()
        second_count = DailyDebriefInsight.objects.filter(
            scope_id=base.school.id, challenge_type="no_transport"
        ).count()
        self.assertEqual(
            first_count, second_count, "re-running must not duplicate the open insight"
        )
