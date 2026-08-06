from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Edify Core"

    def ready(self):
        from django.db.models.signals import post_migrate

        # Importing registers the drf-spectacular authentication extension.
        from apps.core import openapi  # noqa: F401

        # Reference data, for every app that registered any. Connected with
        # sender=self so it runs once per migrate/flush rather than once per
        # installed app, and the registry is read when the signal fires — by
        # which time every other AppConfig.ready() has run and registered.
        #
        # Django emits post_migrate after `flush` as well as after `migrate`,
        # which is the whole point: a TransactionTestCase truncates every table
        # and this is what puts the required rows back.
        post_migrate.connect(
            _restore_reference_data,
            sender=self,
            dispatch_uid="edify_core_reference_data",
        )


def _restore_reference_data(sender, **kwargs):
    from apps.core import reference_data

    reference_data.restore_all()
