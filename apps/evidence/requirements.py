"""EvidenceRequirementService — required evidence by activity type (§G).

Before this, the completion gate accepted ANY single non-quarantined file for
every activity type — one arbitrary photo satisfied a training's attendance
requirement. Requirements are declared per activity type against the
canonical EvidenceKind vocabulary; unlisted types keep the baseline rule
(at least one non-quarantined file of any kind) so new activity types fail
safe rather than blocking.
"""

from __future__ import annotations

from apps.core.enums import EvidenceKind

# activity_type → list of required EvidenceKind values. Every listed kind
# must be present (non-quarantined) before completion may be submitted.
# THE two-form law (owner, 2026-08-19): every activity's required evidence is
# either the VISIT FORM (all school-visit work) or the TRAINING ATTENDANCE
# form (all trainings and cluster meetings). No third form exists; both are
# PDFs (enforced at upload).
REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    # School visits: the visit form is the proof of presence.
    "school_visit": (EvidenceKind.VISIT_FORM,),
    "follow_up_visit": (EvidenceKind.VISIT_FORM,),
    "coaching_visit": (EvidenceKind.VISIT_FORM,),
    "in_school_support": (EvidenceKind.VISIT_FORM,),
    "donor_visit": (EvidenceKind.VISIT_FORM,),
    "story_gathering_visit": (EvidenceKind.VISIT_FORM,),
    "school_invitation": (EvidenceKind.VISIT_FORM,),
    "social_visit": (EvidenceKind.VISIT_FORM,),
    "training_follow_up_visit": (EvidenceKind.VISIT_FORM,),
    "in_school_coaching_visit": (EvidenceKind.VISIT_FORM,),
    "core_visit": (EvidenceKind.VISIT_FORM,),
    "school_visit_ssa_collection": (EvidenceKind.VISIT_FORM,),
    "core_assessment_visit": (EvidenceKind.VISIT_FORM,),
    "project_activity": (EvidenceKind.VISIT_FORM,),
    # Trainings and cluster sessions: attendance is the proof of delivery.
    "training": (EvidenceKind.ATTENDANCE_FORM,),
    "in_school_training": (EvidenceKind.ATTENDANCE_FORM,),
    "school_improvement_training": (EvidenceKind.ATTENDANCE_FORM,),
    "cluster_training": (EvidenceKind.ATTENDANCE_FORM,),
    "core_training": (EvidenceKind.ATTENDANCE_FORM,),
    "cluster_meeting": (EvidenceKind.ATTENDANCE_FORM,),
    "cluster_meeting_ssa_review": (EvidenceKind.ATTENDANCE_FORM,),
}

PROFILE_REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    "TRAINING_ATTENDANCE": (EvidenceKind.ATTENDANCE_FORM,),
    "SCHOOL_VISIT_FORM": (EvidenceKind.VISIT_FORM,),
    "FOLLOW_UP_MEETING": (EvidenceKind.ATTENDANCE_FORM,),
    "YOUTH_CAMP_SAFEGUARDING": (EvidenceKind.ATTENDANCE_FORM,),
    "SSA_DATA_GATHERING": (EvidenceKind.VISIT_FORM,),
    "ADMIN_NONE": (),
}

_LABELS = dict(EvidenceKind.choices)


def required_kinds(activity_type: str) -> tuple[str, ...]:
    return REQUIRED_EVIDENCE.get(activity_type, ())


def required_kinds_for_activity(activity) -> tuple[str, ...]:
    profile = getattr(activity, "evidence_profile_snapshot", None)
    if profile in PROFILE_REQUIRED_EVIDENCE:
        return PROFILE_REQUIRED_EVIDENCE[profile]
    return required_kinds(activity.activity_type)


def evidence_optional(activity) -> bool:
    return getattr(activity, "evidence_profile_snapshot", None) == "ADMIN_NONE"


def _present_kinds(activity) -> set[str]:
    """Which evidence kinds this activity already has, prefetch-aware.

    A caller looping over many activities can prefetch the non-quarantined
    evidence into `_unquarantined_evidence` (see apps/my_plan/day_package.py);
    using it here turns one query per activity into none. Without the
    attribute the behaviour is unchanged.
    """
    cached = getattr(activity, "_unquarantined_evidence", None)
    if cached is not None:
        return {record.kind for record in cached}
    return set(
        activity.evidence.filter(quarantined=False).values_list("kind", flat=True)
    )


def missing_evidence_kinds(activity) -> list[dict]:
    """Which required kinds are absent (non-quarantined) for this activity.
    Empty list = requirement satisfied. Types with no specific requirement
    fall back to the baseline any-file rule enforced by the caller."""
    needed = required_kinds_for_activity(activity)
    if not needed:
        return []
    present = _present_kinds(activity)
    return [
        {"kind": kind, "label": _LABELS.get(kind, kind)}
        for kind in needed
        if kind not in present
    ]


def checklist(activity) -> list[dict]:
    """Full checklist for the frontend: every required kind with its state."""
    needed = required_kinds_for_activity(activity)
    present = set(
        activity.evidence.filter(quarantined=False).values_list("kind", flat=True)
    )
    return [
        {
            "kind": kind,
            "label": _LABELS.get(kind, kind),
            "uploaded": kind in present,
        }
        for kind in needed
    ]
