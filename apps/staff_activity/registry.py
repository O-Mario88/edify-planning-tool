"""The meaningful actions the Staff Activity Log counts.

Owner, 2026-09-29: the log has two layers — platform engagement (sign-ins,
active time, pages) and meaningful operational actions (a plan created, a
visit scheduled, evidence submitted, a plan approved, an activity verified…).
A page view is never an action.

Actions are not recorded twice. Every governed workflow transition already
writes a row to the hash-chained audit log (apps.audit); this registry names
the audit actions that are a person's meaningful work, with the words a
manager reads and the part of the tool they belong to. The audit chain stays
the authoritative record of the business transition; the Activity Log reads
it. An audit action missing from here is machinery (a cost recalculated, a
notification sent, a page refused) and is not counted.

``school`` marks work done for a school — the "schools acted on" column counts
the distinct schools those rows name.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionDefinition:
    label: str
    module: str
    school: bool = False


_A = ActionDefinition

MEANINGFUL_ACTIONS: dict[str, ActionDefinition] = {
    # ── Field work (CCEO, Project Coordinator, Partner) ──
    "activity.planned": _A("Planned an activity", "Planning", True),
    "activity.scheduled": _A("Scheduled an activity", "Planning", True),
    "schedule_core_visit": _A("Scheduled a core school visit", "Planning", True),
    "schedule_core_training": _A("Scheduled a core training", "Planning", True),
    "reschedule_activity": _A("Rescheduled an activity", "Planning", True),
    "cancel_activity": _A("Cancelled an activity", "Planning", True),
    "visit_request_submitted": _A("Requested a school visit", "Planning", True),
    "activity.cluster_meeting_added_to_my_plan": _A(
        "Added a cluster meeting to My Plan", "My Plan"
    ),
    "start_activity": _A("Started an activity", "My Plan", True),
    "partner_start_activity": _A("Started a partner activity", "My Plan", True),
    "submit_for_review": _A("Submitted an activity for review", "My Plan", True),
    "activity.salesforce_id_entered": _A("Entered a Salesforce ID", "My Plan", True),
    "upload_evidence": _A("Submitted activity evidence", "Evidence", True),
    "upload_attendance": _A("Uploaded attendance", "Evidence", True),
    "upload_ssa": _A("Uploaded an SSA", "SSA", True),
    "complete_partner_ssa_support": _A("Completed partner SSA support", "SSA", True),
    "accountability_submitted": _A("Submitted accountability", "Fund Requests"),
    "advance_request.submit_accountability": _A(
        "Submitted accountability", "Fund Requests"
    ),
    "school.profile_updated": _A("Updated a school record", "Schools", True),
    "school.updated": _A("Updated a school record", "Schools", True),
    "cluster.membership_changed": _A("Changed a cluster's schools", "Clusters", True),
    "escalation_raise": _A("Raised an escalation", "Escalations"),
    # ── Team leadership (Programme Lead) ──
    "pl_review_confirm": _A("Confirmed an activity", "Planning Oversight", True),
    "pl_review_return": _A("Returned an activity", "Planning Oversight", True),
    "pl_approve_completion": _A(
        "Confirmed a completed activity", "Planning Oversight", True
    ),
    "pl_return_completion": _A(
        "Returned a completed activity", "Planning Oversight", True
    ),
    "supervisor_approve": _A("Approved a team request", "Planning Oversight"),
    "supervisor_return": _A("Returned a team request", "Planning Oversight"),
    "visit_request_approve": _A("Approved a visit request", "Planning Oversight", True),
    "school_action.sent": _A("Sent a school to an officer", "Planning Oversight", True),
    "oversight.role_queue_nudged": _A("Followed up a team queue", "Planning Oversight"),
    "send_reminder": _A("Sent a reminder", "Planning Oversight"),
    "weekly_fund_request.approve": _A(
        "Approved a weekly fund request", "Fund Approvals"
    ),
    "weekly_fund_request.return": _A(
        "Returned a weekly fund request", "Fund Approvals"
    ),
    "partner.assigned": _A("Assigned a school to a partner", "Partners", True),
    "field_debrief_reviewed": _A("Reviewed a field debrief", "Field Debrief"),
    "escalation_acknowledge": _A("Acknowledged an escalation", "Escalations"),
    "escalation_resolve": _A("Decided an escalation", "Escalations"),
    "staff_activity.follow_up_sent": _A(
        "Sent a follow-up to a team member", "Staff Activity"
    ),
    "staff_activity.follow_up_resolved": _A(
        "Resolved a staff follow-up", "Staff Activity"
    ),
    # ── Country leadership (Country Director) ──
    "hr.strategic_priority_published": _A(
        "Published a strategic priority", "Priorities"
    ),
    "hr.priority_amended": _A("Amended a priority", "Priorities"),
    "hr.uganda_master_milestone_confirmed": _A(
        "Confirmed a master milestone", "Priorities"
    ),
    "country_budget.submit_to_rvp": _A("Submitted the country budget", "Budget"),
    "rate_card.version.published": _A("Published a rate card", "Budget"),
    "rate_card.operational.version.published": _A("Published a rate card", "Budget"),
    "strategic_reserve.approved": _A("Approved a strategic reserve", "Budget"),
    "strategic_reserve.activation.approved": _A(
        "Approved a strategic reserve activation", "Budget"
    ),
    "fy.planning_opened": _A("Opened planning for the year", "Planning"),
    "hr.performance_window_activated": _A("Opened a performance window", "Performance"),
    "rvp_annual_approve": _A("Approved the annual baseline", "Budget"),
    # ── Impact Assessment ──
    "ssa_verify": _A("Confirmed an SSA record", "SSA", True),
    "ssa_return": _A("Returned an SSA record", "SSA", True),
    "ia_verify_completion": _A("Verified an activity", "Verification", True),
    "ia_return_completion": _A("Returned an activity's evidence", "Verification", True),
    "verification_sample_graded": _A(
        "Graded a verification sample", "Verification", True
    ),
    "verification_sample_resolved": _A(
        "Resolved a verification sample", "Verification"
    ),
    "data_quality_issue.resolve": _A("Resolved a data-quality issue", "Data Quality"),
    "targets.reconciliation_resolved": _A(
        "Resolved a target reconciliation", "Targets"
    ),
    "ia.finding.approved": _A("Approved an impact finding", "Impact"),
    "ia.school_evidence.learning_recorded": _A(
        "Recorded learning evidence", "Impact", True
    ),
    "ia.school_evidence.learning_confirmed": _A(
        "Confirmed learning evidence", "Impact", True
    ),
    "ia.school_evidence.discipleship_confirmed": _A(
        "Confirmed discipleship evidence", "Impact", True
    ),
    "mscs.story_approved": _A("Approved a change story", "Impact"),
    # ── Finance (Accountant) ──
    "fund_request.approved": _A("Approved a fund request", "Finance"),
    "fund_request.disburse": _A("Disbursed funds", "Finance"),
    "weekly_fund_request.return_by_accountant": _A(
        "Returned a weekly fund request", "Finance"
    ),
    "advance_request.approve_accountability": _A(
        "Reconciled accountability", "Finance"
    ),
    "finance.partner_paid": _A("Paid a partner", "Finance"),
    "reimbursement_receipt_confirmed": _A("Paid a reimbursement", "Finance"),
    "transport_payment.paid": _A("Paid transport", "Finance"),
    # ── People (HR) ──
    "leave.approved": _A("Approved leave", "Leave"),
    "leave.rejected": _A("Declined leave", "Leave"),
    "leave.returned": _A("Returned a leave request", "Leave"),
    "hr.probation_confirmed": _A("Confirmed a probation", "HR"),
    "hr.offboarding_completed": _A("Completed an offboarding", "HR"),
    "hr.candidate_hired": _A("Hired a candidate", "HR"),
    "hr.coverage_granted": _A("Granted cover", "Leave"),
    "hr.performance_agreement_drafted": _A(
        "Drafted a performance agreement", "Performance"
    ),
    "documents.published": _A("Published a policy or document", "Documents"),
    "pd_supervisor_approve": _A(
        "Approved a development request", "Professional Development"
    ),
    "pd_hr_return": _A("Returned a development request", "Professional Development"),
    # ── Business Transformation ──
    "bt.loan.impact_verified": _A(
        "Verified a loan's impact", "Business Transformation", True
    ),
    "bt.loan.amendment_approved": _A(
        "Approved a loan amendment", "Business Transformation", True
    ),
    "bt.loan.repayment_posted": _A(
        "Posted a loan repayment", "Business Transformation", True
    ),
    "bt.ssa_recommendations_created": _A(
        "Created SSA recommendations", "Business Transformation", True
    ),
}

# A request the platform refused to complete for the person: counted as a
# failed action (repeated failures suggest friction or a training need).
FAILED_REQUEST_ACTIONS = ("request_failed",)

# Audit subjects that are a school, or name one.
SCHOOL_SUBJECTS = {"school", "School"}
ACTIVITY_SUBJECTS = {"Activity", "activity"}


def definition(action: str) -> ActionDefinition | None:
    return MEANINGFUL_ACTIONS.get(action)


def record_link(subject_kind: str | None, subject_id: str | None) -> str:
    """The page a timeline row opens, for the subjects that have one. Links a
    reader's role cannot open are stripped by ForbiddenLinksMiddleware."""
    if not subject_id:
        return ""
    if subject_kind in SCHOOL_SUBJECTS:
        return f"/schools/{subject_id}"
    if subject_kind in ACTIVITY_SUBJECTS:
        return f"/activities/{subject_id}"
    return ""
