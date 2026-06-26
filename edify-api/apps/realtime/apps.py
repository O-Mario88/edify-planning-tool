from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.realtime"
    label = "realtime"
    verbose_name = "Edify Realtime"

    def ready(self) -> None:
        # Register the 4 background jobs with django-apscheduler. Each job
        # early-returns unless ENABLE_BACKGROUND_JOBS is true (single-process
        # worker replica gate, mirroring the NestJS @Cron guard).
        from django.conf import settings

        if not getattr(settings, "ENABLE_BACKGROUND_JOBS", False):
            return
        try:
            from django_apscheduler.jobstores import DjangoJobStore
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger

            from . import jobs

            scheduler = BackgroundScheduler(timezone="Africa/Kampala")
            scheduler.add_jobstore(DjangoJobStore(), "default")
            # Weekly fund-request: Friday 06:00.
            scheduler.add_job(jobs.weekly_fund_request_job, CronTrigger(day_of_week="fri", hour=6),
                              id="weekly_fund_request", replace_existing=True)
            # Monthly work-plan budget: 25th 06:00.
            scheduler.add_job(jobs.monthly_work_plan_job, CronTrigger(day=25, hour=6),
                              id="monthly_work_plan", replace_existing=True)
            # Notification escalation: hourly.
            scheduler.add_job(jobs.notification_escalation_job, CronTrigger(minute=0),
                              id="notification_escalation", replace_existing=True)
            # Daily digest: 07:30.
            scheduler.add_job(jobs.daily_digest_job, CronTrigger(hour=7, minute=30),
                              id="daily_digest", replace_existing=True)
            scheduler.start()
        except Exception:  # noqa: BLE001 — scheduler must never break boot
            import logging
            logging.getLogger("edify.jobs").warning("Scheduler did not start (background jobs disabled).")
