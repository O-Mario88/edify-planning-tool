"""Exits non-zero when background automation is unhealthy -- for use as a
Docker/Kubernetes/Railway health probe on the worker service, or a manual
ops check. Prints a human-readable summary either way.

Usage:
  python manage.py scheduler_health_check
  echo $?   # 0 = healthy, 1 = unhealthy
"""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.realtime.registry import SchedulerHealthService


class Command(BaseCommand):
    help = "Check background-job scheduler health; exits non-zero when unhealthy."

    def handle(self, *args, **options):
        enabled = bool(getattr(settings, "ENABLE_BACKGROUND_JOBS", False))
        if not enabled:
            self.stdout.write(
                self.style.ERROR(
                    "ENABLE_BACKGROUND_JOBS is false -- background automation is OFF."
                )
            )
            raise SystemExit(1)

        jobs = SchedulerHealthService.all_jobs_health()
        unhealthy = [j for j in jobs if j["severity"] != "ok"]

        for j in jobs:
            marker = (
                self.style.SUCCESS("OK")
                if j["severity"] == "ok"
                else self.style.ERROR(j["status"].upper())
            )
            self.stdout.write(
                f"  {j['job_name']:32s} {marker:20s} last_successful={j['last_successful']} "
                f"failures={j['failure_count']}"
            )

        if not SchedulerHealthService.is_scheduler_process_alive():
            self.stdout.write(
                self.style.ERROR(
                    "No job has started recently -- the scheduler process itself may be down."
                )
            )
            raise SystemExit(1)

        if unhealthy:
            self.stdout.write(
                self.style.ERROR(f"{len(unhealthy)}/{len(jobs)} job(s) unhealthy.")
            )
            raise SystemExit(1)

        self.stdout.write(self.style.SUCCESS(f"All {len(jobs)} job(s) healthy."))
