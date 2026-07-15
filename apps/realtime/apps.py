from django.apps import AppConfig


class RealtimeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.realtime"
    label = "realtime"
    verbose_name = "Edify Realtime"

    def ready(self) -> None:
        # IMPORTANT: the scheduler must NEVER start here. AppConfig.ready()
        # runs once per Django process -- including every web worker (each
        # Gunicorn/Daphne process, each horizontally-scaled replica). If the
        # scheduler were started here, N web workers would each run their
        # own copy of every job, firing weekly fund requests, digests, and
        # target-ledger rebuilds N times over. This used to be exactly that
        # bug (see git history) -- it's why ENABLE_BACKGROUND_JOBS has
        # stayed False in every environment.
        #
        # The scheduler now runs in exactly one dedicated process, started
        # explicitly via `python manage.py runscheduler` (see
        # apps/realtime/management/commands/runscheduler.py) -- a separate
        # deployment service/process from the web app, never launched as a
        # side effect of importing Django. See docs/scheduler-deployment.md.
        return
