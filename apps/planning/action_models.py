"""TeamAction — the accountable record behind "Send to <staff>".

Before this existed, delegating an urgent school created one Notification and
nothing else. A notification is an event, not a responsibility: it can be read
and dismissed, it carries no due date, no state, no owner history, and nothing
downstream can ask "is anyone acting on this school?". So the school stayed on
Schools Needing Urgent Attention after it had been assigned, the queue never
drained, and genuinely unattended schools could not rise to the top.

A TeamAction is the missing noun. It says: *this* condition, at *this* school,
is owned by *this* person, due *then*, and here is its state.

Two ideas carry most of the design.

**The condition key.** One school can need several different things, and the
same need can recur across years. `condition_key` identifies the *condition*,
not the school — school + issue + FY + the related record where one exists.
Deduplication, To-Do derivation, resolution and recurrence all key off it, so
"has this already been assigned?" is one indexed lookup rather than a
heuristic. Two distinct issues at one school are two actions; the same issue
twice is one.

**Resolution is observed, not asserted.** A TeamAction for `no_ssa` closes when
a confirmed current-FY SsaRecord exists — not when somebody presses a button.
`resolve_due_actions` re-reads the source condition and closes what is genuinely
done, which is why `RESOLVED` is a state the system reaches rather than one a
user sets. `manual_resolution_reason` exists only for the conditions no query
can settle, and is deliberately awkward to use.

The To-Do is derived from this row rather than stored beside it. Every other
To-Do on this platform is computed at read time from workflow state
(apps/command_center/todo_service.py), which is what makes them auto-closing.
Storing a second one here would need its own sync to disappear on resolution —
reintroducing exactly the drift the derived design avoids.
"""

from __future__ import annotations

from django.db import models

from apps.core.models import CuidField, TimeStampedModel


class ActionState(models.TextChoices):
    """Lifecycle. OPEN..ESCALATED are all *active* — see ACTIVE_STATES.

    ACKNOWLEDGED and IN_PROGRESS deliberately do not resolve anything: a
    recipient saying "I have seen this" or "I have started" changes who is
    waiting on whom, not whether the school still has the problem.
    """

    OPEN = "open", "Open"
    ACKNOWLEDGED = "acknowledged", "Acknowledged"
    IN_PROGRESS = "in_progress", "In progress"
    BLOCKED = "blocked", "Blocked"
    OVERDUE = "overdue", "Overdue"
    ESCALATED = "escalated", "Escalated"
    RESOLVED = "resolved", "Resolved"
    RETURNED = "returned", "Returned to sender"
    CANCELLED = "cancelled", "Cancelled"


# States that mean "somebody owns this right now", and therefore that the
# school must NOT reappear on the unassigned urgent card. OVERDUE and ESCALATED
# are included on purpose: an overdue action has an owner and a history, and
# returning it to the front page as though nobody had acted would erase that.
ACTIVE_STATES = frozenset(
    {
        ActionState.OPEN,
        ActionState.ACKNOWLEDGED,
        ActionState.IN_PROGRESS,
        ActionState.BLOCKED,
        ActionState.OVERDUE,
        ActionState.ESCALATED,
    }
)

# States that release the condition back to the unassigned queue when the
# underlying problem is still there. RESOLVED is absent — a resolved action
# means the condition is gone, and if it returns that is a new occurrence with
# its own detected-at date, not a reopening of history.
RELEASING_STATES = frozenset({ActionState.RETURNED, ActionState.CANCELLED})


class ActionPriority(models.TextChoices):
    URGENT = "urgent", "Urgent"
    HIGH = "high", "High"
    NORMAL = "normal", "Normal"


class TeamAction(TimeStampedModel):
    id = CuidField()

    # ── What ────────────────────────────────────────────────────────────────
    # The identity of the CONDITION, not of the school. Indexed and paired with
    # a partial unique constraint below so a second active action for the same
    # condition cannot exist — which is what stops PL and IA both sending, and
    # what makes a repeated click idempotent rather than duplicating.
    condition_key = models.CharField(max_length=255, db_index=True)
    issue_type = models.CharField(max_length=64)
    severity = models.CharField(max_length=32, default="critical")

    school_id = models.CharField(max_length=30, db_index=True)
    fy = models.CharField(max_length=16, db_index=True)
    # The month the condition was surfaced in. The front card is month-scoped,
    # so an action carries the month it came from for the monitoring views to
    # filter by without recomputing.
    month_of_fy = models.IntegerField(null=True, blank=True)

    # Set only where the condition hangs off a specific record — a missing
    # Salesforce id belongs to one Activity, a missing SSA belongs to none.
    related_activity_id = models.CharField(max_length=30, null=True, blank=True)
    related_ssa_id = models.CharField(max_length=30, null=True, blank=True)

    # ── Who ─────────────────────────────────────────────────────────────────
    sender_id = models.CharField(max_length=30, db_index=True)
    sender_role = models.CharField(max_length=64)
    # A TeamAction without a recipient is not a responsibility, so this is not
    # nullable. The send path refuses rather than creating an ownerless row.
    recipient_id = models.CharField(max_length=30, db_index=True)
    recipient_role = models.CharField(max_length=64)

    # ── The ask ─────────────────────────────────────────────────────────────
    requested_action = models.CharField(max_length=255)
    # Where the recipient has to go to actually do it. A responsibility without
    # a route is a request to go hunting.
    workflow_route = models.CharField(max_length=512)
    message = models.TextField(blank=True, default="")
    priority = models.CharField(
        max_length=16, choices=ActionPriority.choices, default=ActionPriority.URGENT
    )
    due_date = models.DateField(null=True, blank=True)

    # ── State ───────────────────────────────────────────────────────────────
    state = models.CharField(
        max_length=32,
        choices=ActionState.choices,
        default=ActionState.OPEN,
        db_index=True,
    )
    detected_at = models.DateTimeField()
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    blocked_reason = models.TextField(blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Set when the system observed the source condition clear. Left empty on a
    # manual close, which is how System Health tells the two apart.
    resolved_by_system = models.BooleanField(default=False)
    manual_resolution_reason = models.TextField(blank=True, default="")
    returned_reason = models.TextField(blank=True, default="")

    # ── Follow-up ───────────────────────────────────────────────────────────
    reminder_count = models.IntegerField(default=0)
    last_reminder_at = models.DateTimeField(null=True, blank=True)
    escalated_at = models.DateTimeField(null=True, blank=True)
    escalated_to_id = models.CharField(max_length=30, null=True, blank=True)
    # Links a genuine recurrence back to the action that closed last time, so
    # "this school keeps needing the same thing" is answerable without
    # reopening a historical record and destroying its dates.
    supersedes_id = models.CharField(max_length=30, null=True, blank=True)

    class Meta:
        # Explicit because this module sits outside models.py: importing it
        # directly (as the services and tests do) would otherwise fail to
        # infer the app from the import path.
        app_label = "planning"
        db_table = "team_action"
        indexes = [
            # The front-card exclusion query: "is there an active action for
            # any of these condition keys?"
            models.Index(
                fields=["condition_key", "state"], name="idx_teamaction_cond_state"
            ),
            # "What have I been sent?" and "what did I send?"
            models.Index(
                fields=["recipient_id", "state"], name="idx_teamaction_recip_state"
            ),
            models.Index(
                fields=["sender_id", "state"], name="idx_teamaction_sender_state"
            ),
            # The overdue sweep.
            models.Index(fields=["state", "due_date"], name="idx_teamaction_state_due"),
        ]
        constraints = [
            # One active owner per condition, enforced by the database rather
            # than by remembering to check. Resolved, returned and cancelled
            # rows are excluded so history accumulates freely and a genuine
            # recurrence can be assigned again.
            models.UniqueConstraint(
                fields=["condition_key"],
                condition=models.Q(
                    state__in=[
                        ActionState.OPEN,
                        ActionState.ACKNOWLEDGED,
                        ActionState.IN_PROGRESS,
                        ActionState.BLOCKED,
                        ActionState.OVERDUE,
                        ActionState.ESCALATED,
                    ]
                ),
                name="uniq_active_action_per_condition",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.issue_type} @ {self.school_id} → {self.recipient_id} ({self.state})"
        )

    @property
    def is_active(self) -> bool:
        return self.state in ACTIVE_STATES

    @property
    def is_overdue(self) -> bool:
        from django.utils import timezone

        return bool(
            self.due_date
            and self.state in ACTIVE_STATES
            and self.state != ActionState.RESOLVED
            and self.due_date < timezone.localdate()
        )
