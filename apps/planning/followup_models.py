"""PlanningOversightFollowUp — the Country Director's "Follow Up with PL".

Country Planning Oversight is a reading surface. Its one workflow action asks a
Programme Lead to follow up a planning gap with their CCEO — the CD does not
reach past the Lead to the officer, and asking changes no plan, target,
activity or portfolio. This row is that ask: a governed, auditable record of
who asked whom about which gap, with the figures as they stood, and where the
matter now is.

It sits beside TeamAction rather than inside it because the gaps it names are
usually not one school's: "Karamoja's CCEO has 214 Partner slots nobody holds"
is a condition of a portfolio. When the Lead acts on it at school level they
do so through TeamAction, the platform's existing school-action workflow, and
the actions they send are linked here.

**The condition key.** Financial year, period, Lead, CCEO, issue and school or
scope — the identity of the gap, not of the message. A partial unique index
allows one open follow-up per condition, so the CD asking again reminds the
Lead on the same record instead of opening a second one.

**Resolution is observed.** A follow-up whose metric reaches zero closes by
itself (``RESOLVED_AUTOMATICALLY``), because the Lead should not have to mark a
system-derived gap complete. The To-Do the Lead sees is derived from this row's
state, so it closes with it.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class FollowUpStatus(models.TextChoices):
    SENT_TO_PL = "sent_to_pl", "Sent to PL"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    ACTION_LINKED = "action_linked", "Action Linked"
    WAITING_FOR_RESOLUTION = "waiting_for_resolution", "Waiting for Resolution"
    RESOLVED_AUTOMATICALLY = "resolved_automatically", "Resolved Automatically"
    CLOSED_BY_CD = "closed_by_cd", "Closed by CD with Reason"
    RETURNED_FOR_CLARIFICATION = (
        "returned_for_clarification",
        "Returned for Clarification",
    )
    CANCELLED = "cancelled", "Canceled"
    # Execution follow-ups (spec 2026-09-28 §19): what the Lead says the gap
    # now waits on, and a Director's escalation.
    WAITING_FOR_TEAM_MEMBER = "waiting_for_team_member", "Waiting for Team Member"
    WAITING_FOR_PARTNER = "waiting_for_partner", "Waiting for Partner"
    WAITING_FOR_EXTERNAL = "waiting_for_external", "Waiting for External Dependency"
    ESCALATED = "escalated", "Escalated"


class FollowUpModule(models.TextChoices):
    """Which Country Oversight stage asked: the plan, or its execution."""

    PLANNING = "planning", "Planning"
    EXECUTION = "execution", "Execution & Completion"


#: Still somebody's to act on. RETURNED_FOR_CLARIFICATION is open — it is the
#: Country Director's turn — so a second ask about the same gap reaches the
#: same record rather than starting another.
OPEN_FOLLOW_UP_STATES = frozenset(
    {
        FollowUpStatus.SENT_TO_PL,
        FollowUpStatus.ACKNOWLEDGED,
        FollowUpStatus.ACTION_LINKED,
        FollowUpStatus.WAITING_FOR_RESOLUTION,
        FollowUpStatus.RETURNED_FOR_CLARIFICATION,
        FollowUpStatus.WAITING_FOR_TEAM_MEMBER,
        FollowUpStatus.WAITING_FOR_PARTNER,
        FollowUpStatus.WAITING_FOR_EXTERNAL,
        FollowUpStatus.ESCALATED,
    }
)

#: The Programme Lead still has to do something: these carry the Lead's To-Do.
PL_TODO_STATES = frozenset(
    {FollowUpStatus.SENT_TO_PL, FollowUpStatus.ACKNOWLEDGED, FollowUpStatus.ESCALATED}
)

CLOSED_FOLLOW_UP_STATES = frozenset(
    {
        FollowUpStatus.RESOLVED_AUTOMATICALLY,
        FollowUpStatus.CLOSED_BY_CD,
        FollowUpStatus.CANCELLED,
    }
)


class FollowUpPriority(models.TextChoices):
    NORMAL = "normal", "Normal"
    ATTENTION = "attention", "Attention"
    HIGH = "high", "High"
    CRITICAL = "critical", "Critical"


class PlanningOversightFollowUp(TimeStampedModel):
    id = CuidField()

    # ── The period ──────────────────────────────────────────────────────────
    fy = models.CharField(max_length=16, db_index=True)
    period_type = models.CharField(max_length=16, default="fy")
    period_start = models.DateField()
    period_end = models.DateField()
    period_label = models.CharField(max_length=64, blank=True, default="")

    # ── Where ───────────────────────────────────────────────────────────────
    country = models.CharField(max_length=64, blank=True, default="")
    region_id = models.CharField(max_length=30, null=True, blank=True)
    region_name = models.CharField(max_length=255, blank=True, default="")

    # ── Who ─────────────────────────────────────────────────────────────────
    # The Programme Lead the ask is assigned to, in both id spaces: the staff
    # profile names them in the hierarchy, the user id is who is notified and
    # whose To-Do it becomes.
    program_lead_staff_id = models.CharField(max_length=30, db_index=True)
    program_lead_user_id = models.CharField(max_length=30, db_index=True)
    program_lead_name = models.CharField(max_length=255, blank=True, default="")
    # The officer whose gap it is, when it is one officer's. Never notified by
    # this record: the Lead decides how to follow up with them.
    cceo_staff_id = models.CharField(max_length=30, null=True, blank=True)
    cceo_name = models.CharField(max_length=255, blank=True, default="")
    school_id = models.CharField(max_length=30, null=True, blank=True)
    school_name = models.CharField(max_length=512, blank=True, default="")
    # Execution follow-ups: the stage and the record or Partner they name.
    module = models.CharField(
        max_length=16,
        choices=FollowUpModule.choices,
        default=FollowUpModule.PLANNING,
        db_index=True,
    )
    activity_id = models.CharField(max_length=30, null=True, blank=True)
    activity_label = models.CharField(max_length=512, blank=True, default="")
    partner_id = models.CharField(max_length=30, null=True, blank=True)
    partner_name = models.CharField(max_length=255, blank=True, default="")
    stage = models.CharField(max_length=32, blank=True, default="")
    blocker_owner = models.CharField(max_length=32, blank=True, default="")
    days_overdue = models.IntegerField(null=True, blank=True)

    # ── What ────────────────────────────────────────────────────────────────
    condition_key = models.CharField(max_length=255, db_index=True)
    issue_type = models.CharField(max_length=48)
    metric_key = models.CharField(max_length=64)
    required_value = models.IntegerField(default=0)
    planned_value = models.IntegerField(default=0)
    remaining_value = models.IntegerField(default=0)
    affected_school_ids = models.JSONField(default=list, blank=True)
    affected_count = models.IntegerField(default=0)
    # The figures and filters as the Country Director saw them, and the policy
    # version they were computed under.
    snapshot = models.JSONField(default=dict, blank=True)
    # Which rule settles it ("metric_zero" for every system-verifiable issue;
    # "manual" where only a person can say it is done).
    resolution_rule = models.CharField(max_length=32, default="metric_zero")
    live_remaining = models.IntegerField(null=True, blank=True)
    live_checked_at = models.DateTimeField(null=True, blank=True)

    # ── The ask ─────────────────────────────────────────────────────────────
    priority = models.CharField(
        max_length=16,
        choices=FollowUpPriority.choices,
        default=FollowUpPriority.NORMAL,
    )
    instruction = models.TextField()
    # Every instruction the CD has given on this record, oldest first — a
    # reminder adds to it and never overwrites what was asked before.
    instruction_history = models.JSONField(default=list, blank=True)
    assigned_by_id = models.CharField(max_length=30)
    assigned_by_role = models.CharField(max_length=64, blank=True, default="")
    assigned_by_name = models.CharField(max_length=255, blank=True, default="")
    assigned_at = models.DateTimeField()
    due_date = models.DateField()

    # ── State ───────────────────────────────────────────────────────────────
    status = models.CharField(
        max_length=32,
        choices=FollowUpStatus.choices,
        default=FollowUpStatus.SENT_TO_PL,
        db_index=True,
    )
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    action_linked_at = models.DateTimeField(null=True, blank=True)
    # TeamActions the Lead sent their CCEO from this follow-up.
    linked_team_action_ids = models.JSONField(default=list, blank=True)
    linked_note = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by_system = models.BooleanField(default=False)
    resolution_note = models.TextField(blank=True, default="")
    closed_by_id = models.CharField(max_length=30, blank=True, default="")
    returned_reason = models.TextField(blank=True, default="")
    returned_at = models.DateTimeField(null=True, blank=True)
    reminder_count = models.IntegerField(default=0)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    # What happened to the record, in order, for the page to show; the audit
    # chain holds the tamper-evident copy.
    history = models.JSONField(default=list, blank=True)

    class Meta:
        app_label = "planning"
        db_table = "planning_oversight_follow_up"
        ordering = ["-assigned_at"]
        indexes = [
            models.Index(
                fields=["program_lead_user_id", "status"],
                name="idx_cpofu_lead_status",
            ),
            models.Index(fields=["fy", "status"], name="idx_cpofu_fy_status"),
            models.Index(fields=["status", "due_date"], name="idx_cpofu_status_due"),
            models.Index(
                fields=["cceo_staff_id", "status"], name="idx_cpofu_cceo_status"
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["condition_key"],
                condition=models.Q(
                    status__in=[
                        FollowUpStatus.SENT_TO_PL,
                        FollowUpStatus.ACKNOWLEDGED,
                        FollowUpStatus.ACTION_LINKED,
                        FollowUpStatus.WAITING_FOR_RESOLUTION,
                        FollowUpStatus.RETURNED_FOR_CLARIFICATION,
                        FollowUpStatus.WAITING_FOR_TEAM_MEMBER,
                        FollowUpStatus.WAITING_FOR_PARTNER,
                        FollowUpStatus.WAITING_FOR_EXTERNAL,
                        FollowUpStatus.ESCALATED,
                    ]
                ),
                name="uniq_open_cpo_followup_per_condition",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.issue_type} → {self.program_lead_name} ({self.status})"

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_FOLLOW_UP_STATES

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone

        return bool(
            self.is_open and self.due_date and self.due_date < timezone.localdate()
        )
