"""Canonical visit-purpose choices for staff and delivery partners.

``Activity.activity_type`` remains the operational/costing classification.
This module describes *why* a school visit is taking place.  Keeping the two
concepts separate lets the Partner Activities workspace speak plainly without
breaking cost rules, calendars, or reports that depend on activity type.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest


# The forms of support Edify can delegate to a delivery partner. These values
# are deliberately stable database values — the LABEL may be reworded, the
# left-hand value may not.
#
PARTNER_VISIT_PURPOSES: tuple[tuple[str, str], ...] = (
    ("in_school_training", "In-school Training"),
    ("training_follow_up", "Training Follow Up"),
    ("ssa_support", "SSA Support"),
)

# Staff may deliver the delegated support above, as well as the operational
# visit reasons that are not delegable to partner organisations.
#
# Content/Story Collection returned to this list on the owner's brief of
# 2026-09-21, which names it among the purposes a cluster may schedule in
# bulk. It was staff-only before it was withdrawn and it is staff-only now:
# PARTNER_VISIT_PURPOSES is unchanged, so a partner still cannot be handed
# one.
STAFF_VISIT_PURPOSES: tuple[tuple[str, str], ...] = (
    *PARTNER_VISIT_PURPOSES,
    ("donor_visit", "Donor Visit"),
    ("story_gathering", "Content/Story Collection"),
    ("school_invitation", "School Invitation"),
    ("social_visit", "Social Visit"),
    ("in_school_coaching", "In-school Coaching Visit"),
)

# The purposes a cluster roster may schedule for several member schools on one
# day (owner, 2026-09-21). In-school Training is deliberately absent: it pairs
# a governed course with its own companion visit and is chosen one school at a
# time. The order is the owner's.
CLUSTER_BULK_VISIT_PURPOSES: tuple[tuple[str, str], ...] = (
    ("training_follow_up", "Training Follow Up"),
    ("ssa_support", "SSA Support"),
    ("donor_visit", "Donor Visit"),
    ("story_gathering", "Content/Story Collection"),
)

#: The most member schools a cluster bulk schedule may name for one day.
#:
#: This was a FLOOR of five (owner, 2026-09-21: "a minimum of 5 schools per
#: day"), and the floor turned out to describe the exception rather than the
#: work: "some people are planning 4, other 3, other 2 and other 1 — make sure
#: every plan" (owner, 2026-09-22). So five is now the ceiling. One school is a
#: legitimate day and is planned here like any other; six is not a day's route,
#: and is refused rather than quietly written.
CLUSTER_BULK_MAXIMUM_SCHOOLS = 5

# Purposes that move no single SSA intervention: collecting the SSA itself and
# relationship visits. A visit for one of these may name a focus, but its
# governed workflow must not demand one (Core visits inherit theirs otherwise).
INTERVENTION_FREE_PURPOSES = frozenset(
    {
        "ssa_support",
        "donor_visit",
        "story_gathering",
        "school_invitation",
        "social_visit",
    }
)

PURPOSE_ACTIVITY_TYPES = {
    "in_school_training": "in_school_training",
    "training_follow_up": "training_follow_up_visit",
    "ssa_support": "school_visit_ssa_collection",
    "donor_visit": "donor_visit",
    "story_gathering": "story_gathering_visit",
    "school_invitation": "school_invitation",
    "social_visit": "social_visit",
    "in_school_coaching": "in_school_coaching_visit",
}

_PARTNER_VALUES = {value for value, _label in PARTNER_VISIT_PURPOSES}
_STAFF_VALUES = {value for value, _label in STAFF_VISIT_PURPOSES}
_BULK_VALUES = {value for value, _label in CLUSTER_BULK_VISIT_PURPOSES}
_LABELS = {
    **{value: label for value, label in STAFF_VISIT_PURPOSES},
    "in_school_training_delivery_visit": "In-school Training Delivery Visit",
}


def visit_purpose_label(value: str | None, fallback: str = "—") -> str:
    """Return a plain-language label suitable for a staff-facing table."""
    return _LABELS.get(str(value or ""), fallback)


def purpose_activity_type(value: str | None, fallback: str = "school_visit") -> str:
    """Map a purpose to the existing operational activity type."""
    return PURPOSE_ACTIVITY_TYPES.get(str(value or ""), fallback)


def normalise_visit_purpose(
    value: str | None,
    *,
    for_partner: bool,
    fallback_activity_type: str | None = None,
) -> str:
    """Validate a purpose and safely bridge older assignment submissions.

    New forms make the selection mandatory.  The fallback retains compatibility
    with existing API clients and historic automated submissions while still
    producing one of the three partner-safe values.
    """
    purpose = str(value or "").strip()
    allowed = _PARTNER_VALUES if for_partner else _STAFF_VALUES
    if not purpose:
        return _fallback_for_activity_type(fallback_activity_type, for_partner)
    if purpose not in allowed:
        audience = "a delivery partner" if for_partner else "a staff member"
        raise BadRequest(
            f"{visit_purpose_label(purpose, purpose)} cannot be assigned to {audience}."
        )
    return purpose


def normalise_cluster_bulk_purpose(value: str | None) -> str:
    """Validate a purpose chosen for a cluster's bulk day schedule.

    Refuses by name rather than falling back. A bulk schedule writes the same
    purpose to every school it names, so guessing one is the one place a
    silent default would be expensive.
    """
    purpose = str(value or "").strip()
    if not purpose:
        raise BadRequest("Choose what this day of visits is for.")
    if purpose == "in_school_training":
        raise BadRequest(
            "In-school Training is scheduled one school at a time, from that "
            "school's own Schedule drawer — it pairs a governed course with "
            "its companion visit."
        )
    if purpose not in _BULK_VALUES:
        raise BadRequest(
            f"{visit_purpose_label(purpose, purpose)} cannot be scheduled for "
            "a cluster's schools in bulk."
        )
    return purpose


def _fallback_for_activity_type(activity_type: str | None, for_partner: bool) -> str:
    """Give legacy posts a meaningful purpose until their UI is refreshed."""
    activity_type = str(activity_type or "")
    by_type = {
        "in_school_training": "in_school_training",
        "training": "in_school_training",
        "school_improvement_training": "in_school_training",
        "training_follow_up_visit": "training_follow_up",
        "donor_visit": "donor_visit",
        "story_gathering_visit": "story_gathering",
        "school_invitation": "school_invitation",
        "social_visit": "social_visit",
        "in_school_coaching_visit": "in_school_coaching",
    }
    fallback = by_type.get(activity_type, "ssa_support")
    return fallback if not for_partner or fallback in _PARTNER_VALUES else "ssa_support"


__all__ = [
    "CLUSTER_BULK_MAXIMUM_SCHOOLS",
    "CLUSTER_BULK_VISIT_PURPOSES",
    "INTERVENTION_FREE_PURPOSES",
    "PARTNER_VISIT_PURPOSES",
    "STAFF_VISIT_PURPOSES",
    "normalise_cluster_bulk_purpose",
    "normalise_visit_purpose",
    "purpose_activity_type",
    "visit_purpose_label",
]
