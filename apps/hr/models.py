from __future__ import annotations

from django.db import models
from apps.core.models import CuidField, TimeStampedModel
from apps.accounts.models import StaffProfile, User


# ─── RECRUITMENT AND TALENT ACQUISITION ──────────────────────────────────────


class VacancyStatus(models.TextChoices):
    """Free strings in a comment let a typo silently zero a KPI — the class of
    bug that made `OnboardingPlan.status` unreachable from its own view."""

    DRAFT = "draft", "Draft"
    PENDING_APPROVAL = "pending_approval", "Pending approval"
    APPROVED = "approved", "Approved"
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    CANCELLED = "cancelled", "Cancelled"


class ApplicationStage(models.TextChoices):
    APPLIED = "applied", "Applied"
    SCREENING = "screening", "Screening"
    INTERVIEW = "interview", "Interview"
    ASSESSMENT = "assessment", "Assessment"
    REFERENCE_CHECK = "reference_check", "Reference check"
    OFFER = "offer", "Offer"
    ACCEPTED = "accepted", "Offer accepted"
    HIRED = "hired", "Hired"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"


class OnboardingStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not started"
    IN_PROGRESS = "in_progress", "In progress"
    SUPERVISOR_REVIEW = "supervisor_review", "Awaiting supervisor confirmation"
    READY_FOR_ACTIVATION = "ready_for_activation", "Ready for activation"
    CLOSED = "closed", "Closed"


class ProbationDecision(models.TextChoices):
    CONFIRMED = "confirmed", "Confirm employment"
    EXTENDED = "extended", "Extend probation"
    ENDED = "ended", "End employment"


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
        max_length=32, choices=VacancyStatus.choices, default=VacancyStatus.DRAFT
    )
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_vacancies",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_vacancies",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.TextField(null=True, blank=True)

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
    # Applicant data is personal data held about someone who does not work
    # here. Neither consent nor a retention horizon existed anywhere.
    consent_given_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateField(null=True, blank=True)

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
        max_length=64,
        choices=ApplicationStage.choices,
        default=ApplicationStage.APPLIED,
    )
    status_notes = models.TextField(null=True, blank=True)
    # Every stage change carries a reason, and the offer carries an approver —
    # previously a stage was a bare string with no record of who decided or why.
    decision_reason = models.TextField(null=True, blank=True)
    interview_panel = models.TextField(null=True, blank=True)
    assessment_result = models.TextField(null=True, blank=True)
    reference_check_note = models.TextField(null=True, blank=True)
    offer_approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_offers",
    )
    offer_accepted_at = models.DateTimeField(null=True, blank=True)
    # THE handoff. There was no path at all from an accepted candidate to an
    # account: nothing wrote stage="Hired", no signal or service connected the
    # two, and the provisioning service took no candidate reference of any
    # kind — so HR re-keyed name, email and phone into an empty modal.
    provisioned_user = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_application",
    )
    provisioned_at = models.DateTimeField(null=True, blank=True)

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
        max_length=32,
        choices=OnboardingStatus.choices,
        default=OnboardingStatus.NOT_STARTED,
    )
    start_date = models.DateField(null=True, blank=True)
    # A plan with no target date cannot be late, which is why the view's
    # "Overdue" metric filtered on a value nothing could ever set.
    target_completion_date = models.DateField(null=True, blank=True)
    probation_review_date = models.DateField(null=True, blank=True)
    source_application = models.ForeignKey(
        "Application",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="onboarding_plans",
    )
    supervisor_confirmed_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone as _tz

        return bool(
            self.target_completion_date
            and self.status != OnboardingStatus.CLOSED
            and self.target_completion_date < _tz.now().date()
        )

    class Meta:
        db_table = "hr_onboarding_plan"


class OnboardingTask(TimeStampedModel):
    """A specific checklist item in an onboarding plan."""

    id = CuidField()
    plan = models.ForeignKey(
        OnboardingPlan, on_delete=models.CASCADE, related_name="tasks"
    )
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=64, default="general")
    owner_role = models.CharField(max_length=64, default="employee")
    due_date = models.DateField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="completed_onboarding_tasks",
    )

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone as _tz

        return bool(
            self.due_date and not self.is_completed and self.due_date < _tz.now().date()
        )

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


class ReviewStage(models.TextChoices):
    """The performance journey, as stages a record actually moves through.

    Previously the whole cycle was one free-string `status` whose vocabulary
    lived in a `#` comment — no state machine, no legal-transition table, and
    three separate aggregations string-matching on its prefix, so a single typo
    silently zeroed a national KPI.
    """

    NOT_STARTED = "not_started", "Not started"
    PRIORITIES_DRAFT = "priorities_draft", "Employee drafting priorities"
    PRIORITIES_MANAGER_REVIEW = (
        "priorities_manager_review",
        "Manager reviewing priorities",
    )
    PRIORITIES_AGREED = "priorities_agreed", "Priorities agreed"
    EMPLOYEE_REFLECTION = "employee_reflection", "Employee reflection"
    MANAGER_ASSESSMENT = "manager_assessment", "Manager assessment"
    CALIBRATION = "calibration", "Calibration"
    AWAITING_ACKNOWLEDGEMENT = (
        "awaiting_acknowledgement",
        "Awaiting employee acknowledgement",
    )
    CLOSED = "closed", "Closed"


class ReviewType(models.TextChoices):
    ANNUAL_PRIORITIES = "annual_priorities", "Annual priorities"
    MID_YEAR = "mid_year", "Mid-year review"
    YEAR_END = "year_end", "Year-end review"
    QUARTERLY = "quarterly", "Quarterly review"
    PROBATION = "probation", "Probation review"


class PriorityStatus(models.TextChoices):
    ON_TRACK = "on_track", "On track"
    AT_RISK = "at_risk", "At risk"
    OFF_TRACK = "off_track", "Off track"
    ACHIEVED = "achieved", "Achieved"
    NOT_ASSESSED = "not_assessed", "Not assessed"


class PerformanceRating(models.TextChoices):
    """The five conversation ratings, verbatim from the HR document (§12).

    Held as three SEPARATE columns on a priority — employee, manager and
    functional manager each rate independently, and the columns must never be
    collapsed into one.
    """

    FAR_EXCEEDS = "far_exceeds", "Far Exceeds Priority"
    EXCEEDS = "exceeds", "Exceeds Priority"
    MET = "met", "Met Priority"
    MET_SOME = "met_some", "Met Some Priority"
    DID_NOT_MEET = "did_not_meet", "Did Not Meet Priority"


class PerformanceReview(TimeStampedModel):
    """One employee's review for one period.

    The four evidence channels are kept structurally SEPARATE — system
    evidence, employee reflection, manager assessment, calibration — because
    collapsing them is how a manager's opinion becomes indistinguishable from a
    measured figure. Previously only `manager_feedback` existed; the other
    three were never built.
    """

    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="performance_reviews"
    )
    period = models.CharField(max_length=32, db_index=True)
    fy = models.CharField(max_length=16, null=True, blank=True, db_index=True)
    review_type = models.CharField(
        max_length=64, choices=ReviewType.choices, default=ReviewType.ANNUAL_PRIORITIES
    )
    stage = models.CharField(
        max_length=40, choices=ReviewStage.choices, default=ReviewStage.NOT_STARTED
    )
    # Kept for the existing read surfaces; `stage` is the authority.
    status = models.CharField(max_length=32, default="Not Started")
    due_date = models.DateField()

    manager = models.ForeignKey(
        StaffProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews_managed",
    )

    # ── Channel 1: system evidence, computed, never typed ──────────────────
    # Sourced from the canonical validated ledger (targets.my_targets
    # weighted_period_pct) plus workload context, so a shortfall can be read
    # against the portfolio that produced it.
    system_evidence = models.JSONField(null=True, blank=True)
    system_score = models.FloatField(null=True, blank=True)
    system_evidence_generated_at = models.DateTimeField(null=True, blank=True)

    # ── Channel 2: the employee's own words ────────────────────────────────
    employee_reflection = models.TextField(null=True, blank=True)
    employee_reflection_at = models.DateTimeField(null=True, blank=True)

    # ── Channel 3: the manager's judgement ─────────────────────────────────
    manager_feedback = models.TextField(null=True, blank=True)
    manager_rating = models.CharField(max_length=32, null=True, blank=True)
    manager_assessed_at = models.DateTimeField(null=True, blank=True)

    # ── Channel 4: calibration across a cohort ─────────────────────────────
    calibration_result = models.CharField(max_length=32, null=True, blank=True)
    calibration_note = models.TextField(null=True, blank=True)
    calibrated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="calibrated_reviews",
    )
    calibrated_at = models.DateTimeField(null=True, blank=True)

    acknowledged_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    # Legacy field the existing dashboards read. Populated from system_score.
    rating = models.CharField(max_length=32, null=True, blank=True)
    score = models.FloatField(default=0.0)
    functional_manager = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="functionally_managed_reviews",
    )

    class Meta:
        db_table = "hr_performance_review"
        indexes = [models.Index(fields=["staff", "fy"])]


class PerformancePriority(TimeStampedModel):
    """One outcome-based annual priority. Roughly five per employee.

    None of this existed. A review was a single flat row, so the priorities a
    manager and employee agreed in January were unrecoverable in December and
    the year-end assessment was unfalsifiable.
    """

    id = CuidField()
    review = models.ForeignKey(
        PerformanceReview, on_delete=models.CASCADE, related_name="priorities"
    )
    sequence = models.PositiveSmallIntegerField(default=1)

    outcome_statement = models.TextField()
    strategic_alignment = models.CharField(max_length=255, null=True, blank=True)
    measures_of_success = models.TextField(null=True, blank=True)
    baseline = models.CharField(max_length=255, null=True, blank=True)
    target = models.CharField(max_length=255, null=True, blank=True)
    weight = models.PositiveSmallIntegerField(default=20)
    support_needed = models.TextField(null=True, blank=True)

    current_result = models.CharField(max_length=255, null=True, blank=True)
    status = models.CharField(
        max_length=32,
        choices=PriorityStatus.choices,
        default=PriorityStatus.NOT_ASSESSED,
    )

    # The same four-channel separation, at priority level.
    system_evidence = models.JSONField(null=True, blank=True)
    employee_reflection = models.TextField(null=True, blank=True)
    manager_assessment = models.TextField(null=True, blank=True)

    # Three distinct rating columns — the HR form keeps employee, manager
    # and functional manager as separate voices, never merged.
    employee_rating = models.CharField(max_length=32, null=True, blank=True)
    manager_rating = models.CharField(max_length=32, null=True, blank=True)
    functional_manager_rating = models.CharField(max_length=32, null=True, blank=True)
    agreed_action = models.TextField(null=True, blank=True)

    # ── Priority-to-target mapping (the engine) ──────────────────────────
    # A measurable priority names its canonical metric; progress is DERIVED
    # LIVE from the verified ledger on read — never typed, never synced by a
    # job that can lag. "No percentage without a denominator": numeric
    # targets carry one, computed from the real portfolio at build time.
    priority_layer = models.CharField(
        max_length=16,
        choices=[
            ("org", "Organization"),
            ("role", "Role"),
            ("project", "Project"),
            ("personal", "Personal / Values"),
        ],
        default="role",
    )
    metric_key = models.CharField(max_length=64, null=True, blank=True)
    target_number = models.IntegerField(null=True, blank=True)
    denominator_note = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        db_table = "hr_performance_priority"
        ordering = ["sequence"]
        unique_together = (("review", "sequence"),)


class PerformancePriorityMilestone(TimeStampedModel):
    """A critical milestone under one priority."""

    id = CuidField()
    priority = models.ForeignKey(
        PerformancePriority, on_delete=models.CASCADE, related_name="milestones"
    )
    description = models.CharField(max_length=512)
    due_date = models.DateField(null=True, blank=True)
    is_complete = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    evidence_url = models.CharField(max_length=512, null=True, blank=True)

    class Meta:
        db_table = "hr_performance_priority_milestone"
        ordering = ["due_date", "created_at"]


class RecoveryPlanType(models.TextChoices):
    """Informal support and a formal improvement plan are different things.

    They were one model plus a free-string status, so "escalating to conduct"
    was a status flip on the performance record rather than a handoff to a
    process with different evidentiary standards.
    """

    INFORMAL = "informal", "Informal recovery plan"
    FORMAL = "formal", "Formal performance improvement plan"


class RecoveryCause(models.TextChoices):
    """Why performance fell short.

    The old free-text vocabulary lived in a comment and listed only
    planning/execution/conduct/attendance/skills — omitting capacity,
    workload, availability, data quality and manager support, i.e. every
    cause that is not the individual's fault. The platform already computes
    most of these elsewhere (the overload detector, workload_context, and the
    provisional-vs-validated split that IS a data-quality signal).
    """

    CAPACITY = "capacity", "Capacity — portfolio beyond capacity"
    WORKLOAD = "workload", "Workload — competing demands"
    SKILL = "skill", "Skill gap"
    AVAILABILITY = "availability", "Availability — leave or absence"
    DATA_QUALITY = "data_quality", "Data quality — work done but not credited"
    MANAGER_SUPPORT = "manager_support", "Manager support"
    CONDUCT = "conduct", "Conduct"
    OTHER = "other", "Other"


class RecoveryStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    ACTIVE = "active", "Active"
    PROGRESS_REVIEW = "progress_review", "Progress review"
    COMPLETED = "completed", "Successfully completed"
    EXTENDED = "extended", "Extended"
    ESCALATED = "escalated", "Escalated to a conduct case"
    CLOSED = "closed", "Closed"


class PerformanceImprovementPlan(TimeStampedModel):
    """A recovery or improvement plan. `plan_type` says which."""

    id = CuidField()
    staff = models.ForeignKey(
        StaffProfile, on_delete=models.CASCADE, related_name="pip_plans"
    )
    plan_type = models.CharField(
        max_length=16,
        choices=RecoveryPlanType.choices,
        default=RecoveryPlanType.INFORMAL,
    )
    status = models.CharField(
        max_length=32, choices=RecoveryStatus.choices, default=RecoveryStatus.DRAFT
    )
    cause = models.CharField(
        max_length=128, choices=RecoveryCause.choices, default=RecoveryCause.OTHER
    )
    cause_evidence = models.TextField(null=True, blank=True)
    action_plan = models.TextField()
    support_offered = models.TextField(null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    owner = models.ForeignKey(
        StaffProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recovery_plans_owned",
    )
    outcome = models.CharField(max_length=32, null=True, blank=True)
    outcome_note = models.TextField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    # An escalation CREATES a case; it is never a status flip in place.
    escalated_case = models.ForeignKey(
        "EmployeeRelationsCase",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="source_recovery_plans",
    )

    class Meta:
        db_table = "hr_pip_plan"


class RecoveryMilestone(TimeStampedModel):
    id = CuidField()
    plan = models.ForeignKey(
        PerformanceImprovementPlan, on_delete=models.CASCADE, related_name="milestones"
    )
    description = models.CharField(max_length=512)
    due_date = models.DateField(null=True, blank=True)
    is_complete = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_recovery_milestone"
        ordering = ["due_date", "created_at"]


class RecoveryCheckIn(TimeStampedModel):
    id = CuidField()
    plan = models.ForeignKey(
        PerformanceImprovementPlan, on_delete=models.CASCADE, related_name="check_ins"
    )
    held_on = models.DateField()
    note = models.TextField()
    recorded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        db_table = "hr_recovery_check_in"
        ordering = ["-held_on"]


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


class ERCaseType(models.TextChoices):
    GRIEVANCE = "grievance", "Grievance"
    CONFLICT = "conflict", "Conflict"
    HARASSMENT = "harassment", "Harassment concern"
    CONDUCT = "conduct", "Conduct concern"
    WHISTLEBLOWING = "whistleblowing", "Whistleblowing"
    SAFEGUARDING = "safeguarding", "Safeguarding referral"


class ERCaseStatus(models.TextChoices):
    SUBMITTED = "submitted", "Submitted"
    TRIAGE = "triage", "Restricted triage"
    INVESTIGATION = "investigation", "Investigation"
    FINDINGS = "findings", "Findings recorded"
    ACTION = "action", "Action decided"
    APPEAL = "appeal", "Under appeal"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"


class EmployeeRelationsCase(TimeStampedModel):
    """Confidential employee relations concern logging.

    The model had NO subject-employee field, so a conduct case could not
    record whom it concerned — which also made it impossible to scope, since
    there was nothing to scope by. `country` and `subject_staff` exist for
    exactly that: the register was the one HR surface with no scope at all.
    """

    id = CuidField()
    # Whom the case is about. Nullable because a whistleblowing report may
    # legitimately name no individual.
    subject_staff = models.ForeignKey(
        StaffProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relations_cases_about",
    )
    country = models.CharField(max_length=64, default="Uganda", db_index=True)
    case_type = models.CharField(
        max_length=64, choices=ERCaseType.choices, db_index=True
    )
    severity = models.CharField(max_length=32, default="medium")
    status = models.CharField(
        max_length=32, choices=ERCaseStatus.choices, default=ERCaseStatus.SUBMITTED
    )
    case_owner = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relations_cases_assigned",
    )
    investigator = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relations_cases_investigating",
    )
    raised_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relations_cases_raised",
    )
    description = models.TextField()
    findings = models.TextField(null=True, blank=True)
    action_taken = models.TextField(null=True, blank=True)
    appeal_note = models.TextField(null=True, blank=True)
    is_confidential = models.BooleanField(default=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    retention_until = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "hr_relations_case"
        indexes = [models.Index(fields=["country", "status"])]


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


RATING_OPTIONS = [
    ("far_exceeds", "Far Exceeds Priority"),
    ("exceeds", "Exceeds Priority"),
    ("met", "Met Priority"),
    ("met_some", "Met Some Priority"),
    ("did_not_meet", "Did Not Meet Priority"),
]


class PerformanceCycle(TimeStampedModel):
    """HR opens one cycle per fiscal year; agreements hang off it.

    The form stays LOCKED outside an authorized window: only HR activates a
    quarter, extends it, reopens a record (with a reason) or closes it.
    """

    WINDOWS = [
        ("none", "No window open"),
        ("priority_setting", "FY priority setting"),
        ("q1", "Q1 conversation"),
        ("mid_year", "Mid-year review (Q2)"),
        ("q3", "Q3 conversation"),
        ("year_end", "End-of-year review (Q4)"),
    ]

    id = CuidField()
    fy = models.CharField(max_length=16, unique=True)
    active_window = models.CharField(max_length=32, choices=WINDOWS, default="none")
    window_opened_at = models.DateTimeField(null=True, blank=True)
    window_deadline = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[("open", "Open"), ("locked", "Locked"), ("closed", "Closed")],
        default="open",
    )
    opened_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        db_table = "hr_performance_cycle"


class RolePriorityTemplate(TimeStampedModel):
    """A role's standard priorities, from which drafts are generated."""

    id = CuidField()
    role = models.CharField(max_length=64, db_index=True)
    priority_layer = models.CharField(max_length=16, default="role")
    outcome_statement = models.TextField()
    metric_key = models.CharField(max_length=64, null=True, blank=True)
    default_weight = models.PositiveSmallIntegerField(default=20)
    sequence = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "hr_role_priority_template"
        ordering = ["role", "sequence"]


class PriorityAmendment(TimeStampedModel):
    """A MANUAL, approved change to a locked priority. Never silent edits;
    past quarterly snapshots are never rewritten."""

    id = CuidField()
    priority = models.ForeignKey(
        PerformancePriority, on_delete=models.CASCADE, related_name="amendments"
    )
    requested_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    reason = models.TextField()
    changed_target = models.CharField(max_length=255, null=True, blank=True)
    changed_target_number = models.IntegerField(null=True, blank=True)
    effective_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[
            ("requested", "Requested"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
        ],
        default="requested",
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_priority_amendment"


class DevelopmentPlanItem(TimeStampedModel):
    """A development-plan row. PD-workflow rows appear automatically on the
    page (derived live from ProfessionalDevelopmentRequest); this model holds
    only the MANUAL additions the employee makes on top."""

    id = CuidField()
    review = models.ForeignKey(
        PerformanceReview, on_delete=models.CASCADE, related_name="development_items"
    )
    description = models.CharField(max_length=512)
    expected_impact = models.TextField(null=True, blank=True)
    progress_note = models.TextField(null=True, blank=True)
    reflection = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hr_development_plan_item"


class ValueCommitment(TimeStampedModel):
    """An Edify Values or Spiritual Formation commitment. MANUAL by mandate —
    never auto-rated from activity counts. `kind` separates the two sections
    of the form; both share the commitment/reflection shape."""

    id = CuidField()
    review = models.ForeignKey(
        PerformanceReview, on_delete=models.CASCADE, related_name="value_commitments"
    )
    kind = models.CharField(
        max_length=16,
        choices=[("value", "Edify Value"), ("spiritual", "Spiritual Formation")],
        default="value",
    )
    value_name = models.CharField(max_length=128)
    functional_manager_observation = models.TextField(null=True, blank=True)
    agreed_behaviour = models.TextField(null=True, blank=True)
    employee_reflection = models.TextField(null=True, blank=True)
    manager_evidence = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "hr_value_commitment"


class PerformanceSnapshot(TimeStampedModel):
    """The immutable record a conversation is held against.

    Taken when HR activates the window: live figures are frozen so the
    numbers cannot shift mid-meeting, and after sign-off the row is locked
    permanently. Amendments never rewrite an existing snapshot — history
    keeps the original values, future periods use the amended ones.
    """

    id = CuidField()
    review = models.ForeignKey(
        PerformanceReview, on_delete=models.CASCADE, related_name="snapshots"
    )
    window = models.CharField(max_length=32)
    data = models.JSONField()
    taken_at = models.DateTimeField(auto_now_add=True)
    signed_off_at = models.DateTimeField(null=True, blank=True)
    signed_off_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        db_table = "hr_performance_snapshot"
        unique_together = (("review", "window"),)
