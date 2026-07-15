from __future__ import annotations

from django.db import models
from apps.core.models import CuidField, TimeStampedModel
from apps.accounts.models import StaffProfile, User


# ─── RECRUITMENT AND TALENT ACQUISITION ──────────────────────────────────────


class Vacancy(TimeStampedModel):
    """A requested or active job opening."""

    id = CuidField()
    country = models.CharField(max_length=64, db_index=True)
    department = models.CharField(max_length=64, db_index=True)
    role = models.CharField(max_length=64, db_index=True)
    reporting_manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_vacancies",
    )
    employment_type = models.CharField(
        max_length=64, default="Full-time"
    )  # Full-time, Part-time, Contract, etc.
    reason_for_vacancy = models.TextField(null=True, blank=True)
    replacement_or_new_role = models.CharField(
        max_length=32,
        choices=[("replacement", "Replacement"), ("new_role", "New Role")],
        default="new_role",
    )
    required_skills = models.TextField(null=True, blank=True)
    target_start_date = models.DateField(null=True, blank=True)
    approved_salary_band = models.CharField(max_length=64, null=True, blank=True)
    budget_source = models.CharField(max_length=128, null=True, blank=True)
    status = models.CharField(
        max_length=32, default="Draft"
    )  # Draft, Pending Approval, Approved, Open, Screening, etc.
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_vacancies",
    )

    class Meta:
        db_table = "hr_vacancy"


class Candidate(TimeStampedModel):
    """An applicant seeking employment."""

    id = CuidField()
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=64, null=True, blank=True)
    skills = models.TextField(null=True, blank=True)
    talent_pool_notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hr_candidate"


class Application(TimeStampedModel):
    """A candidate's application for a specific vacancy."""

    id = CuidField()
    vacancy = models.ForeignKey(
        Vacancy, on_delete=models.CASCADE, related_name="applications"
    )
    candidate = models.ForeignKey(
        Candidate, on_delete=models.CASCADE, related_name="applications"
    )
    stage = models.CharField(
        max_length=64, default="Applied"
    )  # Applied, Screened, Shortlisted, Interview 1, Interview 2, Assessment, Reference Check, Recommended, Offer, Hired, Rejected, Withdrawn, Talent Pool
    status_notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hr_application"
        unique_together = (("vacancy", "candidate"),)


# ─── ONBOARDING WORKFLOW ─────────────────────────────────────────────────────


class OnboardingPlan(TimeStampedModel):
    """The onboarding timeline and tasks checklist for a new staff member."""

    id = CuidField()
    staff = models.OneToOneField(
        StaffProfile, on_delete=models.CASCADE, related_name="onboarding_plan"
    )
    status = models.CharField(
        max_length=32, default="Not Started"
    )  # Not Started, Documents Pending, Account Setup Pending, Orientation Pending, Role Training Pending, Supervisor Review Pending, Ready for Activation, Active, Overdue
    start_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "hr_onboarding_plan"


class OnboardingTask(TimeStampedModel):
    """A specific checklist item in an onboarding plan."""

    id = CuidField()
    plan = models.ForeignKey(
        OnboardingPlan, on_delete=models.CASCADE, related_name="tasks"
    )
    name = models.CharField(max_length=255)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_onboarding_task"


# ─── COMPLIANCE AND POLICY REGISTER ──────────────────────────────────────────


class ComplianceRequirement(TimeStampedModel):
    """A compliance item that staff in a given country must satisfy."""

    id = CuidField()
    country = models.CharField(max_length=64, db_index=True)  # e.g. "Uganda", "All"
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)
    is_mandatory = models.BooleanField(default=True)

    class Meta:
        db_table = "hr_compliance_requirement"


class EmployeeComplianceRecord(TimeStampedModel):
    """An employee's compliance item status."""

    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="compliance_records"
    )
    requirement = models.ForeignKey(ComplianceRequirement, on_delete=models.CASCADE)
    status = models.CharField(
        max_length=32, default="Missing"
    )  # Compliant, Due Soon, Expired, Missing, Under Review, Exception Approved
    document_url = models.CharField(max_length=512, null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    verified_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="verified_compliance_records",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_employee_compliance_record"
        unique_together = (("staff", "requirement"),)


# ─── PERFORMANCE MANAGEMENT & RECOVERY ───────────────────────────────────────


class PerformanceReview(TimeStampedModel):
    """Periodic staff performance reviews."""

    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="performance_reviews"
    )
    period = models.CharField(
        max_length=32, db_index=True
    )  # e.g. "FY 2024/25", "May 2025"
    review_type = models.CharField(
        max_length=64, default="Quarterly Review"
    )  # Quarterly Review, FY Review, Probation Review
    status = models.CharField(
        max_length=32, default="Not Started"
    )  # Not Started, Self-Assessment Pending, Manager Review Pending, Calibration Pending, HR Review Pending, Completed, Closed
    due_date = models.DateField()
    rating = models.CharField(
        max_length=32, null=True, blank=True
    )  # Strong (70-100%), Fair (50-69%), At Risk (<50%)
    score = models.FloatField(default=0.0)  # computed Target Achievement %
    manager_feedback = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hr_performance_review"


class PerformanceImprovementPlan(TimeStampedModel):
    """A recovery/improvement plan created when performance issues arise."""

    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="pip_plans"
    )
    status = models.CharField(
        max_length=32, default="Draft"
    )  # Draft, Active, Progress Review, Successfully Completed, Escalated, Closed
    cause = models.CharField(
        max_length=128
    )  # planning gap, execution gap, conduct issue, attendance issue, skills gap, etc.
    action_plan = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        db_table = "hr_pip_plan"


# ─── CPD AND SKILLS MATRIX ───────────────────────────────────────────────────


class CPDAssignment(TimeStampedModel):
    """Continuous Professional Development course assignments."""

    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="cpd_assignments"
    )
    course_name = models.CharField(max_length=255)
    category = models.CharField(
        max_length=64
    )  # Leadership, Program Quality, School Improvement, Safeguarding, Compliance, Digital Systems
    status = models.CharField(
        max_length=32, default="Assigned"
    )  # Recommended, Assigned, Enrolled, In Progress, Completed, Verified, Expired
    evidence_url = models.CharField(max_length=512, null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_cpd_assignment"


class Skill(TimeStampedModel):
    """A competency definition."""

    id = CuidField()
    name = models.CharField(max_length=128, unique=True)
    category = models.CharField(max_length=64, null=True, blank=True)

    class Meta:
        db_table = "hr_skill"


class EmployeeSkill(TimeStampedModel):
    """Employee competency levels mapping."""

    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="skills_matrix"
    )
    skill = models.ForeignKey(Skill, on_delete=models.CASCADE)
    level = models.IntegerField(default=1)  # 1 (Beginner) to 5 (Expert)

    class Meta:
        db_table = "hr_employee_skill"
        unique_together = (("staff", "skill"),)


# ─── SUCCESSION PLANNING ─────────────────────────────────────────────────────


class SuccessionCandidate(TimeStampedModel):
    """Potential successors identified for critical organization roles."""

    id = CuidField()
    position_name = models.CharField(max_length=255, db_index=True)
    staff_successor = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="succession_nominations"
    )
    readiness = models.CharField(
        max_length=64, default="Development Required"
    )  # Ready Now, Ready in 6-12 Months, Ready in 1-2 Years, Development Required, Not Currently Ready
    notes = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hr_succession_candidate"


# ─── EMPLOYEE RELATIONS AND CULTURE ──────────────────────────────────────────


class EmployeeRelationsCase(TimeStampedModel):
    """Confidential employee relations concern logging."""

    id = CuidField()
    case_type = models.CharField(
        max_length=64, db_index=True
    )  # Grievance, Conflict, Harassment Concern, Conduct Concern, Whistleblowing, Safeguarding Referral
    severity = models.CharField(
        max_length=32, default="medium"
    )  # low, medium, high, critical
    status = models.CharField(
        max_length=32, default="Submitted"
    )  # Submitted, Triage, Under Review, Investigation, Resolved, Closed
    case_owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relations_cases_assigned",
    )
    description = models.TextField()
    findings = models.TextField(null=True, blank=True)
    is_confidential = models.BooleanField(default=True)

    class Meta:
        db_table = "hr_relations_case"


# ─── COMPENSATION AND PAYROLL READYNESS ──────────────────────────────────────


class CompensationRecord(TimeStampedModel):
    """Compensation, grade structure and bank accounts per staff profile."""

    id = CuidField()
    staff = models.OneToOneField(
        StaffProfile, on_delete=models.CASCADE, related_name="compensation_details"
    )
    salary_band = models.CharField(max_length=64, null=True, blank=True)
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    benefits_tier = models.CharField(max_length=64, null=True, blank=True)
    bank_name = models.CharField(max_length=128, null=True, blank=True)
    account_number = models.CharField(max_length=64, null=True, blank=True)
    status = models.CharField(
        max_length=32, default="HR Review"
    )  # HR Review, Approved, etc.

    class Meta:
        db_table = "hr_compensation"


class PayrollReadinessRecord(TimeStampedModel):
    """Payroll checklist checks for a specific period."""

    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="payroll_checks"
    )
    payroll_period = models.CharField(max_length=32, db_index=True)  # e.g. "2025-05"
    has_exceptions = models.BooleanField(default=False)
    exception_notes = models.TextField(null=True, blank=True)
    is_payroll_ready = models.BooleanField(default=False)

    class Meta:
        db_table = "hr_payroll_readiness"
        unique_together = (("staff", "payroll_period"),)


# ─── TRANSITIONS (OFFBOARDING) ───────────────────────────────────────────────


class OffboardingPlan(TimeStampedModel):
    """timeline checklist for terminated or resigned staff."""

    id = CuidField()
    staff = models.OneToOneField(
        StaffProfile, on_delete=models.CASCADE, related_name="offboarding_details"
    )
    status = models.CharField(
        max_length=32, default="Initiated"
    )  # Initiated, Portfolio Reassigned, Equipment Returned, Finance Cleared, Closed
    last_working_day = models.DateField(null=True, blank=True)
    handover_owner = models.ForeignKey(
        StaffProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_handovers",
    )
    clearance_completed = models.BooleanField(default=False)

    class Meta:
        db_table = "hr_offboarding"


# ─── HR AUDIT LOG ────────────────────────────────────────────────────────────


class HRAuditEvent(TimeStampedModel):
    """Detailed audit log tracking sensitive PII edits."""

    id = CuidField()
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    role = models.CharField(max_length=64)
    action = models.CharField(max_length=255)
    record_id = models.CharField(max_length=64)
    details = models.JSONField(default=dict)

    class Meta:
        db_table = "hr_audit_event"
        indexes = [
            models.Index(fields=["record_id"]),
            models.Index(fields=["created_at"]),
        ]
