"""Send Professional Development reminders (§19).

CLI entry point for apps.professional_development.reminders.send_due_reminders
— the canonical implementation, also invoked automatically every day by the
scheduled job (apps.realtime.jobs.pd_reminders_job) once
ENABLE_BACKGROUND_JOBS is on and the scheduler worker process is running.
Kept as a standalone command for manual/CI/one-off invocation.

Usage:
  python manage.py send_pd_reminders
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.professional_development.reminders import send_due_reminders


class Command(BaseCommand):
    help = "Send due Professional Development reminders (pre-course, in-progress, overdue escalation)."

    def handle(self, *args, **options):
        sent = send_due_reminders()
        self.stdout.write(
            self.style.SUCCESS(f"Sent {sent} Professional Development reminder(s).")
        )
