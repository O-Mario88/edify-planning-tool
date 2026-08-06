"""Deliberately re-stamp this database's environment identity.

The ONLY sanctioned way to change a database's environment stamp — used for
legitimate promotions (staging clone → production) or repairing a wrong
first stamp. Requires a typed confirmation phrase so it can never happen by
reflex, and writes the tamper-evident audit chain.

Usage:
    manage.py stamp_environment --to production
    (then type:  STAMP production  when prompted)
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.system_health.models import EnvironmentStamp


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument(
            "--to", required=True, choices=EnvironmentStamp.ENVIRONMENTS
        )
        parser.add_argument(
            "--confirm",
            default=None,
            help='The phrase "STAMP <env>" (prompted interactively if omitted).',
        )

    def handle(self, *args, **options):
        target = options["to"]
        phrase = options["confirm"]
        expected = f"STAMP {target}"
        if phrase is None:
            phrase = input(f'Type "{expected}" to re-stamp this database: ')
        if phrase != expected:
            raise CommandError(
                f'Confirmation phrase mismatch — expected "{expected}". '
                "The stamp was NOT changed."
            )

        stamp, _created = EnvironmentStamp.objects.get_or_create(
            id=EnvironmentStamp.SINGLETON_ID,
            defaults={"environment": target, "stamped_by": "stamp_environment"},
        )
        previous = stamp.environment
        stamp.environment = target
        stamp.stamped_by = "stamp_environment"
        stamp.stamped_at = timezone.now()
        stamp.save()

        try:
            from apps.audit.services import log as audit_log

            audit_log(
                action="environment.restamped",
                subject_kind="EnvironmentStamp",
                subject_id=str(stamp.id),
                actor_id="cli",
                actor_role="operator",
                success=True,
                payload={"from": previous, "to": target},
            )
        except Exception:  # pragma: no cover
            pass

        self.stdout.write(
            self.style.SUCCESS(
                f"Database re-stamped: '{previous}' → '{target}'. "
                "Processes whose ENVIRONMENT disagrees will now refuse to run."
            )
        )
