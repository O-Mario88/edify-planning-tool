"""
Shared domain enums — TextChoices used across multiple apps.

These mirror the legacy Prisma enums. Cross-domain enums (shared by more than
one module) live here; single-domain enums can live in their own app.
"""

from __future__ import annotations

from django.db import models


# ── Schools ───────────────────────────────────────────────────────────────────
class SchoolType(models.TextChoices):
    CLIENT = "client", "Client"
    CORE = "core", "Core"
    POTENTIAL_CORE = "potential_core", "Potential Core"
    CHAMPION = "champion", "Champion"
    POTENTIAL_CHAMPION = "potential_champion", "Potential Champion"
    OTHER = "other", "Other"


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
    TRAINING = "training", "Training"
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


class ClusterMeetingSlot(models.TextChoices):
    SIT = "sit", "SIT"
    FIRST_MEETING = "first_meeting", "First Meeting"
    SECOND_MEETING = "second_meeting", "Second Meeting"
    THIRD_MEETING = "third_meeting", "Third Meeting"


class DeliveryType(models.TextChoices):
    STAFF = "staff", "Staff"
    PARTNER = "partner", "Partner"


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
