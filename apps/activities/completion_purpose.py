"""The purpose a school visit was made for, chosen as it is completed.

Owner, 2026-10-20: "the activity completion drawer should have all the
options for purpose (SSA support, In-school training, Training Follow up)".
An officer completing a visit says what it was for, and the visit takes that
purpose before it is completed, so its completion asks what that purpose
needs:

* SSA Support — the eight SSA scores, or that none were collected; the
  visit's ID.
* Training Follow Up — the training it followed up; the visit's ID.
* In-school Training, or In-school Training + SSA Collection — which training
  was delivered; the training is created beside the visit as its pair
  (``planning.services.pair_training_with_visit``) and both are completed with
  their own IDs. With SSA Collection the visit collects the school's SSA, its
  scores taken in the same drawer (owner, 2026-10-20: "so there is in school
  training and then inschool training + ssa collection as a seperate
  option").

SSA Support and Training Follow Up are changed on the visit in place, the way
its Edit drawer changes them (``editing.edit`` → ``purpose_change``): the
same activity, re-priced where its workflow moves, audited. The visits that
may change purpose are the ones Edit lets change (``purpose_change.
may_change_purpose``); a Core package visit holds one of its package's two
visit purposes, so it is offered those two.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest

__all__ = [
    "apply_completion_purpose",
    "completion_purpose_options",
    "current_purpose",
]

#: The purposes a completed visit may be given, in the owner's order.
COMPLETION_PURPOSES = (
    "ssa_support",
    "in_school_training",
    "in_school_training_ssa",
    "training_follow_up",
)


def current_purpose(activity) -> str:
    """The purpose the visit holds: the one recorded, else the one its
    workflow is planned under (a "School Visit + SSA Collection" is SSA
    Support), else, for a Core package visit, SSA Support, as an unnamed
    package visit has always been read. Choosing it again changes nothing."""
    from apps.partners.purposes import PURPOSE_ACTIVITY_TYPES

    if activity.purpose_type:
        return activity.purpose_type
    if (activity.activity_type or "") == "core_visit":
        return "ssa_support"
    return next(
        (
            purpose
            for purpose, workflow in PURPOSE_ACTIVITY_TYPES.items()
            if workflow == activity.activity_type
        ),
        "",
    )


def completion_purpose_options(activity) -> list[tuple[str, str]]:
    """The purposes the Complete drawer offers this visit, or none when the
    visit is not one whose purpose decides what it is: the three, as Edit
    names them (``purpose_change.purpose_options``). A purpose it already
    holds outside the three (a donor visit) is offered first, so completing
    it does not change it."""
    from apps.activities.purpose_change import purpose_options

    offered = purpose_options(activity)
    current = current_purpose(activity)
    return [
        (value, label)
        for value, label in offered
        if value == current and value not in COMPLETION_PURPOSES
    ] + sorted(
        ((value, label) for value, label in offered if value in COMPLETION_PURPOSES),
        key=lambda option: COMPLETION_PURPOSES.index(option[0]),
    )


def apply_completion_purpose(activity, purpose, principal, *, course_id="") -> bool:
    """Give ``activity`` the purpose chosen in the Complete drawer, as its
    Edit drawer gives it (``editing.edit``: the same checks, the same money
    take-back, the same audit). Returns whether anything changed; a refusal
    changes nothing.

    Call inside the completion's transaction, so a completion refused after
    the purpose moved leaves the visit as it was."""
    from apps.activities.ssa_collection_to_training import awaits_training
    from apps.partners.purposes import IN_SCHOOL_TRAINING_PURPOSES

    purpose = str(purpose or "").strip()
    if not purpose:
        return False
    # A visit that already reads In-school Training + SSA Collection still
    # needs its training named (apps.activities.ssa_collection_to_training).
    pairs_now = purpose in IN_SCHOOL_TRAINING_PURPOSES and awaits_training(activity)
    if purpose == current_purpose(activity) and not pairs_now:
        return False
    if pairs_now and not str(course_id or "").strip():
        raise BadRequest("Select the training delivered on this visit.")
    offered = dict(completion_purpose_options(activity))
    if purpose not in offered:
        raise BadRequest("Choose one of the purposes offered for this visit.")
    from apps.activities.editing import edit

    edit(
        activity.id,
        {
            "purposeType": purpose,
            "purposeTrainingCourseId": course_id,
            "reason": f"Completed as {offered[purpose]}",
        },
        principal,
    )
    return True
