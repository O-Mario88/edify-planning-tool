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


# ── My Targets: monthly-first personal target model ──────────────────────────


class TargetArea(TimeStampedModel):
    """One of the official personal target areas (School Visits, Cluster
    Meetings, Cluster Trainings, SSA Completed, MSCS). Weights drive the
    weighted Overall Progress and must total 100 across active areas."""

    id = CuidField()
    key = models.CharField(max_length=32, unique=True)
    label = models.CharField(max_length=64)
    weight = models.IntegerField(default=0)  # percent share of Overall Progress
    sort_order = models.IntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "target_area"
        ordering = ["sort_order"]

    def __str__(self) -> str:
        return self.label


class MonthlyPersonalTarget(TimeStampedModel):
    """The source of truth for personal targets: one value per user × area ×
    FY month. Quarters and FY are ALWAYS derived sums — never stored."""

    id = CuidField()
    user_id = models.CharField(max_length=30)  # accounts.User.id
    area = models.ForeignKey(TargetArea, on_delete=models.CASCADE, related_name="monthly_targets")
    fy = models.CharField(max_length=16)
    month_of_fy = models.IntegerField()  # 1 = October … 12 = September
    target = models.IntegerField(default=0)

    class Meta:
        db_table = "monthly_personal_target"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "area", "fy", "month_of_fy"],
                name="uniq_monthly_personal_target",
            )
        ]
        indexes = [models.Index(fields=["user_id", "fy"])]


class TargetAdjustment(TimeStampedModel):
    """Audited change to a monthly target after the period starts — targets
    are never silently edited."""

    id = CuidField()
    user_id = models.CharField(max_length=30)
    area = models.ForeignKey(TargetArea, on_delete=models.CASCADE, related_name="adjustments")
    fy = models.CharField(max_length=16)
    month_of_fy = models.IntegerField()
    old_target = models.IntegerField()
    new_target = models.IntegerField()
    reason = models.CharField(max_length=512)
    requested_by = models.CharField(max_length=30)
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    effective_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "target_adjustment"


class TargetAchievementLedger(TimeStampedModel):
    """One validated (or provisional/reversed) target credit, traceable to its
    source workflow record. The same source can never be counted twice, and a
    late validation credits the month the work actually happened."""

    id = CuidField()
    user_id = models.CharField(max_length=30)
    area = models.ForeignKey(TargetArea, on_delete=models.CASCADE, related_name="ledger")
    source_type = models.CharField(max_length=32)   # activity | ssa_record | mscs
    source_id = models.CharField(max_length=64)
    activity_date = models.DateField()
    fy = models.CharField(max_length=16)
    credited_month = models.IntegerField()           # month-of-FY of activity_date
    credited_quarter = models.CharField(max_length=4)
    quantity = models.IntegerField(default=1)
    validation_status = models.CharField(max_length=16, default="validated")  # validated|provisional|reversed
    validated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "target_achievement_ledger"
        constraints = [
            models.UniqueConstraint(
                fields=["user_id", "area", "source_type", "source_id"],
                name="uniq_target_ledger_source",
            )
        ]
        indexes = [
            models.Index(fields=["user_id", "fy"]),
            models.Index(fields=["validation_status"]),
        ]


class MSCSStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    RETURNED = "returned", "Returned"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    ARCHIVED = "archived", "Archived"


class MostSignificantChangeStory(TimeStampedModel):
    """MSCS — a narrative impact story. Only APPROVED stories count toward the
    MSCS target, credited to the story date."""

    id = CuidField()
    user_id = models.CharField(max_length=30)          # author (accounts.User.id)
    school = models.ForeignKey(
        "schools.School", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mscs_stories",
    )
    cluster_id = models.CharField(max_length=30, null=True, blank=True)
    title = models.CharField(max_length=255)
    narrative = models.TextField()
    evidence_uri = models.CharField(max_length=512, null=True, blank=True)
    story_date = models.DateField()
    status = models.CharField(max_length=16, choices=MSCSStatus.choices, default=MSCSStatus.DRAFT)
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    return_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "mscs_story"
        indexes = [models.Index(fields=["user_id", "status"])]

    def __str__(self) -> str:
        return self.title


class CatchUpStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    RETURNED = "returned", "Returned"
    SCHEDULED = "scheduled", "Scheduled"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETED = "completed", "Completed"
    CLOSED = "closed", "Closed"


class CatchUpPlan(TimeStampedModel):
    """A target-recovery plan: the PL (or the CCEO) proposes catch-up
    activities for a behind target area; on approval the activities enter
    Planning (and, when dated, are scheduled through the costing funnel so
    ActivityScheduleCostLines and the weekly fund request follow)."""

    id = CuidField()
    pl_user_id = models.CharField(max_length=30)       # supervising PL (accounts.User.id)
    staff_user_id = models.CharField(max_length=30)    # CCEO being recovered
    area = models.ForeignKey(TargetArea, on_delete=models.CASCADE, related_name="catchup_plans")
    fy = models.CharField(max_length=16)
    month_of_fy = models.IntegerField()                # 1 = October … 12 = September
    activities_proposed = models.IntegerField(default=0)
    school_ids = models.JSONField(default=list, blank=True)     # school_id strings
    planned_dates = models.JSONField(default=list, blank=True)  # ISO dates
    partner_id = models.CharField(max_length=30, null=True, blank=True)
    note = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=CatchUpStatus.choices, default=CatchUpStatus.SUBMITTED)
    return_reason = models.CharField(max_length=512, null=True, blank=True)
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    created_activity_ids = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "target_catchup_plan"
        indexes = [
            models.Index(fields=["pl_user_id", "status"]),
            models.Index(fields=["staff_user_id", "fy", "month_of_fy"]),
        ]

    def __str__(self) -> str:
        return f"CatchUp {self.area_id} {self.fy} m{self.month_of_fy} ({self.status})"
