"""A visit that collects the SSA is complete once its school's SSA is in.

Owner, 2026-10-17: "if the visit purpose was to collect data (e.g. core school
SSA Support or SSA support), It is not complete until the SSA scores are
entered so the status should say "Awaiting SSA Scores" and Action is "Enter
SSA Scores" ... There are two ways of entering SSA, Upload of ssa data or
manual entry ... if the ssa is uploaded and reflected, the status should
change to complete and green."

Collecting: the visit was scheduled to collect the SSA
(``ssa_collection_expected``), its purpose is SSA Support, or its kind is an
SSA collection — the three signals a partner's SSA Support is recognised by
(apps.activities.services.is_partner_ssa_support_activity).

In: the school has a record holding the visit's year, pending or confirmed
(apps.ssa.creation.HOLDING_STATUSES), however it came — keyed in the
completion drawer, entered from the profile or from this action, or uploaded.
A returned or flagged record leaves the year open, so the visit waits again.
A Champion school takes no SSA (apps.planning.country_oversight.rules), so
its visit never waits.

A read: two signals on the activity and one query for a page of them.
"""

from __future__ import annotations

from typing import Iterable

AWAITING_SSA_LABEL = "Awaiting SSA Scores"
AWAITING_SSA_CLASS = "bg-amber-50 text-amber-700 border-amber-200"
ENTER_SSA_TEXT = "Enter SSA Scores"


def collects_ssa(activity) -> bool:
    """Whether ``activity`` is a school visit made to collect the SSA."""
    from apps.activities.services import PARTNER_SSA_SUPPORT_ACTIVITY_TYPES

    return bool(
        activity.school_id
        and (
            activity.ssa_collection_expected
            or activity.purpose_type == "ssa_support"
            or activity.activity_type in PARTNER_SSA_SUPPORT_ACTIVITY_TYPES
        )
    )


def _takes_ssa(activity) -> bool:
    from apps.planning.country_oversight.rules import takes_ssa

    school = activity.school
    return takes_ssa(school.school_type if school else None)


def awaiting_scores(activities: Iterable) -> set[str]:
    """The ids of the completed SSA visits among ``activities`` whose school
    has no SSA holding the visit's year. One query, whatever the count."""
    from apps.activities.completion_columns import is_officer_completed
    from apps.ssa.creation import HOLDING_STATUSES
    from apps.ssa.models import SsaRecord

    waiting = [
        a
        for a in activities
        if is_officer_completed(a.status) and collects_ssa(a) and _takes_ssa(a)
    ]
    if not waiting:
        return set()
    held = set(
        SsaRecord.objects.filter(
            school_id__in={a.school_id for a in waiting},
            fy__in={str(a.fy) for a in waiting},
            deleted_at__isnull=True,
            verification_status__in=HOLDING_STATUSES,
        ).values_list("school_id", "fy")
    )
    return {a.id for a in waiting if (a.school_id, str(a.fy)) not in held}


def enter_scores_action(activity) -> dict:
    """My Plan's next action for a visit awaiting its scores: the profile's
    SSA drawer, keyed on this visit."""
    return {
        "text": ENTER_SSA_TEXT,
        "action": "ssa",
        "url": f"/schools/{activity.school_id}/ssa-entry?activity={activity.id}",
        "description": "SSA scores not entered",
    }


__all__ = [
    "AWAITING_SSA_CLASS",
    "AWAITING_SSA_LABEL",
    "ENTER_SSA_TEXT",
    "awaiting_scores",
    "collects_ssa",
    "enter_scores_action",
]
