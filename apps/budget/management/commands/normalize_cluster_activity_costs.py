"""Repair mutable cluster cost snapshots after the canonical recipe changed.

This is intentionally a one-off, conservative data repair.  It re-prices only
scheduled cluster activities whose cost-line keys are not the canonical recipe,
then lets the existing scheduling pipeline rebuild associated *draft* weekly
and monthly requests.  Anything that has entered the finance approval/payment
flow is left untouched and reported for an amendment workflow.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.budget.costing import (
    CLUSTER_MEETING_SNACK_RATE_KEY,
    CLUSTER_MEETING_TYPES,
    CLUSTER_TRAINING_TYPES,
    GROUP_TRAINING_RATE_KEYS,
)
from apps.core.exceptions import BadRequest


_HISTORIC_PARTICIPANT_KEYS = {
    CLUSTER_MEETING_SNACK_RATE_KEY,
    "group_training_participant_meal_cost_per_head",
    "cluster_meeting_cost",
    "meals_per_participant",
    "mobilisation_per_participant",
}


def _participant_count(
    activity: Activity, lines: list[ActivityScheduleCostLine]
) -> int:
    actual = sum(
        int(value or 0)
        for value in (
            activity.teachers_attended,
            activity.leaders_attended,
            activity.other_participants,
        )
    )
    if actual:
        return actual
    if activity.expected_participants:
        return int(activity.expected_participants)
    return max(
        (
            int(line.quantity or 0)
            for line in lines
            if line.cost_setting_key in _HISTORIC_PARTICIPANT_KEYS
        ),
        default=0,
    )


class Command(BaseCommand):
    help = (
        "Reprice mutable cluster meetings and trainings with the fixed snack/"
        "meal/facilitation/venue recipe and refresh their draft fund requests."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fy",
            help="Only repair activities in this fiscal year (for example 2026).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be repaired without changing data.",
        )

    def handle(self, *args, **options):
        queryset = Activity.objects.filter(
            deleted_at__isnull=True,
            scheduled_date__isnull=False,
            activity_type__in=sorted(CLUSTER_TRAINING_TYPES | CLUSTER_MEETING_TYPES),
        ).order_by("scheduled_date")
        if options["fy"]:
            queryset = queryset.filter(fy=options["fy"])

        repaired = skipped_missing_people = skipped_locked = already_current = 0
        dry_run = options["dry_run"]
        for activity in queryset:
            lines = list(ActivityScheduleCostLine.objects.filter(activity=activity))
            expected_keys = (
                {CLUSTER_MEETING_SNACK_RATE_KEY}
                if activity.activity_type in CLUSTER_MEETING_TYPES
                else set(GROUP_TRAINING_RATE_KEYS)
            )
            current_keys = {line.cost_setting_key for line in lines}
            people = _participant_count(activity, lines)
            needs_repair = (
                current_keys != expected_keys
                or activity.cost_missing
                or int(activity.expected_participants or 0) != people
            )
            if not needs_repair:
                already_current += 1
                continue
            if not people:
                skipped_missing_people += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"Skipped {activity.id}: no participant count is available."
                    )
                )
                continue
            if dry_run:
                self.stdout.write(
                    f"Would reprice {activity.id} ({activity.activity_type}) for {people} participant(s)."
                )
                repaired += 1
                continue

            # Reuse the live scheduling path so advances, weekly requests and
            # monthly draft requests remain in sync with the repaired snapshot.
            from apps.activities.services import _apply_schedule_cost_snapshot

            try:
                _apply_schedule_cost_snapshot(
                    activity,
                    {"expectedParticipants": people},
                )
            except BadRequest as exc:
                skipped_locked += 1
                self.stdout.write(self.style.WARNING(f"Skipped {activity.id}: {exc}"))
                continue
            activity.expected_participants = people
            activity.save(update_fields=["expected_participants", "updated_at"])
            repaired += 1
            self.stdout.write(
                self.style.SUCCESS(
                    f"Repriced {activity.id} ({activity.activity_type}) for {people} participant(s)."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Cluster cost normalization complete: "
                f"{repaired} repaired, {already_current} already current, "
                f"{skipped_missing_people} skipped without a headcount, "
                f"{skipped_locked} skipped because finance is locked."
            )
        )
