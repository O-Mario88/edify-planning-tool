from django.apps import AppConfig


class SsaConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.ssa"
    label = "ssa"
    verbose_name = "Edify SSA"

    def ready(self):
        # Registration only: importing the handler binds it to its event type
        # and touches no database.
        from . import handlers  # noqa: F401
        from . import signals  # noqa: F401

        # Project baselines are filled when an SSA is confirmed or imported
        # (IA review, 2026-09-13); the SSA side enqueues the event, so it
        # registers its handler too.
        from apps.projects import baselines  # noqa: F401
