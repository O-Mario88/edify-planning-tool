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
    # `status` and `generated_by` are create-only. With them in `defaults`, a
    # second run for the same month — a scheduler restart, or a manual re-run
    # after the envelope had already gone to the RVP — reset an approved or
    # disbursed budget back to `draft_generated` while its submission
    # snapshots stayed put, and the totals repair then treated it as live and
    # overwrote the approved figures. See LOCKED_STATUSES in
    # apps.monthly_work_plan.country_budget_service.
    MonthlyWorkPlanBudget.objects.update_or_create(
        country_id="Uganda",
        month_key=month_key,
        defaults={"fy": fy},
        create_defaults={
            "fy": fy,
            "generated_by": None,
            "status": "draft_generated",
        },
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


def _ia_digest_id(today, recipient_id) -> str:
    # 30-char source_event_id: 4 + 10 + 1 + 14 hex = 29. The recipient is part
    # of the key, so one person's digest never stands in for another's.
    recipient_hash = hashlib.blake2s(
        str(recipient_id).encode(), digest_size=7
    ).hexdigest()
    digest_id = f"iad-{today.isoformat()}-{recipient_hash}"
    assert len(digest_id) <= 30, digest_id
    return digest_id


def _do_ia_verification_digest() -> int:
    """One morning line per verifier: what is waiting, and what is past the
    24-hour SLA (2026-09-03). Bounded to the verifier's country and never
    counting their own submissions, which they may not verify.

    The Country Director gets the same line for the work Impact Assessment
    officers ran themselves (IA review, 2026-09-13): the one case the officers
    cannot verify for themselves and the CD verifies as fallback. The CD was
    told once, at submission, and never again — not even once the work was
    past its SLA. Partner submissions are named, because they are verified in
    Partner Evidence rather than the staff queue."""
    from datetime import timedelta

    from django.db.models import Count, Q

    from apps.activities.models import Activity
    from apps.core.permissions import ia_officer_staff_ids
    from apps.core.rbac import EdifyRole
    from apps.core.scoping import activity_country_q, owner_ids, resolve_user_scope
    from apps.notifications.models import Notification
    from apps.notifications.services import (
        WorkflowNotificationService,
        role_recipients,
    )

    today = timezone.now().date()
    cutoff = timezone.now() - timedelta(hours=24)
    created = 0

    def _send(recipient, waiting, *, body, fallback=False):
        nonlocal created
        counts = waiting.aggregate(
            n=Count("id"),
            overdue=Count("id", filter=Q(submitted_to_ia_at__lte=cutoff)),
            partner=Count("id", filter=Q(delivery_type="partner")),
        )
        if counts["n"] == 0:
            return
        digest_id = _ia_digest_id(today, recipient.id)
        if Notification.objects.filter(
            recipient_id=recipient.id, source_event_id=digest_id
        ).exists():
            return
        noun = "officers' submissions" if fallback else "waiting for verification"
        title = (
            f"{counts['n']} IA {noun} waiting for you"
            if fallback
            else f"{counts['n']} {noun}"
        )
        if counts["overdue"]:
            title += f" · {counts['overdue']} past 24h"
        if counts["partner"]:
            title += f" · {counts['partner']} from partners"
        WorkflowNotificationService.trigger(
            event_type="ia_verification_digest",
            category="verification",
            priority="high" if counts["overdue"] else "normal",
            title=title,
            body=body,
            context_id=digest_id,
            recipients=[recipient],
        )
        created += 1

    waiting_base = Activity.objects.filter(
        deleted_at__isnull=True, status="awaiting_ia_verification"
    )
    for verifier in role_recipients(EdifyRole.IMPACT_ASSESSMENT.value):
        scope = resolve_user_scope(verifier)
        own = [i for i in owner_ids(verifier) if i]
        waiting = waiting_base.filter(activity_country_q(scope)).exclude(
            responsible_staff_id__in=own
        )
        _send(verifier, waiting, body="Your morning verification digest.")

    for director in role_recipients(EdifyRole.COUNTRY_DIRECTOR.value):
        scope = resolve_user_scope(director)
        waiting = waiting_base.filter(activity_country_q(scope)).filter(
            responsible_staff_id__in=ia_officer_staff_ids(scope.country or None)
        )
        _send(
            director,
            waiting,
            body=(
                "Work Impact Assessment officers ran themselves, which you "
                "verify as fallback verifier."
            ),
            fallback=True,
        )
    return created


def _do_verification_sampling() -> int:
    from apps.activities.verification_sampling import draw_samples

    return draw_samples(days=7)


def verification_sampling_job():
    if not _enabled():
        return
    run_tracked_job("verification_sampling", _do_verification_sampling)


def ia_verification_digest_job():
    if not _enabled():
        return
    run_tracked_job("ia_verification_digest", _do_ia_verification_digest)


def daily_digest_job():
    if not _enabled():
        return
    run_tracked_job("daily_digest", _do_daily_digest)


# ── Daily plan notifications (owner, 2026-09-24) ──────────────────────────────
#: "Notifications also should notify the CCEO of the activities of that day.
#: Notification for PL should be to monitor all the plans."
DAILY_PLAN_TODAY_EVENT = "daily_plan_today"
PL_TEAM_DAILY_EVENT = "pl_team_daily_monitor"
#: How many of the day's activities a CCEO's notice names before "and N more".
_DAILY_PLAN_NAMED = 3


def _today_q(today):
    """Activities dated today, read the way My Plan reads a date."""
    from django.db.models import Q

    return Q(planned_date=today) | Q(
        planned_date__isnull=True, scheduled_date__date=today
    )


def _open_work(qs):
    """Work still to do today: not released, and not already delivered —
    a visit submitted for review this morning is not on the day's to-do."""
    from apps.core.activity_types import COMPLETED_WORK_STATUSES
    from apps.my_plan.past_due_service import TERMINAL_OR_COMPLETED_STATUSES
    from apps.my_plan.services import ACTIVE_MY_PLAN_EXCLUDED_STATUSES

    return qs.exclude(
        status__in=(
            *ACTIVE_MY_PLAN_EXCLUDED_STATUSES,
            *COMPLETED_WORK_STATUSES,
            *TERMINAL_OR_COMPLETED_STATUSES,
        )
    )


def _already_told(recipient_id, event_type, key) -> bool:
    """A notice for this person, event and day exists — even one they archived."""
    from apps.notifications.models import Notification

    return Notification.objects.filter(
        recipient_id=recipient_id, source_event_type=event_type, context_id=key
    ).exists()


def _where_label(activity) -> str:
    place = (
        getattr(activity.school, "name", "")
        if activity.school_id
        else getattr(activity.cluster, "name", "")
        if activity.cluster_id
        else (activity.venue or "")
    )
    kind = activity.get_activity_type_display()
    return f"{kind} at {place}" if place else kind


def _do_daily_plan_notifications(today=None) -> int:
    """Each CCEO's plan for the day, and each Programme Lead's team to monitor.

    One notice per person per day, at 06:45 so it lands before the morning
    digest counts unread notices. A person with nothing to act on today gets
    nothing, the same no-nag rule the debrief reminders follow. The notices
    are keyed to the day: a re-run the same day sends nothing twice (even to
    someone who archived theirs), and yesterday's live notices are closed so a
    stale "your plan today" never lingers into tomorrow.

    The CCEO's list is their own My Plan for today (the same membership and
    the same date rule), and the Lead's counts are over the officers they
    lead, cover included (apps.hr.team_roster.team_members).
    """
    from django.db.models import Q

    from apps.activities.models import Activity
    from apps.core.scoping import owner_ids
    from apps.hr.team_roster import team_members
    from apps.my_plan.past_due_service import TERMINAL_OR_COMPLETED_STATUSES
    from apps.my_plan.services import staff_my_plan_q
    from apps.notifications.models import Notification
    from apps.notifications.services import (
        WorkflowNotificationService,
        role_recipients,
    )

    today = today or timezone.localdate()
    key = f"dp-{today.isoformat()}"
    now = timezone.now()

    # Yesterday's notices describe a day that is over.
    Notification.objects.filter(
        source_event_type__in=(DAILY_PLAN_TODAY_EVENT, PL_TEAM_DAILY_EVENT),
        resolved_at__isnull=True,
    ).exclude(context_id=key).update(
        resolved_at=now, status="archived", action_required=False, updated_at=now
    )

    sent = 0
    for user in role_recipients("CCEO"):
        if _already_told(user.id, DAILY_PLAN_TODAY_EVENT, key):
            continue
        ids = [i for i in owner_ids(user) if i]
        if not ids:
            continue
        work = list(
            _open_work(
                Activity.objects.filter(deleted_at__isnull=True)
                .filter(_today_q(today))
                .filter(staff_my_plan_q(ids, user))
            )
            .select_related("school", "cluster")
            .order_by("planned_date", "created_at")
        )
        if not work:
            continue
        named = "; ".join(_where_label(a) for a in work[:_DAILY_PLAN_NAMED])
        more = len(work) - _DAILY_PLAN_NAMED
        WorkflowNotificationService.trigger(
            event_type=DAILY_PLAN_TODAY_EVENT,
            category="activity",
            priority="normal",
            title=f"Your plan today: {len(work)} activit{'y' if len(work) == 1 else 'ies'}",
            body=named + (f"; and {more} more." if more > 0 else "."),
            context_type="daily_plan",
            context_id=key,
            recipients=[user.id],
        )
        sent += 1

    for lead in role_recipients("Program Lead"):
        if _already_told(lead.id, PL_TEAM_DAILY_EVENT, key):
            continue
        team_ids: list[str] = []
        person_of: dict[str, str] = {}
        for member in team_members(lead):
            for identifier in (member.id, member.user_id):
                if identifier:
                    team_ids.append(identifier)
                    # One officer, whichever id space wrote their activity.
                    person_of[identifier] = member.id
        if not team_ids:
            continue
        team_q = staff_my_plan_q(team_ids, lead)
        today_rows = list(
            _open_work(
                Activity.objects.filter(deleted_at__isnull=True)
                .filter(_today_q(today))
                .filter(team_q)
            ).values_list("responsible_staff_id", "monitored_by_staff_id")
        )
        officers = {person_of.get(r or m, r or m) for r, m in today_rows if r or m}
        past_due = (
            Activity.objects.filter(deleted_at__isnull=True)
            .exclude(status__in=TERMINAL_OR_COMPLETED_STATUSES)
            .filter(
                Q(planned_date__lt=today)
                | Q(planned_date__isnull=True, scheduled_date__date__lt=today)
            )
            .filter(team_q)
            .count()
        )
        waiting = Activity.objects.filter(
            deleted_at__isnull=True,
            status="submitted_to_pl",
            responsible_staff_id__in=team_ids,
        ).count()
        if not (today_rows or past_due or waiting):
            continue
        parts = [
            f"{len(today_rows)} activit{'y' if len(today_rows) == 1 else 'ies'} "
            f"planned today by {len(officers)} officer{'s' if len(officers) != 1 else ''}"
        ]
        if past_due:
            parts.append(f"{past_due} past due")
        if waiting:
            parts.append(
                f"{waiting} completion{'s' if waiting != 1 else ''} waiting on you"
            )
        WorkflowNotificationService.trigger(
            event_type=PL_TEAM_DAILY_EVENT,
            category="team",
            # Normal, not high: high sets action_required, and the escalation
            # sweep would turn a daily summary urgent after 48 hours.
            priority="normal",
            title="Monitor your team's plans today",
            body="; ".join(parts) + ".",
            context_type="team_daily",
            context_id=key,
            recipients=[lead.id],
        )
        sent += 1
    return sent


def daily_plan_notifications_job():
    if not _enabled():
        return
    run_tracked_job("daily_plan_notifications", _do_daily_plan_notifications)


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

    from django.db.models import Q

    tomorrow = timezone.localdate() + timedelta(days=1)
    # Staff work is owned through responsible_staff_id; partner-delivered
    # work deliberately carries responsible_staff_id=None and is owned via
    # assigned_partner_id. Excluding null owners alone made every partner
    # activity structurally unreachable for the eve-of-delivery reminder
    # (2026-08-19 audit F6).
    upcoming = (
        Activity.objects.filter(
            deleted_at__isnull=True,
            planned_date=tomorrow,
        )
        .exclude(status__in=("cancelled", "rejected", "deferred", "not_planned"))
        .filter(
            (Q(responsible_staff_id__isnull=False) & ~Q(responsible_staff_id=""))
            | Q(delivery_type="partner", assigned_partner_id__isnull=False)
        )
    )
    created = 0
    for activity in upcoming:
        recipient = _funding_owner_user_id(activity) or _partner_owner_user_id(activity)
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
    if not activity.responsible_staff_id:
        return None
    from apps.accounts.models import StaffProfile

    resolved = (
        StaffProfile.objects.filter(id=activity.responsible_staff_id)
        .values_list("user_id", flat=True)
        .first()
    )
    return resolved or activity.responsible_staff_id


def _partner_owner_user_id(activity):
    """The partner organisation's login, for partner-delivered work."""
    if not activity.assigned_partner_id:
        return None
    from apps.partners.models import Partner

    return (
        Partner.objects.filter(id=activity.assigned_partner_id)
        .values_list("user_id", flat=True)
        .first()
    )


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


# ── Scheduler history retention ──────────────────────────────────────────────
#: How long a run's history row is kept. The every-minute outbox drain alone
#: writes ~525,000 rows a year, and nothing ever deleted one (2026-09-23
#: performance rescue, R13). Failures are kept longer: they are what an
#: incident review reads.
JOB_HISTORY_SUCCESS_RETENTION = timedelta(days=90)
JOB_HISTORY_FAILURE_RETENTION = timedelta(days=365)


def _do_scheduler_history_prune() -> int:
    """Delete run history past retention, keeping each job's latest success.

    System Health reads the latest row and the latest success per job; the
    latest success is kept whatever its age, so a job that has been failing
    for months still reports when it last worked.
    """
    from django.db.models import Max, Q

    from .models import ScheduledJobExecution

    now = timezone.now()
    latest = Q(pk__in=[])
    for row in (
        ScheduledJobExecution.objects.filter(status="success")
        .values("job_name")
        .annotate(started=Max("started_at"))
    ):
        latest |= Q(job_name=row["job_name"], started_at=row["started"])
    deleted, _ = (
        ScheduledJobExecution.objects.filter(
            status="success", started_at__lt=now - JOB_HISTORY_SUCCESS_RETENTION
        )
        .exclude(latest)
        .delete()
    )
    failed, _ = ScheduledJobExecution.objects.filter(
        status="failed", started_at__lt=now - JOB_HISTORY_FAILURE_RETENTION
    ).delete()
    if deleted or failed:
        logger.info(
            "Pruned %s successful and %s failed job runs past retention",
            deleted,
            failed,
        )
    return deleted + failed


def scheduler_history_prune_job():
    if not _enabled():
        return
    run_tracked_job("scheduler_history_prune", _do_scheduler_history_prune)


# ── Closure checklist refresh ────────────────────────────────────────────────
def _do_closure_checklist_refresh() -> int:
    """Persist every open activity's closure checklist and blockers.

    The readiness queue derives its facts read-only on each view; this keeps
    the stored copy that the Blocked Closures page and the System Health
    integrity checks read no more than half an hour behind.
    """
    from apps.activities.closure_services import ClosureEligibilityService

    report = ClosureEligibilityService.refresh_open()
    logger.info("Closure checklist refresh: %s", report)
    return report["checklistsWritten"]


def closure_checklist_refresh_job():
    if not _enabled():
        return
    run_tracked_job("closure_checklist_refresh", _do_closure_checklist_refresh)


# ── 6. Professional Development reminders ────────────────────────────────────
def _do_pd_reminders() -> int:
    from apps.professional_development.reminders import send_due_reminders

    return send_due_reminders()


def pd_reminders_job():
    if not _enabled():
        return
    run_tracked_job("pd_reminders", _do_pd_reminders)


# ── 7. Loan application and repayment follow-ups ─────────────────────────────
def _do_loan_tracking_notifications() -> int:
    from apps.business_transformation.loan_tracking import (
        run_loan_tracking_notifications,
    )

    return run_loan_tracking_notifications()


def loan_tracking_notifications_job():
    if not _enabled():
        return
    run_tracked_job("loan_tracking_notifications", _do_loan_tracking_notifications)


# ── 8. Field Debrief recurring-issue detection ───────────────────────────────
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

    if not _enabled():
        return None
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

    if not _enabled():
        return None
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


# ── School action queue ──────────────────────────────────────────────────────
def _do_school_action_sweep() -> int:
    """Close delegated school actions whose condition has genuinely cleared,
    and flag the ones that have run past their due date.

    This is what makes the urgent queue self-maintaining. Without it, an
    action stays open until somebody notices the SSA landed — and a school
    whose problem is fixed keeps occupying a slot that a school with a real
    problem needs.
    """
    from apps.planning.action_service import mark_overdue_actions, resolve_due_actions

    resolved = resolve_due_actions()
    overdue = mark_overdue_actions()
    return int(resolved["resolved"]) + int(overdue["overdue"])


def school_action_sweep_job():
    if not _enabled():
        return
    run_tracked_job("school_action_sweep", _do_school_action_sweep)


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
    "loan_tracking_notifications_job",
    "field_debrief_recurring_issues_job",
    "analytics_report_delivery_job",
    "escalation_sla_sweep_job",
    "school_action_sweep_job",
    "fiscal_year_rollover_job",
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


def _do_fiscal_year_rollover() -> int:
    from apps.hr.fiscal_year_rollover import ensure_current_fiscal_year

    report = ensure_current_fiscal_year(initiated_by="scheduler")
    return int(report.get("draftAgreementsCreated", 0))


def fiscal_year_rollover_job():
    if not _enabled():
        return
    run_tracked_job("fiscal_year_rollover", _do_fiscal_year_rollover)


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


# ── 14. Staff Time Standard rollup ───────────────────────────────────────────
def _do_interaction_rollup() -> int:
    """Sessionise yesterday's interaction events into person-day aggregates
    (docs/STAFF_TIME_STANDARD.md §4) and prune raw events past retention.
    The aggregates feed role-population percentiles only — the report layer
    exposes no individual."""

    from apps.telemetry.services import rollup_interaction_days

    return rollup_interaction_days()


def interaction_rollup_job():
    if not _enabled():
        return
    run_tracked_job("interaction_rollup", _do_interaction_rollup)


# ── 15. Data-quality scan ────────────────────────────────────────────────────
def _do_data_quality_scan() -> int:
    """Nightly directory hygiene (roadmap Phase 1b): propose duplicate
    candidates, then reconcile every operating school's quality issues as
    durable queues. Detection proposes; humans resolve."""

    from apps.schools.data_quality import scan_all

    result = scan_all()
    logger.info("Data-quality scan: %s", result)
    return result["schools"]


def data_quality_scan_job():
    if not _enabled():
        return
    run_tracked_job("data_quality_scan", _do_data_quality_scan)


def _do_ssa_recommendation_sync() -> int:
    """Converge SSA recommendations with assessments and live plans."""

    from apps.core.fy import get_operational_fy
    from apps.ssa.plan_alignment import judge_unjudged_plans
    from apps.ssa.recommendation_service import sync_recommendations

    result = sync_recommendations()
    # Plans that predate planning-time verdicts, or came in through a path
    # that skipped them, are judged here so no live plan stays unjudged.
    judged, linked = judge_unjudged_plans(get_operational_fy())
    return result["created"] + result["linked"] + judged + linked


def ssa_recommendation_sync_job():
    if not _enabled():
        return
    run_tracked_job("ssa_recommendation_sync", _do_ssa_recommendation_sync)


# ── 16. Durable outbox drain ─────────────────────────────────────────────────
def _do_outbox_drain() -> int:
    """One drain pass over the durable event backbone (roadmap Phase 2)."""

    from apps.outbox.services import drain

    result = drain()
    if result["failed"]:
        logger.warning("Outbox drain: %s", result)
    return result["processed"]


def _do_autopilot_weekly_proposals() -> int:
    """Draft next week for the field roster (roadmap Phase 4 slice 1)."""

    from apps.autopilot.services import generate_weekly_proposals_for_all

    return generate_weekly_proposals_for_all()


def autopilot_weekly_proposals_job():
    if not _enabled():
        return
    run_tracked_job("autopilot_weekly_proposals", _do_autopilot_weekly_proposals)


def outbox_drain_job():
    if not _enabled():
        return
    run_tracked_job("outbox_drain", _do_outbox_drain)


def _do_audit_chain_seal() -> int:
    from apps.audit.services import seal_pending

    return seal_pending()


def audit_chain_seal_job():
    if not _enabled():
        return
    run_tracked_job("audit_chain_seal", _do_audit_chain_seal)


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


# ── Scheduler watchdog ───────────────────────────────────────────────────────
SCHEDULER_JOB_UNHEALTHY = "scheduler.job_unhealthy"


def _do_scheduler_watchdog() -> int:
    """Push what SchedulerHealthService already knows.

    The health of every job was computed correctly and read by exactly two
    things: the System Health page, which somebody has to open, and a CLI
    command no deploy config invokes. So a job could stop and nobody would
    hear — the failure mode the platform's own runbooks call out ("a scheduler
    that can stop without anyone noticing until a job is stale needs its own
    liveness signal").

    This closes the common half: a job that fails or falls behind while the
    scheduler is alive. It cannot close the other half — a watchdog inside the
    scheduler dies with it — and that still needs an external monitor calling
    `manage.py scheduler_health_check`, which already exits non-zero for
    exactly this and checks `is_scheduler_process_alive` too.

    Notifications are keyed per job, so a job broken for a week re-fires into
    the one open notice rather than adding forty-eight. Recovery closes it,
    because a notice that outlives its condition is what taught people to stop
    reading them.
    """
    from apps.accounts.models import User
    from apps.notifications.services import (
        WorkflowNotificationService,
        resolve_condition,
    )

    from .registry import SchedulerHealthService

    admins = list(
        User.objects.filter(
            is_active=True, deleted_at__isnull=True, roles__contains=["Admin"]
        ).values_list("id", flat=True)
    )

    raised = 0
    for health in SchedulerHealthService.all_jobs_health():
        job_name = health["job_name"]
        if health["severity"] == "ok":
            resolve_condition(SCHEDULER_JOB_UNHEALTHY, "scheduled_job", job_name)
            continue

        if not admins:
            logger.error(
                "Scheduled job %s is %s and no active Admin exists to notify.",
                job_name,
                health["status"],
            )
            continue

        last = health["last_successful"]
        WorkflowNotificationService.trigger(
            event_type=SCHEDULER_JOB_UNHEALTHY,
            category="platform",
            # `critical` is a job that failed or has never run at all; `high` is
            # one that is merely late. Neither is urgent — the escalation sweep
            # promotes what stays unresolved, and starting there would leave it
            # nowhere to go.
            priority="high" if health["severity"] == "critical" else "normal",
            title=f"Background job {job_name} is {health['status']}",
            body=(
                f"{health['status'].replace('_', ' ').capitalize()}. "
                f"Last successful run: {last or 'never'}. "
                f"{health['failure_count']} recorded failure(s). "
                f"{health['last_error'] or ''}"
            ).strip(),
            context_type="scheduled_job",
            context_id=job_name,
            recipients=admins,
        )
        raised += 1
    return raised


def scheduler_watchdog_job():
    if not _enabled():
        return
    run_tracked_job("scheduler_watchdog", _do_scheduler_watchdog)
