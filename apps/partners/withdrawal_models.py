"""Taking partner work back — the vocabularies and the durable record.

A withdrawal is a controlled state transition, never a deletion. The
assignment, the activity it became, its cost lines and its evidence are all
history that somebody may later have to answer for, and history that can be
removed is not history.

Three ideas carry most of the weight here.

**Attribution is separate from reason.** "The school was closed" and "the
partner never turned up" both end the same assignment, and counting them the
same way would make a partner's performance record a measure of their bad luck.
Every reason declares who the cause belongs to, and only partner-attributable
ones may reach performance.

**The support slot has one identity.** A replacement assignment points at the
original rather than cloning it, so a school cannot acquire a second
entitlement by having its partner changed. The lineage is the proof.

**Cost belongs to whoever scheduled it.** A replacement carries no cost until
the new partner picks a date, because the price depends on that date and on
that partner's rate. Copying the old cost forward would invent a number nobody
quoted.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class WithdrawalAttribution(models.TextChoices):
    """Whose problem caused this, which is not the same as what happened.

    Performance may only ever read PARTNER. The others exist so that a partner
    who was stood up by a closed school, or handed the wrong school by us, does
    not accumulate a record that reads like failure.
    """

    PARTNER = "partner", "Partner-attributable"
    SCHOOL = "school", "School-attributable"
    EDIFY = "edify", "Edify-attributable"
    EXTERNAL = "external", "External circumstance"


class WithdrawalReason(models.TextChoices):
    """Why the work is being taken back.

    Closed and specific, so a queue of withdrawals can be triaged without
    reading every explanation. Each maps to exactly one attribution in
    REASON_ATTRIBUTION below — the mapping lives in code rather than being
    chosen by the person withdrawing, because someone under pressure to explain
    a delay should not also be the one deciding whether it counts against the
    partner.
    """

    NOT_SCHEDULED = "not_scheduled", "Partner has not scheduled"
    SCHEDULING_DELAY = "scheduling_delay", "Repeated scheduling delay"
    REPEATED_RESCHEDULE = "repeated_reschedule", "Repeated rescheduling"
    CAPACITY = "capacity", "Partner capacity constraint"
    PARTNER_UNAVAILABLE = "partner_unavailable", "Partner unavailable"
    POOR_QUALITY = "poor_quality", "Poor quality of work"
    POOR_EVIDENCE = "poor_evidence", "Poor evidence quality"
    REPEATED_EVIDENCE_RETURN = "repeated_evidence_return", "Repeated evidence return"
    COMMUNICATION = "communication", "Communication breakdown"
    MISSED_DEADLINE = "missed_deadline", "Missed activity deadline"
    CONDUCT = "conduct", "Conduct or integrity concern"
    SAFEGUARDING = "safeguarding", "Safeguarding concern"
    PARTNER_REQUESTED_RELEASE = "partner_requested_release", "Partner requested release"

    SCHOOL_UNAVAILABLE = "school_unavailable", "School unavailable"
    SCHOOL_COMPLAINT = "school_complaint", "School complaint"
    SCHOOL_REQUESTED_CHANGE = "school_requested_change", "School requested a change"

    OUT_OF_SCOPE = "out_of_scope", "Assignment outside partner scope"
    INCORRECT_ASSIGNMENT = "incorrect_assignment", "Incorrect school or activity"
    DUPLICATE_ASSIGNMENT = "duplicate_assignment", "Duplicate assignment"
    SUPPORT_NOT_REQUIRED = "support_not_required", "Support no longer required"
    PROGRAMME_CHANGE = "programme_change", "Project or programme change"
    STRATEGIC_REALLOCATION = "strategic_reallocation", "Strategic reallocation"

    DISTANCE = "distance", "Distance or travel constraint"
    SAFETY = "safety", "Safety or access concern"

    OTHER = "other", "Other documented reason"


#: The one place a reason becomes an attribution. Keyed exhaustively — a reason
#: missing from here raises rather than defaulting, because a silent default
#: would most likely land on PARTNER and quietly blame somebody.
REASON_ATTRIBUTION: dict[str, str] = {
    WithdrawalReason.NOT_SCHEDULED: WithdrawalAttribution.PARTNER,
    WithdrawalReason.SCHEDULING_DELAY: WithdrawalAttribution.PARTNER,
    WithdrawalReason.REPEATED_RESCHEDULE: WithdrawalAttribution.PARTNER,
    WithdrawalReason.CAPACITY: WithdrawalAttribution.PARTNER,
    WithdrawalReason.PARTNER_UNAVAILABLE: WithdrawalAttribution.PARTNER,
    WithdrawalReason.POOR_QUALITY: WithdrawalAttribution.PARTNER,
    WithdrawalReason.POOR_EVIDENCE: WithdrawalAttribution.PARTNER,
    WithdrawalReason.REPEATED_EVIDENCE_RETURN: WithdrawalAttribution.PARTNER,
    WithdrawalReason.COMMUNICATION: WithdrawalAttribution.PARTNER,
    WithdrawalReason.MISSED_DEADLINE: WithdrawalAttribution.PARTNER,
    WithdrawalReason.CONDUCT: WithdrawalAttribution.PARTNER,
    WithdrawalReason.SAFEGUARDING: WithdrawalAttribution.PARTNER,
    # A partner who asks to be released has told us early rather than leaving
    # a school waiting. That is the behaviour we want, so it is not counted as
    # a failure — the withdrawal rate would otherwise punish honesty.
    WithdrawalReason.PARTNER_REQUESTED_RELEASE: WithdrawalAttribution.EXTERNAL,
    WithdrawalReason.SCHOOL_UNAVAILABLE: WithdrawalAttribution.SCHOOL,
    WithdrawalReason.SCHOOL_COMPLAINT: WithdrawalAttribution.SCHOOL,
    WithdrawalReason.SCHOOL_REQUESTED_CHANGE: WithdrawalAttribution.SCHOOL,
    # Our filing error, not theirs.
    WithdrawalReason.OUT_OF_SCOPE: WithdrawalAttribution.EDIFY,
    WithdrawalReason.INCORRECT_ASSIGNMENT: WithdrawalAttribution.EDIFY,
    WithdrawalReason.DUPLICATE_ASSIGNMENT: WithdrawalAttribution.EDIFY,
    WithdrawalReason.SUPPORT_NOT_REQUIRED: WithdrawalAttribution.EDIFY,
    WithdrawalReason.PROGRAMME_CHANGE: WithdrawalAttribution.EDIFY,
    WithdrawalReason.STRATEGIC_REALLOCATION: WithdrawalAttribution.EDIFY,
    WithdrawalReason.DISTANCE: WithdrawalAttribution.EXTERNAL,
    WithdrawalReason.SAFETY: WithdrawalAttribution.EXTERNAL,
    # Unclassifiable by definition. EXTERNAL rather than PARTNER so the
    # catch-all cannot become a quiet way to mark a partner down.
    WithdrawalReason.OTHER: WithdrawalAttribution.EXTERNAL,
}

#: Reasons whose detail must not travel in an ordinary partner notification.
#: The partner is told the work has stopped and who to contact; the substance
#: goes through the restricted route.
RESTRICTED_REASONS = frozenset(
    {WithdrawalReason.SAFEGUARDING, WithdrawalReason.CONDUCT}
)

RESTRICTED_PARTNER_MESSAGE = (
    "This assignment has been withdrawn and is under management review. "
    "Please stop further work and contact the responsible Edify staff member "
    "if clarification is required."
)


class WithdrawalDisposition(models.TextChoices):
    """What happens to the support after the partner lets go of it.

    Required, because a withdrawal that does not say where the school's
    support goes next leaves the school worse off than before anyone
    intervened.
    """

    RETURN_TO_PLANNING = "return_to_planning", "Return to CCEO Planning"
    REASSIGN_PARTNER = "reassign_partner", "Assign to another Partner"
    SCHEDULE_AS_STAFF = "schedule_as_staff", "Schedule as staff"
    HOLD_FOR_REVIEW = "hold_for_review", "Hold for review"
    CANCEL_SUPPORT = "cancel_support", "Cancel support"
    ESCALATE = "escalate", "Escalate to Country Director"


class WithdrawalKind(models.TextChoices):
    """Which controlled workflow this is, decided by the record's state.

    One action on the page, several workflows behind it. A single destructive
    "delete" for every state is how an in-progress visit and an unscheduled
    handover end up treated identically.
    """

    WITHDRAW_UNSCHEDULED = "withdraw_unscheduled", "Withdraw assignment"
    RECALL_SCHEDULED = "recall_scheduled", "Recall scheduled activity"
    SUSPEND_IN_PROGRESS = "suspend_in_progress", "Suspend delivery and review"
    QUALITY_REVIEW = "quality_review", "Withdraw for quality review"
    PAYMENT_HOLD = "payment_hold", "Place payment on hold"
    BLOCKED = "blocked", "Not available in this state"


class WithdrawalState(models.TextChoices):
    """One vocabulary, used identically on every page."""

    REQUESTED = "requested", "Requested"
    UNDER_REVIEW = "under_review", "Under PL review"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    EFFECTIVE = "effective", "Effective"
    SUSPENDED = "suspended", "Suspended pending review"
    REASSIGNED = "reassigned", "Reassigned"
    RETURNED_TO_PLANNING = "returned_to_planning", "Returned to planning"
    CANCELLED = "cancelled", "Cancelled"
    RESOLVED = "resolved", "Resolved"
    ESCALATED = "escalated", "Escalated"


#: States in which the withdrawal is still open and holds the support slot.
OPEN_WITHDRAWAL_STATES = (
    WithdrawalState.REQUESTED,
    WithdrawalState.UNDER_REVIEW,
    WithdrawalState.APPROVED,
    WithdrawalState.SUSPENDED,
)


class PartnerAssignmentWithdrawal(TimeStampedModel):
    """One decision to take work back from a partner, and everything it did.

    A durable record rather than a note on the assignment: a note cannot say
    who decided, what the money did, which slot was released or what replaced
    it, and those are exactly the questions asked months later when a partner
    disputes their performance record or an auditor asks where a budget line
    went.
    """

    id = CuidField()

    assignment = models.ForeignKey(
        "partners.PartnerAssignment",
        on_delete=models.CASCADE,
        related_name="withdrawals",
    )
    # The activity the partner had created, if they had got that far. Kept
    # even after it is cancelled — the point is to be able to find it.
    linked_activity = models.ForeignKey(
        "activities.Activity",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_withdrawals",
    )
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_withdrawals",
    )
    partner = models.ForeignKey(
        "partners.Partner",
        on_delete=models.PROTECT,
        related_name="withdrawals",
    )

    # Who decided, and under which hat.
    requested_by = models.CharField(max_length=30)
    requested_by_role = models.CharField(max_length=48, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    approved_by = models.CharField(max_length=30, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    effective_at = models.DateTimeField(null=True, blank=True)

    # Who was answerable for the work at the moment it was taken back. Copied
    # rather than joined, because supervision changes and the record has to
    # keep saying who it was at the time.
    responsible_cceo_id = models.CharField(max_length=30, null=True, blank=True)
    supervising_pl_id = models.CharField(max_length=30, null=True, blank=True)

    kind = models.CharField(max_length=32, choices=WithdrawalKind.choices)
    state = models.CharField(
        max_length=32,
        choices=WithdrawalState.choices,
        default=WithdrawalState.REQUESTED,
    )

    reason_category = models.CharField(max_length=40, choices=WithdrawalReason.choices)
    # What the partner is told. Written to be shareable.
    partner_facing_reason = models.TextField()
    # What staff need each other to know. Never in a partner notification.
    internal_note = models.TextField(blank=True)
    attribution = models.CharField(max_length=16, choices=WithdrawalAttribution.choices)

    disposition = models.CharField(max_length=32, choices=WithdrawalDisposition.choices)

    # State captured at the moment of withdrawal, so the record still reads
    # correctly after the assignment and activity have moved on.
    assignment_state_at_withdrawal = models.CharField(max_length=32, blank=True)
    activity_state_at_withdrawal = models.CharField(max_length=48, blank=True)
    financial_state_at_withdrawal = models.CharField(max_length=48, blank=True)
    # Whole UGX, matching the rest of the platform outside apps/professional_development.
    original_planned_cost = models.BigIntegerField(default=0)
    # Decided by a completion review, never typed in freehand.
    eligible_partner_cost = models.BigIntegerField(null=True, blank=True)

    # The replacement, when there is one. Nullable because most dispositions
    # return the work to planning rather than to another partner.
    replacement_assignment = models.OneToOneField(
        "partners.PartnerAssignment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replaced_withdrawal",
    )
    budget_amendment = models.ForeignKey(
        "budget.BudgetAmendment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="partner_withdrawals",
    )

    partner_acknowledged_at = models.DateTimeField(null=True, blank=True)
    partner_response = models.TextField(blank=True)

    class Meta:
        db_table = "partner_assignment_withdrawal"
        ordering = ["-requested_at"]
        indexes = [
            models.Index(fields=["assignment", "state"]),
            models.Index(fields=["partner", "attribution"]),
        ]
        constraints = [
            # One open withdrawal per assignment. A double-click, or two
            # supervisors acting on the same row, must produce one decision —
            # two open records would each claim the support slot.
            models.UniqueConstraint(
                fields=["assignment"],
                condition=models.Q(
                    state__in=[
                        "requested",
                        "under_review",
                        "approved",
                        "suspended",
                    ]
                ),
                name="one_open_withdrawal_per_assignment",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} — {self.assignment_id}"

    @property
    def is_open(self) -> bool:
        return self.state in OPEN_WITHDRAWAL_STATES

    @property
    def counts_against_partner(self) -> bool:
        """Only partner-attributable withdrawals may reach performance."""
        return self.attribution == WithdrawalAttribution.PARTNER


class PartnerHold(TimeStampedModel):
    """Stop new assignments reaching a partner, without touching what they hold.

    Deliberately a separate decision from withdrawing any one assignment. One
    broad "suspend partner" button that also cancelled live work is how a
    dozen schools lose support nobody decided to remove — and how a partner
    part-way through a visit finds out mid-delivery.

    So a hold is exactly one thing: no NEW work. Existing assignments continue
    until somebody reviews each on its own merits, and each review is its own
    withdrawal record with its own reason.
    """

    id = CuidField()
    partner = models.ForeignKey(
        "partners.Partner", on_delete=models.CASCADE, related_name="holds"
    )

    reason_category = models.CharField(max_length=40, choices=WithdrawalReason.choices)
    reason = models.TextField()
    # Sensitive detail stays out of anything the partner is shown.
    internal_note = models.TextField(blank=True)

    requested_by = models.CharField(max_length=30)
    requested_by_role = models.CharField(max_length=48, blank=True)
    effective_from = models.DateField()
    # A hold with no review date is a quiet offboarding. Required so somebody
    # has to come back to it rather than letting it lapse into permanence.
    review_on = models.DateField()
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        db_table = "partner_hold"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["partner"],
                condition=models.Q(lifted_at__isnull=True),
                name="one_live_hold_per_partner",
            ),
        ]

    def __str__(self) -> str:
        return f"Hold on {self.partner_id}"

    @property
    def is_live(self) -> bool:
        return self.lifted_at is None
