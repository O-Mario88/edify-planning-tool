"""Targets models — CD/IA annual commitments."""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class TargetType(models.TextChoices):
    SCHOOL_REACH = "SCHOOL_REACH", "School Reach"
    STAFF_DIRECT_SUPPORT = "STAFF_DIRECT_SUPPORT", "Staff Direct Support"
    PARTNER_SUPPORT = "PARTNER_SUPPORT", "Partner Support"
    TRAINING = "TRAINING", "Training"
    SSA = "SSA", "SSA"
    SCHOOL_VISIT = "SCHOOL_VISIT", "School Visit"
    MSCS = "MSCS", "MSCS"
    EXAM_RESULTS = "EXAM_RESULTS", "Exam Results"
    CORE_PACKAGE = "CORE_PACKAGE", "Core Package"
    PROJECT_SUPPORT = "PROJECT_SUPPORT", "Project Support"
    IA_VERIFICATION = "IA_VERIFICATION", "IA Verification"
    ACCOUNTABILITY = "ACCOUNTABILITY", "Accountability"


class TargetScopeType(models.TextChoices):
    COUNTRY = "country", "Country"
    REGION = "region", "Region"
    DISTRICT = "district", "District"
    CLUSTER = "cluster", "Cluster"
    STAFF = "staff", "Staff"
    PL_TEAM = "pl_team", "PL Team"
    PARTNER = "partner", "Partner"
    PROJECT = "project", "Project"
    SCHOOL_TYPE = "school_type", "School Type"


class TargetUnit(models.TextChoices):
    COUNT = "count", "Count"
    PERCENTAGE = "percentage", "Percentage"


class TargetSetting(TimeStampedModel):
    """A CD/IA-set annual target across a category + scope."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    target_type = models.CharField(max_length=32, choices=TargetType.choices)
    scope_type = models.CharField(max_length=16, choices=TargetScopeType.choices)
    scope_id = models.CharField(max_length=30, null=True, blank=True)
    target_value = models.FloatField(null=True, blank=True)
    target_unit = models.CharField(
        max_length=16, choices=TargetUnit.choices, default=TargetUnit.PERCENTAGE
    )
    target_percentage = models.FloatField(null=True, blank=True)
    quarter_distribution = models.JSONField(null=True, blank=True)
    set_by_user_id = models.CharField(max_length=30)
    set_by_role = models.CharField(max_length=64)
    effective_from = models.DateTimeField(auto_now_add=True)
    effective_to = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "target_setting"
        indexes = [
            models.Index(fields=["fy", "target_type"]),
            models.Index(fields=["scope_type", "scope_id"]),
            models.Index(fields=["is_active"]),
        ]


__all__ = ["TargetType", "TargetScopeType", "TargetUnit", "TargetSetting"]
