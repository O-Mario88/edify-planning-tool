from django.apps import AppConfig


class HelpCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.help_center"
    verbose_name = "Edify Knowledge Center"

    def ready(self):
        """Register this app's reference data.

        One receiver in apps.core runs every registration on post_migrate,
        which Django emits after `flush` as well as after `migrate` — so rows a
        data migration created once come back when a TransactionTestCase
        truncates them. See apps/core/reference_data.py for why the wiring
        lives there rather than here.
        """
        from apps.core import reference_data

        from .services import canonical_content_is_installed, ensure_canonical_content

        reference_data.register(
            "help_center", ensure_canonical_content, canonical_content_is_installed
        )
