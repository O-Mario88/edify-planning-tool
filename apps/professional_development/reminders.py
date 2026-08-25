"""send_due_reminders() — the canonical PD-reminders implementation (§19).

Extracted from the send_pd_reminders management command so both the manual
CLI entry point and the scheduled job (apps.realtime.jobs.pd_reminders_job)
call the exact same logic — one implementation, two callers, never two
copies that could drift apart.

Pre-course: 7 / 3 / 1 days before start_date, to the employee.
During course: one reminder per day while IN_PROGRESS, to the employee.
Post-course: escalating overdue reminders at 7 / 14 / 30 days after end_date
while the course is ENDED (not yet marked complete) — to the employee,
their supervisor, and HR.

Idempotent: ProfessionalDevelopmentReminderLog (unique per request + key +
day) guards every send, so calling this more than once on the same day
never double-notifies. Reminders naturally stop firing once a request
leaves ENROLLMENT_CONFIRMED/IN_PROGRESS/ENDED (i.e. once it's marked
complete via the accountability/certificate flow) since it no longer
matches any of the three querysets below.
"""

from __future__ import annotations

from datetime import date

from apps.professional_development.approval_service import PDApprovalRoutingService
from apps.professional_development.models import (
    PDStatus,
    ProfessionalDevelopmentReminderLog,
    ProfessionalDevelopmentRequest,
)

# One event per reminder phase, because each is ended by a different
# transition (INTG-03). PDCourseTrackingService.sync_dates closes the first two
# when the course actually starts and ends; mark_complete /
# mark_deferred_or_withdrawn close the overdue chase.
PD_COURSE_STARTING = "pd_course_starting"
PD_COURSE_IN_PROGRESS = "pd_course_in_progress"
PD_COMPLETION_OVERDUE = "pd_completion_overdue"
PD_REMINDER_EVENTS = (
    PD_COURSE_STARTING,
    PD_COURSE_IN_PROGRESS,
    PD_COMPLETION_OVERDUE,
)


def _already_sent(req, key: str, today: date) -> bool:
    return ProfessionalDevelopmentReminderLog.objects.filter(
        request=req, reminder_key=key, sent_on=today
    ).exists()


def _log_sent(req, key: str, today: date) -> None:
    ProfessionalDevelopmentReminderLog.objects.get_or_create(
        request=req, reminder_key=key, sent_on=today
    )


def _notify(recipient_user_id, title, body, req, event_type=PD_COURSE_STARTING) -> bool:
    """Route through the central service, not a raw insert (INTG-03).

    This wrote `Notification.objects.create` with no `source_event_type`, so
    `resolve_condition` could never close it and the dedupe index could never
    match it. Every 7/3/1-day and every overdue reminder therefore stacked a
    fresh permanent "Action Required" row — 7/14/30 days overdue produced three
    for the employee and three each for the supervisor and HR — and the 48-hour
    escalation job promoted every one of them to urgent, which is how HR's
    urgent count stopped meaning anything (2026-08-20 HR audit).

    Each phase names its own event so the transition that ends it can close it:
    the course starting, the course ending, and the record being marked
    complete (see PDCourseTrackingService).
    """
    if not recipient_user_id:
        return False
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event_type,
            category="professional_development",
            priority="high",
            title=title,
            body=body,
            context_type="pd_request",
            context_id=req.id,
            recipients=[recipient_user_id],
        )
        return True
    except Exception:  # noqa: BLE001
        return False


def send_due_reminders() -> int:
    """Send every due PD reminder for today. Returns the count sent (also
    used as the ScheduledJobExecution.records_processed value)."""
    today = date.today()
    sent = 0

    # Advance the course clock first. `sync_dates` is the ONLY thing that moves
    # a record enrollment_confirmed → in_progress → ended, and its sole caller
    # was the employee's own My PD page. An employee who never reopened that
    # page left their record frozen at enrollment_confirmed forever: the
    # pre-course reminders stopped firing (the day count goes negative), the
    # in-progress and overdue escalations never began because the row never
    # reached those statuses, and the health checks keyed on ENDED never saw
    # it. Money disbursed, and no follow-up was possible.
    from apps.professional_development.completion_service import (
        PDCourseTrackingService,
    )

    for req in ProfessionalDevelopmentRequest.objects.filter(
        status__in=[PDStatus.ENROLLMENT_CONFIRMED, PDStatus.IN_PROGRESS]
    ):
        try:
            PDCourseTrackingService.sync_dates(req, today)
        except Exception:  # noqa: BLE001 - one bad row must not stop the run
            continue

    pre_course = ProfessionalDevelopmentRequest.objects.filter(
        status=PDStatus.ENROLLMENT_CONFIRMED
    )
    for req in pre_course:
        days = (req.start_date - today).days
        if days not in (7, 3, 1):
            continue
        key = f"pre_start_{days}"
        if _already_sent(req, key, today):
            continue
        if _notify(
            req.owner_user_id,
            "Your Professional Development course starts soon",
            f"“{req.course_name}” at {req.institution} starts in {days} "
            f"day{'s' if days != 1 else ''} ({req.start_date:%d %b %Y}).",
            req,
            PD_COURSE_STARTING,
        ):
            sent += 1
        _log_sent(req, key, today)

    in_progress = ProfessionalDevelopmentRequest.objects.filter(
        status=PDStatus.IN_PROGRESS
    )
    for req in in_progress:
        key = "in_progress_daily"
        if _already_sent(req, key, today):
            continue
        days_left = (req.end_date - today).days
        if _notify(
            req.owner_user_id,
            "Professional Development course in progress",
            f"“{req.course_name}” is in progress — "
            f"{days_left} day{'s' if days_left != 1 else ''} remaining.",
            req,
            PD_COURSE_IN_PROGRESS,
        ):
            sent += 1
        _log_sent(req, key, today)

    overdue = ProfessionalDevelopmentRequest.objects.filter(status=PDStatus.ENDED)
    for req in overdue:
        overdue_days = (today - req.end_date).days
        if overdue_days not in (7, 14, 30):
            continue
        key = f"overdue_{overdue_days}"
        if _already_sent(req, key, today):
            continue
        body = (
            f"“{req.course_name}” ended {overdue_days} days ago and has not "
            "been marked complete yet."
        )
        if _notify(
            req.owner_user_id,
            "Mark your Professional Development course complete",
            body,
            req,
            PD_COMPLETION_OVERDUE,
        ):
            sent += 1
        # Escalates to supervisor and HR from 14 days overdue onward.
        if overdue_days >= 14:
            from apps.accounts.models import StaffProfile

            staff = StaffProfile.objects.filter(id=req.staff_id).first()
            supervisor = (
                PDApprovalRoutingService.supervisor_for(staff) if staff else None
            )
            if supervisor:
                _notify(
                    supervisor.user_id,
                    "A team member's PD course is overdue for completion",
                    f"{req.staff_name} — {body}",
                    req,
                    PD_COMPLETION_OVERDUE,
                )
            try:
                from apps.accounts.models import User

                for hr in User.objects.filter(
                    roles__contains=["HumanResources"],
                    status="active",
                    deleted_at__isnull=True,
                ):
                    _notify(
                        hr.id,
                        "A PD course is overdue for completion",
                        f"{req.staff_name} — {body}",
                        req,
                        PD_COMPLETION_OVERDUE,
                    )
            except Exception:  # noqa: BLE001
                pass
        _log_sent(req, key, today)

    return sent
