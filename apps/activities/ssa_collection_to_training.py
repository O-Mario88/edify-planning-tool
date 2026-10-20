"""School Visit + SSA Collection visits become In-school Training + SSA
Collection (owner, 2026-10-20).

"make sure all those who used "school visit + ssa collection" are changed to
In-school training + SSA Collection and they should be able to fetch the
training from the system. Everything should be updated on the training
summary, school visits ... everywhere." Asked, the owner chose: visits already
completed (with the lead, verified, counted) stay as they are; the change is
listed by a dry run first (``convert_ssa_collection_visits``) and applied by a
migration (``activities.0069``).

A School Visit + SSA Collection names no training, so none can be created for
it here. Each one still on the plan — planned, scheduled, rescheduled, or
started and not submitted (``editing.EDITABLE_STATUSES`` and
``BEGUN_STATUSES``, the ones whose purpose may still change) — is given the
purpose In-school Training + SSA Collection and so *awaits its training*
(``awaits_training``): its Complete and Edit drawers open on that purpose and
ask which training was delivered, fetched from the Training Catalogue; the
training is then created beside the visit as its pair
(``planning.services.pair_training_with_visit``) and is counted wherever a
training is, the Training Summary included. Until a training is named the
visit cannot be completed (``assert_training_named``), so none is completed
past it. An officer whose visit only collected the SSA chooses SSA Support in
the drawer instead.

Nothing about the visit moves now but its name and purpose: it reads
In-school Training + SSA Collection wherever it is listed, and its workflow,
its price and its day stay until the training is named. A partner's SSA collection is the partner's and
is not touched; work returned for correction is not a plan and is left, as is
completed work. Each change is written to the audit trail.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest
from apps.partners.purposes import IN_SCHOOL_TRAINING_PURPOSES, IN_SCHOOL_TRAINING_SSA

SOURCE_TYPE = "school_visit_ssa_collection"
NEW_NAME = "In-school Training + SSA Collection"
REASON = (
    "School Visit + SSA Collection is now In-school Training + SSA Collection: "
    "name the training delivered when completing it (owner, 2026-10-20)."
)


def _open_statuses() -> frozenset:
    from apps.activities.editing import BEGUN_STATUSES, EDITABLE_STATUSES

    return EDITABLE_STATUSES | BEGUN_STATUSES


def _visits(Activity):
    """Every staff School Visit + SSA Collection at a school, not yet given
    the new purpose."""
    return Activity.objects.filter(
        activity_type=SOURCE_TYPE,
        delivery_type="staff",
        school_id__isnull=False,
        deleted_at__isnull=True,
    ).exclude(purpose_type=IN_SCHOOL_TRAINING_SSA)


def to_convert(Activity):
    """The visits the change applies to: still on the plan."""
    return _visits(Activity).filter(status__in=_open_statuses())


def left_as_they_are(Activity):
    """The ones it leaves: completed, with a reviewer, returned, cancelled."""
    return _visits(Activity).exclude(status__in=_open_statuses())


def anything_to_convert(apps) -> bool:
    """Whether the migration has work, read with the historical model so a
    database with none (a fresh install, the test database) never reaches the
    live code in ``convert``."""
    return to_convert(apps.get_model("activities", "Activity")).exists()


def convert(*, apply: bool, actor_id: str = "system") -> dict:
    """List, and with ``apply`` change, the visits. Returns ``converted``
    (rows changed, or that would be) and ``left`` (rows left as they are)."""
    from django.db import transaction

    from apps.activities.models import Activity
    from apps.audit.services import log as audit_log

    def row(activity) -> dict:
        return {
            "id": activity.id,
            "school": activity.school.name if activity.school_id else "",
            "schoolId": activity.school.school_id if activity.school_id else "",
            "day": activity.planned_date.isoformat() if activity.planned_date else "",
            "status": activity.status,
            "purposeBefore": activity.purpose_type or "",
            "responsibleStaffId": activity.responsible_staff_id or "",
        }

    found = list(to_convert(Activity).select_related("school").order_by("id"))
    left = [
        row(a)
        for a in left_as_they_are(Activity).select_related("school").order_by("id")
    ]
    converted = [row(a) for a in found]
    if not apply:
        return {"converted": converted, "left": left}
    with transaction.atomic():
        for activity in found:
            # Named as it is now everywhere a visit is listed by its name;
            # the training named later gives the pair its own names.
            Activity.objects.filter(pk=activity.pk).update(
                purpose_type=IN_SCHOOL_TRAINING_SSA,
                ssa_collection_expected=True,
                activity_name_snapshot=NEW_NAME,
            )
            audit_log(
                action="activity.purpose_changed",
                subject_kind="Activity",
                subject_id=str(activity.id),
                actor_id=actor_id,
                reason=REASON,
                payload={
                    "from": {
                        "purposeType": activity.purpose_type,
                        "activityType": activity.activity_type,
                        "name": activity.activity_name_snapshot,
                    },
                    "to": {
                        "purposeType": IN_SCHOOL_TRAINING_SSA,
                        "name": NEW_NAME,
                        "activityType": activity.activity_type,
                        "awaitsTraining": True,
                    },
                },
            )
    return {"converted": converted, "left": left}


def awaits_training(activity) -> bool:
    """A visit given an In-school Training purpose whose training is not yet
    named: no training is paired with it."""
    from apps.activities.models import Activity

    return bool(
        (activity.purpose_type or "") in IN_SCHOOL_TRAINING_PURPOSES
        and (activity.activity_type or "") != "in_school_training"
        and not Activity.objects.filter(
            paired_school_visit_id=activity.id, deleted_at__isnull=True
        ).exists()
    )


def awaiting_training_q():
    """``awaits_training`` as a filter: a visit with an In-school Training
    purpose and no training paired with it."""
    from django.db.models import Q

    return (
        Q(purpose_type__in=tuple(IN_SCHOOL_TRAINING_PURPOSES))
        & ~Q(activity_type="in_school_training")
        & Q(paired_in_school_training__isnull=True)
    )


def assert_training_named(activity) -> None:
    """Refuse to complete a visit that awaits its training, at every door."""
    if awaits_training(activity):
        raise BadRequest(
            "This visit is an In-school Training + SSA Collection. Open "
            "Complete, choose the training delivered from the list, and enter "
            "the training's ID and the visit's ID. If only the SSA was "
            "collected, choose SSA Support as the purpose instead."
        )


__all__ = [
    "anything_to_convert",
    "assert_training_named",
    "awaiting_training_q",
    "awaits_training",
    "convert",
    "left_as_they_are",
    "to_convert",
]
