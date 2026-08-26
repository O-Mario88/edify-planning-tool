from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.enums import (
    ActivityType,
    PARTICIPANT_BEARING_MODES,
    ParticipantMode,
    SsaIntervention,
)
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
    FIELD_EVENT = "field_event", "Field Event"


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
    # Ordinary field support — a school visit, an in-school training, a
    # cluster meeting — is not the property of one intervention. The planner
    # names which of the canonical eight the work is meant to move, and any
    # of them is a valid answer. Modelling that as eight FIXED mappings would
    # say the same thing eight times and still imply the catalogue chose.
    ANY_SSA_INTERVENTION = (
        "any_ssa_intervention",
        "Any SSA intervention (planner selects)",
    )


class MappingAuthor(models.TextChoices):
    """Who wrote a mapping row, so machine writes stop clobbering human ones.

    Seeding and the importer each write one mapping per catalogue item and
    then deactivate every other mapping for that item. That made a second
    intervention impossible to keep — the next import silently retired it —
    and it would have thrown away Impact Assessment's measurement rules
    along with it. Machine writers now only retire what they own.
    """

    SEED = "seed", "Seed data"
    IMPORT = "import", "Catalogue import"
    REFERENCE = "reference", "Reference data"
    IMPACT_ASSESSMENT = "impact_assessment", "Impact Assessment"


#: Rows a seed or import run may retire. An Impact Assessment mapping carries
#: measurement rules a machine did not write and must not remove.
MACHINE_AUTHORS = (
    MappingAuthor.SEED,
    MappingAuthor.IMPORT,
    MappingAuthor.REFERENCE,
)


class MappingRelationship(models.TextChoices):
    """One activity may move more than one intervention, but not equally."""

    PRIMARY = "primary", "Primary intervention"
    SECONDARY = "secondary", "Secondary intervention"


class MeasurementRole(models.TextChoices):
    """What the linked score is used FOR.

    A school can qualify for a project because its Christlike Behaviour score
    is weak, and the same score can be what the project is later judged on.
    Those are two different jobs and an activity may do either or both.
    """

    ELIGIBILITY_ONLY = "eligibility_only", "Eligibility only"
    OUTCOME_ONLY = "outcome_only", "Outcome measurement only"
    ELIGIBILITY_AND_OUTCOME = "eligibility_and_outcome", "Eligibility and outcome"


class ExpectedDirection(models.TextChoices):
    """What counts as the intervention working.

    Not every project is trying to raise a number. A school already scoring
    Strong may be supported to stay there, and holding still is then success
    rather than failure — which is why the rule is declared per mapping
    instead of assumed to be "went up".
    """

    IMPROVE = "improve", "Improve the score"
    MAINTAIN_STRONG = "maintain_strong", "Maintain a Strong score"
    PREVENT_DECLINE = "prevent_decline", "Prevent decline"
    CLOSE_COMPLIANCE_GAP = "close_compliance_gap", "Close a compliance gap"


class MappingStatus(models.TextChoices):
    """A published mapping is what completed activities were measured under."""

    DRAFT = "draft", "Draft"
    PUBLISHED = "published", "Published"
    SUPERSEDED = "superseded", "Superseded"
    RETIRED = "retired", "Retired"


#: Mapping modes that carry no intervention of their own on the mapping row.
NULL_INTERVENTION_MODES = (
    MappingMode.SSA_COMPLETION_PREREQUISITE,
    MappingMode.ADMINISTRATIVE,
    MappingMode.INHERIT_FROM_SOURCE_ACTIVITY,
    MappingMode.ANY_SSA_INTERVENTION,
)


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
    # A certified partner AGENCY is booked onto a date by Edify staff; an
    # ordinary partner picks its own. Two workflows, so two permissions —
    # partner_delivery_allowed alone must not authorise direct booking.
    certified_agency_delivery_allowed = models.BooleanField(default=False)
    individual_school_allowed = models.BooleanField(default=True)
    cluster_delivery_allowed = models.BooleanField(default=False)
    project_delivery_allowed = models.BooleanField(default=True)

    # Ordinary field support: schedulable in its planning context on the
    # strength of a target intervention and a stated rationale alone. It does
    # not have to be the SSA engine's top-ranked pick and it never requires a
    # Special Project. This is the flag that separates "the programme's
    # governed named interventions" (EdTech Foundations, TAM I) from "a
    # school visit" — both are catalogue-governed and both are costed from
    # the CD catalogue, but only the first is a curriculum choice.
    standard_support = models.BooleanField(default=False)

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
    # How the planned participant total is established for this activity —
    # and, for ParticipantMode.NONE, the authority for refusing participant
    # input at the drawer, the serializer AND the costing engine. Hiding a
    # field in JavaScript is not a rule; this is.
    participant_mode = models.CharField(
        max_length=16,
        choices=ParticipantMode.choices,
        default=ParticipantMode.NONE,
    )
    # §25 — verification requirements are configuration, not hardcoded per
    # workflow. Defaults preserve the platform-wide behaviour that predates
    # these flags (Salesforce ID + IA verification required).
    salesforce_id_required = models.BooleanField(default=True)
    ia_verification_required = models.BooleanField(default=True)
    # The governed 21-course Training Catalogue is a deliberately narrower
    # subset of the wider Activity Catalogue.  A catalogue row can describe a
    # visit, meeting, programme event or operational support workflow; only
    # rows marked here may appear in a "Which training?" control.
    is_training_course = models.BooleanField(default=False)
    training_category = models.CharField(max_length=64, blank=True, default="")
    # Preserve the programme's exact source wording (for example
    # "Fee/Budget/Accounts") while the intervention mapping carries the
    # canonical eight-code SSA value used by analytics.
    ssa_indicator_label = models.CharField(max_length=128, blank=True, default="")
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
            # The standard-support item for a workflow kind is what the
            # scheduling drawer derives its costing from when the planner
            # picks a purpose rather than a catalogue row. Two of them for
            # one kind reintroduces exactly the ambiguity that made ordinary
            # support unschedulable — the resolver cannot choose, so it
            # returns nothing and the drawer refuses.
            models.UniqueConstraint(
                fields=["workflow_kind"],
                condition=Q(standard_support=True, status=CatalogueStatus.ACTIVE),
                name="uniq_active_standard_support_per_workflow_kind",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.stable_code} · {self.display_name}"

    def workflow_profile(self) -> dict:
        """The field configuration the scheduling drawer is generated from.

        §7 — a drawer is built from this, never from a hardcoded universal
        form. Everything a planner is asked for, and everything the backend
        will accept, comes from one place.
        """
        mode = self.participant_mode
        return {
            "catalogueItemId": self.id,
            "stableCode": self.stable_code,
            "displayName": self.display_name,
            "workflowKind": self.workflow_kind,
            "standardSupport": self.standard_support,
            "requiresSchool": self.requires_school,
            "requiresCluster": self.requires_cluster,
            "requiresProject": self.requires_project,
            "requiresCurrentSsa": self.requires_current_ssa,
            "requiresSourceActivity": self.requires_source_activity,
            "participantMode": mode,
            "requiresParticipants": mode in PARTICIPANT_BEARING_MODES,
            "participantsPerSchool": mode == ParticipantMode.PER_SCHOOL,
            "participantCategories": mode == ParticipantMode.BY_CATEGORY,
            "multiDayAllowed": self.multi_day_allowed,
            "staffDeliveryAllowed": self.staff_delivery_allowed,
            "partnerDeliveryAllowed": self.partner_delivery_allowed,
            "certifiedAgencyDeliveryAllowed": self.certified_agency_delivery_allowed,
            "clusterDeliveryAllowed": self.cluster_delivery_allowed,
            "individualSchoolAllowed": self.individual_school_allowed,
            "nonSchoolAllowed": self.non_school_allowed,
            "salesforceIdRequired": self.salesforce_id_required,
            "iaVerificationRequired": self.ia_verification_required,
            "isTrainingCourse": self.is_training_course,
            "trainingCategory": self.training_category,
            "ssaIndicatorLabel": self.ssa_indicator_label,
            "evidenceProfile": self.evidence_profile,
            "costingProfile": self.costing_profile,
        }

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
            "standardSupport": self.standard_support,
            "isTrainingCourse": self.is_training_course,
            "trainingCategory": self.training_category,
            "ssaIndicatorLabel": self.ssa_indicator_label,
            "participantMode": self.participant_mode,
            "certifiedAgencyDeliveryAllowed": self.certified_agency_delivery_allowed,
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

    #: Who wrote this row. Machine writers retire only their own; an Impact
    #: Assessment mapping carries measurement rules a seed run did not author
    #: and must not delete.
    authored_by = models.CharField(
        max_length=32, choices=MappingAuthor.choices, default=MappingAuthor.SEED
    )

    relationship = models.CharField(
        max_length=16,
        choices=MappingRelationship.choices,
        default=MappingRelationship.PRIMARY,
    )
    measurement_role = models.CharField(
        max_length=32,
        choices=MeasurementRole.choices,
        default=MeasurementRole.ELIGIBILITY_AND_OUTCOME,
    )
    expected_direction = models.CharField(
        max_length=32,
        choices=ExpectedDirection.choices,
        default=ExpectedDirection.IMPROVE,
    )

    #: Which schools this activity is for, by band. Empty means the mapping
    #: sets no score condition, which is a legitimate answer for work that is
    #: not targeted by weakness — and it is recorded rather than inferred.
    eligible_bands = ArrayField(
        base_field=models.CharField(max_length=16), default=list, blank=True
    )
    eligibility_note = models.TextField(blank=True, default="")

    #: How long the intervention plausibly needs before a score means anything.
    #: Measured in days from the first verified activity. A follow-up outside
    #: the window is not evidence about this activity.
    follow_up_min_days = models.PositiveIntegerField(null=True, blank=True)
    follow_up_expected_days = models.PositiveIntegerField(null=True, blank=True)
    follow_up_max_days = models.PositiveIntegerField(null=True, blank=True)

    #: Deliberately nullable and never defaulted. Where Edify has approved a
    #: meaningful-change threshold, Impact Assessment sets it; where it has
    #: not, any positive movement is Improved and any negative is Declined.
    #: Inventing a threshold would silently reclassify real movement.
    min_meaningful_change = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True
    )

    #: An administrative activity is not measured by a score. Saying so
    #: explicitly is honest; attaching it to an intervention to satisfy a
    #: required field would put governance work into school-improvement
    #: analytics.
    not_ssa_measured_reason = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=16, choices=MappingStatus.choices, default=MappingStatus.DRAFT
    )
    version = models.PositiveIntegerField(default=1)
    approved_by = models.CharField(max_length=30, blank=True, default="")
    approved_at = models.DateTimeField(null=True, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    country = models.CharField(max_length=64, blank=True, default="")
    fy = models.CharField(max_length=9, blank=True, default="")

    class Meta:
        db_table = "activity_intervention_mapping"
        ordering = ["priority", "catalogue_item__display_name"]
        constraints = [
            # Among LIVE rows only. A superseded mapping is the rule some
            # finished activity was measured under, and it has to stay
            # readable beside the version that replaced it — which an
            # unconditional uniqueness on the same three columns forbade.
            models.UniqueConstraint(
                fields=["catalogue_item", "intervention", "mapping_mode"],
                condition=Q(active=True),
                name="uniq_catalogue_intervention_mode",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        mapping_mode__in=list(NULL_INTERVENTION_MODES),
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
            # Exactly one primary per catalogue item, among live rows. An
            # activity may genuinely move several interventions, but it has
            # one purpose, and analytics that weighed every linked
            # intervention equally could not say which.
            models.UniqueConstraint(
                fields=["catalogue_item"],
                condition=Q(
                    relationship=MappingRelationship.PRIMARY,
                    active=True,
                )
                & ~Q(status=MappingStatus.RETIRED),
                name="uniq_primary_intervention_per_item",
            ),
            # A follow-up window has to be orderable to mean anything.
            models.CheckConstraint(
                condition=(
                    Q(follow_up_min_days__isnull=True)
                    | Q(follow_up_max_days__isnull=True)
                    | Q(follow_up_min_days__lte=F("follow_up_max_days"))
                ),
                name="mapping_follow_up_window_ordered",
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
    "NULL_INTERVENTION_MODES",
    "ProjectMappingRequirement",
]
