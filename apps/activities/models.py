"""
Activities models — the operational work ledger (the 21-state lifecycle).

Ports of Activity, ActivityScheduleCostLine (auto-cost breakdown from the CD
rate card at schedule time), and ActivityCompletionVerification (manual
Salesforce SV-/TS- ID confirmation). Payments models (PaymentRequest etc.) live
in the payments app.
"""
from __future__ import annotations

from django.db import models
from django.contrib.postgres.fields import ArrayField

from apps.core.enums import (
    ActivityStatus,
    ActivityType,
    ClusterMeetingSlot,
    DeliveryType,
    EvidenceStatus,
    PaymentStatus,
    SsaIntervention,
    VerificationStatus,
)
from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class Activity(SoftDeleteModel):
    """An operational work item (visit / training / cluster meeting / …)."""

    id = CuidField()
    activity_type = models.CharField(max_length=48, choices=ActivityType.choices)
    school = models.ForeignKey("schools.School", on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    cluster = models.ForeignKey("clusters.Cluster", on_delete=models.SET_NULL, null=True, blank=True, related_name="activities")
    project_id = models.CharField(max_length=30, null=True, blank=True)

    fy = models.CharField(max_length=16)
    quarter = models.CharField(max_length=8)
    month = models.IntegerField(null=True, blank=True)
    week = models.IntegerField(null=True, blank=True)
    scheduled_date = models.DateTimeField(null=True, blank=True)
    planned_date = models.DateField(null=True, blank=True)
    week_start_date = models.DateField(null=True, blank=True)
    week_end_date = models.DateField(null=True, blank=True)
    fiscal_year = models.CharField(max_length=16, null=True, blank=True)
    planned_month = models.IntegerField(null=True, blank=True)
    planned_week = models.IntegerField(null=True, blank=True)

    responsible_staff_id = models.CharField(max_length=30, null=True, blank=True)
    monitored_by_staff_id = models.CharField(max_length=30, null=True, blank=True)
    assigned_partner_id = models.CharField(max_length=30, null=True, blank=True)
    delivery_type = models.CharField(max_length=16, choices=DeliveryType.choices, default=DeliveryType.STAFF)
    cluster_slot = models.CharField(max_length=16, choices=ClusterMeetingSlot.choices, null=True, blank=True)

    purpose_intervention = models.CharField(max_length=64, choices=SsaIntervention.choices, null=True, blank=True)
    activity_purpose_text = models.TextField(null=True, blank=True)
    purpose_type = models.CharField(max_length=64, null=True, blank=True)
    focus_intervention = models.CharField(max_length=64, choices=SsaIntervention.choices, null=True, blank=True)
    secondary_focus_interventions = ArrayField(base_field=models.CharField(max_length=64, choices=SsaIntervention.choices), default=list, blank=True)
    expected_outcome = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=32, choices=ActivityStatus.choices, default=ActivityStatus.NOT_PLANNED)
    evidence_status = models.CharField(max_length=16, choices=EvidenceStatus.choices, default=EvidenceStatus.NONE)

    # Salesforce-ready (manual ID confirmation, not integrated).
    salesforce_activity_id = models.CharField(max_length=128, null=True, blank=True)
    salesforce_activity_type = models.CharField(max_length=16, null=True, blank=True)  # visit | training

    ia_verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.PENDING
    )
    ia_confirmed_at = models.DateTimeField(null=True, blank=True)
    ia_confirmed_by = models.CharField(max_length=30, null=True, blank=True)
    payment_status = models.CharField(max_length=32, choices=PaymentStatus.choices, default=PaymentStatus.NONE)

    # Reschedule trail.
    reschedule_count = models.IntegerField(default=0)
    last_reason = models.CharField(max_length=512, null=True, blank=True)

    # Auto-cost from the CD rate card at schedule time (cents).
    est_cost_cents = models.IntegerField(default=0)
    cost_missing = models.BooleanField(default=False)

    # PL review handoff when a CCEO completes field work.
    pl_review_note = models.CharField(max_length=512, null=True, blank=True)
    pl_reviewed_at = models.DateTimeField(null=True, blank=True)
    pl_reviewed_by = models.CharField(max_length=30, null=True, blank=True)

    # Training/cluster-meeting completion detail.
    teachers_attended = models.IntegerField(null=True, blank=True)
    leaders_attended = models.IntegerField(null=True, blank=True)
    other_participants = models.IntegerField(null=True, blank=True)
    next_meeting_date = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "activity"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["school"]),
            models.Index(fields=["cluster"]),
            models.Index(fields=["fy", "quarter"]),
            models.Index(fields=["responsible_staff_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["scheduled_date"]),
            models.Index(fields=["assigned_partner_id"]),
            models.Index(fields=["ia_verification_status", "payment_status"]),
            models.Index(fields=["evidence_status"]),
        ]


class ActivityScheduleCostLine(TimeStampedModel):
    """Persisted cost breakdown for a scheduled activity — sourced from
    CostSetting at schedule time so fund requests reconcile to the catalogue.

    This IS the activity budget line: one row per cost item (transport, lunch,
    venue, facilitation, meals...), each tracing to the catalogue version it was
    priced against. Amounts are integer UGX (whole shillings)."""

    id = CuidField()
    activity = models.ForeignKey(Activity, on_delete=models.CASCADE, related_name="schedule_cost_lines")
    cost_setting_key = models.CharField(max_length=128)
    label = models.CharField(max_length=255)
    unit_cost = models.IntegerField()  # UGX, integer
    quantity = models.IntegerField(default=1)
    amount = models.IntegerField()  # UGX, integer
    cost_setting_version = models.IntegerField(default=1)
    # Catalogue provenance — the catalogue + version this line was priced from.
    catalogue_id = models.CharField(max_length=30, null=True, blank=True)
    catalogue_version = models.IntegerField(null=True, blank=True)
    # Itemized line type (transport / breakfast / lunch / dinner / accommodation
    # / venue / facilitation / participant_meals / mobilisation / lump_sum ...).
    line_item_type = models.CharField(max_length=64, null=True, blank=True)
    currency = models.CharField(max_length=8, default="UGX")
    description = models.CharField(max_length=255, null=True, blank=True)
    total_cost = models.BigIntegerField(null=True, blank=True)
    planned_date = models.DateField(null=True, blank=True)
    week_start_date = models.DateField(null=True, blank=True)
    week_end_date = models.DateField(null=True, blank=True)
    month = models.IntegerField(null=True, blank=True)
    quarter = models.CharField(max_length=8, null=True, blank=True)
    fiscal_year = models.CharField(max_length=16, null=True, blank=True)
    responsible_user = models.CharField(max_length=30, null=True, blank=True)
    responsible_role = models.CharField(max_length=64, null=True, blank=True)
    school = models.ForeignKey("schools.School", on_delete=models.SET_NULL, null=True, blank=True)
    cluster = models.ForeignKey("clusters.Cluster", on_delete=models.SET_NULL, null=True, blank=True)
    partner = models.ForeignKey("partners.Partner", on_delete=models.SET_NULL, null=True, blank=True)
    project = models.ForeignKey("projects.Project", on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        db_table = "activity_schedule_cost_line"
        indexes = [models.Index(fields=["activity"])]


class ActivityCompletionVerification(TimeStampedModel):
    """Manual Salesforce SV-/TS- ID confirmation (IA verifies the entry)."""

    id = CuidField()
    activity = models.OneToOneField(Activity, on_delete=models.CASCADE, related_name="verification")
    salesforce_id = models.CharField(max_length=128)  # SV- or TS-
    entered_by = models.CharField(max_length=30)  # responsible staff userId
    entered_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.PENDING)
    ia_actor_id = models.CharField(max_length=30, null=True, blank=True)
    ia_action_at = models.DateTimeField(null=True, blank=True)
    ia_note = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "activity_completion_verification"


__all__ = ["Activity", "ActivityScheduleCostLine", "ActivityCompletionVerification"]
