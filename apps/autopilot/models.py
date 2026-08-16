"""The machine-draft state — the autopilot's constitutional guard (Phase 4).

Machine-proposed work is a FOURTH population beside planned, actual and
verified, and it lives in its own tables on purpose: a proposal creates no
Activity row, consumes no budget, feeds no planned-output metric, raises no
To-Do, and appears in no work plan until a human accepts it. Acceptance
routes every item through the canonical activity create() funnel — the same
gates (catalogue eligibility, scheduling policy, duplicate prevention,
costing) that govern hand-planned work. The platform prepares; the staff
member confirms reality.
"""

from __future__ import annotations

from django.db import models

from apps.accounts.models import StaffProfile
from apps.core.models import CuidField, TimeStampedModel


class ProposedPlanStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    ACCEPTED = "accepted", "Accepted"
    DISMISSED = "dismissed", "Dismissed"


class ProposedPlan(TimeStampedModel):
    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="proposed_plans"
    )
    week_start = models.DateField()
    status = models.CharField(
        max_length=16,
        choices=ProposedPlanStatus.choices,
        default=ProposedPlanStatus.PROPOSED,
    )
    # What the generator saw: capacity, exclusions, ordering inputs — the
    # "why" a reviewer reads before accepting. Facts, not persuasion.
    rationale = models.JSONField(default=dict, blank=True)
    accepted_by = models.CharField(max_length=30, blank=True, default="")
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "autopilot_proposed_plan"
        constraints = [
            # One live proposal per person-week: regeneration supersedes by
            # dismissing the old draft first, never by stacking drafts.
            models.UniqueConstraint(
                fields=["staff", "week_start"],
                condition=models.Q(status="proposed"),
                name="uniq_live_proposed_plan",
            )
        ]


class ProposedActivity(TimeStampedModel):
    id = CuidField()
    plan = models.ForeignKey(
        ProposedPlan, on_delete=models.CASCADE, related_name="items"
    )
    school_id = models.CharField(max_length=30, db_index=True)
    school_name = models.CharField(max_length=255, blank=True, default="")
    area = models.CharField(max_length=128, blank=True, default="")
    proposed_date = models.DateField()
    activity_type = models.CharField(max_length=64, default="school_visit")
    catalogue_stable_code = models.CharField(max_length=64, blank=True, default="")
    reason = models.CharField(max_length=255, blank=True, default="")
    # Set only by acceptance — the traceable bridge from draft to the real,
    # costed Activity the canonical funnel created.
    created_activity_id = models.CharField(max_length=30, blank=True, default="")

    class Meta:
        db_table = "autopilot_proposed_activity"
        ordering = ["proposed_date", "area", "school_name"]
