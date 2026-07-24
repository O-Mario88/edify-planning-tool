"""
Background jobs — the complete inventory of periodic tasks, gated on
ENABLE_BACKGROUND_JOBS and registered centrally in apps.realtime.registry.
JOB_REGISTRY. Every job here is invoked ONLY through
apps.realtime.execution.run_tracked_job, which acquires a DB lock, records a
ScheduledJobExecution row, and retries per the job's registry spec — so
locking/idempotency-tracking/health-visibility apply uniformly instead of
being reimplemented per job.

  • weekly_fund_request            — Fri 06:00 — upserts weekly draft FundRequest.
  • monthly_work_plan              — 25th 06:00 — generates next-month envelope.
  • notification_escalation        — hourly — escalates stale action-required notifications.
  • daily_digest                   — 07:30 — one digest notification per user with unreads.
  • target_ledger_sync             — every 30 min — rebuilds TargetAchievementLedger for
                                      every active CCEO/PL (closes the audit's "ledger
                                      staleness" finding: My Targets/Team Targets/CD
                                      Analytics no longer depend on someone having opened
                                      a page recently to see a fresh number).
  • pd_reminders                   — daily 06:30 — apps.professional_development.reminders.
  • field_debrief_recurring_issues — daily 05:30 — apps.debriefs.insight_service.

Each PUBLIC job function early-returns unless ENABLE_BACKGROUND_JOBS is
true, matching the gate every one of these had before this fix — turning
automation on/off is still one flag, it just now runs in exactly one
dedicated worker process (see `python manage.py runscheduler`) instead of
inside every web worker.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .execution import run_tracked_job

logger = logging.getLogger("edify.jobs")


def _enabled() -> bool:
    return bool(getattr(settings, "ENABLE_BACKGROUND_JOBS", False))


# ── 1. Weekly fund request ───────────────────────────────────────────────────
def _do_weekly_fund_request() -> int:
    from apps.fund_requests.services import regenerate

    regenerate("weekly", _system_principal(), strict=False)
    return 1


def weekly_fund_request_job():
    if not _enabled():
        return
    run_tracked_job("weekly_fund_request", _do_weekly_fund_request)


# ── 2. Monthly work-plan budget envelope ─────────────────────────────────────
def _do_monthly_work_plan() -> int:
    from apps.monthly_work_plan.models import MonthlyWorkPlanBudget

    now = timezone.now()
    next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
    month_key = next_month.strftime("%Y-%m")
    fy = str(next_month.year + (1 if next_month.month >= 10 else 0))
    MonthlyWorkPlanBudget.objects.update_or_create(
        country_id="Uganda",
        month_key=month_key,
        defaults={"fy": fy, "generated_by": None, "status": "draft_generated"},
    )
    return 1


def monthly_work_plan_job():
    if not _enabled():
        return
    run_tracked_job("monthly_work_plan", _do_monthly_work_plan)


# ── 3. Notification escalation ───────────────────────────────────────────────
def _do_notification_escalation() -> int:
    from apps.notifications.models import Notification

    cutoff = timezone.now() - timedelta(hours=48)
    stale = Notification.objects.filter(
        status="unread",
        action_required=True,
        priority__in=["normal", "high"],
        created_at__lt=cutoff,
    )
    return stale.update(priority="urgent")


def notification_escalation_job():
    if not _enabled():
        return
    run_tracked_job("notification_escalation", _do_notification_escalation)


# ── 4. Daily digest ───────────────────────────────────────────────────────────
def _do_daily_digest() -> int:
    from apps.notifications.models import Notification
    from apps.notifications.services import WorkflowNotificationService

    today = timezone.now().date()
    unread = (
        Notification.objects.filter(status="unread")
        .values_list("recipient_id", flat=True)
        .distinct()
    )
    created = 0
    for recipient_id in unread:
        n = Notification.objects.filter(
            recipient_id=recipient_id, status="unread"
        ).count()
        if n == 0:
            continue
        # Dedupe per calendar day via source_event_id.
        #
        # source_event_id is 30 chars. The old key was
        # f"digest-{recipient_id}-{today}"[:30], and recipient_id is a 21-char
        # cuid, so the string was 39 chars and the slice cut at
        # "digest-<cuid>-2" -- discarding the date entirely. Every day of every
        # year produced an identical key, so each user received exactly ONE
        # digest ever and the job silently no-opped for them from then on.
        #
        # Put the date first so it can never be the part that gets truncated,
        # and hash the recipient to a fixed width that fits alongside it.
        recipient_hash = hashlib.blake2s(
            recipient_id.encode(), digest_size=8
        ).hexdigest()
        digest_id = f"dg-{today.isoformat()}-{recipient_hash}"
        assert len(digest_id) <= 30, digest_id
        if Notification.objects.filter(
            recipient_id=recipient_id, source_event_id=digest_id
        ).exists():
            continue
        WorkflowNotificationService.trigger(
            event_type="daily_digest",
            category="general",
            priority="normal",
            title=f"You have {n} unread notifications",
            body="Your daily digest.",
            context_id=digest_id,
            recipients=[recipient_id],
        )
        created += 1
    return created


def daily_digest_job():
    if not _enabled():
        return
    run_tracked_job("daily_digest", _do_daily_digest)


# ── 5. Target achievement ledger sync (closes the "ledger staleness" gap) ────
def _do_target_ledger_sync() -> int:
    from apps.accounts.models import User
    from apps.core.fy import get_operational_fy
    from apps.targets.my_targets import TargetAchievementService

    fy = get_operational_fy()
    users = User.objects.filter(
        status="active",
        deleted_at__isnull=True,
        roles__overlap=["CCEO", "Program Lead"],
    )
    rebuilt = 0
    for u in users:
        TargetAchievementService.rebuild(u, fy)
        rebuilt += 1
    return rebuilt


def target_ledger_sync_job():
    if not _enabled():
        return
    run_tracked_job("target_ledger_sync", _do_target_ledger_sync)


# ── 6. Professional Development reminders ────────────────────────────────────
def _do_pd_reminders() -> int:
    from apps.professional_development.reminders import send_due_reminders

    return send_due_reminders()


def pd_reminders_job():
    if not _enabled():
        return
    run_tracked_job("pd_reminders", _do_pd_reminders)


# ── 7. Field Debrief recurring-issue detection ───────────────────────────────
def _do_field_debrief_recurring_issues() -> int:
    from apps.debriefs.insight_service import RecurringIssueDetectionService

    result = RecurringIssueDetectionService.scan()
    return int(result.get("created", 0)) + int(result.get("updated", 0))


def weekly_debrief_reports_job():
    """Monday 06:00 — generate a PL Weekly Team Debrief Report draft for
    every Program Lead with a team, over the just-closed Mon-Sun week. PLs
    then review, correct and sign; the CD compilation reads only finalized
    team reports."""

    def _run():
        from apps.accounts.models import User
        from apps.core.rbac import EdifyRole
        from apps.debriefs.weekly_report_service import WeeklyDebriefReportService

        generated = 0
        for pl in User.objects.filter(
            active_role=EdifyRole.COUNTRY_PROGRAM_LEAD.value, is_active=True
        ):
            WeeklyDebriefReportService.generate_pl_report(pl)
            generated += 1
        return {"pl_reports_generated": generated}

    return run_tracked_job("weekly_debrief_reports", _run)


def field_debrief_recurring_issues_job():
    if not _enabled():
        return
    run_tracked_job(
        "field_debrief_recurring_issues", _do_field_debrief_recurring_issues
    )


# ── 8. User-configured analytics report delivery ────────────────────────────
def _do_analytics_report_delivery() -> int:
    from apps.analytics.report_delivery import deliver_due_schedules

    return deliver_due_schedules()


def analytics_report_delivery_job():
    if not _enabled():
        return
    run_tracked_job("analytics_report_delivery", _do_analytics_report_delivery)


# ── 9. Escalation SLA sweep ─────────────────────────────────────────────────
def _do_escalation_sla_sweep() -> int:
    """Re-notify on CD→RVP escalations past their severity SLA.

    An escalation channel nobody chases becomes a channel nobody uses.
    """
    from apps.flags.escalation_service import sweep_overdue

    return sweep_overdue()


def escalation_sla_sweep_job():
    if not _enabled():
        return
    run_tracked_job("escalation_sla_sweep", _do_escalation_sla_sweep)


def _system_principal():
    """A minimal stand-in principal for system-initiated jobs."""
    from apps.accounts.jwt import AuthPrincipal

    class _SystemUser:
        user_id = "system"
        name = "System Scheduler"

    class _P(AuthPrincipal):
        def __init__(self):
            super().__init__(
                user=_SystemUser(),
                user_id="system",
                email="system@edify",
                name="System",
                roles=[],
                active_role="Admin",
                staff_profile_id=None,
            )

    return _P()


__all__ = [
    "weekly_fund_request_job",
    "monthly_work_plan_job",
    "notification_escalation_job",
    "daily_digest_job",
    "target_ledger_sync_job",
    "pd_reminders_job",
    "field_debrief_recurring_issues_job",
    "analytics_report_delivery_job",
    "escalation_sla_sweep_job",
    "performance_readiness_job",
]


def _do_performance_readiness() -> int:
    from apps.hr.performance_engine import quarterly_readiness

    quarterly_readiness()
    return 1


def performance_readiness_job():
    if not _enabled():
        return
    run_tracked_job("performance_readiness", _do_performance_readiness)
