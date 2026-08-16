"""Uganda Business Transformation records.

Loans are deliberately outside Edify's operating-finance workflow. Activities
may spend Edify programme money to train or verify a school; an MFI loan is an
external financial instrument and lives in this separate, durable ledger.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


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


class LoanPurpose(TimeStampedModel):
    id = CuidField()
    code = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=255)
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
            models.CheckConstraint(
                condition=Q(currency="UGX"), name="bt_referral_uganda_currency"
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
    last_repayment_data_date = models.DateField(null=True, blank=True)
    certified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "bt_mfi_loan"
        ordering = ["-disbursement_date", "-created_at"]
        indexes = [
            models.Index(fields=["mfi", "status"]),
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
                condition=Q(currency="UGX"), name="bt_loan_uganda_currency"
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
        ]

    @property
    def is_edtech(self) -> bool:
        return bool(self.purpose_id and self.purpose.is_edtech)

    @property
    def core_identity_locked(self) -> bool:
        return self.salesforce_status == SalesforceStatus.CONFIRMED


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

    class Meta:
        db_table = "bt_loan_use_result"


class LoanAmendment(TimeStampedModel):
    """Audited correction path for an MFI-certified financial fact."""

    id = CuidField()
    loan = models.ForeignKey(
        MfiLoan, on_delete=models.PROTECT, related_name="amendments"
    )
    reason = models.TextField()
    previous_values = models.JSONField()
    new_values = models.JSONField()
    requested_by = models.CharField(max_length=30)
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
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
    "LoanImpactAssessment",
    "LoanImpactStatus",
    "LoanPurpose",
    "LoanStatus",
    "LoanStatusDimension",
    "LoanStatusHistory",
    "LoanUseFinding",
    "LoanUseResult",
    "LoanVerificationRequirement",
    "MfiLoan",
    "MfiMembership",
    "MfiMembershipRole",
    "MfiOrganization",
    "PortfolioDataException",
    "PortfolioSubmission",
    "RecommendationKind",
    "RepaymentStatus",
    "RepaymentSnapshot",
    "SalesforceStatus",
    "SchoolComplianceAssessment",
    "TransformationCase",
]
