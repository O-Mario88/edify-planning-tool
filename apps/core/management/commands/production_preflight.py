"""Run fail-closed checks after Django initialization and before serving."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.core import boot_gates
from apps.system_health.environment_guard import (
    EnvironmentMismatch,
    validate_environment,
)


class Command(BaseCommand):
    help = "Verify database identity, migrations, and static assets before boot."

    def handle(self, *args, **options):
        if not getattr(settings, "IS_PRODUCTION", False):
            raise CommandError("production_preflight requires production settings")

        try:
            environment_status = validate_environment(force=True)
        except EnvironmentMismatch as exc:
            raise CommandError(str(exc)) from exc

        if environment_status == "unavailable":
            raise CommandError(
                "Could not validate the database environment stamp; refusing boot."
            )

        boot_gates.verify_or_exit()
        self.stdout.write(
            self.style.SUCCESS(
                "Production preflight passed "
                f"(database environment: {environment_status})."
            )
        )
