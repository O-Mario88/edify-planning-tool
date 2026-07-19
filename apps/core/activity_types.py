"""Canonical groupings of ActivityType.

Nine modules each declared their own ``VISIT_TYPES`` and nine their own
``TRAINING_TYPES``, and they disagreed: visits ranged from 4 members
(frontend/views/staff_views) to 15 (budget/costing, projects/my_plan_service).
The same question therefore had different answers depending on which page
asked it -- ``budget/costing`` counts 154 activities as visits where
``analytics`` counts 150, because only the former treats
``school_visit_ssa_collection`` as a visit.

That gap is currently invisible on completed-work counts, because the four
``school_visit_ssa_collection`` rows in the database are still ``scheduled``.
It becomes visible the moment they are completed, which is exactly the kind of
divergence that surfaces as "the dashboard and the budget page disagree" long
after the cause was introduced.

These groupings are derived from ``ActivityType`` rather than retyped, so a new
member of the enum cannot silently fall outside every group: ``check()``
asserts that every ActivityType is classified exactly once.

Where a module genuinely needs a different population, it must name that
difference (``COSTED_VISIT_TYPES``, say) rather than redefining ``VISIT_TYPES``
to mean something local. A metric that means two things needs two names.
"""

from __future__ import annotations

from apps.core.enums import ActivityType

# Field contact with a school. Everything here puts a person on a school site.
VISIT_TYPES: tuple[str, ...] = (
    ActivityType.SCHOOL_VISIT,
    ActivityType.FOLLOW_UP_VISIT,
    ActivityType.COACHING_VISIT,
    ActivityType.IN_SCHOOL_SUPPORT,
    ActivityType.DONOR_VISIT,
    ActivityType.STORY_GATHERING_VISIT,
    ActivityType.SCHOOL_INVITATION,
    ActivityType.SOCIAL_VISIT,
    ActivityType.TRAINING_FOLLOW_UP_VISIT,
    ActivityType.IN_SCHOOL_COACHING_VISIT,
    ActivityType.CORE_VISIT,
    ActivityType.BASELINE_SSA_VISIT,
    ActivityType.SCHOOL_VISIT_SSA_COLLECTION,
)

# Structured delivery to teachers or school leaders.
TRAINING_TYPES: tuple[str, ...] = (
    ActivityType.TRAINING,
    ActivityType.IN_SCHOOL_TRAINING,
    ActivityType.SCHOOL_IMPROVEMENT_TRAINING,
    ActivityType.CLUSTER_TRAINING,
    ActivityType.CORE_TRAINING,
    ActivityType.CLUSTER_TRAINING_SSA_COLLECTION,
)

# Convening a cluster rather than visiting a single school.
CLUSTER_MEETING_TYPES: tuple[str, ...] = (
    ActivityType.CLUSTER_MEETING,
    ActivityType.CLUSTER_MEETING_SSA_REVIEW,
)

# Assessment work that is not itself a school visit.
SSA_TYPES: tuple[str, ...] = (ActivityType.SSA_ACTIVITY,)


def _remaining() -> tuple[str, ...]:
    grouped = set(VISIT_TYPES) | set(TRAINING_TYPES) | set(CLUSTER_MEETING_TYPES) | set(SSA_TYPES)
    return tuple(v for v in ActivityType.values if v not in grouped)


# Everything the groups above do not claim: project, partner and any future
# type. Named rather than left implicit so check() can prove the cover.
OTHER_TYPES: tuple[str, ...] = _remaining()


def check() -> None:
    """Every ActivityType is classified exactly once.

    Without this a new enum member silently belongs to no group, and whichever
    metric was supposed to count it quietly under-reports for as long as
    nobody checks.
    """
    groups = {
        "VISIT_TYPES": VISIT_TYPES,
        "TRAINING_TYPES": TRAINING_TYPES,
        "CLUSTER_MEETING_TYPES": CLUSTER_MEETING_TYPES,
        "SSA_TYPES": SSA_TYPES,
        "OTHER_TYPES": OTHER_TYPES,
    }
    seen: dict[str, str] = {}
    for name, members in groups.items():
        for value in members:
            if value in seen:
                raise ValueError(
                    f"{value!r} is in both {seen[value]} and {name}; an "
                    f"activity type must belong to exactly one group"
                )
            seen[value] = name
    missing = set(ActivityType.values) - set(seen)
    if missing:
        raise ValueError(
            f"unclassified ActivityType(s): {sorted(missing)} -- add them to a "
            f"group in apps/core/activity_types.py"
        )
