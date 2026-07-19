"""Canonical visit-purpose choices for staff and delivery partners.

``Activity.activity_type`` remains the operational/costing classification.
This module describes *why* a school visit is taking place.  Keeping the two
concepts separate lets the Partner Activities workspace speak plainly without
breaking cost rules, calendars, or reports that depend on activity type.
"""

from __future__ import annotations

from apps.core.exceptions import BadRequest


# Delivery partners only receive the three forms of support that Edify can
# delegate to them.  These values are deliberately stable database values.
PARTNER_VISIT_PURPOSES: tuple[tuple[str, str], ...] = (
    ("in_school_training", "In-school Training"),
    ("training_follow_up", "Training Follow Up"),
    ("ssa_support", "SSA Support"),
)

# Staff may deliver the delegated support above, as well as the operational
# visit reasons that are not delegable to partner organisations.
STAFF_VISIT_PURPOSES: tuple[tuple[str, str], ...] = (
    *PARTNER_VISIT_PURPOSES,
    ("donor_visit", "Donor Visit"),
    ("story_gathering", "Story Gathering"),
    ("school_invitation", "School Invitation"),
    ("social_visit", "Social Visit"),
    ("in_school_coaching", "In-school Coaching Visit"),
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
_LABELS = {value: label for value, label in STAFF_VISIT_PURPOSES}


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
    "PARTNER_VISIT_PURPOSES",
    "STAFF_VISIT_PURPOSES",
    "normalise_visit_purpose",
    "purpose_activity_type",
    "visit_purpose_label",
]
