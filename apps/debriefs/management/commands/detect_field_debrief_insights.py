"""Scan recent Field Debriefs for recurring issues (§15).

Idempotent: re-running the same day just refreshes each open insight's
occurrence count and window rather than duplicating it. Nothing in-app
schedules this — an external cron/scheduler must call it daily, matching
`send_pd_reminders` in apps.professional_development.

Usage:
  python manage.py detect_field_debrief_insights
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.debriefs.insight_service import RecurringIssueDetectionService


class Command(BaseCommand):
    help = "Scan recent Field Debriefs for recurring issues and escalate cross-team/cross-country patterns."

    def handle(self, *args, **options):
        result = RecurringIssueDetectionService.scan()
        self.stdout.write(
            self.style.SUCCESS(
                f"Insight scan complete: {result['created']} created, {result['updated']} updated "
                f"(window {result['window_start']} to {result['window_end']})."
            )
        )
