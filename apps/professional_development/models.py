"""Professional Development — one shared employee-owned workflow.

Every eligible employee (CCEO, PL, CD, RVP, IA, Accountant, HR, Project
Coordinator, Admin) uses the SAME request, course-tracking, completion,
certificate, BambooHR and accountability lifecycle. HR administers the
program but never approves or signs off its own staff's requests — see
`apps.professional_development.services.PDApprovalRoutingService`.

`ProfessionalDevelopmentRequest` is a single status-driven record spanning
the whole lifecycle (draft → supervisor → HR → finance → enrollment →
course tracking → employee-marked-complete → certificate → BambooHR →
accountability → HR sign-off → closed) — the same one-record-many-statuses
convention used by MonthlyWorkPlanBudget/AdvanceRequest, so the UI timeline
is a straight status→step lookup rather than a join across many tables.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class PDAllocationStatus(models.TextChoices):
    NOT_ALLOCATED = "not_allocated", "Not Allocated"
    ACTIVE = "active", "Active"
    PARTIALLY_USED = "partially_used", "Partially Used"
    FULLY_USED = "fully_used", "Fully Used"
    SUSPENDED = "suspended", "Suspended"
    CLOSED = "closed", "Closed"


class ProfessionalDevelopmentAllocation(TimeStampedModel):
    """One row per employee per financial year — the PD fund envelope.
    Committed/disbursed/accounted/remaining are always DERIVED from the
    employee's requests at read time (StaffPDService) — never stored here,
    so there is no cached balance that can drift from reality."""

    id = CuidField()
    staff_id = models.CharField(max_length=30)  # StaffProfile.id
    fy = models.CharField(max_length=16)
    country = models.CharField(max_length=64, default="Uganda")
    currency = models.CharField(max_length=8, default="UGX")
    annual_allocation = models.BigIntegerField(default=0)
    status = models.CharField(
        max_length=20, choices=PDAllocationStatus.choices, default=PDAllocationStatus.ACTIVE
    )
    set_by = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "pd_allocation"
        constraints = [
            models.UniqueConstraint(fields=["staff_id", "fy"], name="uniq_pd_allocation_staff_fy")
        ]
        indexes = [models.Index(fields=["staff_id", "fy"])]

    def __str__(self) -> str:
        return f"PD Allocation {self.staff_id} FY{self.fy}"


class PDRoleAllocation(TimeStampedModel):
    """HR-configured default annual PD allocation per role — set once via the
    HR Professional Development Dashboard's "Adjust Allocation" action, then
    bulk-applied to every staff member's own `ProfessionalDevelopmentAllocation`
    row for that role/FY/country (§16). The per-staff row remains the single
    source of truth `StaffPDService.balances()` reads from — this table is
    only the template HR edits; changing it does not retroactively touch
    anyone's balance until an explicit "apply" action runs."""

    id = CuidField()
    role = models.CharField(max_length=32)  # EdifyRole value, e.g. "CCEO"
    fy = models.CharField(max_length=16)
    country = models.CharField(max_length=64, default="Uganda")
    currency = models.CharField(max_length=8, default="UGX")
    annual_allocation_cents = models.BigIntegerField(default=0)
    set_by = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "pd_role_allocation"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "fy", "country"], name="uniq_pd_role_allocation_role_fy_country"
            )
        ]
        indexes = [models.Index(fields=["fy", "country"])]

    def __str__(self) -> str:
        return f"PD Role Allocation {self.role} FY{self.fy} {self.country}"


class PDCourseType(models.TextChoices):
    ONLINE = "online", "Online"
    IN_PERSON = "in_person", "In Person"
    HYBRID = "hybrid", "Hybrid"


class PDFundingType(models.TextChoices):
    FULLY_FUNDED = "fully_funded", "Fully Funded by Edify"
    PARTIALLY_FUNDED = "partially_funded", "Partially Funded by Edify"
    SELF_FUNDED = "self_funded", "Self-Funded"
    FREE = "free", "Free Course"
    SCHOLARSHIP = "scholarship", "External Scholarship"


# Whole-lifecycle status. One field, one source of truth — the course
# progress tracker is a straight lookup from this value (see
# apps/professional_development/services.py TIMELINE_STEPS).
class PDStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED_TO_SUPERVISOR = "submitted_to_supervisor", "Submitted to Supervisor"
    RETURNED_BY_SUPERVISOR = "returned_by_supervisor", "Returned by Supervisor"
    SUBMITTED_TO_HR = "submitted_to_hr", "Submitted to HR"
    RETURNED_BY_HR = "returned_by_hr", "Returned by HR"
    PENDING_EXCEPTION = "pending_exception", "Pending Exception Approval"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
    APPROVED_PENDING_FUNDING = "approved_pending_funding", "Approved — Pending Finance"
    APPROVED_UNFUNDED = "approved_unfunded", "Approved"
    DISBURSED = "disbursed", "Funds Disbursed"
    ENROLLMENT_PENDING = "enrollment_pending", "Enrollment Pending"
    ENROLLMENT_CONFIRMED = "enrollment_confirmed", "Enrollment Confirmed"
    IN_PROGRESS = "in_progress", "Course In Progress"
    ENDED = "ended", "Course Ended"
    MARKED_COMPLETE = "marked_complete", "Employee Marked Complete"
    CERTIFICATE_UPLOADED = "certificate_uploaded", "Certificate Uploaded"
    BAMBOOHR_CONFIRMED = "bamboohr_confirmed", "BambooHR Upload Confirmed"
    ACCOUNTABILITY_SUBMITTED = "accountability_submitted", "Accountability Submitted"
    ACCOUNTABILITY_CLEARED = "accountability_cleared", "Accountability Cleared"
    AWAITING_HR_SIGNOFF = "awaiting_hr_signoff", "Awaiting HR Sign-Off"
    COMPLETED_CLOSED = "completed_closed", "Completed and Closed"
    DEFERRED = "deferred", "Deferred"
    WITHDRAWN = "withdrawn", "Withdrawn"


# Statuses in which the record is a "live" course occupying the KPI's
# Active Courses count.
ACTIVE_COURSE_STATUSES = (
    PDStatus.DISBURSED, PDStatus.APPROVED_UNFUNDED, PDStatus.ENROLLMENT_PENDING,
    PDStatus.ENROLLMENT_CONFIRMED, PDStatus.IN_PROGRESS, PDStatus.ENDED,
)
# Statuses that still hold committed budget against the allocation.
COMMITTED_STATUSES = (
    PDStatus.SUBMITTED_TO_SUPERVISOR, PDStatus.SUBMITTED_TO_HR, PDStatus.PENDING_EXCEPTION,
    PDStatus.APPROVED_PENDING_FUNDING, PDStatus.DISBURSED, PDStatus.ENROLLMENT_PENDING,
    PDStatus.ENROLLMENT_CONFIRMED, PDStatus.IN_PROGRESS, PDStatus.ENDED,
    PDStatus.MARKED_COMPLETE, PDStatus.CERTIFICATE_UPLOADED, PDStatus.BAMBOOHR_CONFIRMED,
    PDStatus.ACCOUNTABILITY_SUBMITTED, PDStatus.AWAITING_HR_SIGNOFF,
)
CLOSED_STATUSES = (PDStatus.COMPLETED_CLOSED, PDStatus.REJECTED, PDStatus.CANCELLED,
                   PDStatus.WITHDRAWN)
FUNDED_TYPES = (PDFundingType.FULLY_FUNDED, PDFundingType.PARTIALLY_FUNDED)


class ProfessionalDevelopmentRequest(TimeStampedModel):
    id = CuidField()
    fy = models.CharField(max_length=16)
    staff_id = models.CharField(max_length=30)  # StaffProfile.id — the owner

    # ── Employee information (auto-populated, read-only to the employee) ────
    staff_name = models.CharField(max_length=255)
    position = models.CharField(max_length=255, null=True, blank=True)
    country = models.CharField(max_length=64, default="Uganda")
    department = models.CharField(max_length=128, null=True, blank=True)
    supervisor_staff_id = models.CharField(max_length=30, null=True, blank=True)
    supervisor_name = models.CharField(max_length=255, null=True, blank=True)

    # ── Course information ───────────────────────────────────────────────────
    course_name = models.CharField(max_length=255)
    course_category = models.CharField(max_length=64)
    course_type = models.CharField(max_length=16, choices=PDCourseType.choices)
    institution = models.CharField(max_length=255)
    course_link = models.CharField(max_length=512, null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    certification_expected = models.BooleanField(default=True)
    course_objectives = models.TextField(null=True, blank=True)
    skills_to_develop = models.TextField(null=True, blank=True)
    relevance_to_role = models.TextField(null=True, blank=True)
    expected_benefit = models.TextField(null=True, blank=True)
    work_time_impact = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    # ── Funding ───────────────────────────────────────────────────────────────
    course_fee_cents = models.BigIntegerField(default=0)
    other_costs_cents = models.BigIntegerField(default=0)
    total_cost_cents = models.BigIntegerField(default=0)
    employee_contribution_cents = models.BigIntegerField(default=0)
    requested_amount_cents = models.BigIntegerField(default=0)
    funding_type = models.CharField(
        max_length=20, choices=PDFundingType.choices, default=PDFundingType.SELF_FUNDED
    )
    currency = models.CharField(max_length=8, default="UGX")
    payment_recipient = models.CharField(max_length=255, null=True, blank=True)
    payment_details = models.TextField(null=True, blank=True)
    is_exception = models.BooleanField(default=False)
    exception_reason = models.TextField(null=True, blank=True)

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    status = models.CharField(max_length=32, choices=PDStatus.choices, default=PDStatus.DRAFT)
    submitted_at = models.DateTimeField(null=True, blank=True)

    # Supervisor stage
    supervisor_reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    supervisor_reviewed_at = models.DateTimeField(null=True, blank=True)
    supervisor_note = models.CharField(max_length=512, null=True, blank=True)

    # HR stage
    hr_reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    hr_reviewed_at = models.DateTimeField(null=True, blank=True)
    hr_note = models.CharField(max_length=512, null=True, blank=True)
    # True when the requester is HR and the reviewer had to be reassigned to
    # an independent HR/leadership approver (§13, §31 conflict-of-interest).
    hr_is_independent_reviewer = models.BooleanField(default=False)

    # Workload/calendar conflict check (§14)
    conflict_status = models.CharField(max_length=20, null=True, blank=True)
    conflict_detail = models.TextField(null=True, blank=True)
    calendar_block_id = models.CharField(max_length=30, null=True, blank=True)

    # Enrollment confirmation (§17)
    enrollment_confirmed = models.BooleanField(default=False)
    enrollment_confirmed_at = models.DateTimeField(null=True, blank=True)
    enrollment_date = models.DateField(null=True, blank=True)
    enrollment_reference = models.CharField(max_length=255, null=True, blank=True)

    # Employee self-reported completion (§20) — does NOT close the record
    marked_complete_at = models.DateTimeField(null=True, blank=True)
    actual_completion_date = models.DateField(null=True, blank=True)
    course_outcome = models.TextField(null=True, blank=True)
    skills_gained = models.TextField(null=True, blank=True)
    application_plan = models.TextField(null=True, blank=True)
    deferred_withdrawn_reason = models.TextField(null=True, blank=True)

    # BambooHR upload confirmation (§22)
    bamboohr_uploaded = models.BooleanField(default=False)
    bamboohr_uploaded_at = models.DateTimeField(null=True, blank=True)
    bamboohr_reference = models.CharField(max_length=255, null=True, blank=True)
    bamboohr_verified_by = models.CharField(max_length=30, null=True, blank=True)
    bamboohr_verified_at = models.DateTimeField(null=True, blank=True)

    # Accountability (funded courses only) — mirrors AdvanceRequest's field
    # shape (accountability_netsuite_id is the canonical "NetSuite Code" field
    # name used across the finance workflow).
    accounted_amount = models.BigIntegerField(null=True, blank=True)
    returned_amount = models.BigIntegerField(null=True, blank=True)
    accountability_netsuite_id = models.CharField(max_length=128, null=True, blank=True)
    accountability_submitted_at = models.DateTimeField(null=True, blank=True)
    accountability_reviewed_at = models.DateTimeField(null=True, blank=True)
    accountability_reviewed_by = models.CharField(max_length=30, null=True, blank=True)
    accountability_status = models.CharField(max_length=32, null=True, blank=True)
    accountability_variance_note = models.TextField(null=True, blank=True)

    # HR sign-off — the ONLY action that closes the record (§24)
    signed_off_by = models.CharField(max_length=30, null=True, blank=True)
    signed_off_at = models.DateTimeField(null=True, blank=True)

    created_by = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "pd_request"
        indexes = [
            models.Index(fields=["staff_id", "fy"]),
            models.Index(fields=["status"]),
            models.Index(fields=["start_date", "end_date"]),
        ]

    @property
    def owner_user_id(self) -> str | None:
        """The User.id that owns this request's StaffProfile — the
        notification/messaging recipient."""
        from apps.accounts.models import StaffProfile

        sp = StaffProfile.objects.filter(id=self.staff_id).values("user_id").first()
        return sp["user_id"] if sp else None

    def __str__(self) -> str:
        return f"{self.course_name} — {self.staff_name}"


class PDEvidenceKind(models.TextChoices):
    ADMISSION_LETTER = "admission_letter", "Admission / Enrollment Letter"
    BROCHURE = "brochure", "Course Brochure"
    INVOICE = "invoice", "Institution Invoice"
    FEE_STRUCTURE = "fee_structure", "Fee Structure"
    ACCEPTANCE_EMAIL = "acceptance_email", "Acceptance Email (PDF)"
    ENROLLMENT_CONFIRMATION = "enrollment_confirmation", "Enrollment Confirmation"
    OTHER = "other", "Other"


class ProfessionalDevelopmentEvidence(TimeStampedModel):
    """Conditional enrollment evidence (§8) — admission letter for in-person,
    supporting docs for online/hybrid. History is kept (never overwritten) so
    a returned upload can be replaced without losing the audit trail."""

    id = CuidField()
    request = models.ForeignKey(
        ProfessionalDevelopmentRequest, on_delete=models.CASCADE, related_name="evidence_files"
    )
    kind = models.CharField(
        max_length=32, choices=PDEvidenceKind.choices, default=PDEvidenceKind.ADMISSION_LETTER
    )
    uri = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=128, null=True, blank=True)
    file_extension = models.CharField(max_length=16, null=True, blank=True)
    file_size = models.IntegerField(default=0)
    uploaded_by = models.CharField(max_length=30)
    status = models.CharField(max_length=16, default="uploaded")  # uploaded | returned
    returned_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "pd_evidence"
        indexes = [models.Index(fields=["request"])]


class ProfessionalDevelopmentCertificate(TimeStampedModel):
    """Completion certificate, uploaded as a protected PDF (§21). Visible only
    to the employee, their supervisor and authorized HR/leadership."""

    id = CuidField()
    request = models.ForeignKey(
        ProfessionalDevelopmentRequest, on_delete=models.CASCADE, related_name="certificates"
    )
    uri = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=128, null=True, blank=True)
    file_size = models.IntegerField(default=0)
    certificate_name = models.CharField(max_length=255, null=True, blank=True)
    certificate_number = models.CharField(max_length=128, null=True, blank=True)
    issuing_institution = models.CharField(max_length=255, null=True, blank=True)
    issue_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    verification_link = models.CharField(max_length=512, null=True, blank=True)
    uploaded_by = models.CharField(max_length=30)
    status = models.CharField(max_length=16, default="uploaded")  # uploaded | returned | verified
    returned_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "pd_certificate"
        indexes = [models.Index(fields=["request"])]


class PDFundRequestStatus(models.TextChoices):
    PENDING_DISBURSEMENT = "pending_disbursement", "Pending Disbursement"
    DISBURSED = "disbursed", "Disbursed"
    HELD = "held", "Held"
    RETURNED = "returned", "Returned"


class ProfessionalDevelopmentFundRequest(TimeStampedModel):
    """A dedicated PD finance queue item (§15) — NEVER routed through the
    school-activity budget workflow (no ActivityBudgetLine, no Weekly Fund
    Request, no Country Monthly Budget)."""

    id = CuidField()
    request = models.OneToOneField(
        ProfessionalDevelopmentRequest, on_delete=models.CASCADE, related_name="fund_request"
    )
    fy = models.CharField(max_length=16)
    staff_id = models.CharField(max_length=30)
    amount_cents = models.BigIntegerField()
    currency = models.CharField(max_length=8, default="UGX")
    payment_recipient = models.CharField(max_length=255, null=True, blank=True)
    payment_details = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=24, choices=PDFundRequestStatus.choices,
        default=PDFundRequestStatus.PENDING_DISBURSEMENT,
    )
    hold_reason = models.CharField(max_length=512, null=True, blank=True)
    return_reason = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "pd_fund_request"
        indexes = [models.Index(fields=["status"])]


class ProfessionalDevelopmentDisbursement(TimeStampedModel):
    id = CuidField()
    fund_request = models.ForeignKey(
        ProfessionalDevelopmentFundRequest, on_delete=models.CASCADE, related_name="disbursements"
    )
    amount_cents = models.BigIntegerField()
    disbursed_by = models.CharField(max_length=30)
    disbursed_at = models.DateTimeField(auto_now_add=True)
    payment_method = models.CharField(max_length=64, null=True, blank=True)
    payment_reference = models.CharField(max_length=128, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "pd_disbursement"


class ProfessionalDevelopmentReminderLog(TimeStampedModel):
    """One row per (request, reminder_key, date) — prevents duplicate sends
    and lets the daily reminder scheduler know what already went out today."""

    id = CuidField()
    request = models.ForeignKey(
        ProfessionalDevelopmentRequest, on_delete=models.CASCADE, related_name="reminder_logs"
    )
    reminder_key = models.CharField(max_length=64)
    sent_on = models.DateField()

    class Meta:
        db_table = "pd_reminder_log"
        constraints = [
            models.UniqueConstraint(
                fields=["request", "reminder_key", "sent_on"], name="uniq_pd_reminder_once_per_day"
            )
        ]
