"""Impact Assessment's own records (owner, 2026-09-13).

The IA role description: define what success means and map how programme
steps reach Edify's mission; collect evidence before and after programmes;
track change in student outcomes, discipleship engagement and learning; tell
what works across training, EdTech and lending; and report it, unbiased, to
Country Directors, donors and partner schools.

Activity counts are outputs. These tables hold the evidence and judgements
that sit above them: the framework IA measures against, school-level evidence
the SSA does not capture (learning results, discipleship indicators, EdTech
use), findings, and impact reports with their review and release.

Review (owner decision, 2026-09-13): there is one ImpactAssessment role, so a
second IA officer in the same country reviews what another wrote; a country
with a single IA officer falls back to the Country Director's
acknowledgement. Donor releases are approved by the RVP. See apps.impact.review.
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.enums import SsaIntervention
from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class ReviewBasis(models.TextChoices):
    PEER_IA = "peer_ia", "Reviewed by a second IA officer"
    CD_FALLBACK = "cd_fallback", "Acknowledged by the Country Director"


class ReviewedRecord(models.Model):
    """Who wrote a judgement and who, independently, reviewed it."""

    author_id = models.CharField(max_length=30, db_index=True)
    author_role = models.CharField(max_length=32, blank=True, default="")
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_by_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_basis = models.CharField(
        max_length=16, choices=ReviewBasis.choices, blank=True, default=""
    )
    review_note = models.TextField(blank=True, default="")

    class Meta:
        abstract = True


class DefinitionStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    IN_REVIEW = "in_review", "In review"
    RETURNED = "returned", "Returned"
    APPROVED = "approved", "Approved"
    SUPERSEDED = "superseded", "Superseded"
    RETIRED = "retired", "Retired"


# ── Framework ────────────────────────────────────────────────────────────────


class OutcomeArea(ReviewedRecord, TimeStampedModel):
    """A dimension of transformation Edify measures (for example spiritual
    formation), defined by IA and approved through review — never hard-coded."""

    id = CuidField()
    code = models.SlugField(max_length=64)
    name = models.CharField(max_length=120)
    definition = models.TextField()
    status = models.CharField(
        max_length=16, choices=DefinitionStatus.choices, default=DefinitionStatus.DRAFT
    )
    version = models.PositiveIntegerField(default=1)
    change_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "impact_outcome_area"
        ordering = ["name", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["code", "version"], name="uniq_outcome_area_version"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class OutcomeAreaDomain(TimeStampedModel):
    """An SSA domain read as a school-level proxy for an outcome area."""

    id = CuidField()
    area = models.ForeignKey(
        OutcomeArea, on_delete=models.CASCADE, related_name="domains"
    )
    intervention = models.CharField(max_length=64, choices=SsaIntervention.choices)
    note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "impact_outcome_area_domain"
        constraints = [
            models.UniqueConstraint(
                fields=["area", "intervention"], name="uniq_outcome_area_domain"
            ),
        ]


class IndicatorLevel(models.TextChoices):
    OUTPUT = "output", "Output"
    INTERMEDIATE = "intermediate", "Intermediate outcome"
    OUTCOME = "outcome", "Outcome"


class IndicatorSource(models.TextChoices):
    SSA = "ssa", "School Self-Assessment"
    LEARNING_RESULTS = "learning_results", "Student learning results"
    DISCIPLESHIP = "discipleship", "Discipleship indicators"
    EDTECH = "edtech", "EdTech deployments and checks"
    LENDING = "lending", "Lending impact evidence"
    ACTIVITY = "activity", "Verified activity records"
    STORIES = "stories", "Most Significant Change stories"


class IndicatorDefinition(ReviewedRecord, TimeStampedModel):
    """One measure of success, versioned append-only: a changed definition is a
    new version, so earlier results keep the definition they were measured by."""

    id = CuidField()
    key = models.SlugField(max_length=80)
    version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=160)
    outcome_area = models.ForeignKey(
        OutcomeArea,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="indicators",
    )
    level = models.CharField(max_length=16, choices=IndicatorLevel.choices)
    unit = models.CharField(max_length=48)
    source = models.CharField(max_length=24, choices=IndicatorSource.choices)
    calculation = models.TextField()
    population = models.TextField(blank=True, default="")
    denominator = models.TextField(blank=True, default="")
    baseline_rule = models.TextField(blank=True, default="")
    frequency = models.CharField(max_length=64, blank=True, default="")
    disaggregation = models.TextField(blank=True, default="")
    limitations = models.TextField(blank=True, default="")
    data_owner_role = models.CharField(max_length=32, blank=True, default="")
    # Blank means the deployment-wide definition.
    country = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=16, choices=DefinitionStatus.choices, default=DefinitionStatus.DRAFT
    )
    effective_from = models.DateField(null=True, blank=True)
    change_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "impact_indicator_definition"
        ordering = ["key", "-version"]
        constraints = [
            models.UniqueConstraint(
                fields=["key", "version"], name="uniq_indicator_key_version"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} (v{self.version})"


# ── School-level evidence the SSA does not capture ───────────────────────────


class EvidenceVerification(models.TextChoices):
    PENDING = "pending", "Pending verification"
    CONFIRMED = "confirmed", "Confirmed"
    RETURNED = "returned", "Returned"


class SchoolEvidenceRecord(SoftDeleteModel):
    """Recorded by one person, confirmed by another (no self-verification)."""

    school = models.ForeignKey(
        "schools.School", on_delete=models.CASCADE, related_name="+"
    )
    country = models.CharField(max_length=64, blank=True, default="", db_index=True)
    fy = models.CharField(max_length=16, db_index=True)
    source_activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    evidence_reference = models.CharField(max_length=512, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    recorded_by_user_id = models.CharField(max_length=30, db_index=True)
    verification_status = models.CharField(
        max_length=16,
        choices=EvidenceVerification.choices,
        default=EvidenceVerification.PENDING,
        db_index=True,
    )
    verified_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    return_reason = models.TextField(blank=True, default="")

    class Meta:
        abstract = True


class LearningAssessmentType(models.TextChoices):
    ONETEST = "onetest", "OneTest"
    NATIONAL_EXAM = "national_exam", "National examination"
    INTERNAL = "internal", "School internal assessment"


class LearningAssessmentResult(SchoolEvidenceRecord):
    """Class-level student learning results — no pupil records, no names."""

    id = CuidField()
    assessment_type = models.CharField(
        max_length=24, choices=LearningAssessmentType.choices
    )
    assessed_on = models.DateField()
    grade_level = models.CharField(max_length=32)
    subject = models.CharField(max_length=64)
    learners_tested = models.PositiveIntegerField()
    mean_score = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    max_score = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True
    )
    learners_proficient = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "impact_learning_result"
        ordering = ["-assessed_on", "school_id"]
        indexes = [
            models.Index(
                fields=["school", "subject", "grade_level", "assessed_on"],
                name="idx_learning_result_school",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(learners_proficient__isnull=True)
                | models.Q(learners_proficient__lte=models.F("learners_tested")),
                name="learning_result_proficient_within_tested",
            ),
        ]


class DiscipleshipIndicatorRecord(SchoolEvidenceRecord):
    """Observable discipleship practice at a school, beside the SSA's
    self-scored spiritual domains."""

    id = CuidField()
    observed_on = models.DateField()
    devotions_per_week = models.PositiveSmallIntegerField(null=True, blank=True)
    discipleship_groups_active = models.PositiveIntegerField(null=True, blank=True)
    learners_in_groups = models.PositiveIntegerField(null=True, blank=True)
    learners_enrolled = models.PositiveIntegerField(null=True, blank=True)
    staff_in_devotions_pct = models.PositiveSmallIntegerField(null=True, blank=True)
    spiritual_lead_in_post = models.BooleanField(null=True, blank=True)
    bible_lessons_timetabled = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = "impact_discipleship_record"
        ordering = ["-observed_on", "school_id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(staff_in_devotions_pct__isnull=True)
                | models.Q(staff_in_devotions_pct__lte=100),
                name="discipleship_staff_pct_within_100",
            ),
        ]


class EdTechAssetType(models.TextChoices):
    TABLET = "tablet", "Tablets"
    LAPTOP = "laptop", "Laptops"
    DESKTOP = "desktop", "Desktop computers"
    PROJECTOR = "projector", "Projectors"
    DIGITAL_LIBRARY = "digital_library", "Digital library / server"
    CONNECTIVITY = "connectivity", "Connectivity"
    OTHER = "other", "Other"


class EdTechFunding(models.TextChoices):
    PROJECT = "project", "Special project"
    LOAN = "loan", "School loan"
    GRANT = "grant", "Grant or donation"
    SCHOOL = "school", "School's own funds"


class EdTechDeployment(SchoolEvidenceRecord):
    """Technology a school received for teaching and learning."""

    id = CuidField()
    asset_type = models.CharField(max_length=24, choices=EdTechAssetType.choices)
    quantity = models.PositiveIntegerField()
    deployed_on = models.DateField()
    funding = models.CharField(max_length=16, choices=EdTechFunding.choices)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    loan = models.ForeignKey(
        "business_transformation.MfiLoan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    teachers_trained = models.PositiveIntegerField(null=True, blank=True)
    learners_with_access = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "impact_edtech_deployment"
        ordering = ["-deployed_on", "school_id"]


class EdTechCheck(SchoolEvidenceRecord):
    """A later look at whether the technology works and is used."""

    id = CuidField()
    deployment = models.ForeignKey(
        EdTechDeployment, on_delete=models.CASCADE, related_name="checks"
    )
    checked_on = models.DateField()
    units_functional = models.PositiveIntegerField()
    teachers_using = models.PositiveIntegerField(null=True, blank=True)
    learners_using = models.PositiveIntegerField(null=True, blank=True)
    weekly_use_hours = models.DecimalField(
        max_digits=5, decimal_places=1, null=True, blank=True
    )
    issues = models.TextField(blank=True, default="")

    class Meta:
        db_table = "impact_edtech_check"
        ordering = ["-checked_on"]


# ── Findings and reports ─────────────────────────────────────────────────────


class Programme(models.TextChoices):
    TRAINING = "training", "Christian training"
    LENDING = "lending", "Lending"
    EDTECH = "edtech", "Educational technology"
    VISITS = "visits", "School visits"
    CROSS = "cross", "Across programmes"


class FindingStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    IN_REVIEW = "in_review", "In review"
    RETURNED = "returned", "Returned"
    APPROVED = "approved", "Approved"
    SUPERSEDED = "superseded", "Superseded"


class ImpactFinding(ReviewedRecord, TimeStampedModel):
    """What IA concluded from the evidence, with the numbers it rested on."""

    id = CuidField()
    country = models.CharField(max_length=64, blank=True, default="", db_index=True)
    programme = models.CharField(max_length=16, choices=Programme.choices)
    intervention = models.CharField(
        max_length=64, choices=SsaIntervention.choices, blank=True, default=""
    )
    cohort_filters = models.JSONField(default=dict, blank=True)
    metric_snapshot = models.JSONField(default=dict, blank=True)
    statement = models.TextField()
    contrary_evidence = models.TextField(blank=True, default="")
    limitations = models.TextField(blank=True, default="")
    recommendation = models.TextField(blank=True, default="")
    action_owner_role = models.CharField(max_length=32, blank=True, default="")
    follow_up_due = models.DateField(null=True, blank=True)
    evidence_refs = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=16, choices=FindingStatus.choices, default=FindingStatus.DRAFT
    )

    class Meta:
        db_table = "impact_finding"
        ordering = ["-created_at"]


class ReportStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted for review"
    RETURNED = "returned", "Returned"
    REVIEWED = "reviewed", "Reviewed"
    RELEASED = "released", "Released"
    WITHDRAWN = "withdrawn", "Withdrawn"
    SUPERSEDED = "superseded", "Superseded"


class ImpactReport(ReviewedRecord, TimeStampedModel):
    """An evidence-based impact report. Submitting freezes the evidence it
    rests on; a correction after that is a new version."""

    id = CuidField()
    country = models.CharField(max_length=64, db_index=True)
    fy = models.CharField(max_length=16, blank=True, default="")
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    project = models.ForeignKey(
        "projects.Project",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    programme_areas = ArrayField(
        models.CharField(max_length=16, choices=Programme.choices),
        default=list,
        blank=True,
    )
    title = models.CharField(max_length=200)
    status = models.CharField(
        max_length=16, choices=ReportStatus.choices, default=ReportStatus.DRAFT
    )
    methodology = models.TextField(blank=True, default="")
    findings = models.TextField(blank=True, default="")
    limitations = models.TextField(blank=True, default="")
    evidence_snapshot = models.JSONField(default=dict, blank=True)
    snapshot_hash = models.CharField(max_length=64, blank=True, default="")
    version = models.PositiveIntegerField(default=1)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="superseded_by",
    )

    class Meta:
        db_table = "impact_report"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["country", "status"], name="idx_impact_report_country"
            ),
        ]


class RecommendationStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"
    DEFERRED = "deferred", "Deferred"
    IN_PROGRESS = "in_progress", "In progress"
    DONE = "done", "Done"


class ImpactReportRecommendation(TimeStampedModel):
    id = CuidField()
    report = models.ForeignKey(
        ImpactReport, on_delete=models.CASCADE, related_name="recommendations"
    )
    text = models.TextField()
    owner_role = models.CharField(max_length=32, blank=True, default="")
    owner_user_id = models.CharField(max_length=30, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=RecommendationStatus.choices,
        default=RecommendationStatus.PROPOSED,
    )
    response = models.TextField(blank=True, default="")
    responded_by_id = models.CharField(max_length=30, null=True, blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)
    team_action_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "impact_report_recommendation"
        ordering = ["due_date", "created_at"]


class ReleaseAudience(models.TextChoices):
    LEADERSHIP = "leadership", "Country leadership"
    SCHOOL = "school", "Partner school"
    DONOR = "donor", "Donors"


class ReleaseStatus(models.TextChoices):
    PENDING_APPROVAL = "pending_approval", "Awaiting approval"
    APPROVED = "approved", "Approved"
    RELEASED = "released", "Released"
    REVOKED = "revoked", "Revoked"


class ImpactReportRelease(TimeStampedModel):
    """One audience's version of a reviewed report. Donor versions are
    requested by country leadership and approved by the RVP."""

    id = CuidField()
    report = models.ForeignKey(
        ImpactReport, on_delete=models.CASCADE, related_name="releases"
    )
    audience = models.CharField(max_length=16, choices=ReleaseAudience.choices)
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    redaction_profile = models.CharField(max_length=32, blank=True, default="")
    rendered_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20,
        choices=ReleaseStatus.choices,
        default=ReleaseStatus.PENDING_APPROVAL,
    )
    requested_by_id = models.CharField(max_length=30, blank=True, default="")
    approved_by_id = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    released_by_id = models.CharField(max_length=30, null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "impact_report_release"
        ordering = ["audience", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["report", "audience", "school"],
                name="uniq_impact_release_audience_school",
                nulls_distinct=False,
            ),
        ]
