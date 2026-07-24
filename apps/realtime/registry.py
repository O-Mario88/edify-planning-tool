"""ScheduledJobRegistry — the single, central inventory of every periodic
job in the platform (§7.13 / Issue 2 of the audit). Nothing schedules or
reports health from anywhere else; the scheduler process (management command
`runscheduler`), the health-check command, and System Health all read this
same registry.

Add a new periodic task by adding one entry here and one function to
apps.realtime.jobs (or wherever the task lives) -- never by hand-rolling a
second scheduler, a second cron entry, or a second health surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone


@dataclass(frozen=True)
class JobSpec:
    name: str
    description: str
    cron: str  # human-readable cron expression, also fed to APScheduler's CronTrigger
    cron_kwargs: dict  # kwargs for apscheduler.triggers.cron.CronTrigger
    expected_runtime_seconds: int
    max_interval_minutes: (
        int  # longest acceptable gap between successful runs before "overdue"
    )
    idempotent: bool
    idempotency_note: str
    retryable: bool
    max_retries: int


# ── The complete inventory ───────────────────────────────────────────────────
JOB_REGISTRY: list[JobSpec] = [
    JobSpec(
        name="weekly_fund_request",
        description="Upserts weekly draft FundRequest for the upcoming Mon-Sun.",
        cron="Fri 06:00 Africa/Kampala",
        cron_kwargs={"day_of_week": "fri", "hour": 6},
        expected_runtime_seconds=30,
        max_interval_minutes=60 * 24 * 8,  # weekly + 1 day grace
        idempotent=True,
        idempotency_note="fund_requests.services.regenerate() upserts by (week, owner) — safe to re-run.",
        retryable=True,
        max_retries=3,
    ),
    JobSpec(
        name="monthly_work_plan",
        description="Generates next month's MonthlyWorkPlanBudget draft envelope.",
        cron="25th 06:00 Africa/Kampala",
        cron_kwargs={"day": 25, "hour": 6},
        expected_runtime_seconds=15,
        max_interval_minutes=60 * 24 * 32,  # monthly + a few days grace
        idempotent=True,
        idempotency_note="update_or_create keyed on (country_id, month_key) — safe to re-run.",
        retryable=True,
        max_retries=3,
    ),
    JobSpec(
        name="notification_escalation",
        description="Escalates stale action-required notifications past a 48h SLA.",
        cron="hourly :00 Africa/Kampala",
        cron_kwargs={"minute": 0},
        expected_runtime_seconds=10,
        max_interval_minutes=180,  # 3 missed hourly runs
        idempotent=True,
        idempotency_note="Re-running only re-escalates already-urgent rows to the same state — no-op on repeat.",
        retryable=True,
        max_retries=2,
    ),
    JobSpec(
        name="daily_digest",
        description="One digest notification per user with unread notifications.",
        cron="daily 07:30 Africa/Kampala",
        cron_kwargs={"hour": 7, "minute": 30},
        expected_runtime_seconds=30,
        max_interval_minutes=60 * 30,  # 30h grace
        idempotent=True,
        idempotency_note="Deduped per calendar day via a deterministic source_event_id.",
        retryable=True,
        max_retries=2,
    ),
    JobSpec(
        name="target_ledger_sync",
        description=(
            "Rebuilds TargetAchievementLedger for every active CCEO/PL so My "
            "Targets/Team Targets/CD Analytics never show a stale ledger "
            "between page visits (the audit's 'ledger staleness' finding)."
        ),
        cron="every 30 min Africa/Kampala",
        cron_kwargs={"minute": "*/30"},
        expected_runtime_seconds=120,
        max_interval_minutes=90,
        idempotent=True,
        idempotency_note="TargetAchievementService.rebuild() is get_or_create per (user, area, source) — safe to re-run.",
        retryable=True,
        max_retries=2,
    ),
    JobSpec(
        name="pd_reminders",
        description="Sends due Professional Development pre-course/in-progress/overdue reminders.",
        cron="daily 06:30 Africa/Kampala",
        cron_kwargs={"hour": 6, "minute": 30},
        expected_runtime_seconds=30,
        max_interval_minutes=60 * 30,
        idempotent=True,
        idempotency_note="ProfessionalDevelopmentReminderLog uniqueness on (request, key, day) blocks double-sends.",
        retryable=True,
        max_retries=2,
    ),
    JobSpec(
        name="escalation_sla_sweep",
        description="Re-notifies the RVP about CD escalations past their severity SLA.",
        cron="daily 07:00 Africa/Kampala",
        cron_kwargs={"hour": 7, "minute": 0},
        expected_runtime_seconds=15,
        max_interval_minutes=60 * 30,
        idempotent=True,
        idempotency_note="Re-notification is intentionally repeated daily while an escalation stays overdue; resolving it stops the sweep.",
        retryable=True,
        max_retries=2,
    ),
    JobSpec(
        name="field_debrief_recurring_issues",
        description="Scans recent Field Debriefs for recurring cross-team/cross-country issues.",
        cron="daily 05:30 Africa/Kampala",
        cron_kwargs={"hour": 5, "minute": 30},
        expected_runtime_seconds=60,
        max_interval_minutes=60 * 30,
        idempotent=True,
        idempotency_note="RecurringIssueDetectionService.scan() updates the existing open insight instead of duplicating.",
        retryable=True,
        max_retries=2,
    ),
    JobSpec(
        name="weekly_debrief_reports",
        description="Generates Monday-morning PL Weekly Team Debrief Report drafts for the closed Mon-Sun week.",
        cron="weekly Mon 06:00 Africa/Kampala",
        cron_kwargs={"day_of_week": "mon", "hour": 6, "minute": 0},
        expected_runtime_seconds=120,
        max_interval_minutes=60 * 24 * 8,
        idempotent=True,
        idempotency_note="Draft reports regenerate in place; finalized reports are never overwritten (a rerun creates a new version only when data changed and the owner regenerates).",
        retryable=True,
        max_retries=2,
    ),
    JobSpec(
        name="analytics_report_delivery",
        description="Delivers due user-configured analytics CSV digests by email.",
        cron="every 15 min Africa/Kampala",
        cron_kwargs={"minute": "*/15"},
        expected_runtime_seconds=120,
        max_interval_minutes=45,
        idempotent=True,
        idempotency_note="Due rows are atomically claimed by advancing next_run_at before network delivery.",
        retryable=True,
        max_retries=2,
    ),
    JobSpec(
        name="performance_readiness",
        description="Daily performance-cycle readiness; notifies HR 7 days before quarter end.",
        cron="daily 06:45 Africa/Kampala",
        cron_kwargs={"hour": 6, "minute": 45},
        expected_runtime_seconds=30,
        max_interval_minutes=1560,
        idempotent=True,
        idempotency_note="Read-only report; the 7-day notification dedupes per condition via the canonical trigger.",
        retryable=True,
        max_retries=2,
    ),
]

JOB_NAMES = {spec.name for spec in JOB_REGISTRY}


def get_spec(job_name: str) -> JobSpec | None:
    return next((s for s in JOB_REGISTRY if s.name == job_name), None)


class SchedulerHealthService:
    """Computes the health state System Health and `scheduler_health_check`
    both read -- the SINGLE place "is background automation actually alive"
    is answered, from ScheduledJobExecution rows (ground truth: did a run
    actually happen and succeed), never from "is ENABLE_BACKGROUND_JOBS
    true" alone (a process can be enabled and still silently die)."""

    @staticmethod
    def job_health(job_name: str) -> dict:
        from .models import ScheduledJobExecution

        spec = get_spec(job_name)
        latest = (
            ScheduledJobExecution.objects.filter(job_name=job_name)
            .order_by("-started_at")
            .first()
        )
        latest_success = (
            ScheduledJobExecution.objects.filter(job_name=job_name, status="success")
            .order_by("-started_at")
            .first()
        )
        now = timezone.now()

        never_run = latest is None
        overdue = False
        if spec and latest_success:
            overdue = (now - latest_success.started_at) > timedelta(
                minutes=spec.max_interval_minutes
            )
        elif spec and never_run:
            overdue = True

        failed = bool(latest and latest.status == "failed")

        if never_run:
            status, severity = "never_run", "critical"
        elif failed:
            status, severity = "failed", "critical"
        elif overdue:
            status, severity = "overdue", "high"
        else:
            status, severity = "healthy", "ok"

        return {
            "job_name": job_name,
            "spec": spec,
            "status": status,
            "severity": severity,
            "last_started": latest.started_at if latest else None,
            "last_completed": latest.completed_at if latest else None,
            "last_successful": latest_success.started_at if latest_success else None,
            "duration_seconds": latest.duration_seconds if latest else None,
            "failure_count": ScheduledJobExecution.objects.filter(
                job_name=job_name, status="failed"
            ).count(),
            "last_error": latest.error_message
            if (latest and latest.status == "failed")
            else None,
            "records_processed": latest.records_processed if latest else None,
        }

    @staticmethod
    def all_jobs_health() -> list[dict]:
        return [SchedulerHealthService.job_health(spec.name) for spec in JOB_REGISTRY]

    @staticmethod
    def is_scheduler_process_alive(stale_after_minutes: int = 10) -> bool:
        """Heartbeat check: has ANY job execution started recently enough
        that the scheduler process itself is plausibly still running (as
        opposed to every job independently going overdue)."""
        from .models import ScheduledJobExecution

        cutoff = timezone.now() - timedelta(minutes=stale_after_minutes)
        # At minimum, notification_escalation runs hourly -- if nothing at
        # all has started in `stale_after_minutes` and jobs are enabled,
        # treat the scheduler process as suspect rather than trusting silence.
        return ScheduledJobExecution.objects.filter(started_at__gte=cutoff).exists()

    @staticmethod
    def overall_healthy() -> bool:
        from django.conf import settings

        if not getattr(settings, "ENABLE_BACKGROUND_JOBS", False):
            return False
        return all(
            j["severity"] == "ok" for j in SchedulerHealthService.all_jobs_health()
        )
