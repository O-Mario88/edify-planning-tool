from django.apps import AppConfig


class GeographyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.geography"
    label = "geography"
    verbose_name = "Edify Geography"

    def ready(self):
        """Register this app's reference data.

        One receiver in apps.core runs every registration on post_migrate,
        which Django emits after `flush` as well as after `migrate` — so rows a
        data migration created once come back when a TransactionTestCase
        truncates them. See apps/core/reference_data.py for why the wiring
        lives there rather than here.
        """
        from apps.core import reference_data

        from apps.geography.ubos_registry import ensure_geography_reference

        # A no-op until geography is bootstrapped. Once districts exist, the
        # same registered function restores statistical sub-regions and adds
        # any missing current UBOS sub-county identities.
        reference_data.register("geography", ensure_geography_reference)
