"""Special-projects models — intervention-specific/pilot/selective projects."""

from __future__ import annotations

from django.db import models

from apps.core.enums import SsaIntervention
from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class ProjectCategory(models.TextChoices):
    INTERVENTION_SPECIFIC = "intervention_specific", "Intervention Specific"
    PILOT = "pilot", "Pilot"
    SELECTIVE_LIMITED = "selective_limited", "Selective Limited"


class ProjectStatus(models.TextChoices):
    """The lifecycle an RVP strategic decision actually moves.

    Before this existed, an RVP could choose scale/pause/close and the platform
    recorded an audit row while every queue and dashboard kept rendering the
    project as active — the highest-authority decision in the system enforced
    nothing.
    """

    PROPOSED = "proposed", "Proposed"
    ACTIVE = "active", "Active"
    UNDER_REVIEW = "under_review", "Under Review"
    PAUSED = "paused", "Paused"
    SCALING = "scaling", "Scaling"
    CLOSED = "closed", "Closed"


# Statuses that still accept new school assignments and new planned work.
OPEN_PROJECT_STATUSES = {
    ProjectStatus.PROPOSED,
    ProjectStatus.ACTIVE,
    ProjectStatus.UNDER_REVIEW,
    ProjectStatus.SCALING,
}

# Statuses that appear in operational queues at all (a closed project stays
# readable for reporting but leaves the working surfaces).
LIVE_PROJECT_STATUSES = OPEN_PROJECT_STATUSES | {ProjectStatus.PAUSED}


class Project(SoftDeleteModel):
    """A special project (e.g. SP-EDTECH, SP-CCSEL)."""

    id = CuidField()
    code = models.CharField(max_length=64, null=True, blank=True, unique=True)
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=32, choices=ProjectCategory.choices)
    status = models.CharField(
        max_length=32,
        choices=ProjectStatus.choices,
        default=ProjectStatus.ACTIVE,
    )
    # Provenance of the last strategic decision, so a coordinator opening a
    # paused project can see who paused it and why without hunting the log.
    status_changed_at = models.DateTimeField(null=True, blank=True)
    status_changed_by = models.CharField(max_length=30, null=True, blank=True)
    status_reason = models.TextField(null=True, blank=True)
    # Ceiling for plan-vs-actual. Plain integer UGX, like the rest of the
    # platform's money (the PD app is the sole cents island).
    budget_ceiling_ugx = models.BigIntegerField(null=True, blank=True)
    intervention = models.CharField(
        max_length=64, choices=SsaIntervention.choices, null=True, blank=True
    )
    # Ecosystem audit: a Special Project must declare WHICH of the eight SSA
    # interventions it intends to improve — a single nullable `intervention`
    # (kept for back-compat) under-specified real multi-intervention projects
    # and let a project exist with no target at all. List of SsaIntervention
    # values; target_intervention_list() merges both fields.
    target_interventions = models.JSONField(default=list, blank=True)
    # Measurement window for verified SSA impact comparison.
    measurement_start_fy = models.CharField(max_length=16, null=True, blank=True)
    measurement_end_fy = models.CharField(max_length=16, null=True, blank=True)
    manager_staff_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "project"
        ordering = ["name"]

    def target_intervention_list(self) -> list[str]:
        merged = list(self.target_interventions or [])
        if self.intervention and self.intervention not in merged:
            merged.append(self.intervention)
        return merged

    @property
    def accepts_new_work(self) -> bool:
        """Whether new schools/activities may be attached. A paused or closed
        project must stop absorbing new commitments — that is what pausing
        means."""
        return self.status in {s.value for s in OPEN_PROJECT_STATUSES}

    @property
    def is_live(self) -> bool:
        """Whether the project belongs in operational queues at all."""
        return self.status in {s.value for s in LIVE_PROJECT_STATUSES}

    @property
    def status_label(self) -> str:
        return ProjectStatus(self.status).label if self.status else "Active"


class ProjectSchoolAssignment(TimeStampedModel):
    id = CuidField()
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="school_assignments"
    )
    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="project_assignments"
    )
    assigned_by = models.CharField(max_length=30, null=True, blank=True)
    project_type = models.CharField(max_length=128, null=True, blank=True)
    participation_type = models.CharField(max_length=128, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    support_area = models.CharField(max_length=255, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    # Ecosystem audit: when a school is assigned OFF-recommendation (its
    # confirmed SSA does not show weakness in the project's target
    # interventions), the override must carry a persisted reason.
    assignment_reason = models.TextField(null=True, blank=True)
    matched_intervention = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "project_school_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "school"], name="uniq_project_school"
            )
        ]


class ProjectPartnerAssignment(TimeStampedModel):
    id = CuidField()
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="partner_assignments"
    )
    partner = models.ForeignKey(
        "partners.Partner", on_delete=models.CASCADE, related_name="project_assignments"
    )

    class Meta:
        db_table = "project_partner_assignment"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "partner"], name="uniq_project_partner"
            )
        ]


class ProjectImpactSnapshot(TimeStampedModel):
    id = CuidField()
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="impact_snapshots"
    )
    fy = models.CharField(max_length=16)
    metrics_json = models.JSONField(default=dict)

    class Meta:
        db_table = "project_impact_snapshot"


__all__ = [
    "ProjectCategory",
    "ProjectStatus",
    "OPEN_PROJECT_STATUSES",
    "LIVE_PROJECT_STATUSES",
    "Project",
    "ProjectSchoolAssignment",
    "ProjectPartnerAssignment",
    "ProjectImpactSnapshot",
]
