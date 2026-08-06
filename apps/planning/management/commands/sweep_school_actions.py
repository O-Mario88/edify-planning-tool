"""Run the school-action sweep by hand, and report what it would change.

The hourly job (`school_action_sweep`) does this automatically. This command
exists for the two cases the job cannot serve: checking, before trusting the
automation, that resolution agrees with reality; and catching up after the
scheduler has been down.

Dry-run by default. `--apply` writes.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.planning.action_models import ACTIVE_STATES, ActionState, TeamAction
from apps.planning.action_service import (
    condition_still_holds,
    mark_overdue_actions,
    resolve_due_actions,
)


class Command(BaseCommand):
    help = "Close school actions whose condition has cleared; flag overdue ones."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Write the changes. Without this the command only reports.",
        )

    def handle(self, *args, **options):
        apply = options["apply"]
        active = TeamAction.objects.filter(state__in=ACTIVE_STATES)
        total = active.count()

        if not apply:
            from django.utils import timezone

            today = timezone.localdate()
            clearable, still_open, unevaluable = [], 0, 0
            for action in active.iterator():
                try:
                    if condition_still_holds(action):
                        still_open += 1
                    else:
                        clearable.append(action)
                except Exception as exc:  # noqa: BLE001
                    unevaluable += 1
                    self.stderr.write(f"  ! {action.id}: {exc}")

            would_overdue = (
                active.filter(due_date__lt=today)
                .exclude(state__in=[ActionState.OVERDUE, ActionState.ESCALATED])
                .count()
            )

            self.stdout.write(f"Active actions:        {total}")
            self.stdout.write(f"Would be resolved:     {len(clearable)}")
            self.stdout.write(f"Would become overdue:  {would_overdue}")
            self.stdout.write(f"Still genuinely open:  {still_open}")
            if unevaluable:
                self.stdout.write(
                    self.style.WARNING(f"Could not evaluate:    {unevaluable}")
                )
            for action in clearable[:20]:
                self.stdout.write(
                    f"  → {action.issue_type} @ {action.school_id} "
                    f"(sent {action.created_at:%-d %b})"
                )
            if len(clearable) > 20:
                self.stdout.write(f"  … and {len(clearable) - 20} more")
            self.stdout.write("\nDry run. Re-run with --apply to write.")
            return

        resolved = resolve_due_actions()
        overdue = mark_overdue_actions()
        self.stdout.write(
            self.style.SUCCESS(
                f"Checked {resolved['checked']}, resolved {resolved['resolved']}, "
                f"marked overdue {overdue['overdue']}."
            )
        )
