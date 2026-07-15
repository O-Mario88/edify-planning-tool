"""The ONE dedicated scheduler process. Run this as its own deployment
service/process — never inside a web worker (see apps/realtime/apps.py for
why). Blocks in the foreground until terminated (SIGTERM/SIGINT), so a
process supervisor (Railway, systemd, Docker) can manage it exactly like any
other long-running service.

Usage:
  python manage.py runscheduler

Deployment: see docs/scheduler-deployment.md and the `worker` entry in
Procfile. Requires ENABLE_BACKGROUND_JOBS=true in THIS process's
environment; refuses to start otherwise (loudly, not silently) unless
--allow-disabled is passed for local debugging.
"""

from __future__ import annotations

import logging
import signal
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger("edify.jobs")


class Command(BaseCommand):
    help = "Run the dedicated background-job scheduler process (one per deployment, never per web worker)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--allow-disabled",
            action="store_true",
            help="Start even if ENABLE_BACKGROUND_JOBS is false (local debugging only).",
        )

    def handle(self, *args, **options):
        if (
            not getattr(settings, "ENABLE_BACKGROUND_JOBS", False)
            and not options["allow_disabled"]
        ):
            raise CommandError(
                "ENABLE_BACKGROUND_JOBS is not set on this process. Refusing to start an "
                "idle scheduler silently -- set ENABLE_BACKGROUND_JOBS=true on the worker "
                "service's environment, or pass --allow-disabled for local debugging."
            )

        from django_apscheduler.jobstores import DjangoJobStore
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        from apps.realtime import jobs
        from apps.realtime.registry import JOB_REGISTRY

        job_funcs = {
            "weekly_fund_request": jobs.weekly_fund_request_job,
            "monthly_work_plan": jobs.monthly_work_plan_job,
            "notification_escalation": jobs.notification_escalation_job,
            "daily_digest": jobs.daily_digest_job,
            "target_ledger_sync": jobs.target_ledger_sync_job,
            "pd_reminders": jobs.pd_reminders_job,
            "field_debrief_recurring_issues": jobs.field_debrief_recurring_issues_job,
        }

        scheduler = BackgroundScheduler(timezone="Africa/Kampala")
        scheduler.add_jobstore(DjangoJobStore(), "default")
        for spec in JOB_REGISTRY:
            func = job_funcs.get(spec.name)
            if func is None:
                raise CommandError(
                    f"JOB_REGISTRY entry '{spec.name}' has no matching function in apps.realtime.jobs."
                )
            scheduler.add_job(
                func,
                CronTrigger(**spec.cron_kwargs),
                id=spec.name,
                replace_existing=True,
            )
            self.stdout.write(f"  registered: {spec.name:32s} {spec.cron}")

        scheduler.start()
        self.stdout.write(
            self.style.SUCCESS(
                f"Scheduler started with {len(JOB_REGISTRY)} job(s). ENABLE_BACKGROUND_JOBS="
                f"{getattr(settings, 'ENABLE_BACKGROUND_JOBS', False)}. Blocking until terminated."
            )
        )
        logger.info("Scheduler process started (pid=%s).", __import__("os").getpid())

        stop = {"flag": False}

        def _handle_signal(signum, _frame):
            logger.info("Scheduler received signal %s -- shutting down.", signum)
            stop["flag"] = True

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)

        try:
            while not stop["flag"]:
                time.sleep(1)
        finally:
            scheduler.shutdown(wait=True)
            self.stdout.write("Scheduler stopped.")
