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
REQUIRED_EVIDENCE: dict[str, tuple[str, ...]] = {
    # School visits: the visit form is the proof of presence.
    "school_visit": (EvidenceKind.VISIT_FORM,),
    "follow_up_visit": (EvidenceKind.VISIT_FORM,),
    "coaching_visit": (EvidenceKind.VISIT_FORM,),
    "in_school_support": (EvidenceKind.VISIT_FORM,),
    "core_visit": (EvidenceKind.VISIT_FORM,),
    # Trainings: attendance is the proof of delivery.
    "training": (EvidenceKind.ATTENDANCE_FORM,),
    "school_improvement_training": (EvidenceKind.ATTENDANCE_FORM,),
    "cluster_training": (EvidenceKind.ATTENDANCE_FORM,),
    "core_training": (EvidenceKind.ATTENDANCE_FORM,),
    # Cluster meetings: minutes.
    "cluster_meeting": (EvidenceKind.MEETING_MINUTES,),
    "cluster_meeting_ssa_review": (EvidenceKind.MEETING_MINUTES,),
    # Core assessment: the assessment form.
    "core_assessment_visit": (EvidenceKind.ASSESSMENT_FORM,),
    # Special projects: the project report.
    "project_activity": (EvidenceKind.PROJECT_REPORT,),
}

_LABELS = dict(EvidenceKind.choices)


def required_kinds(activity_type: str) -> tuple[str, ...]:
    return REQUIRED_EVIDENCE.get(activity_type, ())


def missing_evidence_kinds(activity) -> list[dict]:
    """Which required kinds are absent (non-quarantined) for this activity.
    Empty list = requirement satisfied. Types with no specific requirement
    fall back to the baseline any-file rule enforced by the caller."""
    needed = required_kinds(activity.activity_type)
    if not needed:
        return []
    present = set(
        activity.evidence.filter(quarantined=False).values_list("kind", flat=True)
    )
    return [
        {"kind": kind, "label": _LABELS.get(kind, kind)}
        for kind in needed
        if kind not in present
    ]


def checklist(activity) -> list[dict]:
    """Full checklist for the frontend: every required kind with its state."""
    needed = required_kinds(activity.activity_type)
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
