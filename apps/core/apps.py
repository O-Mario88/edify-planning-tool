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

        if not getattr(settings, "IS_PRODUCTION", False):
            return
        command = sys.argv[1] if len(sys.argv) > 1 else None
        if command in _SKIP_BOOT_GATES_FOR_COMMANDS:
            return

        from apps.core import boot_gates

        boot_gates.verify_or_exit()
