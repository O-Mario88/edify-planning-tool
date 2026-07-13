"""
SSA (School Self-Assessment) models — ports of SsaRecord, SsaScore.

An SSA record holds 8 intervention scores (0–10) for a school on a date. The
collection source drives QA: staff/IA-collected is auto-verified; partner-
collected lands `pending` until staff/IA confirm.
"""

from __future__ import annotations

from django.db import models

from apps.core.enums import SsaCollectorType, SsaIntervention, VerificationStatus
from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class SsaRecord(SoftDeleteModel):
    """One SSA collection for a school (8 intervention scores via SsaScore)."""

    id = CuidField()
    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="ssa_records"
    )
    date_of_ssa = models.DateTimeField()
    fy = models.CharField(max_length=16)
    quarter = models.CharField(max_length=8)  # Q1..Q4
    new_enrollment = models.IntegerField(null=True, blank=True)
    average_score = models.FloatField(null=True, blank=True)

    # Salesforce-ready verification of the SSA itself.
    salesforce_id = models.CharField(max_length=128, null=True, blank=True)
    verification_status = models.CharField(
        max_length=32,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING,
    )

    # Collection source + verification provenance (the contract-worthy QA layer).
    collector_type = models.CharField(
        max_length=32, choices=SsaCollectorType.choices, default=SsaCollectorType.STAFF
    )
    verification_source = models.CharField(max_length=64, null=True, blank=True)
    collected_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    collected_by_partner_id = models.CharField(max_length=30, null=True, blank=True)
    verified_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    qa_reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    qa_reviewed_at = models.DateTimeField(null=True, blank=True)

    uploaded_by = models.CharField(max_length=30)  # userId (IA)

    class Meta:
        db_table = "ssa_record"
        ordering = ["-date_of_ssa"]
        indexes = [
            models.Index(fields=["school"]),
            models.Index(fields=["fy"]),
            models.Index(fields=["collector_type"]),
            models.Index(fields=["verification_status"]),
        ]


class SsaScore(TimeStampedModel):
    """A single intervention score within an SSA record."""

    id = CuidField()
    ssa_record = models.ForeignKey(
        SsaRecord, on_delete=models.CASCADE, related_name="scores"
    )
    intervention = models.CharField(max_length=64, choices=SsaIntervention.choices)
    score = models.FloatField()

    class Meta:
        db_table = "ssa_score"
        constraints = [
            models.UniqueConstraint(
                fields=["ssa_record", "intervention"],
                name="uniq_ssa_record_intervention",
            ),
        ]


__all__ = ["SsaRecord", "SsaScore"]
