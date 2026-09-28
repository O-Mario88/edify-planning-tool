"""An in-school Training and its companion School Visit cost one school visit.

Owner, 2026-09-28: "in-school training should register both visits and
training on the same day and use the visit cost. training cost for in-school
training should be 0 since it is part of school visit and the school visit is
already costed."

``apps.planning.services.schedule_in_school_training_pair`` turns one planning
decision into two records on the same day: the Training (TS-) and its School
Visit (SVE-). The School Visit is the journey, so it carries the cost — the
visit day shared with every other school the officer visits that day, or the
partner visit rate — and the Training carries none. Until 2026-09-28 it was
the other way round: the Training was priced (at the visit recipe) and the
visit was the uncosted twin. Pricing the Training ran it through the funded
scheduling gate, which is how an in-school training could be refused for a
participant count the drawer never asks for.

``UNCOSTED_PAIR_TRAINING`` is the one definition every "priced work" reader
uses to leave the Training out: fund requests, the day pools, the costing
repair and the missing-cost health checks. An in-school training with no
companion visit (the Core Schools training drawer, a partner's dated
assignment) is still the only record of its journey and keeps the visit cost.

``find_pair_trainings_carrying_cost`` and ``move_pair_costs_to_visits`` move
pairs scheduled before the change (activities migration 0060, and the
``move_in_school_training_cost_to_visit`` command for a dry run).
"""

from __future__ import annotations

from django.db.models import Q

#: The Training of an in-school Training / School Visit pair.
UNCOSTED_PAIR_TRAINING = Q(
    activity_type="in_school_training", paired_school_visit__isnull=False
)

#: Pair work not yet delivered. Its cost is a plan the owner may still move;
#: delivered and settled work is history and keeps the lines it was paid on.
MOVABLE_STATUSES = (
    "planned",
    "scheduled",
    "rescheduled",
    "assigned_to_partner",
    "partner_scheduled",
)


def is_uncosted_pair_training(activity) -> bool:
    return activity.activity_type == "in_school_training" and bool(
        activity.paired_school_visit_id
    )


def find_pair_trainings_carrying_cost(apps=None) -> list[str]:
    """Ids of undelivered pair Trainings that still carry cost lines.

    Takes the migration's historical ``apps`` so the migration can ask
    without touching live models; the command passes nothing."""
    if apps is not None:
        Activity = apps.get_model("activities", "Activity")
    else:
        from apps.activities.models import Activity

    return list(
        Activity.objects.filter(
            UNCOSTED_PAIR_TRAINING,
            deleted_at__isnull=True,
            scheduled_date__isnull=False,
            status__in=MOVABLE_STATUSES,
            schedule_cost_lines__isnull=False,
        )
        .distinct()
        .order_by("id")
        .values_list("id", flat=True)
    )


def move_pair_costs_to_visits(ids=None, *, write=print) -> dict:
    """Re-price each pair Training: it drops to 0 and its School Visit takes
    the visit cost (``_apply_schedule_cost_snapshot`` does both).

    A pair whose money has already moved, or whose day has left draft, is
    refused by the cost writer's finance locks; it is reported and left as
    it is rather than failing the rest."""
    from django.db import transaction

    from apps.activities.models import Activity
    from apps.activities.services import reprice_activity
    from apps.core.exceptions import BadRequest

    ids = find_pair_trainings_carrying_cost() if ids is None else list(ids)
    moved: list[str] = []
    skipped: list[str] = []
    for training in Activity.objects.filter(id__in=ids).order_by("id"):
        try:
            with transaction.atomic():
                reprice_activity(training)
        except BadRequest as exc:
            skipped.append(training.id)
            write(
                f"  kept {training.id} (visit {training.paired_school_visit_id}): "
                f"{getattr(exc, 'detail', exc)}"
            )
            continue
        moved.append(training.id)
        write(f"  moved {training.id} -> visit {training.paired_school_visit_id}")
    return {"moved": moved, "skipped": skipped}
