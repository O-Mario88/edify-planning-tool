"""
Background jobs — the complete inventory of periodic tasks, gated on
ENABLE_BACKGROUND_JOBS and registered centrally in apps.realtime.registry.
JOB_REGISTRY. Every job here is invoked ONLY through
apps.realtime.execution.run_tracked_job, which acquires a DB lock, records a
ScheduledJobExecution row, and retries per the job's registry spec — so
locking/idempotency-tracking/health-visibility apply uniformly instead of
being reimplemented per job.

  • weekly_fund_request            — Fri 06:00 — retired to a no-op (see below).
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
  • mfa_challenge_purge            — daily 03:20 — deletes spent second-factor
                                      challenges past MFA_CHALLENGE_RETENTION.

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

# How long a dead second-factor challenge is kept before being deleted. Long
# enough that an incident review the next day can still see the shape of a
# sign-in attempt, short enough that the table does not become a permanent
# archive of credential hashes.
MFA_CHALLENGE_RETENTION = timedelta(days=7)


def _enabled() -> bool:
    return bool(getattr(settings, "ENABLE_BACKGROUND_JOBS", False))


# ── 1. Weekly fund request ───────────────────────────────────────────────────
def _do_weekly_fund_request() -> int:
    # Deliberately a no-op. This job used to call
    # fund_requests.services.regenerate("weekly", ...) with no week, which —
    # before submit() learned to refuse a weekly period without an explicit
    # week — filed ONE country-scope FundRequest whose total was the entire
    # FY's national planned spend, sitting one Accountant click away from
    # flipping every advance in the FY to disbursed. The weekly money the job
    # was meant to produce never needed it: draft WeeklyFundRequests are
    # already auto-generated per owner at scheduling time (see
    # apps.fund_requests.advance_service / weekly_service). The registry entry
    # is kept so the schedule/health tooling still sees the slot.
    return 0


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


def _do_activity_reminders() -> int:
    """§33 — 'Activity starts tomorrow' for every responsible person.

    Covers school, cluster, project and non-school programme work alike (one
    reminder per activity per person, deduped per day via source_event_id).
    Multi-day activities remind on the eve of their START only.
    """
    from datetime import timedelta

    from apps.activities.models import Activity
    from apps.notifications.models import Notification
    from apps.notifications.services import WorkflowNotificationService

    tomorrow = timezone.localdate() + timedelta(days=1)
    upcoming = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            planned_date=tomorrow,
        )
        .exclude(status__in=("cancelled", "rejected", "deferred", "not_planned"))
        .exclude(responsible_staff_id__isnull=True)
        .exclude(responsible_staff_id="")
    )
    created = 0
    for activity in upcoming:
        recipient = _funding_owner_user_id(activity)
        if not recipient:
            continue
        act_hash = hashlib.blake2s(activity.id.encode(), digest_size=6).hexdigest()
        reminder_id = f"act-{tomorrow.isoformat()}-{act_hash}"
        assert len(reminder_id) <= 30, reminder_id
        if Notification.objects.filter(
            recipient_id=recipient, source_event_id=reminder_id
        ).exists():
            continue
        name = activity.activity_name_snapshot or activity.get_activity_type_display()
        span = (
            f" ({activity.planned_date:%-d %b}–{activity.end_date:%-d %b})"
            if activity.end_date and activity.end_date != activity.planned_date
            else ""
        )
        WorkflowNotificationService.trigger(
            event_type="activity_reminder",
            category="activity",
            priority="normal",
            title=f"Starts tomorrow: {name}{span}",
            body="Review the plan, funding and evidence requirements before you start.",
            context_type="Activity",
            context_id=reminder_id,
            recipients=[recipient],
        )
        created += 1
    return created


def _funding_owner_user_id(activity):
    """responsible_staff_id may be a StaffProfile id or a User id."""
    from apps.accounts.models import StaffProfile

    resolved = (
        StaffProfile.objects.filter(id=activity.responsible_staff_id)
        .values_list("user_id", flat=True)
        .first()
    )
    return resolved or activity.responsible_staff_id


def activity_reminders_job():
    if not _enabled():
        return
    run_tracked_job("activity_reminders", _do_activity_reminders)


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


def daily_debrief_reminders_job():
    """18:00 — remind field staff who had scheduled activities today but have
    not submitted a Daily Debrief; 08:00 next morning re-reminds for
    yesterday. Users with no scheduled work that day (leave, holidays,
    office days) are never nagged (mandate: no debrief on non-work days).
    One notification per user per run — the notification service dedupes
    repeats against the same context."""

    def _run():
        from datetime import timedelta

        from django.utils import timezone as tz

        from apps.accounts.models import User
        from apps.debriefs.field_debrief_service import (
            SUBMITTER_ROLES,
            DailyDebriefFlowService,
            _daily_midnight,
        )
        from apps.debriefs.models import DailyDebrief, DebriefKind, DebriefStatus
        from apps.notifications.services import WorkflowNotificationService

        now = tz.localtime()
        target = (
            tz.localdate() if now.hour >= 12 else tz.localdate() - timedelta(days=1)
        )
        when = "today" if target == tz.localdate() else "yesterday"
        reminded = 0
        for user in User.objects.filter(
            active_role__in=SUBMITTER_ROLES, is_active=True
        ):
            if not DailyDebriefFlowService.activities_for(user, target):
                continue
            done = (
                DailyDebrief.objects.filter(
                    submitted_by_user_id=user.user_id,
                    kind=DebriefKind.DAILY,
                    date=_daily_midnight(target),
                    deleted_at__isnull=True,
                )
                .exclude(status=DebriefStatus.DRAFT)
                .exists()
            )
            if done:
                continue
            WorkflowNotificationService.trigger(
                event_type="field_debrief.due",
                category="debrief",
                priority="normal",
                title=f"Daily Debrief due for {when}",
                body="You had scheduled activities but no debrief yet. "
                "It takes two to three minutes.",
                context_type="daily_debrief_due",
                context_id=f"{user.user_id}:{target}",
                recipients=[user.user_id],
            )
            reminded += 1
        return {"reminded": reminded, "for_date": str(target)}

    return run_tracked_job("daily_debrief_reminders", _run)


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


# ── 13. Spent second-factor challenges ───────────────────────────────────────
def _do_mfa_challenge_purge() -> int:
    """Delete second-factor challenges that can no longer do anything.

    A row is written for every sign-in by every enrolled account, so without
    this the table only grows. Each spent row also holds the hash of what was
    briefly a credential, and keeping those long after they stopped working is
    keeping a liability with no matching use.

    Only rows that are already dead are touched — consumed, or expired past the
    retention window. A challenge someone is part-way through answering is
    never in scope, whatever the window is set to.
    """
    from apps.accounts.models import MfaChallenge

    cutoff = timezone.now() - MFA_CHALLENGE_RETENTION
    deleted, _ = MfaChallenge.objects.filter(
        expires_at__lt=cutoff, created_at__lt=cutoff
    ).delete()
    if deleted:
        logger.info("Purged %s spent MFA challenges older than %s", deleted, cutoff)
    return deleted


def mfa_challenge_purge_job():
    if not _enabled():
        return
    run_tracked_job("mfa_challenge_purge", _do_mfa_challenge_purge)


# ── Admin platform maintenance ───────────────────────────────────────────────
def _do_admin_maintenance_generation() -> int:
    """Turn every due MaintenanceTemplate into scheduled Admin work.

    Routine upkeep -- backup verification, restore rehearsal, dead-route scans,
    permission review -- should not depend on anyone remembering it. When a
    template falls due this puts it in Admin My Plan with a date on it.
    """
    from apps.admin_ops.services import MaintenanceService

    return MaintenanceService.generate_due()


def admin_maintenance_generation_job():
    if not _enabled():
        return
    run_tracked_job("admin_maintenance_generation", _do_admin_maintenance_generation)


# ── Document Library lifecycle ───────────────────────────────────────────────
def _do_document_lifecycle() -> int:
    """One daily pass over the Document Library.

    Grouped into a single job because each step is small, they share no state,
    and five separate registry entries would be five things to monitor for one
    daily sweep.
    """
    from apps.documents import jobs as document_jobs

    return (
        document_jobs.activate_effective_documents()
        + document_jobs.expire_documents()
        + document_jobs.retry_failed_previews()
        + document_jobs.send_acknowledgement_reminders()
        + document_jobs.finalise_engagement_sessions()
    )


def document_lifecycle_job():
    if not _enabled():
        return
    run_tracked_job("document_lifecycle", _do_document_lifecycle)
