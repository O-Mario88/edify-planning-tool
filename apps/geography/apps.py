from django.apps import AppConfig


class GeographyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.geography"
    label = "geography"
    verbose_name = "Edify Geography"

    def ready(self):
        """Restore this app's reference data whenever the schema is established.

        Django emits post_migrate after `flush` as well as after `migrate`, so
        rows a data migration created once come back after a TransactionTestCase
        truncates them. Without it the table stays empty for the rest of that
        database's life, and every read of it quietly returns nothing.
        """
        from django.db.models.signals import post_migrate

        post_migrate.connect(
            _ensure_reference_data,
            sender=self,
            dispatch_uid="edify_geography_reference_data",
        )


def _ensure_reference_data(sender, **kwargs):
    from apps.geography.subregions import sync

    # A no-op until geography is bootstrapped: sync() survives finding zero
    # districts, which is exactly the state a fresh or flushed database is in.
    sync()
