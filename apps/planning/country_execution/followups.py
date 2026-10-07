"""ExecutionFollowUpService — "Follow Up with PL" for work that has not happened.

The same governed record, workflow and rules as planning follow-ups
(apps.planning.country_oversight.followups), on ``module="execution"``:

* The Country Director asks the Programme Lead — never the CCEO directly. One
  open follow-up per condition (financial year, period, Lead, CCEO, Partner,
  issue, activity); asking again reminds on the same record and keeps the
  instruction history.
* Asking writes the follow-up, the Lead's notification and an audit event. It
  changes no activity, plan, target or achievement.
* The Lead answers through Team Oversight: acknowledges, says what the gap
  waits on (a team member, a Partner, an external dependency), or returns it
  for clarification.
* It closes itself when the condition clears — the activity starts, evidence
  is submitted, the review is done, the slot is verified — re-read through the
  same execution fold the page counts with. "Other" asks close by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.planning.country_oversight import followups as planning_fu
from apps.planning.followup_models import (
    OPEN_FOLLOW_UP_STATES,
    FollowUpModule,
    FollowUpStatus,
    PlanningOversightFollowUp,
)
from apps.schools.lifecycle_service import active_schools

logger = logging.getLogger(__name__)

FollowUpError = planning_fu.FollowUpError


@dataclass(frozen=True)
class ExecIssue:
    key: str
    label: str
    # What measures the gap: an execution tally figure, or "slots_visit" /
    # "slots_training" for required-slot completion.
    figure: str
    stage: str
    owner: str
    resolution_rule: str = "metric_zero"
    team_action: str | None = None
    todo_verb: str = "Follow Up with CCEO on Execution Gap"


EXEC_ISSUES: dict[str, ExecIssue] = {
    issue.key: issue
    for issue in (
        ExecIssue(
            "exec_not_started",
            "Activity Not Started",
            "od_execution",
            "scheduled",
            "staff",
        ),
        ExecIssue(
            "exec_evidence_overdue",
            "Evidence Submission Overdue",
            "od_evidence",
            "in_field",
            "staff",
        ),
        ExecIssue(
            "exec_pl_review_backlog",
            "PL Review Backlog",
            "od_pl_review",
            "pl_review",
            "pl",
            todo_verb="Clear the PL Review Backlog",
        ),
        ExecIssue("exec_team_gap", "Team Execution Gap", "overdue", "", "staff"),
        ExecIssue(
            "exec_partner_gap",
            "Partner Execution Gap",
            "own_partner",
            "",
            "partner",
            todo_verb="Follow Up the Partner's Execution",
        ),
        ExecIssue(
            "exec_visit_slot_gap",
            "Visit-Slot Completion Gap",
            "slots_visit",
            "",
            "staff",
        ),
        ExecIssue(
            "exec_training_slot_gap",
            "Training-Slot Completion Gap",
            "slots_training",
            "",
            "staff",
        ),
        ExecIssue(
            "exec_carryover",
            "Carryover Requires Resolution",
            "carried_forward",
            "",
            "staff",
            resolution_rule="manual",
        ),
        ExecIssue(
            "exec_returned",
            "Returned Activity Requires Support",
            "returned",
            "returned",
            "staff",
        ),
        ExecIssue(
            "exec_other",
            "Other Approved Execution Follow-Up",
            "overdue",
            "",
            "",
            resolution_rule="manual",
        ),
    )
}

#: The waits a Lead can name on an execution follow-up (spec §19).
WAITING_STATES = {
    "team_member": FollowUpStatus.WAITING_FOR_TEAM_MEMBER,
    "partner": FollowUpStatus.WAITING_FOR_PARTNER,
    "external": FollowUpStatus.WAITING_FOR_EXTERNAL,
}


def issue_of(issue_type: str):
    """The issue a follow-up names, from either catalogue."""
    return EXEC_ISSUES.get(issue_type) or planning_fu.ISSUES.get(issue_type)


# ── Scope and evaluation ─────────────────────────────────────────────────────
@dataclass
class ExecScope:
    fy: str
    period_type: str
    period_start: date
    period_end: date
    lead_key: str
    cceo_key: str = ""
    partner_key: str = ""
    activity_id: str = ""
    country: str = ""

    @property
    def window(self):
        return planning_fu.Scope(
            fy=self.fy,
            period_type=self.period_type,
            period_start=self.period_start,
            period_end=self.period_end,
            lead_key=self.lead_key,
        ).window

    @classmethod
    def of(cls, followup) -> "ExecScope":
        return cls(
            fy=followup.fy,
            period_type=followup.period_type,
            period_start=followup.period_start,
            period_end=followup.period_end,
            lead_key=followup.program_lead_staff_id,
            cceo_key=followup.cceo_staff_id or "",
            partner_key=followup.partner_id or "",
            activity_id=followup.activity_id or "",
            country=followup.country,
        )

    def filters(self):
        from apps.planning.country_execution.service import ExecFilters

        window = self.window
        return ExecFilters(
            fy=self.fy,
            period=window.period,
            quarter=window.quarter or "",
            month=window.month,
            week=window.start.strftime("%G-W%V") if window.period == "week" else "",
            program_lead=self.lead_key,
            cceo=self.cceo_key,
            partner=self.partner_key,
        )


def condition_key(scope: ExecScope, issue_key: str) -> str:
    return (
        f"cpx|{scope.fy}|{scope.period_type}:{scope.period_start.isoformat()}"
        f"|pl:{scope.lead_key}|cceo:{scope.cceo_key or '-'}"
        f"|partner:{scope.partner_key or '-'}|issue:{issue_key}"
        f"|activity:{scope.activity_id or '-'}"
    )


def evaluate(scope: ExecScope, *, datasets: dict | None = None) -> dict:
    """The live figures for a scope: the execution tally, the affected records
    and required-slot completion, read through the page's own fold."""
    from apps.planning.country_execution import dataset as ds
    from apps.planning.country_execution.service import filtered_records, fold
    from apps.planning.country_oversight.service import system_scope

    window = scope.window
    memo = (scope.country, window.cache_part)
    dataset = datasets.get(memo) if datasets is not None else None
    if dataset is None:
        dataset = ds.build(system_scope(scope.country), window)
        if datasets is not None:
            datasets[memo] = dataset
    filters = scope.filters()
    tree = fold(dataset, filters)
    records = [
        r
        for r in filtered_records(dataset, filters)
        if not scope.activity_id or r.id == scope.activity_id
    ]
    return {"dataset": dataset, "tree": tree, "records": records, "filters": filters}


def metric(issue: ExecIssue, scope: ExecScope, figures: dict) -> int:
    """How much of the gap is still open."""
    records = figures["records"]
    if scope.activity_id:
        record = records[0] if records else None
        if record is None or record.cancelled:
            return 0
        return 1 if _record_open(issue, record) else 0
    if issue.figure in ("slots_visit", "slots_training"):
        return _slots_left(issue.figure, scope)
    return int(getattr(figures["tree"].country, issue.figure, 0) or 0)


def _record_open(issue: ExecIssue, record) -> bool:
    figure = issue.figure
    if figure == "overdue":
        return bool(record.overdue)
    if figure == "own_partner":
        return record.owner == "partner"
    if figure == "returned":
        return record.returned
    if figure.startswith("od_"):
        return record.overdue == figure[3:]
    return bool(record.overdue)


def _slots_left(figure: str, scope: ExecScope) -> int:
    from apps.planning.country_oversight.service import (
        build_dataset,
        fold,
        system_scope,
    )
    from apps.planning.country_oversight.followups import _portfolio_owner_ids

    filters = scope.filters().planning()
    base = active_schools().filter(
        account_owner_id__in=_portfolio_owner_ids(
            planning_fu.Scope(
                fy=scope.fy,
                period_type=scope.period_type,
                period_start=scope.period_start,
                period_end=scope.period_end,
                lead_key=scope.lead_key,
                cceo_key=scope.cceo_key,
            )
        )
    )
    dataset = build_dataset(system_scope(scope.country), filters.window, base=base)
    tally = fold(dataset, filters).country
    if figure == "slots_visit":
        return max(0, tally.visit_slots - tally.staff_verified - tally.partner_verified)
    return max(0, tally.training_slots - tally.training_verified)


# ── Asking ───────────────────────────────────────────────────────────────────
def send_follow_up(
    *,
    sender,
    scope: ExecScope,
    issue_key: str,
    instruction: str,
    due_date: date | None,
    priority: str,
) -> tuple[PlanningOversightFollowUp, bool]:
    """Create the execution follow-up, or remind on the open one. (row, created)."""
    if not planning_fu.may_follow_up(sender):
        raise FollowUpError(
            "Following up with a Programme Lead from Country Oversight belongs to "
            "the Country Director."
        )
    issue = EXEC_ISSUES.get(issue_key)
    if issue is None:
        raise FollowUpError("Choose what kind of follow-up this is.")
    instruction = (instruction or "").strip()
    if not instruction:
        raise FollowUpError("Write the instruction for the Programme Lead.")
    if due_date is None:
        raise FollowUpError("Give the follow-up a due date.")
    if due_date < timezone.localdate():
        raise FollowUpError("The due date cannot be in the past.")
    if priority not in {value for value, _ in planning_fu.PRIORITY_CHOICES}:
        raise FollowUpError("Choose a priority.")
    lead = planning_fu._lead(scope.lead_key)
    if lead is None or not lead.user_id:
        raise FollowUpError(
            "This work has no Programme Lead on record, so there is nobody to "
            "follow up with. Place the officer under a Programme Lead first."
        )
    if (getattr(lead.user, "active_role", "") or "") != "Program Lead":
        raise FollowUpError(f"{lead.user.name} is not a Programme Lead.")

    figures = evaluate(scope)
    open_now = metric(issue, scope, figures)
    if issue.resolution_rule == "metric_zero" and open_now <= 0:
        raise FollowUpError(
            f"There is no {issue.label.lower()} in this scope right now, so there "
            "is nothing to follow up."
        )
    tally = figures["tree"].country
    records = [
        r for r in figures["records"] if r.overdue or r.returned or r.finance_open
    ]
    oldest = max((r.age for r in records), default=0)
    dataset = figures["dataset"]
    key = condition_key(scope, issue_key)
    now = timezone.now()
    entry = {
        "at": now.isoformat(),
        "by": getattr(sender, "id", ""),
        "name": getattr(sender, "name", "") or "Country Director",
        "instruction": instruction,
        "priority": priority,
        "due": due_date.isoformat(),
        "open": open_now,
    }
    school_ids = sorted({r.school_id for r in records if r.school_id})[:500]

    with transaction.atomic():
        existing = (
            PlanningOversightFollowUp.objects.select_for_update()
            .filter(condition_key=key, status__in=OPEN_FOLLOW_UP_STATES)
            .first()
        )
        if existing is not None:
            existing.instruction = instruction
            existing.instruction_history = list(existing.instruction_history or []) + [
                entry
            ]
            existing.reminder_count += 1
            existing.last_reminder_at = now
            existing.priority = priority
            existing.due_date = due_date
            existing.remaining_value = open_now
            existing.live_remaining, existing.live_checked_at = open_now, now
            existing.days_overdue = oldest
            if existing.status == FollowUpStatus.RETURNED_FOR_CLARIFICATION:
                existing.status = FollowUpStatus.SENT_TO_PL
                existing.returned_reason = ""
            planning_fu._history(existing, sender, "reminded", instruction)
            existing.save()
            planning_fu._notify_lead(
                existing,
                title=f"Reminder: {issue.label}",
                body=_lead_body(existing, issue, reminder=True),
                event="planning_followup_assigned",
            )
            planning_fu._audit(
                "reminded",
                existing,
                sender,
                module="execution",
                reminder_count=existing.reminder_count,
            )
            return existing, False

        owner = dataset.owners.get(scope.cceo_key) if scope.cceo_key else None
        record = (
            figures["records"][0] if scope.activity_id and figures["records"] else None
        )
        window = scope.window
        try:
            followup = PlanningOversightFollowUp.objects.create(
                module=FollowUpModule.EXECUTION,
                fy=scope.fy,
                period_type=scope.period_type,
                period_start=scope.period_start,
                period_end=scope.period_end,
                period_label=window.label,
                country=scope.country,
                program_lead_staff_id=lead.id,
                program_lead_user_id=lead.user_id,
                program_lead_name=lead.user.name or lead.user.email,
                cceo_staff_id=scope.cceo_key or None,
                cceo_name=owner.name if owner else "",
                partner_id=scope.partner_key or None,
                partner_name=dataset.partner_names.get(scope.partner_key, "")
                if scope.partner_key
                else "",
                activity_id=scope.activity_id or None,
                activity_label=(
                    f"{dataset.type_labels.get(record.activity_type, record.activity_type)} · due {record.due:%-d %b %Y}"
                    if record is not None and record.due
                    else ""
                ),
                stage=issue.stage or (record.stage if record is not None else ""),
                blocker_owner=issue.owner,
                days_overdue=oldest,
                condition_key=key,
                issue_type=issue.key,
                metric_key=issue.figure,
                required_value=tally.due,
                planned_value=tally.verified,
                remaining_value=open_now,
                affected_school_ids=school_ids,
                affected_count=len(school_ids),
                snapshot={
                    "due": tally.due,
                    "started": tally.started,
                    "executed": tally.executed,
                    "verified": tally.verified,
                    "closed": tally.closed,
                    "overdue": tally.overdue,
                    "open": open_now,
                    "as_of": dataset.today.isoformat(),
                },
                resolution_rule=issue.resolution_rule,
                live_remaining=open_now,
                live_checked_at=now,
                priority=priority,
                instruction=instruction,
                instruction_history=[entry],
                assigned_by_id=getattr(sender, "id", ""),
                assigned_by_role=getattr(sender, "active_role", "") or "",
                assigned_by_name=getattr(sender, "name", "") or "",
                assigned_at=now,
                due_date=due_date,
                status=FollowUpStatus.SENT_TO_PL,
            )
        except IntegrityError as exc:
            raise FollowUpError(
                "Someone has just sent this same follow-up. It is on the list."
            ) from exc
        planning_fu._history(followup, sender, "sent", instruction)
        followup.save(update_fields=["history", "updated_at"])
        planning_fu._notify_lead(
            followup,
            title=f"Follow up: {issue.label}",
            body=_lead_body(followup, issue),
            event="planning_followup_assigned",
        )
        planning_fu._audit(
            "sent",
            followup,
            sender,
            module="execution",
            open=open_now,
            due=due_date.isoformat(),
            priority=priority,
            stage=followup.stage,
        )
    return followup, True


def _lead_body(followup, issue: ExecIssue, *, reminder: bool = False) -> str:
    who = followup.assigned_by_name or "The Country Director"
    subject = (
        followup.activity_label
        or followup.partner_name
        or followup.cceo_name
        or "your team"
    )
    verb = "reminded you to follow up" if reminder else "asked you to follow up"
    return (
        f"{who} {verb} with {subject} on the {issue.label.lower()} "
        f"({followup.remaining_value:,} open, {followup.period_label}). "
        f"Due {followup.due_date:%-d %b}. “{followup.instruction}”"
    )


def mark_waiting_on(followup, actor, waiting_on: str, note: str):
    """The Lead names what an execution follow-up now waits on (spec §19)."""
    planning_fu._must_be_lead(followup, actor)
    status = WAITING_STATES.get(waiting_on)
    if status is None:
        return planning_fu.mark_waiting(followup, actor, note)
    note = (note or "").strip()
    if not note:
        raise FollowUpError("Say what the work is waiting on.")
    followup.status = status
    followup.linked_note = note
    followup.acknowledged_at = followup.acknowledged_at or timezone.now()
    planning_fu._history(followup, actor, f"waiting_{waiting_on}", note)
    followup.save()
    planning_fu._audit("waiting", followup, actor, waiting_on=waiting_on, note=note)
    return followup


# ── Closing the loop ─────────────────────────────────────────────────────────
def refresh(followup, *, datasets: dict | None = None) -> bool:
    """Re-read the condition; close the follow-up when it has cleared."""
    if not followup.is_open:
        return False
    issue = EXEC_ISSUES.get(followup.issue_type)
    if issue is None:
        return False
    scope = ExecScope.of(followup)
    open_now = metric(issue, scope, evaluate(scope, datasets=datasets))
    now = timezone.now()
    followup.live_remaining = open_now
    followup.live_checked_at = now
    if issue.resolution_rule == "metric_zero" and open_now <= 0:
        followup.status = FollowUpStatus.RESOLVED_AUTOMATICALLY
        followup.resolved_at = now
        followup.resolved_by_system = True
        planning_fu._history(followup, None, "resolved", "The condition cleared.")
        followup.save()
        planning_fu._resolve_lead_notifications(followup)
        planning_fu._notify(
            followup.assigned_by_id,
            followup,
            title=f"Follow-up resolved: {issue.label}",
            body=(
                f"The {issue.label.lower()} for "
                f"{followup.activity_label or followup.partner_name or followup.cceo_name or followup.program_lead_name} "
                "has cleared, so the follow-up closed itself."
            ),
            event="planning_followup_resolved",
            route="/country-planning-oversight/?view=execution",
        )
        planning_fu._audit("auto_resolved", followup, None, module="execution")
        return True
    followup.save(update_fields=["live_remaining", "live_checked_at", "updated_at"])
    return False


def open_counts(fy: str) -> dict:
    """Open execution follow-ups per Lead and per officer, for the table."""
    return planning_fu.open_counts(fy, module=FollowUpModule.EXECUTION)


class ExecutionFollowUpService:
    """The execution follow-up workflow, as one importable surface."""

    issues = EXEC_ISSUES
    send = staticmethod(send_follow_up)
    mark_waiting_on = staticmethod(mark_waiting_on)
    refresh = staticmethod(refresh)
    evaluate = staticmethod(evaluate)
    open_counts = staticmethod(open_counts)
