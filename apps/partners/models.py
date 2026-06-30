"""Partners models — the partner-org directory + self-service link."""
from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class Partner(SoftDeleteModel):
    """A partner organization (trains/supports schools on Edify's behalf)."""

    id = CuidField()
    name = models.CharField(max_length=255)
    region_name = models.CharField(max_length=255, null=True, blank=True)
    trains_on = ArrayField(base_field=models.CharField(max_length=128), default=list, blank=True)
    notes = models.TextField(null=True, blank=True)
    # CD onboarding profile: eligibility, coverage, contract.
    contact_person = models.CharField(max_length=255, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    phone = models.CharField(max_length=64, null=True, blank=True)
    coverage_districts = ArrayField(base_field=models.CharField(max_length=255), default=list, blank=True)
    contract_status = models.CharField(max_length=32, null=True, blank=True)  # active|pending|expired|none
    onboarded_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    onboarded_at = models.DateTimeField(null=True, blank=True)
    # Certification (drives staff-vs-certified-partner contribution correlation).
    is_certified = models.BooleanField(default=False)
    certification_status = models.CharField(max_length=32, null=True, blank=True)
    expertise_areas = ArrayField(base_field=models.CharField(max_length=128), default=list, blank=True)
    active_status = models.BooleanField(default=True)
    # Backend login link — a partner field officer authenticates as this user.
    user = models.OneToOneField(
        "accounts.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="partner"
    )

    class Meta:
        db_table = "partner"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class PartnerAssignment(TimeStampedModel):
    """Tracks assignment of a school to a partner organization for interventions."""
    id = CuidField()
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="partner_assignments")
    partner = models.ForeignKey(Partner, on_delete=models.CASCADE, related_name="school_assignments")
    assigning_staff_id = models.CharField(max_length=30, null=True, blank=True)
    purpose = models.TextField(null=True, blank=True)
    focus_intervention = models.CharField(max_length=64, null=True, blank=True)
    expected_activity_type = models.CharField(max_length=64, null=True, blank=True)
    scheduled_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=32, default="assigned")
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "partner_assignment"
        ordering = ["-created_at"]


__all__ = ["Partner", "PartnerAssignment"]
