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
pairs scheduled before the change (activities migration 0061, within the
deploy's time limit, and the ``move_in_school_training_cost_to_visit`` command
for a dry run or whatever the migration left).
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


#: What a page writes beside the UGX 0 of a pair's Training (owner,
#: 2026-10-05: "since in-school training is done during school visit, it is
#: ok to keep it at UGX 0 just add (captured in the school visit cost)").
CAPTURED_IN_VISIT_NOTE = "(captured in the school visit cost)"
#: A pair scheduled before 2026-09-28 whose money had already moved is the
#: other way round: its Training carries the cost and its visit is at 0.
CAPTURED_IN_TRAINING_NOTE = "(captured in the in-school training cost)"


def pair_cost_notes(activities) -> dict[str, str]:
    """The note to write beside the UGX 0 half of each in-school Training /
    School Visit pair among ``activities``, by activity id.

    One half of a pair carries the day's cost and the other carries none, by
    design, so a page that looks for work nobody has priced asks here before
    calling the empty half uncosted (the Work Plan read every pair Training
    as "Cost setup required"). A half with no cost lines that is missing
    from the result has no priced other half either: that pair is unpriced.

    ``activities`` are read with ``schedule_cost_lines`` prefetched, as the
    Work Plan and My Plan load them. Nothing is queried unless a pair's
    other half is outside the list, or a School Visit in it has no lines.
    """
    from django.db.models import Exists, OuterRef

    from apps.activities.models import Activity, ActivityScheduleCostLine

    activities = list(activities)
    by_id = {activity.id: activity for activity in activities}

    def has_lines(activity) -> bool:
        return bool(list(activity.schedule_cost_lines.all()))

    # (training id, visit id) for every pair with a half in the list.
    pairs = {
        (activity.id, activity.paired_school_visit_id)
        for activity in activities
        if is_uncosted_pair_training(activity)
    }
    paired_visits = {visit_id for _training_id, visit_id in pairs}
    bare_visits = [
        activity.id
        for activity in activities
        if activity.activity_type == "school_visit"
        and activity.id not in paired_visits
        and not has_lines(activity)
    ]
    if bare_visits:
        pairs.update(
            (training_id, visit_id)
            for visit_id, training_id in Activity.objects.filter(
                paired_school_visit_id__in=bare_visits,
                activity_type="in_school_training",
                deleted_at__isnull=True,
            ).values_list("paired_school_visit_id", "id")
        )
    if not pairs:
        return {}

    priced = {
        activity.id
        for activity in activities
        if not activity.cost_missing and has_lines(activity)
    }
    outside = {half for pair in pairs for half in pair} - set(by_id)
    if outside:
        priced.update(
            Activity.objects.filter(
                Exists(
                    ActivityScheduleCostLine.objects.filter(activity_id=OuterRef("pk"))
                ),
                id__in=outside,
                cost_missing=False,
            ).values_list("id", flat=True)
        )

    notes: dict[str, str] = {}
    for training_id, visit_id in pairs:
        training, visit = by_id.get(training_id), by_id.get(visit_id)
        if training is not None and not has_lines(training) and visit_id in priced:
            notes[training_id] = CAPTURED_IN_VISIT_NOTE
        elif visit is not None and not has_lines(visit) and training_id in priced:
            notes[visit_id] = CAPTURED_IN_TRAINING_NOTE
    return notes


def find_pair_trainings_carrying_cost(apps=None) -> list[str]:
    """Ids of undelivered pair Trainings that still carry cost lines.

    Takes the migration's historical ``apps`` so the migration can ask
    without touching live models; the command passes nothing."""
    from django.db.models import Exists, OuterRef

    if apps is not None:
        Activity = apps.get_model("activities", "Activity")
        CostLine = apps.get_model("activities", "ActivityScheduleCostLine")
    else:
        from apps.activities.models import Activity
        from apps.activities.models import ActivityScheduleCostLine as CostLine

    # A partner facilitator's fee is the one line a pair Training keeps
    # (owner, 2026-09-29; apps.activities.facilitation): not visit cost.
    visit_cost = CostLine.objects.filter(activity_id=OuterRef("pk")).exclude(
        line_item_type="facilitation"
    )
    return list(
        Activity.objects.filter(
            UNCOSTED_PAIR_TRAINING,
            Exists(visit_cost),
            deleted_at__isnull=True,
            scheduled_date__isnull=False,
            status__in=MOVABLE_STATUSES,
        )
        .distinct()
        .order_by("id")
        .values_list("id", flat=True)
    )


def move_pair_costs_to_visits(ids=None, *, write=print, deadline=None) -> dict:
    """Re-price each pair Training: it drops to 0 and its School Visit takes
    the visit cost (``_apply_schedule_cost_snapshot`` does both).

    A pair whose money has already moved, or whose day has left draft, is
    refused by the cost writer's finance locks; it is reported and left as
    it is rather than failing the rest.

    ``deadline`` is a ``time.monotonic()`` value after which no further pair
    is started; the pairs not reached are returned as ``left`` and still
    carry their cost, so a later run finds them again."""
    import time

    from django.db import transaction

    from apps.activities.models import Activity
    from apps.activities.services import reprice_activity
    from apps.core.exceptions import BadRequest

    ids = find_pair_trainings_carrying_cost() if ids is None else list(ids)
    moved: list[str] = []
    skipped: list[str] = []
    left: list[str] = []
    for training in Activity.objects.filter(id__in=ids).order_by("id"):
        if deadline is not None and time.monotonic() >= deadline:
            left.append(training.id)
            continue
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
    return {"moved": moved, "skipped": skipped, "left": left}
