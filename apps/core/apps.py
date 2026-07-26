import sys

from django.apps import AppConfig

# Commands that legitimately manage or introspect the DB schema themselves —
# running the boot gates (apps.core.boot_gates) here would either be
# redundant (migrate is literally about to resolve "pending migrations") or
# actively wrong (makemigrations/dbshell have no business being blocked by
# collectstatic state). Only the actual server process (gunicorn/daphne
# workers, `runserver`) gets gated.
_SKIP_BOOT_GATES_FOR_COMMANDS = {
    "migrate",
    "makemigrations",
    "shell",
    "shell_plus",
    "dbshell",
    "check",
    "test",
    "showmigrations",
    "collectstatic",
    "seed",
}


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    label = "core"
    verbose_name = "Edify Core"

    def ready(self):
        from django.conf import settings
        from django.db.models.signals import post_migrate

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

        if not getattr(settings, "IS_PRODUCTION", False):
            return
        command = sys.argv[1] if len(sys.argv) > 1 else None
        if command in _SKIP_BOOT_GATES_FOR_COMMANDS:
            return

        from apps.core import boot_gates

        boot_gates.verify_or_exit()


def _restore_reference_data(sender, **kwargs):
    from apps.core import reference_data

    reference_data.restore_all()
