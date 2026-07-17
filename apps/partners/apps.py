from django.apps import AppConfig


class PartnersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.partners"
    label = "partners"
    verbose_name = "Edify Partners"

    def ready(self):
        from apps.partners import signals  # noqa: F401 — register receivers
