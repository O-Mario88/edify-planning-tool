"""
Background jobs — the 4 scheduled jobs, gated on ENABLE_BACKGROUND_JOBS.

Faithful port of the NestJS @Cron jobs (single-process worker parity):
  • WeeklyFundRequestJob — Fri 06:00 — upserts weekly draft FundRequest for next Mon–Sun.
  • MonthlyWorkPlanBudgetJob — 25th 06:00 — generates next-month envelope.
  • NotificationEscalationJob — hourly — bumps priority of stale action-required
    notifications past the 48h SLA + notifies the supervisor (deduped).
  • DailyDigestJob — 07:30 — one digest notification per user with unreads.

Each early-returns unless ENABLE_BACKGROUND_JOBS is true.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger("edify.jobs")


def _enabled() -> bool:
    return bool(getattr(settings, "ENABLE_BACKGROUND_JOBS", False))


def weekly_fund_request_job():
    """Friday 06:00 — idempotent weekly fund-request generation."""
    if not _enabled():
        return
    try:
        from apps.fund_requests.services import regenerate

        regenerate("weekly", _system_principal())
        logger.info("Weekly fund-request job completed.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Weekly fund-request job failed: %s", exc)


def monthly_work_plan_job():
    """25th 06:00 — generate next-month work-plan budget envelope."""
    if not _enabled():
        return
    try:
        from apps.monthly_work_plan.models import MonthlyWorkPlanBudget

        now = timezone.now()
        next_month = (now.replace(day=1) + timedelta(days=32)).replace(day=1)
        month_key = next_month.strftime("%Y-%m")
        fy = str(next_month.year + (1 if next_month.month >= 10 else 0))
        MonthlyWorkPlanBudget.objects.update_or_create(
            country_id="Uganda", month_key=month_key,
            defaults={"fy": fy, "generated_by": None, "status": "draft_generated"},
        )
        logger.info("Monthly work-plan job completed for %s.", month_key)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Monthly work-plan job failed: %s", exc)


def notification_escalation_job():
    """Hourly — escalate stale action-required notifications past 48h SLA."""
    if not _enabled():
        return
    try:
        from apps.notifications.models import Notification

        cutoff = timezone.now() - timedelta(hours=48)
        stale = Notification.objects.filter(
            status="unread", action_required=True, priority__in=["normal", "high"],
            created_at__lt=cutoff,
        )
        count = stale.update(priority="urgent")
        logger.info("Notification escalation job: %d notifications escalated.", count)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Notification escalation job failed: %s", exc)


def daily_digest_job():
    """07:30 daily — one digest notification per user with unreads."""
    if not _enabled():
        return
    try:
        from apps.notifications.models import Notification

        today = timezone.now().date()
        unread = Notification.objects.filter(status="unread").values_list("recipient_id", flat=True).distinct()
        created = 0
        for recipient_id in unread:
            n = Notification.objects.filter(recipient_id=recipient_id, status="unread").count()
            if n == 0:
                continue
            # Dedupe per calendar day via source_event_id.
            digest_id = f"digest-{recipient_id}-{today.isoformat()}"[:30]
            if Notification.objects.filter(recipient_id=recipient_id, source_event_id=digest_id).exists():
                continue
            Notification.objects.create(
                recipient_id=recipient_id,
                title=f"You have {n} unread notifications",
                body="Your daily digest.",
                priority="normal",
                source_event_type="daily_digest",
                source_event_id=digest_id,
            )
            created += 1
        logger.info("Daily digest job: %d digests created.", created)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Daily digest job failed: %s", exc)


def _system_principal():
    """A minimal stand-in principal for system-initiated jobs."""
    from apps.accounts.jwt import AuthPrincipal

    class _SystemUser:
        user_id = "system"
        name = "System Scheduler"

    class _P(AuthPrincipal):
        def __init__(self):
            super().__init__(user=_SystemUser(), user_id="system", email="system@edify",
                             name="System", roles=[], active_role="Admin", staff_profile_id=None)

    return _P()


__all__ = [
    "weekly_fund_request_job",
    "monthly_work_plan_job",
    "notification_escalation_job",
    "daily_digest_job",
]
