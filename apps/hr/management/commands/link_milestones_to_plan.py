"""Link the priorities to the plan, both ways — idempotently.

THE DEFECT THIS FIXES (owner, 2026-09-07)

"Add activity rules to the milestones so the bars actually fill."

A milestone's progress is read from the activities that match its rules
(milestone_plan_progress). Two things kept every bar empty:

  1. Only eleven of the sixty-eight FY2027 milestones had a rule — the
     curriculum ones. The shape-of-work milestones (every school visit, every
     cluster meeting, every training, SSA coverage) had nothing to match.
     ACTIVITY_MAPPINGS now names their standard-support items; this command
     re-runs the seeder, which is create-only and so adds the missing rules
     without touching a defined or approved milestone.

  2. A rule matches on the activity's catalogue item — and 274 of the 277
     activities carried none. Work scheduled through the drawer is stamped at
     creation; seeded and imported history never was. This resolves each one
     the way the drawer would (the standard item for its kind, on its planned
     date; a partner activity takes the item its assignment named) and stamps
     it through apply_catalogue_snapshot, so the link carries the same
     version, snapshots and intervention a fresh schedule would.

What it will not do: invent a target. A milestone's target is the RVP's
decision in Define metric; the bar shows real counts as soon as the rule
exists, and a percentage the moment a target does.
"""

from __future__ import annotations

import json
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Add activity rules to the milestones and link historical activities to the catalogue."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--actor-id", default="management-command")
        parser.add_argument(
            "--skip-rules", action="store_true", help="Only backfill activity links."
        )
        parser.add_argument(
            "--skip-activities", action="store_true", help="Only add milestone rules."
        )

    def handle(self, *args, **options):
        report = {"dryRun": options["dry_run"]}
        if not options["skip_rules"]:
            report["rules"] = link_milestone_rules(
                actor_id=options["actor_id"], dry_run=options["dry_run"]
            )
        if not options["skip_activities"]:
            report["activities"] = link_activities_to_catalogue(
                dry_run=options["dry_run"]
            )
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))


def link_milestone_rules(*, actor_id: str = "system", dry_run: bool = False) -> dict:
    """The seeder's rule pass, on whatever cycle already exists."""

    from apps.hr.models import MilestoneActivityRule
    from apps.hr.priority_seeding import seed_fy2027_priorities

    before = MilestoneActivityRule.objects.filter(active=True).count()
    if dry_run:
        with transaction.atomic():
            seed_fy2027_priorities(actor_id=actor_id, dry_run=False)
            after = MilestoneActivityRule.objects.filter(active=True).count()
            transaction.set_rollback(True)
    else:
        seed_fy2027_priorities(actor_id=actor_id, dry_run=False)
        after = MilestoneActivityRule.objects.filter(active=True).count()
    return {"before": before, "after": after, "added": after - before}


def link_activities_to_catalogue(*, dry_run: bool = False) -> dict:
    """Stamp a catalogue item onto every activity that has none and can have one."""

    from apps.activities.models import Activity
    from apps.activity_catalogue.services import (
        apply_catalogue_snapshot,
        resolve_item_for_workflow_kind,
    )
    from apps.core.exceptions import BadRequest
    from apps.partners.models import PartnerAssignment

    linked: Counter = Counter()
    skipped: Counter = Counter()
    unlinked = Activity.objects.filter(
        deleted_at__isnull=True, catalogue_item__isnull=True
    ).select_related("school")

    def resolve(activity):
        if activity.activity_type == "partner_activity":
            assignment = (
                PartnerAssignment.objects.filter(scheduled_activity_id=activity.id)
                .select_related("catalogue_item")
                .first()
            )
            if assignment and assignment.catalogue_item_id:
                return assignment.catalogue_item, "assignment"
            return None, "partner activity with no assigned catalogue item"
        item = resolve_item_for_workflow_kind(
            activity.activity_type, on_date=activity.planned_date
        )
        if item is None:
            return None, "no single standard item for this kind"
        return item, "standard item"

    with transaction.atomic():
        for activity in unlinked.iterator():
            item, why = resolve(activity)
            if item is None:
                skipped[f"{activity.activity_type}: {why}"] += 1
                continue
            try:
                apply_catalogue_snapshot(
                    activity,
                    item=item,
                    requested_intervention=activity.focus_intervention or None,
                    recommendation_reason="Linked to the catalogue by link_milestones_to_plan",
                )
            except BadRequest as exc:
                skipped[f"{activity.activity_type}: {exc.detail}"] += 1
                continue
            activity.save()
            linked[f"{activity.activity_type} -> {item.stable_code}"] += 1
        if dry_run:
            transaction.set_rollback(True)
    return {
        "linked": dict(linked),
        "linkedTotal": sum(linked.values()),
        "skipped": dict(skipped),
        "skippedTotal": sum(skipped.values()),
    }
