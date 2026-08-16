import json

from django.core.management.base import BaseCommand

from apps.outbox.models import OutboxEvent, OutboxStatus
from apps.outbox.services import requeue_dead


class Command(BaseCommand):
    help = (
        "Replay dead-lettered outbox events after their cause is fixed. "
        "With no arguments, lists the dead events; --all or --ids replays."
    )

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--ids", nargs="*", default=None)

    def handle(self, *args, **options):
        if options["all"]:
            count = requeue_dead()
        elif options["ids"]:
            count = requeue_dead(options["ids"])
        else:
            rows = [
                {
                    "id": event.id,
                    "eventType": event.event_type,
                    "attempts": event.attempts,
                    "lastError": event.last_error[:200],
                }
                for event in OutboxEvent.objects.filter(
                    status=OutboxStatus.DEAD
                ).order_by("created_at")[:50]
            ]
            self.stdout.write(json.dumps({"dead": rows}, indent=2))
            return
        self.stdout.write(json.dumps({"requeued": count}))
