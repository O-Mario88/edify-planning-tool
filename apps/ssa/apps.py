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
