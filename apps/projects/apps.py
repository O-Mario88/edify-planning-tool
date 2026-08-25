from django.apps import AppConfig


class ProjectsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.projects"
    label = "projects"
    verbose_name = "Edify Projects"

    def ready(self):
        # Registration only. The outbox handler and the two event bridges do
        # not query at import time, and the enqueue rides the surrounding
        # transaction so a source write and its projection commit together.
        from . import handlers, signals  # noqa: F401
