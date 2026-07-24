"""Field Debrief models — the operational learning layer between field
execution and leadership decision-making (mandate §1-§19).

`DailyDebrief` is the core record (kept its original name/table to avoid a
disruptive rename of already-shipped data — "Daily Debrief" is also the
existing, unchanged sidebar label). Everything else here is new: activity/
school linking (supports one debrief covering many schools, or one debrief
per school — mandate addendum), structured challenges/commitments/support
requests (richer than the old flat arrays), leadership actions, peer
learning, and automated recurring-issue insights.

Deliberately NOT modeled as separate tables (see mandate §19's full list):
FieldDebriefObservation (folded onto DailyDebrief — 1:1 narrative fields,
not repeating data), FieldDebriefWeeklySummary (computed on read by
FieldDebriefWeeklyRollupService, matching every other "roll-up" in this
codebase — no cron needed just to populate a cache), FieldDebriefEscalation
(the `risk_level`/`is_restricted_incident` fields on DailyDebrief plus
DailyDebriefAction already cover escalation without a redundant table).
"""

from __future__ import annotations

from django.contrib.postgres.fields import ArrayField
from django.db import models

from apps.core.enums import SsaIntervention
from apps.core.models import CuidField, SoftDeleteModel, TimeStampedModel


class DebriefType(models.TextChoices):
    STAFF = "staff", "Staff"
    PARTNER = "partner", "Partner"
    MERGED = "merged", "Merged"


class DebriefKind(models.TextChoices):
    """§6 — what shape of debrief this is, independent of who submitted it."""

    ACTIVITY = "activity", "Activity Debrief"
    DAILY = "daily", "Daily Field Debrief"
    PARTNER = "partner", "Partner Debrief"
    SUPERVISION = "supervision", "Supervision Debrief"
    INCIDENT = "incident", "Incident Debrief"
    WEEKLY_SUMMARY = "weekly_summary", "Weekly Field Summary"


class DebriefStatus(models.TextChoices):
    """§9 — debrief-record status. Kept the original 6 values (some still
    written by the pre-existing DRF merge path) and added the mandate's
    richer lifecycle on top."""

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    CLARIFICATION_REQUESTED = "clarification_requested", "Clarification Requested"
    UPDATED = "updated", "Updated"
    LEADERSHIP_REVIEW = "leadership_review", "Leadership Review"
    ACTION_REQUIRED = "action_required", "Action Required"
    ESCALATED = "escalated", "Escalated"
    ACTION_IN_PROGRESS = "action_in_progress", "Action in Progress"
    RESOLVED = "resolved", "Resolved"
    CLOSED = "closed", "Closed"
    RESTRICTED_INCIDENT = "restricted_incident", "Restricted Incident"
    REVIEWED = "reviewed", "Reviewed"
    MERGED = "merged", "Merged"
    RETURNED = "returned", "Returned"
    ARCHIVED = "archived", "Archived"


class CompletionStatus(models.TextChoices):
    COMPLETED_AS_PLANNED = "completed_as_planned", "Completed as Planned"
    PARTIALLY_COMPLETED = "partially_completed", "Partially Completed"
    UNSUCCESSFUL = "unsuccessful", "Unsuccessful"
    POSTPONED = "postponed", "Postponed"
    CANCELLED = "cancelled", "Cancelled"
    RESCHEDULED = "rescheduled", "Rescheduled"


class EngagementLevel(models.TextChoices):
    EXCELLENT = "excellent", "Excellent"
    GOOD = "good", "Good"
    MODERATE = "moderate", "Moderate"
    LOW = "low", "Low"
    VERY_LOW = "very_low", "Very Low"


class RecommendedActivityType(models.TextChoices):
    SCHOOL_VISIT = "school_visit", "School Visit"
    FOLLOW_UP_VISIT = "follow_up_visit", "Follow-Up Visit"
    BASELINE_SSA = "baseline_ssa", "Baseline SSA"
    SSA_REFRESH = "ssa_refresh", "SSA Refresh"
    CLUSTER_MEETING = "cluster_meeting", "Cluster Meeting"
    CLUSTER_TRAINING = "cluster_training", "Cluster Training"
    CORE_VISIT = "core_visit", "Core Visit"
    CORE_TRAINING = "core_training", "Core Training"
    PARTNER_COACHING = "partner_coaching", "Partner Coaching"
    LEADERSHIP_FOLLOW_UP = "leadership_follow_up", "Leadership Follow-Up"
    FINANCE_FOLLOW_UP = "finance_follow_up", "Finance Follow-Up"
    DATA_CLEANUP = "data_cleanup", "Data Cleanup"
    NO_FURTHER_ACTION = "no_further_action", "No Further Action"


class RecommendationStatus(models.TextChoices):
    NONE = "none", "None"
    PROPOSED = "proposed", "Proposed"
    ACCEPTED = "accepted", "Accepted"
    REJECTED = "rejected", "Rejected"


class RiskLevel(models.TextChoices):
    NONE = "none", "No Escalation"
    MONITOR = "monitor", "Monitor"
    PL_ATTENTION = "pl_attention", "PL Attention"
    CD_ATTENTION = "cd_attention", "CD Attention"
    IA_ATTENTION = "ia_attention", "IA Attention"
    HR_ATTENTION = "hr_attention", "HR Attention"
    FINANCE_ATTENTION = "finance_attention", "Finance Attention"
    CRITICAL = "critical", "Critical Leadership Attention"


class RestrictedIncidentCategory(models.TextChoices):
    SAFEGUARDING = "safeguarding", "Safeguarding"
    FRAUD = "fraud", "Fraud or Misuse of Funds"
    STAFF_SAFETY = "staff_safety", "Serious Staff Safety Issue"
    DATA_INTEGRITY = "data_integrity", "Serious Data Integrity Issue"
    PARTNER_MISCONDUCT = "partner_misconduct", "Major Partner Misconduct"
    SCHOOL_COMPLAINT = "school_complaint", "Severe School Complaint"
    OTHER = "other", "Other"


class DailyDebrief(SoftDeleteModel):
    """A field debrief — staff, partner, or merged."""

    id = CuidField()
    fy = models.CharField(max_length=16)
    date = models.DateTimeField()
    submitted_by_user_id = models.CharField(max_length=30)
    submitted_by_role = models.CharField(max_length=64)
    staff_id = models.CharField(max_length=30, null=True, blank=True)
    partner_id = models.CharField(max_length=30, null=True, blank=True)
    debrief_type = models.CharField(
        max_length=16, choices=DebriefType.choices, default=DebriefType.STAFF
    )
    kind = models.CharField(
        max_length=16, choices=DebriefKind.choices, default=DebriefKind.ACTIVITY
    )
    status = models.CharField(
        max_length=32, choices=DebriefStatus.choices, default=DebriefStatus.SUBMITTED
    )

    # Title — replaces "Key Challenge" as the Team & Partner Debriefs table's
    # link column into this debrief's detail page.
    title = models.CharField(max_length=255, blank=True)

    summary = models.TextField(null=True, blank=True)
    what_happened = models.TextField(null=True, blank=True)
    what_went_well = models.TextField(null=True, blank=True)
    what_did_not_go_well = models.TextField(null=True, blank=True)
    # Daily Debrief Q4 ("What challenges did you face?") — free narrative.
    # Distinct from the structured DailyDebriefChallenge rows, which the
    # insight engine derives AFTER submission; staff never re-enter them.
    challenges_faced = models.TextField(null=True, blank=True)
    # Daily Debrief "Add Other Work" — authorized work not present in My
    # Plan. Free description only; material/unplanned work routes to the
    # manager for future Planning, never recreates an Activity here.
    other_work_description = models.TextField(null=True, blank=True)
    blockers = ArrayField(
        base_field=models.CharField(max_length=255), default=list, blank=True
    )
    blocker_other = models.CharField(max_length=512, null=True, blank=True)
    support_needed = models.TextField(null=True, blank=True)
    recommendations = models.TextField(null=True, blank=True)
    next_action = models.CharField(max_length=512, null=True, blank=True)

    # Loose cross-app refs kept for the pre-existing DRF API's shape.
    # New code should prefer DailyDebriefActivityLink (real FK, supports
    # grouping several activities/schools under one debrief).
    linked_school_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    linked_cluster_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    linked_partner_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    linked_project_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    linked_activity_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )

    parent_debrief_id = models.CharField(max_length=30, null=True, blank=True)
    merged_into_debrief_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(null=True, blank=True)
    submitted_at = models.DateTimeField()

    # B. Execution Summary (§7-B)
    completion_status = models.CharField(
        max_length=24, choices=CompletionStatus.choices, null=True, blank=True
    )
    incomplete_reason = models.TextField(null=True, blank=True)
    actual_start_time = models.TimeField(null=True, blank=True)
    actual_end_time = models.TimeField(null=True, blank=True)
    participants_summary = models.TextField(null=True, blank=True)
    what_was_done = models.TextField(null=True, blank=True)
    intended_purpose = models.TextField(null=True, blank=True)
    purpose_achieved = models.BooleanField(null=True, blank=True)

    # C. School/Cluster Observations (§7-C) — 1:1 narrative, not repeating.
    what_observed = models.TextField(null=True, blank=True)
    what_improved = models.TextField(null=True, blank=True)
    what_remains_weak = models.TextField(null=True, blank=True)
    what_surprised = models.TextField(null=True, blank=True)
    support_needed_next = models.TextField(null=True, blank=True)
    intervention_tags = ArrayField(
        base_field=models.CharField(max_length=64, choices=SsaIntervention.choices),
        default=list,
        blank=True,
    )

    # D. Participant and Engagement Quality (§7-D)
    expected_participants = models.IntegerField(null=True, blank=True)
    actual_participants = models.IntegerField(null=True, blank=True)
    school_leaders_present = models.IntegerField(null=True, blank=True)
    teachers_present = models.IntegerField(null=True, blank=True)
    other_participants_present = models.IntegerField(null=True, blank=True)
    engagement_level = models.CharField(
        max_length=16, choices=EngagementLevel.choices, null=True, blank=True
    )
    attendance_concerns = models.TextField(null=True, blank=True)

    # F. Route and Travel Debrief (§7-F) — feeds Route Intelligence.
    planned_route = models.TextField(null=True, blank=True)
    actual_route = models.TextField(null=True, blank=True)
    schools_planned_count = models.IntegerField(null=True, blank=True)
    schools_reached_count = models.IntegerField(null=True, blank=True)
    travel_start_time = models.TimeField(null=True, blank=True)
    travel_end_time = models.TimeField(null=True, blank=True)
    estimated_travel_minutes = models.IntegerField(null=True, blank=True)
    actual_travel_minutes = models.IntegerField(null=True, blank=True)
    route_quality = models.CharField(
        max_length=16, null=True, blank=True
    )  # excellent|good|fair|poor
    transport_issue = models.TextField(null=True, blank=True)

    # G. Outcomes and Commitments — recommendation half (§7-G). The actual
    # per-party commitments live in DailyDebriefCommitment (repeatable).
    immediate_result = models.TextField(null=True, blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_owner_id = models.CharField(max_length=30, null=True, blank=True)
    recommended_next_activity_type = models.CharField(
        max_length=32, choices=RecommendedActivityType.choices, null=True, blank=True
    )
    recommended_intervention = models.CharField(
        max_length=64, choices=SsaIntervention.choices, null=True, blank=True
    )
    recommendation_status = models.CharField(
        max_length=16,
        choices=RecommendationStatus.choices,
        default=RecommendationStatus.NONE,
    )
    recommendation_accepted_activity_id = models.CharField(
        max_length=30, null=True, blank=True
    )
    recommendation_reviewed_by_user_id = models.CharField(
        max_length=30, null=True, blank=True
    )
    recommendation_reviewed_at = models.DateTimeField(null=True, blank=True)

    # I. Success and Learning (§7-I)
    key_success = models.TextField(null=True, blank=True)
    key_lesson_learned = models.TextField(null=True, blank=True)
    practice_worth_repeating = models.TextField(null=True, blank=True)
    innovation_observed = models.TextField(null=True, blank=True)
    potential_mscs_flag = models.BooleanField(default=False)
    potential_mscs_title = models.CharField(max_length=255, null=True, blank=True)
    potential_mscs_narrative = models.TextField(null=True, blank=True)
    mscs_draft_story_id = models.CharField(max_length=30, null=True, blank=True)
    potential_champion_flag = models.BooleanField(default=False)
    potential_champion_note = models.TextField(null=True, blank=True)
    potential_partner_success_flag = models.BooleanField(default=False)

    # J. Risk and Escalation (§7-J)
    risk_level = models.CharField(
        max_length=24, choices=RiskLevel.choices, default=RiskLevel.NONE
    )
    is_restricted_incident = models.BooleanField(default=False)
    restricted_incident_category = models.CharField(
        max_length=24, choices=RestrictedIncidentCategory.choices, null=True, blank=True
    )

    class Meta:
        db_table = "daily_debrief"
        ordering = ["-date"]
        indexes = [
            models.Index(fields=["fy", "date"]),
            models.Index(fields=["submitted_by_user_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["partner_id"]),
            models.Index(fields=["risk_level"]),
            models.Index(fields=["is_restricted_incident"]),
        ]
        constraints = [
            # One Daily Debrief per user per local date. The daily flow
            # normalizes `date` to midnight, so equality on the datetime is
            # equality on the day. Draft → submitted reuses the same row;
            # only the DAILY kind participates (activity/partner/etc. kinds
            # may legitimately have several records a day).
            models.UniqueConstraint(
                fields=["submitted_by_user_id", "date"],
                condition=models.Q(kind="daily", deleted_at__isnull=True),
                name="uniq_daily_debrief_per_user_per_day",
            )
        ]

    def __str__(self) -> str:
        return self.title or f"Debrief {self.id}"


class DailyDebriefRecipient(TimeStampedModel):
    """Routing of a debrief to its recipients (PL/CD/IA/HR/RVP)."""

    id = CuidField()
    debrief = models.ForeignKey(
        DailyDebrief, on_delete=models.CASCADE, related_name="recipients"
    )
    recipient_user_id = models.CharField(max_length=30)
    recipient_role = models.CharField(max_length=64)
    routing_reason = models.CharField(max_length=255, null=True, blank=True)
    action_required = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "daily_debrief_recipient"
        indexes = [
            models.Index(fields=["recipient_user_id", "read_at"]),
            models.Index(fields=["debrief"]),
        ]


class DailyDebriefActivityLink(TimeStampedModel):
    """One row per Activity a debrief covers — lets a submitter group
    several schools/activities into one debrief, or submit one debrief per
    activity (mandate addendum). `school_id` is denormalized from the
    activity at link time purely to avoid an extra join on every list
    render; it is not authoritative."""

    id = CuidField()
    debrief = models.ForeignKey(
        DailyDebrief, on_delete=models.CASCADE, related_name="activity_links"
    )
    activity = models.ForeignKey(
        "activities.Activity", on_delete=models.CASCADE, related_name="debrief_links"
    )
    school_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "daily_debrief_activity_link"
        constraints = [
            models.UniqueConstraint(
                fields=["debrief", "activity"], name="uniq_debrief_activity_link"
            )
        ]
        indexes = [
            models.Index(fields=["activity"]),
            models.Index(fields=["school_id"]),
        ]


class DebriefChallengeType(models.TextChoices):
    LEADER_UNAVAILABLE = "leader_unavailable", "School Leader Unavailable"
    TEACHERS_UNAVAILABLE = "teachers_unavailable", "Teachers Unavailable"
    LOW_ATTENDANCE = "low_attendance", "Low Attendance"
    STARTED_LATE = "started_late", "Activity Started Late"
    TRANSPORT_LATE = "transport_late", "Transport Came Late"
    NO_TRANSPORT = "no_transport", "No Transport"
    WEATHER = "weather", "Weather"
    ROAD_CONDITIONS = "road_conditions", "Road Conditions"
    DISTANCE_ROUTE = "distance_route", "Distance or Route Problem"
    HOLIDAY_CONFLICT = "holiday_conflict", "Public Holiday Conflict"
    SCHOOL_EVENT_CONFLICT = "school_event_conflict", "School Event Conflict"
    FUNDS_DELAYED = "funds_delayed", "Funds Delayed"
    FUNDS_INSUFFICIENT = "funds_insufficient", "Funds Insufficient"
    PARTNER_DELAYED = "partner_delayed", "Partner Delayed"
    MATERIALS_UNAVAILABLE = "materials_unavailable", "Materials Unavailable"
    TECHNOLOGY_PROBLEM = "technology_problem", "Technology Problem"
    DATA_QUALITY = "data_quality", "Data-Quality Problem"
    SSA_FORM_ISSUE = "ssa_form_issue", "SSA Form Issue"
    LANGUAGE_COMMUNICATION = (
        "language_communication",
        "Language or Communication Problem",
    )
    SAFETY_CONCERN = "safety_concern", "Safety Concern"
    HEALTH_CONCERN = "health_concern", "Health Concern"
    COMMUNITY_RESISTANCE = "community_resistance", "Community Resistance"
    GOVERNMENT_REGULATORY = "government_regulatory", "Government or Regulatory Issue"
    OTHER = "other", "Other"


class DailyDebriefChallenge(TimeStampedModel):
    """One structured challenge row (§7-E) — richer than a flat string tag:
    each challenge carries its own severity, response, and resolution."""

    id = CuidField()
    debrief = models.ForeignKey(
        DailyDebrief, on_delete=models.CASCADE, related_name="challenges"
    )
    challenge_type = models.CharField(
        max_length=32, choices=DebriefChallengeType.choices
    )
    description = models.TextField(null=True, blank=True)
    severity = models.CharField(
        max_length=8,
        choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")],
        default="medium",
    )
    immediate_response = models.TextField(null=True, blank=True)
    resolved = models.BooleanField(default=False)
    follow_up_owner_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "daily_debrief_challenge"
        indexes = [
            models.Index(fields=["challenge_type"]),
            models.Index(fields=["debrief"]),
        ]


class DebriefCommitmentParty(models.TextChoices):
    SCHOOL = "school", "School"
    STAFF = "staff", "Edify Staff"
    PARTNER = "partner", "Partner"


class DailyDebriefCommitment(TimeStampedModel):
    """A commitment made by the school, Edify staff, or the Partner (§7-G)."""

    id = CuidField()
    debrief = models.ForeignKey(
        DailyDebrief, on_delete=models.CASCADE, related_name="commitments"
    )
    party = models.CharField(max_length=8, choices=DebriefCommitmentParty.choices)
    commitment_text = models.TextField()
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_owner_id = models.CharField(max_length=30, null=True, blank=True)
    status = models.CharField(
        max_length=8,
        choices=[("open", "Open"), ("resolved", "Resolved")],
        default="open",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "daily_debrief_commitment"
        indexes = [models.Index(fields=["debrief"]), models.Index(fields=["status"])]


class DebriefSupportRole(models.TextChoices):
    PL = "Program Lead", "Program Lead"
    CD = "CountryDirector", "Country Director"
    IA = "ImpactAssessment", "Impact Assessment"
    HR = "HumanResources", "HR"
    ACCOUNTANT = "Accountant", "Accountant"
    PARTNER_MANAGER = "partner_manager", "Partner Manager"
    PROJECT_COORDINATOR = "ProjectCoordinator", "Project Coordinator"
    RVP = "RegionalVicePresident", "RVP"


class DebriefSupportType(models.TextChoices):
    TECHNICAL = "technical", "Technical Support"
    INTERVENTION_GUIDANCE = "intervention_guidance", "Intervention Guidance"
    BUDGET = "budget", "Budget Support"
    TRANSPORT = "transport", "Transport Support"
    PARTNER = "partner", "Partner Support"
    TRAINING_MATERIALS = "training_materials", "Training Materials"
    SSA_DATA = "ssa_data", "SSA/Data Support"
    WORKLOAD = "workload", "Workload Support"
    HR_SUPPORT = "hr_support", "HR Support"
    LEADERSHIP_DECISION = "leadership_decision", "Leadership Decision"
    POLICY_CLARIFICATION = "policy_clarification", "Policy Clarification"


class DailyDebriefSupportRequest(TimeStampedModel):
    """A request for support routed to a specific role (§7-H)."""

    id = CuidField()
    debrief = models.ForeignKey(
        DailyDebrief, on_delete=models.CASCADE, related_name="support_requests"
    )
    requested_from_role = models.CharField(
        max_length=32, choices=DebriefSupportRole.choices
    )
    support_type = models.CharField(max_length=32, choices=DebriefSupportType.choices)
    note = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=[
            ("open", "Open"),
            ("in_progress", "In Progress"),
            ("resolved", "Resolved"),
        ],
        default="open",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_user_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "daily_debrief_support_request"
        indexes = [
            models.Index(fields=["requested_from_role", "status"]),
            models.Index(fields=["debrief"]),
        ]


class DebriefActionStatus(models.TextChoices):
    OPEN = "open", "Open"
    ASSIGNED = "assigned", "Assigned"
    ACCEPTED = "accepted", "Accepted"
    IN_PROGRESS = "in_progress", "In Progress"
    WAITING_ON_ANOTHER_ROLE = "waiting_on_another_role", "Waiting on Another Role"
    RESOLVED = "resolved", "Resolved"
    RETURNED = "returned", "Returned"
    ESCALATED = "escalated", "Escalated"
    CLOSED = "closed", "Closed"


class DebriefActionPriority(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class DailyDebriefAction(TimeStampedModel):
    """A leadership action created from a debrief issue (§12). The debrief's
    own status and its actions' statuses are deliberately independent — a
    debrief can stay "submitted" while several actions are still open."""

    id = CuidField()
    debrief = models.ForeignKey(
        DailyDebrief, on_delete=models.CASCADE, related_name="actions"
    )
    issue = models.TextField()
    action = models.TextField()
    owner_user_id = models.CharField(max_length=30)
    owner_role = models.CharField(max_length=64, null=True, blank=True)
    assigned_by_user_id = models.CharField(max_length=30)
    priority = models.CharField(
        max_length=8,
        choices=DebriefActionPriority.choices,
        default=DebriefActionPriority.MEDIUM,
    )
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=24,
        choices=DebriefActionStatus.choices,
        default=DebriefActionStatus.OPEN,
    )
    resolution = models.TextField(null=True, blank=True)
    resolved_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "daily_debrief_action"
        indexes = [
            models.Index(fields=["owner_user_id", "status"]),
            models.Index(fields=["debrief"]),
            models.Index(fields=["status", "priority"]),
        ]


class PeerSolutionStatus(models.TextChoices):
    PROPOSED = "proposed", "Proposed"
    UNDER_DISCUSSION = "under_discussion", "Under Discussion"
    ENDORSED = "endorsed", "Endorsed"
    ADOPTED = "adopted", "Adopted"
    PILOTING = "piloting", "Piloting"
    REJECTED = "rejected", "Rejected"
    ARCHIVED = "archived", "Archived"


class PeerSolutionPLClassification(models.TextChoices):
    USEFUL = "useful", "Useful"
    ADOPT_FOR_TEAM = "adopt_for_team", "Adopt for Team"
    PILOT = "pilot", "Pilot"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence", "Needs More Evidence"
    NOT_APPLICABLE = "not_applicable", "Not Applicable"


class DailyDebriefPeerSolution(TimeStampedModel):
    """A peer-proposed solution attached to someone else's debrief (§16)."""

    id = CuidField()
    debrief = models.ForeignKey(
        DailyDebrief, on_delete=models.CASCADE, related_name="peer_solutions"
    )
    author_user_id = models.CharField(max_length=30)
    suggestion = models.TextField()
    related_experience = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=16,
        choices=PeerSolutionStatus.choices,
        default=PeerSolutionStatus.PROPOSED,
    )
    endorsed_by_user_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    pl_classification = models.CharField(
        max_length=20,
        choices=PeerSolutionPLClassification.choices,
        null=True,
        blank=True,
    )
    pl_classified_by_user_id = models.CharField(max_length=30, null=True, blank=True)
    pl_classified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "daily_debrief_peer_solution"
        indexes = [
            models.Index(fields=["debrief"]),
            models.Index(fields=["author_user_id"]),
        ]


class InsightScope(models.TextChoices):
    SCHOOL = "school", "School"
    CLUSTER = "cluster", "Cluster"
    DISTRICT = "district", "District"
    PARTNER = "partner", "Partner"
    STAFF = "staff", "Staff"
    TEAM = "team", "Team"
    COUNTRY = "country", "Country"
    REGION = "region", "Region"


class InsightEscalationLevel(models.TextChoices):
    TEAM = "team", "Team"
    COUNTRY = "country", "Country"
    REGION = "region", "Region"


class DailyDebriefInsight(TimeStampedModel):
    """A detected recurring pattern across 3+ debriefs within a rolling
    window (§15) — e.g. the same challenge type at the same school, or the
    same strategic issue across PL teams/countries."""

    id = CuidField()
    scope = models.CharField(max_length=16, choices=InsightScope.choices)
    scope_id = models.CharField(max_length=30, null=True, blank=True)
    challenge_type = models.CharField(max_length=32, null=True, blank=True)
    title = models.CharField(max_length=255)
    description = models.TextField()
    occurrence_count = models.IntegerField(default=1)
    window_start = models.DateField()
    window_end = models.DateField()
    debrief_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )
    escalation_level = models.CharField(
        max_length=8,
        choices=InsightEscalationLevel.choices,
        default=InsightEscalationLevel.TEAM,
    )
    status = models.CharField(
        max_length=16,
        choices=[
            ("open", "Open"),
            ("acknowledged", "Acknowledged"),
            ("dismissed", "Dismissed"),
        ],
        default="open",
    )
    notified_user_ids = ArrayField(
        base_field=models.CharField(max_length=30), default=list, blank=True
    )

    class Meta:
        db_table = "daily_debrief_insight"
        indexes = [
            models.Index(fields=["scope", "scope_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["escalation_level"]),
        ]


__all__ = [
    "DebriefType",
    "DebriefKind",
    "DebriefStatus",
    "CompletionStatus",
    "EngagementLevel",
    "RecommendedActivityType",
    "RecommendationStatus",
    "RiskLevel",
    "RestrictedIncidentCategory",
    "DailyDebrief",
    "DailyDebriefRecipient",
    "DailyDebriefActivityLink",
    "DebriefChallengeType",
    "DailyDebriefChallenge",
    "DebriefCommitmentParty",
    "DailyDebriefCommitment",
    "DebriefSupportRole",
    "DebriefSupportType",
    "DailyDebriefSupportRequest",
    "DebriefActionStatus",
    "DebriefActionPriority",
    "DailyDebriefAction",
    "PeerSolutionStatus",
    "PeerSolutionPLClassification",
    "DailyDebriefPeerSolution",
    "InsightScope",
    "InsightEscalationLevel",
    "DailyDebriefInsight",
]
