from django.apps import AppConfig


class DocumentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.documents"
    verbose_name = "Document Library and Policy Compliance"

    def ready(self):
        # Registration only: binds the sign-in receiver, touches no database.
        from . import signals  # noqa: F401
