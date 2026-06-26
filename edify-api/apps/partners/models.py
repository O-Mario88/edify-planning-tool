"""Partners models — the partner-org directory + self-service link."""
from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.models import CuidField, SoftDeleteModel


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


__all__ = ["Partner"]
