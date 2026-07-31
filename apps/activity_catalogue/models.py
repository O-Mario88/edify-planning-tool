from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.enums import ActivityType, SsaIntervention
from apps.core.models import CuidField, TimeStampedModel


class CatalogueStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"
    RETIRED = "retired", "Retired"


class CatalogueActivityType(models.TextChoices):
    TRAINING = "training", "Training"
    SCHOOL_VISIT = "school_visit", "School Visit"
    YOUTH_CAMP = "youth_camp", "Youth Camp"
    ADMIN = "admin", "Admin"
    PROGRAMME_EVENT = "programme_event", "Programme Event"


class DeliveryMethod(models.TextChoices):
    IN_SCHOOL_TRAINING = "in_school_training", "In-school Training"
    CLUSTER_MEETING = "cluster_meeting", "Cluster Meeting"
    CLUSTER_TRAINING = "cluster_training", "Cluster Training"
    ONLINE = "online", "Online"
    SCHOOL_VISIT = "school_visit", "School Visit"
    GROUP = "group", "Group"
    ADMIN = "admin", "Admin"
    PROGRAMME_EVENT = "programme_event", "Programme Event"


class MappingMode(models.TextChoices):
    FIXED = "fixed", "Fixed"
    MULTIPLE_ALLOWED = "multiple_allowed", "Multiple allowed"
    INHERIT_FROM_SOURCE_ACTIVITY = (
        "inherit_from_source_activity",
        "Inherit from source activity",
    )
    SSA_COMPLETION_PREREQUISITE = (
        "ssa_completion_prerequisite",
        "SSA completion prerequisite",
    )
    ADMINISTRATIVE = "administrative", "Administrative"


class ProjectMappingRequirement(models.TextChoices):
    REQUIRED = "required", "Required"
    OPTIONAL = "optional", "Optional"


class ActivityCatalogueItem(TimeStampedModel):
    """Governed master data describing an approved response to a support need."""

    id = CuidField()
    stable_code = models.CharField(max_length=96, unique=True)
    source_name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    activity_type = models.CharField(
        max_length=32, choices=CatalogueActivityType.choices
    )
    delivery_method = models.CharField(max_length=32, choices=DeliveryMethod.choices)
    # Existing Activity.activity_type value used by the canonical operational,
    # costing, evidence and My Plan workflow.
    workflow_kind = models.CharField(max_length=48, choices=ActivityType.choices)
    target_audience = models.CharField(max_length=128, default="School staff")
    status = models.CharField(
        max_length=16, choices=CatalogueStatus.choices, default=CatalogueStatus.DRAFT
    )
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)

    staff_delivery_allowed = models.BooleanField(default=True)
    partner_delivery_allowed = models.BooleanField(default=True)
    individual_school_allowed = models.BooleanField(default=True)
    cluster_delivery_allowed = models.BooleanField(default=False)
    project_delivery_allowed = models.BooleanField(default=True)

    requires_school = models.BooleanField(default=True)
    requires_cluster = models.BooleanField(default=False)
    requires_project = models.BooleanField(default=False)
    requires_current_ssa = models.BooleanField(default=True)
    # Non-school programme work (conferences, camps, exhibitions, launches):
    # schedulable without a school or cluster, through the Work Plan entry
    # point, with a strategic rationale instead of an SSA recommendation.
    non_school_allowed = models.BooleanField(default=False)
    multi_day_allowed = models.BooleanField(default=False)
    requires_participant_counts = models.BooleanField(default=False)
    # §25 — verification requirements are configuration, not hardcoded per
    # workflow. Defaults preserve the platform-wide behaviour that predates
    # these flags (Salesforce ID + IA verification required).
    salesforce_id_required = models.BooleanField(default=True)
    ia_verification_required = models.BooleanField(default=True)
    programme_category = models.CharField(max_length=64, blank=True, default="")
    requires_source_activity = models.BooleanField(default=False)
    new_school_only = models.BooleanField(default=False)

    counts_toward_client_visit = models.BooleanField(default=False)
    counts_toward_client_training = models.BooleanField(default=False)
    core_slot_type = models.CharField(max_length=32, null=True, blank=True)

    salesforce_record_type = models.CharField(max_length=32)
    salesforce_expected_prefix = models.CharField(max_length=16, blank=True)
    evidence_profile = models.CharField(max_length=64)
    costing_profile = models.CharField(max_length=64)
    support_objective = models.CharField(max_length=64, blank=True)
    follow_up_required = models.BooleanField(default=False)
    override_reason_required = models.BooleanField(default=True)

    created_by = models.CharField(max_length=30, null=True, blank=True)
    updated_by = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "activity_catalogue_item"
        ordering = ["display_name", "stable_code"]
        indexes = [
            models.Index(fields=["status", "effective_from", "effective_to"]),
            models.Index(fields=["activity_type", "delivery_method"]),
            models.Index(fields=["workflow_kind"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True)
                | Q(effective_from__isnull=True)
                | Q(effective_to__gte=models.F("effective_from")),
                name="activity_catalogue_effective_range_valid",
            ),
            models.CheckConstraint(
                condition=~Q(status=CatalogueStatus.ACTIVE)
                | (
                    ~Q(evidence_profile="")
                    & ~Q(salesforce_record_type="")
                    & ~Q(costing_profile="")
                ),
                name="active_catalogue_profiles_required",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.stable_code} · {self.display_name}"

    def is_selectable_on(self, on_date=None) -> bool:
        on_date = on_date or timezone.localdate()
        return bool(
            self.status == CatalogueStatus.ACTIVE
            and (self.effective_from is None or self.effective_from <= on_date)
            and (self.effective_to is None or self.effective_to >= on_date)
        )

    def snapshot(self) -> dict:
        mapping = self.intervention_mappings.filter(active=True).order_by(
            "-is_primary", "priority", "id"
        )
        return {
            "stableCode": self.stable_code,
            "displayName": self.display_name,
            "sourceName": self.source_name,
            "activityType": self.activity_type,
            "deliveryMethod": self.delivery_method,
            "workflowKind": self.workflow_kind,
            "targetAudience": self.target_audience,
            "salesforceRecordType": self.salesforce_record_type,
            "salesforceExpectedPrefix": self.salesforce_expected_prefix,
            "evidenceProfile": self.evidence_profile,
            "costingProfile": self.costing_profile,
            "supportObjective": self.support_objective,
            "mappingModes": list(mapping.values_list("mapping_mode", flat=True)),
            "interventions": list(
                mapping.exclude(intervention__isnull=True).values_list(
                    "intervention", flat=True
                )
            ),
        }


class ActivityInterventionMapping(TimeStampedModel):
    id = CuidField()
    catalogue_item = models.ForeignKey(
        ActivityCatalogueItem,
        on_delete=models.PROTECT,
        related_name="intervention_mappings",
    )
    intervention = models.CharField(
        max_length=64, choices=SsaIntervention.choices, null=True, blank=True
    )
    mapping_mode = models.CharField(max_length=48, choices=MappingMode.choices)
    priority = models.PositiveSmallIntegerField(default=100)
    is_primary = models.BooleanField(default=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "activity_intervention_mapping"
        ordering = ["priority", "catalogue_item__display_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["catalogue_item", "intervention", "mapping_mode"],
                name="uniq_catalogue_intervention_mode",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        mapping_mode__in=[
                            MappingMode.SSA_COMPLETION_PREREQUISITE,
                            MappingMode.ADMINISTRATIVE,
                            MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
                        ],
                        intervention__isnull=True,
                    )
                    | Q(
                        mapping_mode__in=[
                            MappingMode.FIXED,
                            MappingMode.MULTIPLE_ALLOWED,
                        ],
                        intervention__isnull=False,
                    )
                ),
                name="catalogue_mapping_intervention_shape",
            ),
        ]


class ActivityProjectMapping(TimeStampedModel):
    id = CuidField()
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.CASCADE,
        related_name="allowed_catalogue_activities",
    )
    catalogue_item = models.ForeignKey(
        ActivityCatalogueItem,
        on_delete=models.PROTECT,
        related_name="project_mappings",
    )
    required_or_optional = models.CharField(
        max_length=16,
        choices=ProjectMappingRequirement.choices,
        default=ProjectMappingRequirement.OPTIONAL,
    )
    eligible_school_levels = ArrayField(
        models.CharField(max_length=64), default=list, blank=True
    )
    eligible_school_types = ArrayField(
        models.CharField(max_length=32), default=list, blank=True
    )
    staff_delivery_allowed = models.BooleanField(default=True)
    partner_delivery_allowed = models.BooleanField(default=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "activity_project_mapping"
        constraints = [
            models.UniqueConstraint(
                fields=["project", "catalogue_item"],
                name="uniq_project_catalogue_item",
            )
        ]


class ActivityEligibilityRule(TimeStampedModel):
    id = CuidField()
    catalogue_item = models.OneToOneField(
        ActivityCatalogueItem,
        on_delete=models.CASCADE,
        related_name="eligibility_rule",
    )
    eligible_school_levels = ArrayField(
        models.CharField(max_length=64), default=list, blank=True
    )
    eligible_school_categories = ArrayField(
        models.CharField(max_length=32), default=list, blank=True
    )
    eligible_support_tiers = ArrayField(
        models.CharField(max_length=32), default=list, blank=True
    )
    allowed_target_audiences = ArrayField(
        models.CharField(max_length=128), default=list, blank=True
    )
    core_school_only = models.BooleanField(default=False)
    client_school_only = models.BooleanField(default=False)
    requires_project_membership = models.BooleanField(default=False)
    requires_cluster_membership = models.BooleanField(default=False)
    maximum_frequency_per_fy = models.PositiveSmallIntegerField(null=True, blank=True)
    cooldown_days = models.PositiveIntegerField(null=True, blank=True)
    counts_toward_entitlement = models.BooleanField(default=False)

    class Meta:
        db_table = "activity_eligibility_rule"


class ActivityCatalogueVersion(TimeStampedModel):
    id = CuidField()
    catalogue_item = models.ForeignKey(
        ActivityCatalogueItem,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version = models.PositiveIntegerField()
    snapshot = models.JSONField()
    change_reason = models.TextField()
    created_by = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "activity_catalogue_version"
        ordering = ["catalogue_item", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["catalogue_item", "version"],
                name="uniq_activity_catalogue_version",
            )
        ]


class ActivityCatalogueAlias(TimeStampedModel):
    id = CuidField()
    catalogue_item = models.ForeignKey(
        ActivityCatalogueItem, on_delete=models.PROTECT, related_name="aliases"
    )
    normalized_alias = models.CharField(max_length=255, unique=True)
    source_alias = models.CharField(max_length=255)

    class Meta:
        db_table = "activity_catalogue_alias"


class ActivityCatalogueReviewQueue(TimeStampedModel):
    id = CuidField()
    review_kind = models.CharField(max_length=64)
    source_model = models.CharField(max_length=128)
    source_record_id = models.CharField(max_length=64)
    source_value = models.TextField()
    candidate_codes = ArrayField(
        models.CharField(max_length=96), default=list, blank=True
    )
    status = models.CharField(max_length=24, default="needs_review")
    resolution_note = models.TextField(blank=True)
    resolved_by = models.CharField(max_length=30, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "activity_catalogue_review_queue"
        constraints = [
            models.UniqueConstraint(
                fields=["review_kind", "source_model", "source_record_id"],
                name="uniq_catalogue_review_source",
            )
        ]


__all__ = [
    "ActivityCatalogueAlias",
    "ActivityCatalogueItem",
    "ActivityCatalogueReviewQueue",
    "ActivityCatalogueVersion",
    "ActivityEligibilityRule",
    "ActivityInterventionMapping",
    "ActivityProjectMapping",
    "CatalogueActivityType",
    "CatalogueStatus",
    "DeliveryMethod",
    "MappingMode",
    "ProjectMappingRequirement",
]
