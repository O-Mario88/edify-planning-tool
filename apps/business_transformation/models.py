"""Uganda Business Transformation records.

Loans are deliberately outside Edify's operating-finance workflow. Activities
may spend Edify programme money to train or verify a school; an MFI loan is an
external financial instrument and lives in this separate, durable ledger.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class AppendOnlyQuerySet(models.QuerySet):
    """Prevent ORM bulk mutation of value-bearing postings."""

    def update(self, **kwargs):
        raise ValueError("Financial postings are append-only; post a reversal.")

    def delete(self):
        raise ValueError("Financial postings are append-only; post a reversal.")


class AppendOnlyManager(models.Manager.from_queryset(AppendOnlyQuerySet)):
    pass


class ImmutablePosting(TimeStampedModel):
    """Application-level append-only guard shared by financial ledger rows.

    Reversals are separate postings. The model and queryset guards cover normal
    ORM paths; database privileges must also deny UPDATE/DELETE in production.
    """

    objects = AppendOnlyManager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("Financial postings are append-only; post a reversal.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Financial postings are append-only; post a reversal.")


class CaseStatus(models.TextChoices):
    RECOMMENDED = "recommended", "Recommended"
    TRIAGE = "triage", "In triage"
    ACTIVE = "active", "Active"
    MONITORING = "monitoring", "Monitoring"
    DEFERRED = "deferred", "Deferred"
    CLOSED = "closed", "Closed"


OPEN_CASE_STATUSES = (
    CaseStatus.RECOMMENDED,
    CaseStatus.TRIAGE,
    CaseStatus.ACTIVE,
    CaseStatus.MONITORING,
    CaseStatus.DEFERRED,
)


class TriggerType(models.TextChoices):
    VERIFIED_SSA = "verified_ssa", "Verified SSA"
    SCHOOL_REQUEST = "school_request", "School request"
    STAFF_REFERRAL = "staff_referral", "Staff referral"
    MFI_LOAN_IMPORT = "mfi_loan_import", "MFI loan import"
    CAMPAIGN = "campaign", "Campaign"
    COUNTRY_PRIORITY = "country_priority", "Uganda priority"


class RecommendationKind(models.TextChoices):
    FINANCIAL_HEALTH_TRAINING = (
        "financial_health_training",
        "Financial Health training",
    )
    ACCOUNTANT_TRAINING = "accountant_training", "School accountant training"
    COMPLIANCE_SUPPORT = "compliance_support", "Government requirements support"
    LOAN_READINESS = "loan_readiness", "Loan readiness assessment"
    LOAN_REFERRAL = "loan_referral", "MFI referral"
    LOAN_USE_VERIFICATION = "loan_use_verification", "Loan-use verification"
    LOAN_IMPACT_ASSESSMENT = "loan_impact_assessment", "Loan impact assessment"
    FOLLOW_UP_MENTORSHIP = "follow_up_mentorship", "Follow-up mentorship"
    FURTHER_ASSESSMENT = "further_assessment", "Further assessment"
    NO_IMMEDIATE_INTERVENTION = (
        "no_immediate_intervention",
        "No immediate intervention",
    )


class RecommendationStatus(models.TextChoices):
    OPEN = "open", "Open"
    ACCEPTED = "accepted", "Accepted"
    CHANGED = "changed", "Changed"
    DEFERRED = "deferred", "Deferred"
    CLOSED = "closed", "Closed"


class BusinessTransformationPolicy(TimeStampedModel):
    """Versioned Uganda policy used to turn verified need into recommendations."""

    id = CuidField()
    country_code = models.CharField(max_length=2, default="UG")
    fy = models.CharField(max_length=16, db_index=True)
    financial_health_max_score = models.DecimalField(
        max_digits=4, decimal_places=2, default=5.5
    )
    government_requirements_max_score = models.DecimalField(
        max_digits=4, decimal_places=2, default=5.5
    )
    loan_use_verification_days = models.PositiveSmallIntegerField(default=60)
    active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=30, blank=True, default="system")

    class Meta:
        db_table = "bt_policy"
        constraints = [
            models.UniqueConstraint(
                fields=["country_code", "fy"], name="uniq_bt_policy_country_fy"
            ),
            models.CheckConstraint(
                condition=Q(financial_health_max_score__gte=0)
                & Q(financial_health_max_score__lte=10)
                & Q(government_requirements_max_score__gte=0)
                & Q(government_requirements_max_score__lte=10),
                name="bt_policy_ssa_thresholds_0_10",
            ),
        ]


class TransformationCase(SoftDeleteModel):
    id = CuidField()
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.PROTECT,
        related_name="business_transformation_cases",
    )
    status = models.CharField(
        max_length=20, choices=CaseStatus.choices, default=CaseStatus.RECOMMENDED
    )
    owner_staff_id = models.CharField(max_length=30, null=True, blank=True)
    opened_fy = models.CharField(max_length=16, db_index=True)
    triage_decision = models.CharField(max_length=48, blank=True, default="")
    triage_reason = models.TextField(blank=True, default="")
    triaged_by = models.CharField(max_length=30, null=True, blank=True)
    triaged_at = models.DateTimeField(null=True, blank=True)
    deferred_until = models.DateField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closure_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bt_case"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "opened_fy"]),
            models.Index(fields=["owner_staff_id", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["school"],
                condition=Q(status__in=OPEN_CASE_STATUSES, deleted_at__isnull=True),
                name="uniq_open_bt_case_per_school",
            )
        ]


class CaseTrigger(TimeStampedModel):
    id = CuidField()
    case = models.ForeignKey(
        TransformationCase, on_delete=models.CASCADE, related_name="triggers"
    )
    trigger_type = models.CharField(max_length=32, choices=TriggerType.choices)
    source_id = models.CharField(max_length=64)
    source_snapshot = models.JSONField(default=dict, blank=True)
    triggered_by = models.CharField(max_length=30, blank=True, default="system")

    class Meta:
        db_table = "bt_case_trigger"
        constraints = [
            models.UniqueConstraint(
                fields=["trigger_type", "source_id"], name="uniq_bt_trigger_source"
            )
        ]


class CaseRecommendation(TimeStampedModel):
    id = CuidField()
    case = models.ForeignKey(
        TransformationCase, on_delete=models.CASCADE, related_name="recommendations"
    )
    trigger = models.ForeignKey(
        CaseTrigger, on_delete=models.PROTECT, related_name="recommendations"
    )
    kind = models.CharField(max_length=48, choices=RecommendationKind.choices)
    status = models.CharField(
        max_length=16,
        choices=RecommendationStatus.choices,
        default=RecommendationStatus.OPEN,
    )
    reason = models.TextField()
    source_intervention = models.CharField(max_length=64, blank=True, default="")
    source_score = models.DecimalField(
        max_digits=4, decimal_places=2, null=True, blank=True
    )
    decided_by = models.CharField(max_length=30, null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_case_recommendation"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["trigger", "kind"], name="uniq_bt_recommendation_trigger_kind"
            )
        ]


class MfiOrganization(SoftDeleteModel):
    id = CuidField()
    code = models.CharField(max_length=32, unique=True)
    name = models.CharField(max_length=255, unique=True)
    country_code = models.CharField(max_length=2, default="UG", db_index=True)
    contact_name = models.CharField(max_length=255, blank=True, default="")
    contact_email = models.EmailField(blank=True, default="")
    contact_phone = models.CharField(max_length=64, blank=True, default="")
    active = models.BooleanField(default=True)
    data_sharing_agreement_active = models.BooleanField(default=False)
    onboarded_by = models.CharField(max_length=30, null=True, blank=True)
    onboarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_mfi_organization"
        ordering = ["name"]


class MfiMembershipRole(models.TextChoices):
    ADMIN = "admin", "MFI Partner Administrator"
    LOAN_OFFICER = "loan_officer", "MFI Loan Officer"


class MfiMembership(TimeStampedModel):
    id = CuidField()
    mfi = models.ForeignKey(
        MfiOrganization, on_delete=models.CASCADE, related_name="memberships"
    )
    user = models.ForeignKey(
        "accounts.User", on_delete=models.CASCADE, related_name="mfi_memberships"
    )
    role = models.CharField(max_length=16, choices=MfiMembershipRole.choices)
    officer_reference = models.CharField(max_length=64, blank=True, default="")
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "bt_mfi_membership"
        constraints = [
            models.UniqueConstraint(
                fields=["mfi", "user"], name="uniq_bt_mfi_user_membership"
            )
        ]


class FundingFacilityStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    APPROVED = "approved", "Approved"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"
    CANCELLED = "cancelled", "Cancelled"


class FacilityCapitalSource(models.TextChoices):
    ORIGINAL = "original", "Original funder capital"
    RECOVERED = "recovered", "Recovered principal"


class FacilityMovementKind(models.TextChoices):
    AUTHORIZED_DEDUCTION = "authorized_deduction", "Authorized facility deduction"
    CAPITAL_RETURN = "capital_return", "Capital returned to funder"


class FundingFacility(TimeStampedModel):
    """Approved capital envelope for one lending partner and currency."""

    id = CuidField()
    mfi = models.ForeignKey(
        MfiOrganization, on_delete=models.PROTECT, related_name="funding_facilities"
    )
    external_reference = models.CharField(max_length=128)
    name = models.CharField(max_length=255)
    country_code = models.CharField(max_length=2, default="UG", db_index=True)
    currency = models.CharField(max_length=3, default="UGX")
    funding_source = models.CharField(max_length=255, blank=True, default="")
    facility_type = models.CharField(max_length=64, blank=True, default="")
    approved_amount = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    commitment_amount = models.DecimalField(max_digits=20, decimal_places=2)
    revolving = models.BooleanField(default=False)
    starts_on = models.DateField()
    ends_on = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=FundingFacilityStatus.choices,
        default=FundingFacilityStatus.DRAFT,
        db_index=True,
    )
    agreement_reference = models.CharField(max_length=255, blank=True, default="")
    permitted_purpose_codes = models.JSONField(default=list, blank=True)
    geographic_restrictions = models.JSONField(default=dict, blank=True)
    school_eligibility_restrictions = models.JSONField(default=dict, blank=True)
    interest_structure = models.JSONField(default=dict, blank=True)
    reporting_conditions = models.JSONField(default=dict, blank=True)
    created_by = models.CharField(max_length=30)
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_funding_facility"
        ordering = ["-starts_on", "name"]
        indexes = [
            models.Index(fields=["mfi", "status"]),
            models.Index(fields=["country_code", "currency", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["mfi", "external_reference"],
                name="uniq_bt_facility_mfi_reference",
            ),
            models.CheckConstraint(
                condition=Q(commitment_amount__gt=0),
                name="bt_facility_commitment_positive",
            ),
            models.CheckConstraint(
                condition=Q(approved_amount__isnull=True) | Q(approved_amount__gt=0),
                name="bt_facility_approved_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(approved_amount__isnull=True)
                | Q(approved_amount__gte=models.F("commitment_amount")),
                name="bt_facility_approval_covers_commitment",
            ),
            models.CheckConstraint(
                condition=Q(ends_on__isnull=True)
                | Q(ends_on__gte=models.F("starts_on")),
                name="bt_facility_dates_ordered",
            ),
            models.CheckConstraint(
                condition=~Q(
                    status__in=[
                        FundingFacilityStatus.APPROVED,
                        FundingFacilityStatus.ACTIVE,
                        FundingFacilityStatus.SUSPENDED,
                        FundingFacilityStatus.CLOSED,
                    ]
                )
                | (Q(approved_by__isnull=False) & Q(approved_at__isnull=False)),
                name="bt_facility_approved_state_has_actor",
            ),
        ]


class FundingFacilityTranche(ImmutablePosting):
    """Confirmed cash receipt into a facility."""

    id = CuidField()
    facility = models.ForeignKey(
        FundingFacility, on_delete=models.PROTECT, related_name="tranches"
    )
    external_reference = models.CharField(max_length=128)
    tranche_number = models.PositiveIntegerField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, unique=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    received_on = models.DateField(db_index=True)
    value_date = models.DateField()
    evidence_reference = models.CharField(max_length=255)
    payment_reference = models.CharField(max_length=255, blank=True, default="")
    source_account = models.CharField(max_length=255, blank=True, default="")
    currency = models.CharField(max_length=3, default="UGX")
    exchange_rate = models.DecimalField(max_digits=18, decimal_places=8, default=1)
    reconciliation_status = models.CharField(
        max_length=24, default="confirmed", db_index=True
    )
    confirmed_by = models.CharField(max_length=30)
    confirmed_at = models.DateTimeField()

    class Meta:
        db_table = "bt_funding_facility_tranche"
        ordering = ["value_date", "created_at"]
        indexes = [models.Index(fields=["facility", "value_date"])]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "external_reference"],
                name="uniq_bt_facility_tranche_reference",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="bt_facility_tranche_amount_positive"
            ),
        ]


class FundingFacilityTrancheReversal(ImmutablePosting):
    """Compensating posting for an incorrectly confirmed facility receipt."""

    id = CuidField()
    tranche = models.OneToOneField(
        FundingFacilityTranche, on_delete=models.PROTECT, related_name="reversal"
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    reason = models.TextField()
    reversed_by = models.CharField(max_length=30)
    reversed_at = models.DateTimeField()

    class Meta:
        db_table = "bt_funding_facility_tranche_reversal"


class FundingFacilityMovement(ImmutablePosting):
    """Governed deduction or funder return against a named capital pool."""

    id = CuidField()
    facility = models.ForeignKey(
        FundingFacility, on_delete=models.PROTECT, related_name="movements"
    )
    kind = models.CharField(max_length=24, choices=FacilityMovementKind.choices)
    capital_source = models.CharField(
        max_length=16,
        choices=FacilityCapitalSource.choices,
        default=FacilityCapitalSource.ORIGINAL,
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    external_reference = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=128, unique=True)
    value_date = models.DateField(db_index=True)
    evidence_reference = models.CharField(max_length=255)
    posted_by = models.CharField(max_length=30)
    posted_at = models.DateTimeField()

    class Meta:
        db_table = "bt_funding_facility_movement"
        indexes = [models.Index(fields=["facility", "capital_source", "value_date"])]
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "external_reference"],
                name="uniq_bt_facility_movement_reference",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="bt_facility_movement_amount_positive"
            ),
        ]


class FundingFacilityMovementReversal(ImmutablePosting):
    id = CuidField()
    movement = models.OneToOneField(
        FundingFacilityMovement, on_delete=models.PROTECT, related_name="reversal"
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    reason = models.TextField()
    reversed_by = models.CharField(max_length=30)
    reversed_at = models.DateTimeField()

    class Meta:
        db_table = "bt_funding_facility_movement_reversal"


class LoanPurpose(TimeStampedModel):
    id = CuidField()
    code = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    parent_category = models.CharField(max_length=128, blank=True, default="")
    applicable_countries = models.JSONField(default=list, blank=True)
    applicable_school_types = models.JSONField(default=list, blank=True)
    unit_of_measure = models.CharField(max_length=64, default="count")
    requires_baseline = models.BooleanField(default=True)
    requires_planned_output = models.BooleanField(default=True)
    requires_actual_output = models.BooleanField(default=True)
    required_evidence = models.JSONField(default=list, blank=True)
    verification_method = models.TextField(blank=True, default="")
    impact_indicators = models.JSONField(default=list, blank=True)
    follow_up_days = models.PositiveIntegerField(default=60)
    allows_multiple = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)
    measurement_profile_complete = models.BooleanField(default=False)
    is_edtech = models.BooleanField(default=False)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "bt_loan_purpose"
        ordering = ["label"]


class ReferralStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SENT = "sent", "Received by MFI"
    UNDER_ASSESSMENT = "under_assessment", "Under assessment"
    MORE_INFORMATION = "more_information", "Additional information required"
    APPROVED = "approved", "Approved"
    DECLINED = "declined", "Declined"
    WITHDRAWN = "withdrawn", "Withdrawn"
    EXPIRED = "expired", "Expired"


class FinanceReferral(SoftDeleteModel):
    id = CuidField()
    case = models.ForeignKey(
        TransformationCase, on_delete=models.PROTECT, related_name="referrals"
    )
    mfi = models.ForeignKey(
        MfiOrganization, on_delete=models.PROTECT, related_name="referrals"
    )
    purpose = models.ForeignKey(
        LoanPurpose, on_delete=models.PROTECT, related_name="referrals"
    )
    requested_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(max_length=3, default="UGX")
    intended_use = models.TextField()
    consent_recorded_at = models.DateTimeField()
    status = models.CharField(
        max_length=24, choices=ReferralStatus.choices, default=ReferralStatus.DRAFT
    )
    referred_by = models.CharField(max_length=30)
    referred_at = models.DateTimeField(null=True, blank=True)
    mfi_decided_by = models.CharField(max_length=30, null=True, blank=True)
    mfi_decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bt_finance_referral"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["mfi", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(requested_amount__isnull=True) | Q(requested_amount__gt=0),
                name="bt_referral_requested_amount_positive",
            ),
        ]


class LoanStatus(models.TextChoices):
    """The MFI-controlled lifecycle; never repayment or assurance state."""

    PROCESSING = "processing", "Processing"
    DISBURSED = "disbursed", "Disbursed"
    ACTIVE = "active", "Active"
    REPAID = "repaid", "Repaid"
    DEFAULTED = "defaulted", "Defaulted"
    CANCELED = "canceled", "Canceled"


DISBURSED_LOAN_STATUSES = (
    LoanStatus.DISBURSED,
    LoanStatus.ACTIVE,
    LoanStatus.REPAID,
    LoanStatus.DEFAULTED,
)


class SalesforceStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    RETURNED = "returned", "Returned"


class IAValidationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    VERIFIED = "verified", "Verified"
    RETURNED = "returned", "Returned"


class LoanImpactStatus(models.TextChoices):
    NOT_DUE = "not_due", "Not Due"
    BASELINE_REQUIRED = "baseline_required", "Baseline Required"
    DUE = "due", "Due"
    UNDER_REVIEW = "under_review", "Under Review"
    STRONG_POSITIVE = "strong_positive", "Strong Positive Impact"
    POSITIVE = "positive", "Positive Impact"
    EARLY_PROGRESS = "early_progress", "Early Progress"
    MIXED = "mixed", "Mixed Impact"
    NO_CHANGE = "no_change", "No Measurable Change"
    NEGATIVE = "negative", "Negative Impact"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence", "Insufficient Evidence"


class LoanStatusDimension(models.TextChoices):
    LIFECYCLE = "lifecycle", "Loan lifecycle"
    SALESFORCE = "salesforce", "Salesforce confirmation"
    IA_VALIDATION = "ia_validation", "IA validation"
    REPAYMENT = "repayment", "Repayment health"
    IMPACT = "impact", "Loan impact"


class MfiLoan(SoftDeleteModel):
    id = CuidField()
    mfi = models.ForeignKey(
        MfiOrganization, on_delete=models.PROTECT, related_name="loans"
    )
    school = models.ForeignKey(
        "schools.School", on_delete=models.PROTECT, related_name="mfi_loans"
    )
    case = models.ForeignKey(
        TransformationCase, on_delete=models.PROTECT, related_name="loans"
    )
    referral = models.ForeignKey(
        FinanceReferral,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="loans",
    )
    facility = models.ForeignKey(
        FundingFacility,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="loans",
    )
    purpose = models.ForeignKey(
        LoanPurpose, on_delete=models.PROTECT, related_name="loans"
    )
    external_loan_reference = models.CharField(max_length=128)
    salesforce_loan_id = models.CharField(
        max_length=32, null=True, blank=True, unique=True
    )
    salesforce_status = models.CharField(
        max_length=16,
        choices=SalesforceStatus.choices,
        default=SalesforceStatus.PENDING,
        db_index=True,
    )
    salesforce_entry_date = models.DateField(null=True, blank=True)
    salesforce_confirmation_note = models.TextField(blank=True, default="")
    salesforce_confirmed_by = models.CharField(max_length=30, null=True, blank=True)
    salesforce_confirmed_at = models.DateTimeField(null=True, blank=True)
    salesforce_return_reason = models.CharField(max_length=64, blank=True, default="")
    salesforce_return_note = models.TextField(blank=True, default="")
    salesforce_returned_by = models.CharField(max_length=30, null=True, blank=True)
    salesforce_returned_at = models.DateTimeField(null=True, blank=True)
    ia_validation_status = models.CharField(
        max_length=16,
        choices=IAValidationStatus.choices,
        default=IAValidationStatus.PENDING,
        db_index=True,
    )
    ia_validated_by = models.CharField(max_length=30, null=True, blank=True)
    ia_validated_at = models.DateTimeField(null=True, blank=True)
    ia_return_reason = models.TextField(blank=True, default="")
    impact_status = models.CharField(
        max_length=32,
        choices=LoanImpactStatus.choices,
        default=LoanImpactStatus.NOT_DUE,
        db_index=True,
    )
    assigned_officer_reference = models.CharField(max_length=64, blank=True, default="")
    requested_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    approved_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    disbursed_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    currency = models.CharField(max_length=3, default="UGX")
    processing_date = models.DateField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    disbursement_date = models.DateField(null=True, blank=True)
    disbursement_confirmed_at = models.DateTimeField(null=True, blank=True)
    term_months = models.PositiveSmallIntegerField(null=True, blank=True)
    repayment_frequency = models.CharField(max_length=32, blank=True, default="")
    installment_amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True
    )
    maturity_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=LoanStatus.choices, default=LoanStatus.PROCESSING
    )
    registered_by = models.CharField(max_length=30)
    submitted_by = models.CharField(max_length=30, null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    default_classified_at = models.DateField(null=True, blank=True)
    default_reason = models.TextField(blank=True, default="")
    last_repayment_data_date = models.DateField(null=True, blank=True)
    certified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_mfi_loan"
        ordering = ["-disbursement_date", "-created_at"]
        indexes = [
            models.Index(fields=["mfi", "status"]),
            models.Index(fields=["facility", "status"]),
            models.Index(fields=["school", "status"]),
            models.Index(fields=["disbursement_date"]),
            models.Index(fields=["last_repayment_data_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["mfi", "external_loan_reference"],
                name="uniq_bt_mfi_external_loan_reference",
            ),
            models.CheckConstraint(
                condition=Q(requested_amount__isnull=True) | Q(requested_amount__gt=0),
                name="bt_loan_requested_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(approved_amount__isnull=True) | Q(approved_amount__gt=0),
                name="bt_loan_approved_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(disbursed_amount__isnull=True) | Q(disbursed_amount__gt=0),
                name="bt_loan_disbursed_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(installment_amount__isnull=True)
                | Q(installment_amount__gt=0),
                name="bt_loan_installment_amount_positive",
            ),
            models.CheckConstraint(
                condition=Q(approved_amount__isnull=True)
                | Q(disbursed_amount__isnull=True)
                | Q(approved_amount__gte=models.F("disbursed_amount")),
                name="bt_loan_approved_covers_legacy_disbursed",
            ),
            models.CheckConstraint(
                condition=~Q(status__in=DISBURSED_LOAN_STATUSES)
                | (
                    Q(disbursed_amount__isnull=False)
                    & Q(disbursement_date__isnull=False)
                    & Q(disbursement_confirmed_at__isnull=False)
                ),
                name="bt_disbursed_loan_has_confirmation",
            ),
            models.CheckConstraint(
                condition=~Q(status=LoanStatus.DEFAULTED)
                | (Q(default_classified_at__isnull=False) & ~Q(default_reason="")),
                name="bt_defaulted_loan_has_date_and_reason",
            ),
        ]

    @property
    def is_edtech(self) -> bool:
        return bool(self.purpose_id and self.purpose.is_edtech)

    @property
    def core_identity_locked(self) -> bool:
        return self.salesforce_status == SalesforceStatus.CONFIRMED


class SchoolLoan(MfiLoan):
    """Domain-language proxy retained over the compatible legacy table."""

    class Meta:
        proxy = True
        verbose_name = "School loan"
        verbose_name_plural = "School loans"


class FacilityAllocationStatus(models.TextChoices):
    RESERVED = "reserved", "Reserved"
    CONSUMED = "consumed", "Consumed"
    RELEASED = "released", "Released"


class FundingFacilityAllocation(TimeStampedModel):
    """A concurrency-locked reservation of facility capital for one loan."""

    id = CuidField()
    facility = models.ForeignKey(
        FundingFacility, on_delete=models.PROTECT, related_name="allocations"
    )
    loan = models.OneToOneField(
        MfiLoan, on_delete=models.PROTECT, related_name="facility_allocation"
    )
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    capital_source = models.CharField(
        max_length=16,
        choices=FacilityCapitalSource.choices,
        default=FacilityCapitalSource.ORIGINAL,
        db_index=True,
    )
    status = models.CharField(
        max_length=16,
        choices=FacilityAllocationStatus.choices,
        default=FacilityAllocationStatus.RESERVED,
        db_index=True,
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    reserved_by = models.CharField(max_length=30)
    reserved_at = models.DateTimeField()
    released_by = models.CharField(max_length=30, null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bt_funding_facility_allocation"
        indexes = [models.Index(fields=["facility", "status"])]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="bt_facility_allocation_positive"
            ),
            models.CheckConstraint(
                condition=~Q(status=FacilityAllocationStatus.RELEASED)
                | (
                    Q(released_by__isnull=False)
                    & Q(released_at__isnull=False)
                    & ~Q(release_reason="")
                ),
                name="bt_released_allocation_has_reason",
            ),
        ]


class LoanDisbursement(ImmutablePosting):
    """Confirmed multi-tranche principal movement from a facility to a loan."""

    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="disbursements"
    )
    allocation = models.ForeignKey(
        FundingFacilityAllocation,
        on_delete=models.PROTECT,
        related_name="disbursements",
    )
    sequence = models.PositiveSmallIntegerField()
    external_reference = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=128, unique=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    capital_source = models.CharField(
        max_length=16,
        choices=FacilityCapitalSource.choices,
        default=FacilityCapitalSource.ORIGINAL,
        db_index=True,
    )
    disbursed_on = models.DateField(db_index=True)
    value_date = models.DateField()
    bank_reference = models.CharField(max_length=255)
    confirmed_by = models.CharField(max_length=30)
    confirmed_at = models.DateTimeField()

    class Meta:
        db_table = "bt_loan_disbursement"
        ordering = ["loan", "sequence"]
        indexes = [
            models.Index(fields=["loan", "value_date"]),
            models.Index(fields=["allocation", "value_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "sequence"], name="uniq_bt_loan_disbursement_sequence"
            ),
            models.UniqueConstraint(
                fields=["allocation", "external_reference"],
                name="uniq_bt_allocation_disbursement_reference",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="bt_loan_disbursement_amount_positive"
            ),
        ]


class LoanDisbursementReversal(ImmutablePosting):
    id = CuidField()
    disbursement = models.OneToOneField(
        LoanDisbursement, on_delete=models.PROTECT, related_name="reversal"
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    reason = models.TextField()
    reversed_by = models.CharField(max_length=30)
    reversed_at = models.DateTimeField()

    class Meta:
        db_table = "bt_loan_disbursement_reversal"


class LoanRepaymentInstallment(ImmutablePosting):
    """Versioned contractual installment; paid state is always derived."""

    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="repayment_installments"
    )
    schedule_version = models.PositiveSmallIntegerField(default=1)
    installment_number = models.PositiveIntegerField()
    due_date = models.DateField(db_index=True)
    principal_due = models.DecimalField(max_digits=20, decimal_places=2)
    interest_due = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    fee_due = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    created_by = models.CharField(max_length=30)

    class Meta:
        db_table = "bt_loan_repayment_installment"
        ordering = ["loan", "schedule_version", "installment_number"]
        indexes = [
            models.Index(fields=["loan", "schedule_version", "due_date"]),
            models.Index(fields=["due_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "schedule_version", "installment_number"],
                name="uniq_bt_installment_version_number",
            ),
            models.CheckConstraint(
                condition=Q(principal_due__gte=0)
                & Q(interest_due__gte=0)
                & Q(fee_due__gte=0)
                & (Q(principal_due__gt=0) | Q(interest_due__gt=0) | Q(fee_due__gt=0)),
                name="bt_installment_has_positive_due",
            ),
        ]


class RepaymentTransactionKind(models.TextChoices):
    PAYMENT = "payment", "Payment"
    REVERSAL = "reversal", "Reversal"


class RepaymentTransaction(ImmutablePosting):
    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="repayment_transactions"
    )
    kind = models.CharField(
        max_length=12,
        choices=RepaymentTransactionKind.choices,
        default=RepaymentTransactionKind.PAYMENT,
    )
    reversal_of = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversal_entry",
    )
    external_reference = models.CharField(max_length=128)
    idempotency_key = models.CharField(max_length=128, unique=True)
    amount = models.DecimalField(max_digits=20, decimal_places=2)
    received_on = models.DateField(db_index=True)
    value_date = models.DateField()
    evidence_reference = models.CharField(max_length=255)
    posted_by = models.CharField(max_length=30)
    posted_at = models.DateTimeField()
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bt_repayment_transaction"
        ordering = ["value_date", "created_at"]
        indexes = [
            models.Index(fields=["loan", "value_date"]),
            models.Index(fields=["loan", "kind", "received_on"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "external_reference"],
                name="uniq_bt_repayment_loan_reference",
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="bt_repayment_transaction_positive"
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind=RepaymentTransactionKind.PAYMENT, reversal_of__isnull=True)
                    | (
                        Q(kind=RepaymentTransactionKind.REVERSAL)
                        & Q(reversal_of__isnull=False)
                        & ~Q(reason="")
                    )
                ),
                name="bt_repayment_reversal_shape",
            ),
        ]


class RepaymentComponent(models.TextChoices):
    PRINCIPAL = "principal", "Principal"
    INTEREST = "interest", "Interest"
    FEE = "fee", "Fee"
    PENALTY = "penalty", "Penalty"


class RepaymentAllocation(ImmutablePosting):
    id = CuidField()
    transaction = models.ForeignKey(
        RepaymentTransaction, on_delete=models.PROTECT, related_name="allocations"
    )
    installment = models.ForeignKey(
        LoanRepaymentInstallment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_allocations",
    )
    component = models.CharField(max_length=12, choices=RepaymentComponent.choices)
    amount = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        db_table = "bt_repayment_allocation"
        indexes = [
            models.Index(fields=["transaction", "component"]),
            models.Index(fields=["installment", "component"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["transaction", "installment", "component"],
                name="uniq_bt_repayment_allocation_component",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=Q(amount__gt=0), name="bt_repayment_allocation_positive"
            ),
        ]


class PurposeAllocationStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    REPORTED = "reported", "Reported"
    VERIFIED = "verified", "Verified"
    RETURNED = "returned", "Returned"


class LoanPurposeAllocation(TimeStampedModel):
    """Amount-based purpose split, separate from reported and verified use."""

    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="purpose_allocations"
    )
    purpose = models.ForeignKey(
        LoanPurpose, on_delete=models.PROTECT, related_name="loan_allocations"
    )
    planned_amount = models.DecimalField(max_digits=20, decimal_places=2)
    reported_amount = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    verified_amount = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    intended_output = models.TextField()
    status = models.CharField(
        max_length=16,
        choices=PurposeAllocationStatus.choices,
        default=PurposeAllocationStatus.PLANNED,
        db_index=True,
    )
    recorded_by = models.CharField(max_length=30)
    verified_by = models.CharField(max_length=30, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    verification_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bt_loan_purpose_allocation"
        indexes = [models.Index(fields=["loan", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "purpose"], name="uniq_bt_loan_purpose_allocation"
            ),
            models.CheckConstraint(
                condition=Q(planned_amount__gt=0)
                & (Q(reported_amount__isnull=True) | Q(reported_amount__gte=0))
                & (Q(verified_amount__isnull=True) | Q(verified_amount__gte=0)),
                name="bt_purpose_allocation_amounts_valid",
            ),
            models.CheckConstraint(
                condition=~Q(status=PurposeAllocationStatus.VERIFIED)
                | (
                    Q(verified_amount__isnull=False)
                    & Q(verified_by__isnull=False)
                    & Q(verified_at__isnull=False)
                ),
                name="bt_verified_purpose_has_evidence_actor",
            ),
        ]


class ImpactEvidenceStatus(models.TextChoices):
    REPORTED = "reported", "Reported"
    VERIFIED = "verified", "Verified"
    RETURNED = "returned", "Returned"


class TeacherProgrammeStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    ENROLLED = "enrolled", "Enrolled"
    STUDYING = "studying", "Currently studying"
    DEFERRED = "deferred", "Deferred"
    WITHDRAWN = "withdrawn", "Withdrawn"
    COMPLETED = "completed", "Completed"
    VERIFICATION_PENDING = "verification_pending", "Verification pending"
    VERIFIED_COMPLETED = "verified_completed", "Verified completed"


class EnrolmentSnapshotKind(models.TextChoices):
    BASELINE = "baseline", "Baseline"
    FOLLOW_UP = "follow_up", "Follow-up"


class EnrolmentSnapshot(TimeStampedModel):
    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="enrolment_snapshots"
    )
    kind = models.CharField(max_length=12, choices=EnrolmentSnapshotKind.choices)
    as_of_date = models.DateField(db_index=True)
    learner_count = models.PositiveIntegerField()
    cohort_definition = models.TextField()
    evidence_reference = models.CharField(max_length=255)
    status = models.CharField(
        max_length=12,
        choices=ImpactEvidenceStatus.choices,
        default=ImpactEvidenceStatus.REPORTED,
        db_index=True,
    )
    reported_by = models.CharField(max_length=30)
    verified_by = models.CharField(max_length=30, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_enrolment_snapshot"
        ordering = ["loan", "as_of_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "kind", "as_of_date"],
                name="uniq_bt_enrolment_snapshot_date",
            ),
            models.CheckConstraint(
                condition=~Q(status=ImpactEvidenceStatus.VERIFIED)
                | (Q(verified_by__isnull=False) & Q(verified_at__isnull=False)),
                name="bt_verified_enrolment_has_actor",
            ),
        ]


class TeacherDegreeUpgradeBeneficiary(TimeStampedModel):
    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="teacher_beneficiaries"
    )
    anonymized_reference = models.CharField(max_length=128)
    qualification_before = models.CharField(max_length=255, blank=True, default="")
    institution = models.CharField(max_length=255)
    programme = models.CharField(max_length=255)
    started_on = models.DateField()
    expected_completion_on = models.DateField(null=True, blank=True)
    completed_on = models.DateField(null=True, blank=True)
    funding_amount = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    programme_status = models.CharField(
        max_length=24,
        choices=TeacherProgrammeStatus.choices,
        default=TeacherProgrammeStatus.PLANNED,
        db_index=True,
    )
    evidence_reference = models.CharField(max_length=255)
    status = models.CharField(
        max_length=12,
        choices=ImpactEvidenceStatus.choices,
        default=ImpactEvidenceStatus.REPORTED,
    )
    reported_by = models.CharField(max_length=30)
    verified_by = models.CharField(max_length=30, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_teacher_degree_beneficiary"
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "anonymized_reference"],
                name="uniq_bt_loan_teacher_beneficiary",
            ),
            models.CheckConstraint(
                condition=Q(completed_on__isnull=True)
                | Q(completed_on__gte=models.F("started_on")),
                name="bt_teacher_beneficiary_dates_ordered",
            ),
            models.CheckConstraint(
                condition=Q(funding_amount__isnull=True) | Q(funding_amount__gte=0),
                name="bt_teacher_funding_nonnegative",
            ),
            models.CheckConstraint(
                condition=~Q(programme_status=TeacherProgrammeStatus.VERIFIED_COMPLETED)
                | (
                    Q(completed_on__isnull=False)
                    & ~Q(evidence_reference="")
                    & Q(verified_by__isnull=False)
                    & Q(verified_at__isnull=False)
                ),
                name="bt_teacher_verified_completion_has_evidence",
            ),
        ]


class PurposeSpecificAssetOutput(TimeStampedModel):
    id = CuidField()
    allocation = models.ForeignKey(
        LoanPurposeAllocation, on_delete=models.PROTECT, related_name="asset_outputs"
    )
    asset_type = models.CharField(max_length=128)
    unit = models.CharField(max_length=64, default="count")
    planned_quantity = models.PositiveIntegerField()
    reported_quantity = models.PositiveIntegerField(null=True, blank=True)
    verified_quantity = models.PositiveIntegerField(null=True, blank=True)
    reported_operational_quantity = models.PositiveIntegerField(null=True, blank=True)
    verified_operational_quantity = models.PositiveIntegerField(null=True, blank=True)
    learner_capacity = models.PositiveIntegerField(null=True, blank=True)
    area = models.DecimalField(max_digits=20, decimal_places=4, null=True, blank=True)
    area_unit = models.CharField(max_length=16, blank=True, default="")
    reported_completion_state = models.CharField(max_length=64, blank=True, default="")
    verified_completion_state = models.CharField(max_length=64, blank=True, default="")
    unit_cost = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True
    )
    evidence_reference = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=12,
        choices=ImpactEvidenceStatus.choices,
        default=ImpactEvidenceStatus.REPORTED,
    )
    reported_by = models.CharField(max_length=30)
    verified_by = models.CharField(max_length=30, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_purpose_asset_output"
        constraints = [
            models.UniqueConstraint(
                fields=["allocation", "asset_type"],
                name="uniq_bt_allocation_asset_type",
            ),
            models.CheckConstraint(
                condition=Q(unit_cost__isnull=True) | Q(unit_cost__gte=0),
                name="bt_asset_unit_cost_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(area__isnull=True) | Q(area__gte=0),
                name="bt_asset_area_nonnegative",
            ),
            models.CheckConstraint(
                condition=(
                    Q(reported_quantity__isnull=True)
                    | Q(reported_quantity__lte=models.F("planned_quantity"))
                )
                & (
                    Q(verified_quantity__isnull=True)
                    | (
                        Q(reported_quantity__isnull=False)
                        & Q(verified_quantity__lte=models.F("reported_quantity"))
                    )
                )
                & (
                    Q(verified_operational_quantity__isnull=True)
                    | (
                        Q(verified_quantity__isnull=False)
                        & Q(
                            verified_operational_quantity__lte=models.F(
                                "verified_quantity"
                            )
                        )
                    )
                ),
                name="bt_asset_output_quantity_funnel",
            ),
            models.CheckConstraint(
                condition=~Q(status=ImpactEvidenceStatus.VERIFIED)
                | (
                    ~Q(evidence_reference="")
                    & Q(verified_by__isnull=False)
                    & Q(verified_at__isnull=False)
                ),
                name="bt_asset_verified_has_evidence_actor",
            ),
        ]


class LoanPurposeProposalStatus(models.TextChoices):
    REQUESTED = "requested", "Requested"
    BT_REVIEWED = "bt_reviewed", "BT reviewed"
    IA_DEFINED = "ia_defined", "IA measurement defined"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class LoanPurposeProposal(TimeStampedModel):
    id = CuidField()
    proposed_code = models.CharField(max_length=64)
    proposed_label = models.CharField(max_length=255)
    proposed_is_edtech = models.BooleanField(default=False)
    rationale = models.TextField()
    description = models.TextField(blank=True, default="")
    expected_outputs = models.TextField(blank=True, default="")
    unit_of_measure = models.CharField(max_length=64, blank=True, default="")
    required_evidence = models.JSONField(default=list, blank=True)
    expected_impact = models.TextField(blank=True, default="")
    verification_method = models.TextField(blank=True, default="")
    impact_indicators = models.JSONField(default=list, blank=True)
    example_loan_reference = models.CharField(max_length=128, blank=True, default="")
    bt_reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    bt_reviewed_at = models.DateTimeField(null=True, blank=True)
    ia_defined_by = models.CharField(max_length=30, null=True, blank=True)
    ia_defined_at = models.DateTimeField(null=True, blank=True)
    cd_approved_by = models.CharField(max_length=30, null=True, blank=True)
    cd_approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12,
        choices=LoanPurposeProposalStatus.choices,
        default=LoanPurposeProposalStatus.REQUESTED,
        db_index=True,
    )
    requested_by = models.CharField(max_length=30)
    reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True, default="")
    resulting_purpose = models.OneToOneField(
        LoanPurpose,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_proposal",
    )

    class Meta:
        db_table = "bt_loan_purpose_proposal"


class SalesforceConfirmation(ImmutablePosting):
    """Append-only source reconciliation event; MfiLoan fields are a projection."""

    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="salesforce_confirmations"
    )
    status = models.CharField(max_length=16, choices=SalesforceStatus.choices)
    salesforce_loan_id = models.CharField(max_length=32, blank=True, default="")
    reason = models.TextField(blank=True, default="")
    payload_sha256 = models.CharField(max_length=64)
    idempotency_key = models.CharField(max_length=128, unique=True)
    recorded_by = models.CharField(max_length=30)
    recorded_at = models.DateTimeField()

    class Meta:
        db_table = "bt_salesforce_confirmation"
        indexes = [models.Index(fields=["loan", "recorded_at"])]


class LoanStatusHistory(TimeStampedModel):
    """Append-only events for period activity and point-in-time reporting."""

    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="status_history"
    )
    dimension = models.CharField(max_length=24, choices=LoanStatusDimension.choices)
    previous_value = models.CharField(max_length=64, blank=True, default="")
    new_value = models.CharField(max_length=64)
    reason = models.TextField(blank=True, default="")
    changed_by = models.CharField(max_length=30)
    effective_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "bt_loan_status_history"
        ordering = ["-effective_at", "-created_at"]
        indexes = [
            models.Index(fields=["loan", "dimension", "effective_at"]),
            models.Index(fields=["dimension", "new_value", "effective_at"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValueError("Loan status history is append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Loan status history is append-only.")


class RepaymentStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not Started"
    CURRENT = "current", "Current"
    DUE_SOON = "due_soon", "Due Soon"
    OVERDUE_1_30 = "overdue_1_30", "Overdue 1–30"
    OVERDUE_31_90 = "overdue_31_90", "Overdue 31–90"
    OVERDUE_90_PLUS = "overdue_90_plus", "Overdue 90+"
    RESTRUCTURED = "restructured", "Restructured"
    UNKNOWN = "unknown", "Unknown"


class RepaymentSnapshot(TimeStampedModel):
    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="repayment_snapshots"
    )
    as_of_date = models.DateField()
    reporting_month = models.DateField(null=True, blank=True, db_index=True)
    amount_due_during_period = models.DecimalField(
        max_digits=18, decimal_places=2, default=0
    )
    amount_paid_during_period = models.DecimalField(
        max_digits=18, decimal_places=2, default=0
    )
    principal_repaid = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    outstanding_amount = models.DecimalField(max_digits=18, decimal_places=2)
    amount_currently_due = models.DecimalField(
        max_digits=18, decimal_places=2, default=0
    )
    amount_overdue = models.DecimalField(max_digits=18, decimal_places=2, default=0)
    days_in_arrears = models.PositiveIntegerField(default=0)
    next_payment_date = models.DateField(null=True, blank=True)
    last_payment_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=RepaymentStatus.choices)
    restructuring_status = models.CharField(max_length=64, blank=True, default="")
    submitted_by = models.CharField(max_length=30)
    certified = models.BooleanField(default=False)
    certified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_repayment_snapshot"
        ordering = ["-as_of_date", "-created_at"]
        indexes = [
            models.Index(fields=["loan", "as_of_date"]),
            models.Index(fields=["status", "as_of_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "as_of_date"], name="uniq_bt_loan_repayment_as_of"
            ),
            models.CheckConstraint(
                condition=Q(principal_repaid__gte=0)
                & Q(amount_due_during_period__gte=0)
                & Q(amount_paid_during_period__gte=0)
                & Q(outstanding_amount__gte=0)
                & Q(amount_currently_due__gte=0)
                & Q(amount_overdue__gte=0),
                name="bt_repayment_amounts_nonnegative",
            ),
        ]


class PortfolioSubmissionStatus(models.TextChoices):
    STAGED = "staged", "Staged"
    NEEDS_CORRECTION = "needs_correction", "Needs correction"
    IMPORTED = "imported", "Imported"
    CERTIFIED = "certified", "Certified"


class PortfolioSubmission(TimeStampedModel):
    id = CuidField()
    mfi = models.ForeignKey(
        MfiOrganization, on_delete=models.PROTECT, related_name="portfolio_submissions"
    )
    reporting_month = models.DateField()
    source_type = models.CharField(
        max_length=16,
        choices=[("manual", "Manual"), ("spreadsheet", "Spreadsheet"), ("api", "API")],
    )
    source_file_name = models.CharField(max_length=255, blank=True, default="")
    file_sha256 = models.CharField(max_length=64, blank=True, default="")
    status = models.CharField(
        max_length=24,
        choices=PortfolioSubmissionStatus.choices,
        default=PortfolioSubmissionStatus.STAGED,
    )
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    exception_rows = models.PositiveIntegerField(default=0)
    submitted_by = models.CharField(max_length=30)
    certified_by = models.CharField(max_length=30, null=True, blank=True)
    certified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_portfolio_submission"
        ordering = ["-reporting_month", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["mfi", "reporting_month", "file_sha256"],
                name="uniq_bt_portfolio_submission_file",
            )
        ]


class PortfolioDataException(TimeStampedModel):
    id = CuidField()
    submission = models.ForeignKey(
        PortfolioSubmission, on_delete=models.CASCADE, related_name="exceptions"
    )
    row_number = models.PositiveIntegerField(null=True, blank=True)
    code = models.CharField(max_length=64)
    message = models.TextField()
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, default="open")
    resolved_by = models.CharField(max_length=30, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_portfolio_data_exception"
        indexes = [models.Index(fields=["submission", "status"])]


class PortfolioImportRowStatus(models.TextChoices):
    VALID = "valid", "Valid"
    INVALID = "invalid", "Invalid"
    APPLIED = "applied", "Applied"


class PortfolioImportRow(TimeStampedModel):
    """Immutable-source staging row; normalized facts are applied idempotently."""

    id = CuidField()
    submission = models.ForeignKey(
        PortfolioSubmission, on_delete=models.CASCADE, related_name="rows"
    )
    row_number = models.PositiveIntegerField()
    raw_data = models.JSONField(default=dict)
    normalized_data = models.JSONField(default=dict)
    status = models.CharField(
        max_length=12,
        choices=PortfolioImportRowStatus.choices,
        default=PortfolioImportRowStatus.VALID,
    )
    error_codes = models.JSONField(default=list, blank=True)
    idempotency_key = models.CharField(max_length=191, unique=True)
    loan = models.ForeignKey(
        MfiLoan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_rows",
    )
    repayment_transaction = models.OneToOneField(
        RepaymentTransaction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_row",
    )

    class Meta:
        db_table = "bt_portfolio_import_row"
        ordering = ["submission", "row_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "row_number"],
                name="uniq_bt_portfolio_submission_row",
            )
        ]


class VerificationRequirementStatus(models.TextChoices):
    NEEDS_SCHEDULING = "needs_scheduling", "Needs scheduling"
    SCHEDULED = "scheduled", "Scheduled"
    AWAITING_VERIFICATION = "awaiting_verification", "Awaiting IA verification"
    VERIFIED = "verified", "Verified"
    OVERDUE = "overdue", "Overdue"
    CANCELLED = "cancelled", "Cancelled"


class LoanVerificationRequirement(TimeStampedModel):
    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="verification_requirements"
    )
    due_date = models.DateField()
    status = models.CharField(
        max_length=24,
        choices=VerificationRequirementStatus.choices,
        default=VerificationRequirementStatus.NEEDS_SCHEDULING,
    )
    activity = models.OneToOneField(
        "activities.Activity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loan_verification_requirement",
    )
    assigned_by = models.CharField(max_length=30, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_loan_verification_requirement"
        ordering = ["due_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan"], name="uniq_bt_initial_verification_per_loan"
            )
        ]


class LoanUseVerification(LoanVerificationRequirement):
    class Meta:
        proxy = True
        verbose_name = "Loan-use verification"
        verbose_name_plural = "Loan-use verifications"


class BusinessTransformationActivityLink(TimeStampedModel):
    id = CuidField()
    activity = models.OneToOneField(
        "activities.Activity",
        on_delete=models.PROTECT,
        related_name="business_transformation_link",
    )
    case = models.ForeignKey(
        TransformationCase, on_delete=models.PROTECT, related_name="activity_links"
    )
    loan = models.ForeignKey(
        MfiLoan,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="activity_links",
    )
    purpose = models.CharField(max_length=48, choices=RecommendationKind.choices)

    class Meta:
        db_table = "bt_activity_link"


class LoanUseFinding(models.TextChoices):
    FULLY_APPROVED = "fully_approved", "Used fully as approved"
    PARTLY_APPROVED = "partly_approved", "Used partly as approved"
    DELAYED = "delayed", "Use delayed"
    PURPOSE_CHANGED = "purpose_changed", "Purpose changed with MFI approval"
    POSSIBLE_DIVERSION = "possible_diversion", "Possible diversion"
    ASSET_NOT_DELIVERED = "asset_not_delivered", "Asset not yet delivered"
    ASSET_NOT_OPERATIONAL = (
        "asset_not_operational",
        "Asset delivered but not operational",
    )
    INSUFFICIENT_EVIDENCE = "insufficient_evidence", "Insufficient evidence"
    NOT_COMPLETED = "not_completed", "Verification could not be completed"


class LoanUseResult(TimeStampedModel):
    id = CuidField()
    requirement = models.OneToOneField(
        LoanVerificationRequirement,
        on_delete=models.PROTECT,
        related_name="result",
    )
    finding = models.CharField(max_length=32, choices=LoanUseFinding.choices)
    notes = models.TextField(blank=True, default="")
    edtech_asset_operational = models.BooleanField(null=True, blank=True)
    recorded_by = models.CharField(max_length=30)
    verification_status = models.CharField(max_length=16, default="provisional")
    ia_verified_at = models.DateTimeField(null=True, blank=True)
    concern_reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    concern_reviewed_at = models.DateTimeField(null=True, blank=True)
    concern_review_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bt_loan_use_result"


class LoanAmendment(TimeStampedModel):
    """Audited correction path for an MFI-certified financial fact."""

    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="amendments"
    )
    idempotency_key = models.CharField(
        max_length=128, unique=True, null=True, blank=True
    )
    reason = models.TextField()
    previous_values = models.JSONField()
    new_values = models.JSONField()
    requested_by = models.CharField(max_length=30)
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approval_note = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, default="requested")

    class Meta:
        db_table = "bt_loan_amendment"
        ordering = ["-created_at"]


class LoanImpactAssessment(TimeStampedModel):
    """BT prepares purpose-specific outcomes; IA publishes the verified result."""

    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="impact_assessments"
    )
    due_date = models.DateField()
    assessment_date = models.DateField(null=True, blank=True)
    baseline_indicators = models.JSONField(default=dict, blank=True)
    follow_up_indicators = models.JSONField(default=dict, blank=True)
    classification = models.CharField(
        max_length=32,
        choices=LoanImpactStatus.choices,
        default=LoanImpactStatus.NOT_DUE,
    )
    narrative = models.TextField(blank=True, default="")
    limitations = models.TextField(blank=True, default="")
    evidence_references = models.JSONField(default=list, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    prepared_by = models.CharField(max_length=30, null=True, blank=True)
    prepared_at = models.DateTimeField(null=True, blank=True)
    ia_status = models.CharField(
        max_length=16,
        choices=IAValidationStatus.choices,
        default=IAValidationStatus.PENDING,
    )
    ia_verified_by = models.CharField(max_length=30, null=True, blank=True)
    ia_verified_at = models.DateTimeField(null=True, blank=True)
    ia_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bt_loan_impact_assessment"
        ordering = ["due_date", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "due_date"], name="uniq_bt_loan_impact_due_date"
            )
        ]


class FinancialPracticeAssessment(TimeStampedModel):
    """Operational practice adoption, separate from training attendance and SSA."""

    id = CuidField()
    case = models.ForeignKey(
        TransformationCase,
        on_delete=models.PROTECT,
        related_name="financial_practice_assessments",
    )
    assessed_on = models.DateField()
    practices = models.JSONField(default=dict)
    notes = models.TextField(blank=True, default="")
    recorded_by = models.CharField(max_length=30)
    verification_status = models.CharField(
        max_length=16,
        choices=IAValidationStatus.choices,
        default=IAValidationStatus.PENDING,
    )
    verified_by = models.CharField(max_length=30, null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_financial_practice_assessment"
        ordering = ["-assessed_on", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["case", "assessed_on"],
                name="uniq_bt_financial_practice_case_date",
            )
        ]


class ComplianceRequirement(TimeStampedModel):
    id = CuidField()
    country_code = models.CharField(max_length=2, default="UG")
    code = models.CharField(max_length=64)
    label = models.CharField(max_length=255)
    responsible_authority = models.CharField(max_length=255, blank=True, default="")
    school_type = models.CharField(max_length=64, blank=True, default="all")
    description = models.TextField(blank=True, default="")
    evidence_description = models.TextField(blank=True, default="")
    renewal_months = models.PositiveSmallIntegerField(null=True, blank=True)
    applicability_rule = models.JSONField(default=dict, blank=True)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "bt_compliance_requirement"
        ordering = ["label"]
        constraints = [
            models.UniqueConstraint(
                fields=["country_code", "code"], name="uniq_bt_compliance_country_code"
            ),
            models.CheckConstraint(
                condition=Q(country_code="UG"), name="bt_compliance_uganda_only"
            ),
        ]


class ComplianceStatus(models.TextChoices):
    NOT_ASSESSED = "not_assessed", "Not Assessed"
    UNKNOWN = "unknown", "Unknown"
    NOT_STARTED = "not_started", "Not Started"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLIANT = "compliant", "Compliant"
    ACTION_REQUIRED = "action_required", "Action Required"
    EXPIRED = "expired", "Expired"
    EXEMPT = "exempt", "Exempt/Not Applicable"
    UNDER_REVIEW = "under_review", "Under Review"


class SchoolComplianceAssessment(TimeStampedModel):
    id = CuidField()
    case = models.ForeignKey(
        TransformationCase,
        on_delete=models.PROTECT,
        related_name="compliance_assessments",
    )
    requirement = models.ForeignKey(
        ComplianceRequirement,
        on_delete=models.PROTECT,
        related_name="school_assessments",
    )
    status = models.CharField(
        max_length=24,
        choices=ComplianceStatus.choices,
        default=ComplianceStatus.NOT_ASSESSED,
    )
    registration_number = models.CharField(max_length=128, blank=True, default="")
    registration_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True, db_index=True)
    evidence_reference = models.CharField(max_length=255, blank=True, default="")
    follow_up_action = models.TextField(blank=True, default="")
    responsible_person = models.CharField(max_length=255, blank=True, default="")
    assessed_by = models.CharField(max_length=30)
    assessed_at = models.DateTimeField()
    ia_status = models.CharField(
        max_length=16,
        choices=IAValidationStatus.choices,
        default=IAValidationStatus.PENDING,
    )
    ia_verified_by = models.CharField(max_length=30, null=True, blank=True)
    ia_verified_at = models.DateTimeField(null=True, blank=True)
    ia_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "bt_school_compliance_assessment"
        ordering = ["requirement__label", "-assessed_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["case", "requirement"],
                name="uniq_bt_school_compliance_requirement",
            )
        ]


__all__ = [
    "FacilityCapitalSource",
    "FacilityMovementKind",
    "FacilityAllocationStatus",
    "EnrolmentSnapshot",
    "EnrolmentSnapshotKind",
    "FundingFacility",
    "FundingFacilityAllocation",
    "FundingFacilityStatus",
    "FundingFacilityTranche",
    "FundingFacilityTrancheReversal",
    "FundingFacilityMovement",
    "FundingFacilityMovementReversal",
    "BusinessTransformationActivityLink",
    "BusinessTransformationPolicy",
    "CaseRecommendation",
    "CaseStatus",
    "CaseTrigger",
    "ComplianceStatus",
    "ComplianceRequirement",
    "FinancialPracticeAssessment",
    "FinanceReferral",
    "IAValidationStatus",
    "LoanAmendment",
    "LoanDisbursement",
    "LoanDisbursementReversal",
    "LoanImpactAssessment",
    "LoanImpactStatus",
    "LoanPurpose",
    "LoanPurposeAllocation",
    "LoanPurposeProposal",
    "LoanPurposeProposalStatus",
    "LoanRepaymentInstallment",
    "LoanStatus",
    "LoanStatusDimension",
    "LoanStatusHistory",
    "LoanUseFinding",
    "LoanUseResult",
    "LoanUseVerification",
    "LoanVerificationRequirement",
    "MfiLoan",
    "MfiMembership",
    "MfiMembershipRole",
    "MfiOrganization",
    "PortfolioDataException",
    "PortfolioImportRow",
    "PortfolioImportRowStatus",
    "PortfolioSubmission",
    "PurposeAllocationStatus",
    "PurposeSpecificAssetOutput",
    "RecommendationKind",
    "RepaymentStatus",
    "RepaymentAllocation",
    "RepaymentComponent",
    "RepaymentSnapshot",
    "RepaymentTransaction",
    "RepaymentTransactionKind",
    "SalesforceStatus",
    "SalesforceConfirmation",
    "SchoolComplianceAssessment",
    "SchoolLoan",
    "TeacherDegreeUpgradeBeneficiary",
    "TeacherProgrammeStatus",
    "ImpactEvidenceStatus",
    "TransformationCase",
]
