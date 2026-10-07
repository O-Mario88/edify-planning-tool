"""PlanningOversightFollowUpService — "Follow Up with PL", governed end to end.

The Country Director asks; the Programme Lead acts; the record watches the gap.

* **Asking** writes one follow-up, one notification to the Lead and one audit
  event, inside one transaction. It changes no target, plan, activity or
  portfolio, and it does not notify the CCEO: how to follow up with their
  officer is the Lead's decision. Asking again about the same gap reminds the
  Lead on the same record — the instruction history keeps every earlier ask.
* **Acting** is the Lead's, through the workflows that already exist: they
  acknowledge, send their CCEO school actions (TeamAction, the platform's
  school-action workflow — linked back here), say what they are waiting on, or
  return the ask for clarification.
* **Closing** is observed: the sweep re-reads the gap through the same
  coverage service the page uses and closes the follow-up when it reaches
  zero. Only "Other" asks, which no query can settle, need the Director to
  close them, with a reason.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.planning.followup_models import (
    OPEN_FOLLOW_UP_STATES,
    PL_TODO_STATES,
    FollowUpPriority,
    FollowUpStatus,
    PlanningOversightFollowUp,
)
from apps.schools.lifecycle_service import active_schools

logger = logging.getLogger(__name__)

TEAM_OVERSIGHT_PATH = "/team-planning-oversight/"


class FollowUpError(Exception):
    """A refusal meant for the person who pressed the button."""


# ── The issues a follow-up can be about ──────────────────────────────────────
@dataclass(frozen=True)
class Issue:
    key: str
    label: str
    # Tally fields: what is required, what is planned, what is left.
    required: str
    planned: str
    remaining: str
    # The school-level test for "this school is part of the gap".
    school_test: str
    # The TeamAction a Lead sends a CCEO for one of the schools, if any.
    team_action: str | None
    resolution_rule: str = "metric_zero"
    todo_verb: str = "Follow Up with CCEO on Planning Gap"


ISSUES: dict[str, Issue] = {
    issue.key: issue
    for issue in (
        Issue(
            "staff_visit_gap",
            "Staff Visit Planning Gap",
            "staff_expected",
            "staff",
            "staff_gap",
            "staff_gap",
            "planning_visit_gap",
        ),
        Issue(
            "partner_assignment_gap",
            "Partner Assignment Gap",
            "partner_expected",
            "partner_assigned",
            "partner_gap",
            "partner_gap",
            "planning_partner_gap",
        ),
        Issue(
            "partner_scheduling_gap",
            "Partner Scheduling Gap",
            "partner_assigned",
            "partner_scheduled",
            "assigned_unscheduled",
            "awaiting_partner",
            None,
        ),
        Issue(
            "training_gap",
            "Training Planning Gap",
            "training_slots",
            "training",
            "training_gap",
            "training_gap",
            "planning_training_gap",
        ),
        Issue(
            "unclustered_schools",
            "Unclustered Schools",
            "schools",
            "clustered",
            "unclustered",
            "unclustered",
            "planning_cluster_gap",
        ),
        Issue(
            "meeting_gap",
            "Cluster-Meeting Planning Gap",
            "clustered",
            "meeting_covered_clustered",
            "clustered_no_meeting",
            "clustered_no_meeting",
            "planning_meeting_gap",
        ),
        Issue(
            "capacity_deficit",
            "Internal Capacity Deficit",
            "core_staff_slots",
            "staff_core",
            "deficit",
            "deficit",
            None,
        ),
        Issue(
            "school_gap",
            "School-Specific Planning Gap",
            "visit_slots",
            "planned",
            "unallocated",
            "unallocated",
            "planning_school_gap",
        ),
        Issue(
            "other",
            "Other Approved Planning Follow-Up",
            "visit_slots",
            "planned",
            "unallocated",
            "unallocated",
            None,
            resolution_rule="manual",
        ),
    )
}


def issue_of(issue_type: str):
    """The issue a follow-up names — planning here, or execution
    (apps.planning.country_execution.followups) — or None."""
    issue = ISSUES.get(issue_type)
    if issue is None:
        from apps.planning.country_execution.followups import EXEC_ISSUES

        issue = EXEC_ISSUES.get(issue_type)
    return issue


PRIORITY_CHOICES = FollowUpPriority.choices
STATUS_TONES = {
    FollowUpStatus.SENT_TO_PL: "sent",
    FollowUpStatus.ACKNOWLEDGED: "seen",
    FollowUpStatus.ACTION_LINKED: "seen",
    FollowUpStatus.WAITING_FOR_RESOLUTION: "wait",
    FollowUpStatus.RETURNED_FOR_CLARIFICATION: "back",
    FollowUpStatus.RESOLVED_AUTOMATICALLY: "done",
    FollowUpStatus.CLOSED_BY_CD: "done",
    FollowUpStatus.CANCELLED: "off",
    FollowUpStatus.WAITING_FOR_TEAM_MEMBER: "wait",
    FollowUpStatus.WAITING_FOR_PARTNER: "wait",
    FollowUpStatus.WAITING_FOR_EXTERNAL: "wait",
    FollowUpStatus.ESCALATED: "back",
}

#: How many school actions one "Ask my CCEO" sends at once. A portfolio gap can
#: be hundreds of schools; a CCEO's queue should get the worst first, not all.
MAX_SCHOOL_ACTIONS_PER_ASK = 25


def may_follow_up(user) -> bool:
    """Only the Country Director follows up with a Programme Lead from here.

    Not Impact Assessment (the verifier, not the line manager), not the RVP
    (who reads the country), and not Admin: technical access to the platform
    is not management authority over its people.
    """
    return (getattr(user, "active_role", "") or "") == "CountryDirector"


# ── Scope and evaluation ─────────────────────────────────────────────────────
@dataclass
class Scope:
    fy: str
    period_type: str
    period_start: date
    period_end: date
    lead_key: str
    cceo_key: str = ""
    school_id: str = ""
    country: str = ""

    @property
    def window(self):
        from apps.planning.country_oversight.coverage import window_for

        if self.period_type == "quarter":
            from apps.core.fy import get_quarter_for_date

            return window_for(
                self.fy, "quarter", quarter=get_quarter_for_date(self.period_start)
            )
        if self.period_type == "month":
            return window_for(self.fy, "month", month=self.period_start.month)
        if self.period_type == "week":
            return window_for(self.fy, "week", week_start=self.period_start)
        return window_for(self.fy, "fy")

    @classmethod
    def of(cls, followup: PlanningOversightFollowUp) -> "Scope":
        return cls(
            fy=followup.fy,
            period_type=followup.period_type,
            period_start=followup.period_start,
            period_end=followup.period_end,
            lead_key=followup.program_lead_staff_id,
            cceo_key=followup.cceo_staff_id or "",
            school_id=followup.school_id or "",
            country=followup.country,
        )


def condition_key(scope: Scope, issue_key: str) -> str:
    return (
        f"cpo|{scope.fy}|{scope.period_type}:{scope.period_start.isoformat()}"
        f"|pl:{scope.lead_key}|cceo:{scope.cceo_key or '-'}"
        f"|issue:{issue_key}|school:{scope.school_id or '-'}"
    )


def _system_scope(country: str):
    from apps.planning.country_oversight.service import system_scope

    return system_scope(country)


def _portfolio_owner_ids(scope: Scope) -> set[str]:
    """The owners whose whole portfolios a scope's figures are read from."""
    from apps.planning.oversight_service import (
        _both_id_spaces,
        program_lead_members,
    )

    if scope.cceo_key:
        return _both_id_spaces({scope.cceo_key})
    members = program_lead_members(scope.lead_key)
    ids = {scope.lead_key}
    for member in members:
        ids |= set(member.get("ids") or {member["id"]})
    return _both_id_spaces(ids)


def evaluate(scope: Scope, *, dataset=None):
    """(tally, dataset, placements) for a follow-up's scope, read live.

    Reads the scope's own portfolios only — a Lead's personal schools and
    their team's, or one officer's — through the same dataset and fold the
    page uses, so a follow-up closes exactly when the page stops showing the
    gap.
    """
    from apps.planning.country_oversight.service import Filters, build_dataset, fold

    if dataset is None:
        owners = _portfolio_owner_ids(scope)
        base = active_schools().filter(account_owner_id__in=owners)
        dataset = build_dataset(_system_scope(scope.country), scope.window, base=base)
    filters = Filters(
        fy=scope.fy,
        period=scope.period_type,
        program_lead=scope.lead_key,
        cceo=scope.cceo_key,
    )
    # Where each school landed, for the schools a gap names.
    tree = fold(dataset, filters, placement=True)
    if scope.school_id:
        return _school_tally(dataset, scope.school_id), dataset, tree
    return tree.country, dataset, tree


def _school_tally(dataset, school_id: str):
    from apps.planning.country_oversight.coverage import claims_for
    from apps.planning.country_oversight.hierarchy import Tally, phase, school_values

    school = dataset.facts.get(school_id)
    if school is None or not school.is_governed:
        return Tally()
    claims = claims_for(school, dataset.allocations.get(school_id), dataset.window)
    return Tally(phase(school_values(school, claims), dataset.window))


def metric_values(issue: Issue, tally) -> tuple[int, int, int]:
    return (
        int(getattr(tally, issue.required) or 0),
        int(getattr(tally, issue.planned) or 0),
        int(getattr(tally, issue.remaining) or 0),
    )


def affected_schools(
    issue: Issue, dataset, tree, *, limit: int = 500
) -> tuple[list, int]:
    """The schools in scope that are part of the gap, worst first."""
    from apps.planning.country_oversight.coverage import claims_for
    from apps.planning.country_oversight.hierarchy import IDX

    rows = []
    for school_id in tree.placement:
        school = dataset.facts[school_id]
        if issue.school_test == "awaiting_partner":
            claims = claims_for(school, dataset.allocations[school_id], dataset.window)
            amount = max(0, claims.cum_partner_assigned - claims.cum_partner_scheduled)
        else:
            # The school's own figures, as the dataset kept them.
            values = school.vector
            amount = values[IDX[issue.school_test]] if issue.school_test in IDX else 0
        if amount > 0:
            rows.append((amount, school.name, school.id))
    rows.sort(key=lambda row: (-row[0], row[1].casefold(), row[2]))
    return [row[2] for row in rows[:limit]], len(rows)


# ── Asking ───────────────────────────────────────────────────────────────────
def _lead(lead_key: str):
    from apps.accounts.models import StaffProfile

    return StaffProfile.objects.filter(id=lead_key).select_related("user").first()


def _history(followup, actor, action: str, note: str = "") -> None:
    followup.history = list(followup.history or []) + [
        {
            "at": timezone.now().isoformat(),
            "by": getattr(actor, "id", None) or "system",
            "name": getattr(actor, "name", "") or "System",
            "action": action,
            "note": note,
        }
    ]


def _audit(action: str, followup, actor, **payload) -> None:
    from apps.audit.services import log

    log(
        action=f"planning_followup.{action}",
        subject_kind="PlanningOversightFollowUp",
        subject_id=followup.id,
        actor_id=getattr(actor, "id", None) or "system",
        actor_role=getattr(actor, "active_role", None) or "system",
        payload={
            "condition_key": followup.condition_key,
            "issue_type": followup.issue_type,
            "program_lead": followup.program_lead_staff_id,
            "cceo": followup.cceo_staff_id,
            "school": followup.school_id,
            "status": followup.status,
            **payload,
        },
    )


def team_oversight_link(followup) -> str:
    """Where the Lead acts: Team Oversight, opened on the officer, the period
    and the gap, with the follow-up itself in view."""
    from urllib.parse import urlencode

    params = {"followup": followup.id, "fy": followup.fy}
    if followup.period_type and followup.period_type != "fy":
        params["period"] = followup.period_type
        if followup.period_type == "quarter":
            from apps.core.fy import get_quarter_for_date

            params["quarter"] = get_quarter_for_date(followup.period_start)
        elif followup.period_type == "month":
            params["month"] = followup.period_start.month
        elif followup.period_type == "week":
            params["week"] = followup.period_start.strftime("%G-W%V")
    if followup.cceo_staff_id:
        params["owner"] = followup.cceo_staff_id
    return f"{TEAM_OVERSIGHT_PATH}?{urlencode(params)}"


def _notify_lead(followup, *, title: str, body: str, event: str) -> None:
    from apps.notifications.models import Notification

    Notification.objects.update_or_create(
        recipient_id=followup.program_lead_user_id,
        context_type="PlanningOversightFollowUp",
        context_id=followup.id,
        source_event_type=event,
        defaults={
            "recipient_role": "Program Lead",
            "title": title,
            "body": body,
            "category": "planning",
            "target_route": team_oversight_link(followup),
            "action_label": "Follow up",
            "action_required": True,
            "priority": "high"
            if followup.priority in (FollowUpPriority.HIGH, FollowUpPriority.CRITICAL)
            else "normal",
            "status": "unread",
            "source_event_id": followup.id,
            "read_at": None,
            "resolved_at": None,
        },
    )


def _notify(
    recipient_id: str, followup, *, title: str, body: str, event: str, route: str
) -> None:
    from apps.notifications.models import Notification

    if not recipient_id:
        return
    Notification.objects.update_or_create(
        recipient_id=recipient_id,
        context_type="PlanningOversightFollowUp",
        context_id=followup.id,
        source_event_type=event,
        defaults={
            "title": title,
            "body": body,
            "category": "planning",
            "target_route": route,
            "priority": "normal",
            "status": "unread",
            "source_event_id": followup.id,
            "read_at": None,
        },
    )


def _resolve_lead_notifications(followup) -> None:
    from apps.notifications.models import Notification

    Notification.objects.filter(
        recipient_id=followup.program_lead_user_id,
        context_type="PlanningOversightFollowUp",
        context_id=followup.id,
        resolved_at__isnull=True,
    ).update(resolved_at=timezone.now(), action_required=False)


def send_follow_up(
    *,
    sender,
    scope: Scope,
    issue_key: str,
    instruction: str,
    due_date: date | None,
    priority: str,
    snapshot: dict | None = None,
) -> tuple[PlanningOversightFollowUp, bool]:
    """Create the follow-up, or remind the Lead on the open one. (row, created)."""
    if not may_follow_up(sender):
        raise FollowUpError(
            "Following up with a Programme Lead from Country Planning Oversight "
            "belongs to the Country Director."
        )
    issue = ISSUES.get(issue_key)
    if issue is None:
        raise FollowUpError("Choose what kind of follow-up this is.")
    instruction = (instruction or "").strip()
    if not instruction:
        raise FollowUpError("Write the instruction for the Programme Lead.")
    if due_date is None:
        raise FollowUpError("Give the follow-up a due date.")
    if due_date < timezone.localdate():
        raise FollowUpError("The due date cannot be in the past.")
    if priority not in {value for value, _ in PRIORITY_CHOICES}:
        raise FollowUpError("Choose a priority.")
    lead = _lead(scope.lead_key)
    if lead is None or not lead.user_id:
        raise FollowUpError(
            "This gap has no Programme Lead on record, so there is nobody to "
            "follow up with. Place the officer under a Programme Lead first."
        )
    if (getattr(lead.user, "active_role", "") or "") != "Program Lead":
        raise FollowUpError(f"{lead.user.name} is not a Programme Lead.")

    tally, dataset, tree = evaluate(scope)
    required, planned, remaining = metric_values(issue, tally)
    if issue.resolution_rule == "metric_zero" and remaining <= 0:
        raise FollowUpError(
            f"There is no {issue.label.lower()} in this scope right now, so "
            "there is nothing to follow up."
        )
    school_ids, affected = (
        ([scope.school_id], 1)
        if scope.school_id
        else affected_schools(issue, dataset, tree)
    )
    key = condition_key(scope, issue_key)
    now = timezone.now()
    entry = {
        "at": now.isoformat(),
        "by": getattr(sender, "id", ""),
        "name": getattr(sender, "name", "") or "Country Director",
        "instruction": instruction,
        "priority": priority,
        "due": due_date.isoformat(),
        "required": required,
        "planned": planned,
        "remaining": remaining,
    }

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
            existing.required_value, existing.planned_value = required, planned
            existing.remaining_value = remaining
            existing.live_remaining, existing.live_checked_at = remaining, now
            existing.affected_school_ids, existing.affected_count = school_ids, affected
            if existing.status == FollowUpStatus.RETURNED_FOR_CLARIFICATION:
                existing.status = FollowUpStatus.SENT_TO_PL
                existing.returned_reason = ""
            _history(existing, sender, "reminded", instruction)
            existing.save()
            _notify_lead(
                existing,
                title=f"Reminder: {issue.label}",
                body=_lead_body(existing, issue, reminder=True),
                event="planning_followup_assigned",
            )
            _audit("reminded", existing, sender, reminder_count=existing.reminder_count)
            return existing, False

        school_name = ""
        if scope.school_id:
            school = dataset.facts.get(scope.school_id)
            school_name = school.name if school else ""
        cceo_name = ""
        if scope.cceo_key:
            owner = dataset.owners.get(scope.cceo_key)
            cceo_name = owner.name if owner else ""
        window = scope.window
        try:
            followup = PlanningOversightFollowUp.objects.create(
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
                cceo_name=cceo_name,
                school_id=scope.school_id or None,
                school_name=school_name,
                condition_key=key,
                issue_type=issue.key,
                metric_key=issue.remaining,
                required_value=required,
                planned_value=planned,
                remaining_value=remaining,
                affected_school_ids=school_ids,
                affected_count=affected,
                snapshot={
                    **(snapshot or {}),
                    "policy_version": _policy_version(),
                    "as_of": dataset.as_of.isoformat(),
                    "required": required,
                    "planned": planned,
                    "remaining": remaining,
                },
                resolution_rule=issue.resolution_rule,
                live_remaining=remaining,
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
        _history(followup, sender, "sent", instruction)
        followup.save(update_fields=["history", "updated_at"])
        _notify_lead(
            followup,
            title=f"Follow up: {issue.label}",
            body=_lead_body(followup, issue),
            event="planning_followup_assigned",
        )
        _audit(
            "sent",
            followup,
            sender,
            required=required,
            planned=planned,
            remaining=remaining,
            due=due_date.isoformat(),
            priority=priority,
        )
    return followup, True


def _policy_version() -> str:
    from apps.planning.country_oversight.policy import POLICY_VERSION

    return POLICY_VERSION


def _lead_body(followup, issue: Issue, *, reminder: bool = False) -> str:
    who = followup.assigned_by_name or "The Country Director"
    subject = followup.cceo_name or followup.school_name or "your team"
    lead = "reminded you to follow up" if reminder else "asked you to follow up"
    return (
        f"{who} {lead} with {subject} on the {issue.label.lower()} "
        f"({followup.remaining_value:,} of {followup.required_value:,} remaining, "
        f"{followup.period_label}). Due {followup.due_date:%-d %b}. "
        f"“{followup.instruction}”"
    )


# ── The Programme Lead's response ────────────────────────────────────────────
def _must_be_lead(followup, actor) -> None:
    if str(getattr(actor, "id", "")) != str(followup.program_lead_user_id):
        raise FollowUpError("Only the Programme Lead this was sent to can do that.")
    if not followup.is_open:
        raise FollowUpError("This follow-up is already closed.")


def acknowledge(followup, actor):
    _must_be_lead(followup, actor)
    if followup.status != FollowUpStatus.SENT_TO_PL:
        return followup
    followup.status = FollowUpStatus.ACKNOWLEDGED
    followup.acknowledged_at = timezone.now()
    _history(followup, actor, "acknowledged")
    followup.save()
    _audit("acknowledged", followup, actor)
    return followup


def mark_waiting(followup, actor, note: str):
    _must_be_lead(followup, actor)
    note = (note or "").strip()
    if not note:
        raise FollowUpError("Say what the gap is waiting on.")
    followup.status = FollowUpStatus.WAITING_FOR_RESOLUTION
    followup.linked_note = note
    followup.acknowledged_at = followup.acknowledged_at or timezone.now()
    _history(followup, actor, "waiting", note)
    followup.save()
    _audit("waiting", followup, actor, note=note)
    return followup


def return_for_clarification(followup, actor, reason: str):
    _must_be_lead(followup, actor)
    reason = (reason or "").strip()
    if not reason:
        raise FollowUpError("Say what needs clarifying before returning it.")
    followup.status = FollowUpStatus.RETURNED_FOR_CLARIFICATION
    followup.returned_reason = reason
    followup.returned_at = timezone.now()
    _history(followup, actor, "returned", reason)
    followup.save()
    _notify(
        followup.assigned_by_id,
        followup,
        title=f"Follow-up returned: {getattr(issue_of(followup.issue_type), 'label', 'Follow-up')}",
        body=f"{followup.program_lead_name} returned it for clarification: {reason}",
        event="planning_followup_returned",
        route="/country-planning-oversight/",
    )
    _audit("returned", followup, actor, reason=reason)
    return followup


def ask_cceo(followup, actor, *, note: str = "", school_ids=None):
    """Send the officer school actions for the gap's schools, and link them.

    Goes through `action_service.send_action` — the TeamAction workflow every
    "Send to <staff>" already uses — one school at a time, worst first, for up
    to MAX_SCHOOL_ACTIONS_PER_ASK schools that still have the gap. An action
    already open for a school is linked rather than sent twice.
    """
    from apps.planning.action_models import ACTIVE_STATES, TeamAction
    from apps.planning.action_service import ActionError, send_action
    from apps.schools.models import School

    _must_be_lead(followup, actor)
    issue = issue_of(followup.issue_type)
    if issue is None or not issue.team_action:
        raise FollowUpError(
            "This gap is not one a school action settles. Say what it is "
            "waiting on instead."
        )
    if not followup.cceo_staff_id:
        raise FollowUpError(
            "This follow-up is about your own or your whole team's schools; "
            "open one officer's gap to ask them."
        )
    scope = Scope.of(followup)
    tally, dataset, tree = evaluate(scope)
    wanted = set(school_ids or [])
    candidates, _ = affected_schools(issue, dataset, tree, limit=10_000)
    if wanted:
        candidates = [pk for pk in candidates if pk in wanted]
    candidates = candidates[:MAX_SCHOOL_ACTIONS_PER_ASK]
    if not candidates:
        raise FollowUpError("No school in this gap still needs a school action.")

    from apps.planning.oversight_service import _both_id_spaces

    team = _both_id_spaces({followup.cceo_staff_id})
    linked = list(followup.linked_team_action_ids or [])
    sent = 0
    refusals: list[str] = []
    schools = School.objects.in_bulk(candidates)
    for school_id in candidates:
        school = schools.get(school_id)
        if school is None:
            continue
        key = f"planning_gap|{issue.team_action}|school|{school.id}|{followup.fy}"
        existing = TeamAction.objects.filter(
            condition_key=key, state__in=ACTIVE_STATES
        ).first()
        if existing is not None:
            if existing.id not in linked:
                linked.append(existing.id)
            continue
        try:
            action = send_action(
                sender=actor,
                school=school,
                issue={
                    "key": issue.team_action,
                    "condition_key": key,
                    "severity": "high",
                    "detail": "",
                },
                fy=followup.fy,
                note=(note or followup.instruction).strip(),
                within_staff_ids=team,
            )
        except ActionError as exc:
            refusals.append(f"{school.name}: {exc}")
            continue
        linked.append(action.id)
        sent += 1
    if not linked:
        raise FollowUpError(
            "No school action could be sent. " + (refusals[0] if refusals else "")
        )
    followup.linked_team_action_ids = linked
    followup.status = FollowUpStatus.ACTION_LINKED
    followup.action_linked_at = timezone.now()
    followup.acknowledged_at = followup.acknowledged_at or followup.action_linked_at
    if note:
        followup.linked_note = note.strip()
    _history(followup, actor, "action_linked", f"{sent} sent, {len(linked)} linked")
    followup.save()
    _audit("action_linked", followup, actor, sent=sent, linked=len(linked))
    return followup, sent, refusals


# ── The Country Director's closure ───────────────────────────────────────────
def _must_be_director(followup, actor) -> None:
    if not may_follow_up(actor):
        raise FollowUpError("Only the Country Director can do that.")
    if not followup.is_open:
        raise FollowUpError("This follow-up is already closed.")


def close_with_reason(followup, actor, reason: str):
    _must_be_director(followup, actor)
    reason = (reason or "").strip()
    if not reason:
        raise FollowUpError("A follow-up closed by hand needs a reason.")
    followup.status = FollowUpStatus.CLOSED_BY_CD
    followup.resolution_note = reason
    followup.resolved_at = timezone.now()
    followup.closed_by_id = getattr(actor, "id", "")
    _history(followup, actor, "closed", reason)
    followup.save()
    _resolve_lead_notifications(followup)
    _audit("closed", followup, actor, reason=reason)
    return followup


def escalate(followup, actor, note: str):
    """The Director escalates a follow-up still open past its due date (spec
    §19): it stays open, becomes critical and returns to the Lead's queue, and
    the escalation is on the record. Where an escalation goes beyond the Lead
    is not approved yet, so it goes nowhere else."""
    _must_be_director(followup, actor)
    if not followup.is_overdue:
        raise FollowUpError("Only a follow-up past its due date can be escalated.")
    note = (note or "").strip()
    if not note:
        raise FollowUpError("Say why the follow-up is being escalated.")
    followup.status = FollowUpStatus.ESCALATED
    followup.priority = FollowUpPriority.CRITICAL
    _history(followup, actor, "escalated", note)
    followup.save()
    issue = issue_of(followup.issue_type)
    label = issue.label if issue else "Follow-up"
    _notify_lead(
        followup,
        title=f"Escalated: {label}",
        body=(
            f"{getattr(actor, 'name', '') or 'The Country Director'} escalated this "
            f"follow-up, due {followup.due_date:%-d %b}: “{note}”"
        ),
        event="planning_followup_assigned",
    )
    _audit("escalated", followup, actor, note=note)
    return followup


def cancel(followup, actor, reason: str = ""):
    _must_be_director(followup, actor)
    followup.status = FollowUpStatus.CANCELLED
    followup.resolution_note = (reason or "").strip()
    followup.resolved_at = timezone.now()
    followup.closed_by_id = getattr(actor, "id", "")
    _history(followup, actor, "cancelled", followup.resolution_note)
    followup.save()
    _resolve_lead_notifications(followup)
    _audit("cancelled", followup, actor)
    return followup


# ── Closing the loop ─────────────────────────────────────────────────────────
def refresh(followup, *, datasets: dict | None = None) -> bool:
    """Re-read the gap; close the follow-up when it has cleared. True if closed."""
    if not followup.is_open:
        return False
    if getattr(followup, "module", "planning") == "execution":
        from apps.planning.country_execution.followups import (
            refresh as refresh_execution,
        )

        return refresh_execution(followup, datasets=datasets)
    scope = Scope.of(followup)
    issue = ISSUES.get(followup.issue_type)
    if issue is None:
        return False
    cache_key = (
        scope.fy,
        scope.period_type,
        scope.period_start,
        scope.lead_key,
        scope.cceo_key,
    )
    dataset = datasets.get(cache_key) if datasets is not None else None
    tally, dataset, _tree = evaluate(scope, dataset=dataset)
    if datasets is not None:
        datasets[cache_key] = dataset
    _required, _planned, remaining = metric_values(issue, tally)
    now = timezone.now()
    followup.live_remaining = remaining
    followup.live_checked_at = now
    if issue.resolution_rule == "metric_zero" and remaining <= 0:
        followup.status = FollowUpStatus.RESOLVED_AUTOMATICALLY
        followup.resolved_at = now
        followup.resolved_by_system = True
        _history(followup, None, "resolved", "The gap reached zero.")
        followup.save()
        _resolve_lead_notifications(followup)
        _notify(
            followup.assigned_by_id,
            followup,
            title=f"Follow-up resolved: {issue.label}",
            body=(
                f"The {issue.label.lower()} for "
                f"{followup.cceo_name or followup.school_name or followup.program_lead_name} "
                "has cleared, so the follow-up closed itself."
            ),
            event="planning_followup_resolved",
            route="/country-planning-oversight/",
        )
        _audit("auto_resolved", followup, None)
        return True
    followup.save(update_fields=["live_remaining", "live_checked_at", "updated_at"])
    return False


def sweep(*, limit: int | None = None) -> dict:
    """Refresh every open follow-up. Idempotent; one bad row never stops it."""
    queryset = PlanningOversightFollowUp.objects.filter(
        status__in=OPEN_FOLLOW_UP_STATES
    ).order_by("assigned_at")
    if limit:
        queryset = queryset[:limit]
    datasets: dict = {}
    checked = resolved = 0
    for followup in queryset:
        checked += 1
        try:
            if refresh(followup, datasets=datasets):
                resolved += 1
        except Exception:  # noqa: BLE001
            logger.exception("Could not refresh planning follow-up %s", followup.id)
    return {"checked": checked, "resolved": resolved}


#: One owner's portfolio, read once for every school action the TeamAction
#: sweep asks about in the same minute — an ask sends up to 25 of them, and
#: each would otherwise read the same portfolio again.
GAP_DATASET_SECONDS = 60
_GAP_DATASETS: dict = {}

#: Which school-level figure each school action closes on.
SCHOOL_GAP_FIGURE = {
    "planning_visit_gap": "staff_gap",
    "planning_school_gap": "unallocated",
    "planning_partner_gap": "partner_gap",
    "planning_training_gap": "training_gap",
    "planning_cluster_gap": "unclustered",
    "planning_meeting_gap": "clustered_no_meeting",
}


def school_gap_open(school_id: str, fy: str, action_type: str) -> bool:
    """Whether one school still has the planning gap a school action names.

    Read over the school owner's whole portfolio (the Partner/staff split is
    made per owner), for the year the action was sent in.
    """
    from apps.planning.country_oversight.coverage import claims_for, window_for
    from apps.planning.country_oversight.hierarchy import IDX, school_values
    from apps.planning.country_oversight.service import build_dataset
    from apps.schools.models import School

    figure = SCHOOL_GAP_FIGURE.get(action_type)
    school = School.objects.filter(id=school_id).first()
    if figure is None or school is None or not fy:
        return figure is not None and school is not None
    memo_key = (school.account_owner_id or school.id, str(fy))
    held = _GAP_DATASETS.get(memo_key)
    if held is not None and time.monotonic() - held[0] < GAP_DATASET_SECONDS:
        dataset = held[1]
    else:
        base = active_schools()
        base = (
            base.filter(account_owner_id=school.account_owner_id)
            if school.account_owner_id
            else base.filter(id=school.id)
        )
        dataset = build_dataset(_system_scope(""), window_for(fy, "fy"), base=base)
        if len(_GAP_DATASETS) > 64:
            _GAP_DATASETS.clear()
        _GAP_DATASETS[memo_key] = (time.monotonic(), dataset)
    facts = dataset.facts.get(school.id)
    if facts is None or not facts.is_governed:
        return False
    claims = claims_for(facts, dataset.allocations.get(school.id), dataset.window)
    return school_values(facts, claims)[IDX[figure]] > 0


def open_counts(fy: str, *, module: str = "planning") -> dict:
    """Open follow-ups per Lead and per officer, for the table's column —
    each Country Oversight stage counts its own."""
    from collections import Counter

    counts: Counter = Counter()
    for lead_key, cceo_key in PlanningOversightFollowUp.objects.filter(
        fy=fy, status__in=OPEN_FOLLOW_UP_STATES, module=module
    ).values_list("program_lead_staff_id", "cceo_staff_id"):
        counts[("lead", lead_key)] += 1
        counts[("country", "")] += 1
        if cceo_key:
            counts[("owner", cceo_key)] += 1
        else:
            counts[("owner", lead_key)] += 1
    return dict(counts)


def lead_todo_states():
    return PL_TODO_STATES


def default_due_date() -> date:
    return timezone.localdate() + timedelta(days=7)


class PlanningOversightFollowUpService:
    """The follow-up workflow, as one importable surface."""

    issues = ISSUES
    may_follow_up = staticmethod(may_follow_up)
    send = staticmethod(send_follow_up)
    acknowledge = staticmethod(acknowledge)
    ask_cceo = staticmethod(ask_cceo)
    mark_waiting = staticmethod(mark_waiting)
    return_for_clarification = staticmethod(return_for_clarification)
    close_with_reason = staticmethod(close_with_reason)
    cancel = staticmethod(cancel)
    refresh = staticmethod(refresh)
    sweep = staticmethod(sweep)
    open_counts = staticmethod(open_counts)
    evaluate = staticmethod(evaluate)
