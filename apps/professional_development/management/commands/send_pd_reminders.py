"""Send Professional Development reminders (§19).

Pre-course: 7 / 3 / 1 days before start_date, to the employee.
During course: one reminder per day while IN_PROGRESS, to the employee.
Post-course: escalating overdue reminders at 7 / 14 / 30 days after end_date
while the course is ENDED (not yet marked complete) — to the employee,
their supervisor, and HR.

Idempotent: `ProfessionalDevelopmentReminderLog` (unique per request + key +
day) guards every send, so running this command more than once on the same
day never double-notifies. Intended to be invoked once daily by an external
scheduler (cron); the command itself carries no scheduling logic.

Usage:
  python manage.py send_pd_reminders
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand

from apps.professional_development.approval_service import PDApprovalRoutingService
from apps.professional_development.models import (
    PDStatus,
    ProfessionalDevelopmentReminderLog,
    ProfessionalDevelopmentRequest,
)


def _already_sent(req, key: str, today: date) -> bool:
    return ProfessionalDevelopmentReminderLog.objects.filter(
        request=req, reminder_key=key, sent_on=today
    ).exists()


def _log_sent(req, key: str, today: date) -> None:
    ProfessionalDevelopmentReminderLog.objects.get_or_create(
        request=req, reminder_key=key, sent_on=today
    )


def _notify(recipient_user_id, title, body, req) -> bool:
    if not recipient_user_id:
        return False
    try:
        from apps.notifications.models import Notification

        Notification.objects.create(
            recipient_id=recipient_user_id, title=title, body=body,
            category="professional_development", context_type="pd_request",
            context_id=req.id, target_route=f"/my-professional-development/request?id={req.id}",
            action_label="Open", action_required=True, priority="high",
        )
        return True
    except Exception:  # noqa: BLE001
        return False


class Command(BaseCommand):
    help = "Send due Professional Development reminders (pre-course, in-progress, overdue escalation)."

    def handle(self, *args, **options):
        today = date.today()
        sent = 0

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
                req.owner_user_id, "Your Professional Development course starts soon",
                f"“{req.course_name}” at {req.institution} starts in {days} "
                f"day{'s' if days != 1 else ''} ({req.start_date:%d %b %Y}).", req,
            ):
                sent += 1
            _log_sent(req, key, today)

        in_progress = ProfessionalDevelopmentRequest.objects.filter(status=PDStatus.IN_PROGRESS)
        for req in in_progress:
            key = "in_progress_daily"
            if _already_sent(req, key, today):
                continue
            days_left = (req.end_date - today).days
            if _notify(
                req.owner_user_id, "Professional Development course in progress",
                f"“{req.course_name}” is in progress — "
                f"{days_left} day{'s' if days_left != 1 else ''} remaining.", req,
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
            if _notify(req.owner_user_id, "Mark your Professional Development course complete", body, req):
                sent += 1
            # Escalates to supervisor and HR from 14 days overdue onward.
            if overdue_days >= 14:
                from apps.accounts.models import StaffProfile

                staff = StaffProfile.objects.filter(id=req.staff_id).first()
                supervisor = PDApprovalRoutingService.supervisor_for(staff) if staff else None
                if supervisor:
                    _notify(
                        supervisor.user_id, "A team member's PD course is overdue for completion",
                        f"{req.staff_name} — {body}", req,
                    )
                try:
                    from apps.accounts.models import User

                    for hr in User.objects.filter(
                        roles__contains=["HumanResources"], status="active", deleted_at__isnull=True
                    ):
                        _notify(hr.id, "A PD course is overdue for completion",
                                f"{req.staff_name} — {body}", req)
                except Exception:  # noqa: BLE001
                    pass
            _log_sent(req, key, today)

        self.stdout.write(self.style.SUCCESS(f"Sent {sent} Professional Development reminder(s)."))
