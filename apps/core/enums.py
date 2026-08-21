"""
Shared domain enums — TextChoices used across multiple apps.

These mirror the legacy Prisma enums. Cross-domain enums (shared by more than
one module) live here; single-domain enums can live in their own app.
"""

from __future__ import annotations

from django.db import models


# ── Schools ───────────────────────────────────────────────────────────────────
class SchoolType(models.TextChoices):
    CHAMPION = "champion", "Champion"
    CLIENT = "client", "Client"
    CORE = "core", "Core"
    CORE_GRADUATE = "core_graduate", "Core Graduate"
    CORE_TRAINED = "core_trained", "Core Trained"


class AccountOwnerStatus(models.TextChoices):
    MATCHED = "matched", "Matched"
    UNMATCHED = "unmatched", "Unmatched"
    AMBIGUOUS = "ambiguous", "Ambiguous"
    PENDING = "pending", "Pending"


class DuplicateStatus(models.TextChoices):
    NONE = "none", "None"
    POTENTIAL = "potential", "Potential"
    CONFIRMED = "confirmed", "Confirmed"
    NOT_DUPLICATE = "not_duplicate", "Not Duplicate"
    MERGED = "merged", "Merged"


class ClusterStatus(models.TextChoices):
    UNCLUSTERED = "unclustered", "Unclustered"
    CLUSTERED = "clustered", "Clustered"
    NEEDS_REVIEW = "needs_review", "Needs Review"


class ClusterRecordStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    NEEDS_REVIEW = "needs_review", "Needs Review"
    INACTIVE = "inactive", "Inactive"


class ClusterType(models.TextChoices):
    CLIENT = "client", "Client"
    CORE = "core", "Core"
    MIXED = "mixed", "Mixed"


class DistrictType(models.TextChoices):
    PRIMARY = "primary", "Primary"
    SECONDARY = "secondary", "Secondary"


class SsaStatus(models.TextChoices):
    NOT_DONE = "not_done", "Not Done"
    SCHEDULED = "scheduled", "Scheduled"
    PARTNER_ASSIGNED = "partner_assigned", "Partner Assigned"
    DONE = "done", "Done"


class PlanningReadiness(models.TextChoices):
    REQUIRES_CLUSTER = "requires_cluster", "Requires Cluster"
    READY_FOR_BASELINE_SSA = "ready_for_baseline_ssa", "SSA Required"
    READY_FOR_SUPPORT_PLANNING = (
        "ready_for_support_planning",
        "Ready for Support Planning",
    )
    READY_FOR_PARTNER_ASSIGNMENT = (
        "ready_for_partner_assignment",
        "Ready for Partner Assignment",
    )
    SCHEDULED = "scheduled", "Scheduled"
    IN_MY_PLAN = "in_my_plan", "In My Plan"
    AWAITING_EVIDENCE = "awaiting_evidence", "Awaiting Evidence"
    AWAITING_IA = "awaiting_ia", "Awaiting IA"
    FINANCE_PENDING = "finance_pending", "Finance Pending"
    CLOSED = "closed", "Closed"
    DATA_CLEANUP_REQUIRED = "data_cleanup_required", "Data Cleanup Required"
    COST_CATALOGUE_REQUIRED = "cost_catalogue_required", "Cost Catalogue Required"

    @classmethod
    def planning_ready_values(cls) -> list[str]:
        """States meaning "the school is unblocked/visible in Planning"."""
        return [
            cls.READY_FOR_SUPPORT_PLANNING,
            cls.READY_FOR_BASELINE_SSA,
        ]


class SsaCollectorType(models.TextChoices):
    STAFF = "staff", "Staff"
    PARTNER = "partner", "Partner"
    IA = "ia", "IA"
    IMPORTED_PREVIOUS_FY = "imported_previous_fy", "Imported (previous FY)"
    SYSTEM_MIGRATION = "system_migration", "System Migration"


class SsaIntervention(models.TextChoices):
    """The 8 SSA interventions, in the canonical CSV column order (2026-07-15
    clarification — do not rename, reorder, merge, or omit without an
    approved data migration and product decision). Note ENROLMENT is the
    school's *performance score* on enrolment (0-10) — entirely distinct
    from School.enrollment, the actual headcount. Never conflate the two;
    see apps.schools.models.School.enrollment."""

    CHRISTLIKE_BEHAVIOUR = "christlike_behaviour", "Christlike Behaviour"
    EXPOSURE_TO_WORD_OF_GOD = (
        "exposure_to_word_of_god",
        "Exposure to the Word of God",
    )
    FINANCIAL_HEALTH = "financial_health", "Financial Health"
    LEADERSHIP = "leadership", "Leadership"
    GOVERNMENT_REQUIREMENT = "government_requirement", "Government Requirements"
    LEARNING_ENVIRONMENT = "learning_environment", "Learning Environment"
    TEACHING_ENVIRONMENT = "teaching_environment", "Teacher's Environment"
    ENROLMENT = "enrolment", "Enrolment"


# Canonical SSA status bands on the 0-10 intervention/average score. This is
# the single source of truth (§5): Critical 0-4.9 / Warning 5-6.9 /
# Improving 7-7.9 / Strong 8-10. Everything that classifies an SSA score
# (dashboards, analytics, services) must derive from here — never redefine
# thresholds locally.
def ssa_score_band(score: float | None) -> tuple[str, str, str]:
    """Classify a 0-10 SSA score into (label, hex, tone)."""
    if score is None:
        return ("No SSA", "#94a3b8", "neutral")
    if score >= 8.0:
        return ("Strong", "#16a34a", "success")
    if score >= 7.0:
        return ("Improving", "#84cc16", "lime")
    if score >= 5.0:
        return ("Warning", "#f59e0b", "warning")
    return ("Critical", "#dc2626", "danger")


# ── Activities ────────────────────────────────────────────────────────────────
class ActivityType(models.TextChoices):
    SCHOOL_VISIT = "school_visit", "School Visit"
    FOLLOW_UP_VISIT = "follow_up_visit", "Follow-up Visit"
    COACHING_VISIT = "coaching_visit", "Coaching Visit"
    IN_SCHOOL_SUPPORT = "in_school_support", "In-school Support"
    DONOR_VISIT = "donor_visit", "Donor Visit"
    STORY_GATHERING_VISIT = "story_gathering_visit", "Gathering Story"
    SCHOOL_INVITATION = "school_invitation", "School Invitation"
    SOCIAL_VISIT = "social_visit", "Social Visit"
    TRAINING_FOLLOW_UP_VISIT = "training_follow_up_visit", "Training Follow-up Visit"
    IN_SCHOOL_COACHING_VISIT = "in_school_coaching_visit", "In-school Coaching Visit"
    TRAINING = "training", "Training"
    IN_SCHOOL_TRAINING = "in_school_training", "In-school Training"
    SCHOOL_IMPROVEMENT_TRAINING = (
        "school_improvement_training",
        "School Improvement Training",
    )
    CLUSTER_MEETING = "cluster_meeting", "Cluster Meeting"
    CLUSTER_TRAINING = "cluster_training", "Cluster Training"
    SSA_ACTIVITY = "ssa_activity", "SSA Activity"
    PROJECT_ACTIVITY = "project_activity", "Project Activity"
    PARTNER_ACTIVITY = "partner_activity", "Partner Activity"
    CORE_VISIT = "core_visit", "Core Visit"
    CORE_TRAINING = "core_training", "Core Training"
    BASELINE_SSA_VISIT = "baseline_ssa_visit", "SSA Visit"
    SCHOOL_VISIT_SSA_COLLECTION = (
        "school_visit_ssa_collection",
        "School Visit + SSA Collection",
    )
    CLUSTER_TRAINING_SSA_COLLECTION = (
        "cluster_training_ssa_collection",
        "Cluster Training + SSA Collection",
    )
    CLUSTER_MEETING_SSA_REVIEW = (
        "cluster_meeting_ssa_review",
        "Cluster Meeting + SSA Review",
    )
    PARTNER_SSA_COLLECTION = "partner_ssa_collection", "Partner SSA Collection"
    CORE_ASSESSMENT_VISIT = "core_assessment_visit", "Core Assessment Visit"
    # Dated programme work that does not originate from a school or cluster
    # plan: conferences, student camps, exhibitions, launches, stakeholder
    # events, staff workshops. Still a full canonical Activity.
    PROGRAMME_EVENT = "programme_event", "Programme Event"
    # Attendee-side field work: district meetings, boot camps, workshops —
    # priced from the MOU travel per-diems, not a venue recipe.
    FIELD_EVENT = "field_event", "Field Event"


class PlanningSource(models.TextChoices):
    """Where a planned Activity's budget authority originates (§1: every
    amount in an operational budget must originate from a dated plan)."""

    SCHOOL_PLANNING = "school_planning", "School Planning"
    CLUSTER_PLANNING = "cluster_planning", "Cluster Planning"
    CORE_PLANNING = "core_planning", "Core School Planning"
    PROJECT_PLANNING = "project_planning", "Special Project Planning"
    MANUAL_WORK_PLAN = "manual_work_plan", "Work Plan (Non-School)"


class ActivityContextType(models.TextChoices):
    SCHOOL = "school", "School"
    CLUSTER = "cluster", "Cluster"
    PROJECT = "project", "Project"
    PROGRAMME = "programme", "Programme"
    ORGANIZATION = "organization", "Organization"


class SupportRationale(models.TextChoices):
    """Strategic rationale for work that has no school SSA recommendation."""

    PROJECT_OBJECTIVE = "project_objective", "Project Objective"
    ORGANIZATIONAL_PRIORITY = "organizational_priority", "Organizational Priority"
    STAFF_DEVELOPMENT = "staff_development", "Staff Development"
    PROGRAMME_GROWTH = "programme_growth", "Programme Growth"
    PROGRAMME_QUALITY = "programme_quality", "Programme Quality"
    COMPLIANCE_REQUIREMENT = "compliance_requirement", "Compliance Requirement"
    STAKEHOLDER_ENGAGEMENT = "stakeholder_engagement", "Stakeholder Engagement"
    APPROVED_SPECIAL_INITIATIVE = (
        "approved_special_initiative",
        "Approved Special Initiative",
    )
    OTHER_AUTHORIZED = "other_authorized", "Other Authorized Rationale"


class ClusterMeetingSlot(models.TextChoices):
    SIT = "sit", "SIT"
    FIRST_MEETING = "first_meeting", "First Meeting"
    SECOND_MEETING = "second_meeting", "Second Meeting"
    THIRD_MEETING = "third_meeting", "Third Meeting"


class DeliveryType(models.TextChoices):
    STAFF = "staff", "Staff"
    PARTNER = "partner", "Partner"


class ExecutorType(models.TextChoices):
    """WHO performs the work — a finer distinction than DeliveryType.

    DeliveryType stays the two-valued staff/partner axis every existing
    surface keys on (My Plan scoping, oversight, costing, partner payment),
    so it must not grow a third value. But "partner" covers two workflows
    that are not the same commitment:

      • PARTNER — an assigned partner that still has to choose its own date.
        The Activity does not exist until the partner schedules it.
      • CERTIFIED_PARTNER_AGENCY — a certified agency that Edify staff book
        directly onto a chosen date. The Activity is scheduled the moment
        staff confirm, and lands in the agency's My Plan already dated.

    Conflating them is what made a booked agency see a "Schedule" action for
    work Edify had already scheduled.
    """

    STAFF = "staff", "Internal Staff"
    PARTNER = "partner", "Assigned Partner — Partner Selects Schedule"
    CERTIFIED_PARTNER_AGENCY = (
        "certified_partner_agency",
        "Certified Partner Agency",
    )


#: Executor types that are delivered by a partner organisation, and therefore
#: carry DeliveryType.PARTNER on the Activity.
PARTNER_EXECUTOR_TYPES = frozenset(
    {ExecutorType.PARTNER, ExecutorType.CERTIFIED_PARTNER_AGENCY}
)


class ParticipantMode(models.TextChoices):
    """How an activity's planned participant count is established.

    A visit is not scheduled on a participant basis: one officer goes to one
    school. Asking for a participant number there invents a quantity nobody
    measured and — because participant counts multiply into cost — prices the
    visit off it. NONE is therefore a real mode with teeth, not an absence of
    configuration: the backend clears participant values and the costing
    engine ignores them.
    """

    NONE = "none", "No participants"
    DIRECT_TOTAL = "direct_total", "Total entered directly"
    PER_SCHOOL = "per_school", "Participants per school × active schools"
    BY_CATEGORY = "by_category", "Teachers + leaders + other"


#: Participant modes whose total is a planned scheduling quantity.
PARTICIPANT_BEARING_MODES = frozenset(
    {
        ParticipantMode.DIRECT_TOTAL,
        ParticipantMode.PER_SCHOOL,
        ParticipantMode.BY_CATEGORY,
    }
)


class ProgrammeActivityType(models.TextChoices):
    """Leadership reporting categories for non-school Work Plan activities."""

    EDTECH_FOR_SCHOOLS = "edtech_for_schools", "EdTech for Schools"
    SCHOOL_LEADERSHIP_TRAINING = (
        "school_leadership_training",
        "School Leadership Training",
    )
    STUDENT_ACTIVITIES = "student_activities", "Student Activities"
    TEACHER_TRAINING = "teacher_training", "Teacher Training"
    ALUMNI = "alumni", "Alumni"
    TRAINING = "training", "Training"
    SCHOOL_VISIT = "school_visit", "School Visit"
    FIELD_EVENT = "field_event", "Field Event"
    YOUTH_CAMP = "youth_camp", "Youth Camp"
    ADMIN = "admin", "Admin"
    PROGRAMME_EVENT = "programme_event", "Programme Event"


class ProgrammeDeliveryMode(models.TextChoices):
    GROUP = "group", "Group"
    CLUSTER = "cluster", "Cluster"
    IN_SCHOOL = "in_school", "In-school Training"
    ONLINE = "online", "Online"
    VISIT = "visit", "School Visit"
    ADMIN = "admin", "Admin"


class ActivityStatus(models.TextChoices):
    """The 21-state activity workflow lifecycle."""

    NOT_PLANNED = "not_planned", "Not Planned"
    PLANNED = "planned", "Planned"
    SCHEDULED = "scheduled", "Scheduled"
    ASSIGNED_TO_PARTNER = "assigned_to_partner", "Assigned to Partner"
    PARTNER_SCHEDULED = "partner_scheduled", "Partner Scheduled"
    IN_PROGRESS = "in_progress", "In Progress"
    COMPLETION_STARTED = "completion_started", "Completion Started"
    EVIDENCE_UPLOADED = "evidence_uploaded", "Evidence Uploaded"
    EVIDENCE_ACCEPTED = "evidence_accepted", "Evidence Accepted"
    SALESFORCE_ID_REQUIRED = "salesforce_id_required", "Salesforce ID Required"
    SUBMITTED_TO_PL = "submitted_to_pl", "Submitted to PL"
    RETURNED_BY_PL = "returned_by_pl", "Returned by PL"
    AWAITING_IA_VERIFICATION = "awaiting_ia_verification", "Awaiting IA Verification"
    IA_VERIFIED = "ia_verified", "IA Verified"
    ACCOUNTANT_CONFIRMED = "accountant_confirmed", "Accountant Confirmed"
    COMPLETED = "completed", "Completed"
    RETURNED = "returned", "Returned"
    RETURNED_BY_IA = "returned_by_ia", "Returned by IA"
    CLOSED = "closed", "Closed"
    REJECTED = "rejected", "Rejected"
    RESCHEDULED = "rescheduled", "Rescheduled"
    CANCELLED = "cancelled", "Cancelled"
    DEFERRED = "deferred", "Deferred"


class EvidenceStatus(models.TextChoices):
    NONE = "none", "None"
    UPLOADED = "uploaded", "Uploaded"
    ACCEPTED = "accepted", "Accepted"
    RETURNED = "returned", "Returned"
    REJECTED = "rejected", "Rejected"


class EvidenceKind(models.TextChoices):
    VISIT_FORM = "visit_form", "Visit Form"
    SCHOOL_STAMP = "school_stamp", "School Stamp"
    ATTENDANCE_FORM = "attendance_form", "Attendance Form"
    MEETING_MINUTES = "meeting_minutes", "Meeting Minutes"
    RESOLUTIONS = "resolutions", "Resolutions"
    EVALUATION_FORM = "evaluation_form", "Evaluation Form"
    ASSESSMENT_FORM = "assessment_form", "Assessment Form"
    PHOTO = "photo", "Photo"
    PDF = "pdf", "PDF"
    PROJECT_REPORT = "project_report", "Project Report"
    COACHING_NOTES = "coaching_notes", "Coaching Notes"


class VerificationStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    RETURNED = "returned", "Returned"
    FLAGGED = "flagged", "Flagged"


class PaymentStatus(models.TextChoices):
    NONE = "none", "None"
    # Advance funds paid out pre-execution; accountability still open.
    DISBURSED = "disbursed", "Disbursed"
    PENDING_IA = "pending_ia", "Pending IA"
    IA_CONFIRMED = "ia_confirmed", "IA Confirmed"
    PL_APPROVAL_REQUIRED = "pl_approval_required", "PL Approval Required"
    PL_APPROVED = "pl_approved", "PL Approved"
    ACCOUNTANT_CLEARED = "accountant_cleared", "Accountant Cleared"
    PAID = "paid", "Paid"
    NETSUITE_ACCOUNTABILITY = "netsuite_accountability", "Netsuite Accountability"
    CLOSED = "closed", "Closed"
    REJECTED = "rejected", "Rejected"


class PaymentPath(models.TextChoices):
    PARTNER = "partner", "Partner"
    STAFF = "staff", "Staff"


class SalesforceSyncStatus(models.TextChoices):
    NOT_SYNCED = "not_synced", "Not Synced"
    PENDING = "pending", "Pending"
    SYNCED = "synced", "Synced"
    ERROR = "error", "Error"


# ── Comms / ops ───────────────────────────────────────────────────────────────
class NotificationPriority(models.TextChoices):
    LOW = "low", "Low"
    NORMAL = "normal", "Normal"
    HIGH = "high", "High"
    URGENT = "urgent", "Urgent"


class MessageStatus(models.TextChoices):
    UNREAD = "unread", "Unread"
    READ = "read", "Read"
    ARCHIVED = "archived", "Archived"


__all__ = [
    "SchoolType",
    "AccountOwnerStatus",
    "DuplicateStatus",
    "ClusterStatus",
    "ClusterRecordStatus",
    "ClusterType",
    "DistrictType",
    "SsaStatus",
    "PlanningReadiness",
    "SsaCollectorType",
    "SsaIntervention",
    "ActivityType",
    "ClusterMeetingSlot",
    "DeliveryType",
    "ActivityStatus",
    "EvidenceStatus",
    "EvidenceKind",
    "VerificationStatus",
    "PaymentStatus",
    "PaymentPath",
    "SalesforceSyncStatus",
    "NotificationPriority",
    "MessageStatus",
]
