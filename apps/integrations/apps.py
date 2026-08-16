from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.integrations"
    label = "integrations"
    verbose_name = "Edify External Integrations"

    def ready(self):
        # Handler registration only — module import wires the outbox handlers.
        # No queries, no scheduler, nothing that touches the database here.
        from . import services  # noqa: F401
