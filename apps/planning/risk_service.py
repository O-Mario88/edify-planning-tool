"""Planning risks — one detector, read from the oversight items themselves.

A risk here is a *current* condition of a real record, computed from the fields
the oversight service already loaded. Nothing is stored: a risk that outlives
the condition it describes is worse than no risk at all, because somebody acts
on it. The sweep that closes TeamActions works the same way — it re-reads the
condition rather than trusting a flag.

Every risk carries the six things a supervisor needs to act without going
hunting: how bad it is, why it fired, who owns it, when it is due, what to do,
and where to do it. A risk missing any of those is a notification, not a
responsibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

# Severity drives the due date the action inherits and the order risks appear
# in. Same vocabulary as TeamAction so nothing has to be translated.
CRITICAL = "critical"
HIGH = "high"
WARNING = "warning"

# A partner has this long to schedule before the handover is treated as stalled.
# Short enough that a school term is not lost waiting, long enough that a
# partner who receives work on Friday is not delinquent on Monday.
PARTNER_SCHEDULE_GRACE_DAYS = 7

# How long after the activity date evidence may be outstanding before the
# completion is treated as at risk of never being verifiable.
EVIDENCE_GRACE_DAYS = 3

# A third date change is a planning problem rather than a scheduling one.
RESCHEDULE_LIMIT = 2

# The states in which evidence is genuinely outstanding: delivery has begun or
# been sent back, and the record is still moving. Terminal states are excluded
# because the verification chain has already ruled on them.
_EVIDENCE_EXPECTED_STATUSES = (
    "in_progress",
    "completion_started",
    "returned_by_pl",
    "returned",
    "returned_by_ia",
)

# The one state that means "this is waiting for a Salesforce identifier".
# ia_verified and completed were here and fired on every finished activity in
# the live data — a signal that is always on is not a signal.
_SALESFORCE_EXPECTED_STATUSES = ("salesforce_id_required",)


@dataclass(frozen=True)
class PlanningRisk:
    """One current condition, with everything needed to act on it."""

    key: str
    severity: str
    reason: str
    recommended_action: str
    route: str
    owner_id: str | None = None
    owner_name: str = ""
    due_date: date | None = None

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "severity": self.severity,
            "reason": self.reason,
            "recommended_action": self.recommended_action,
            "route": self.route,
            "owner_id": self.owner_id,
            "owner_name": self.owner_name,
            "due_date": self.due_date,
        }


_SEVERITY_ORDER = {CRITICAL: 0, HIGH: 1, WARNING: 2}


def annotate(items, *, today: date | None = None):
    """Attach current risks to each item, in place, and return the items.

    Deliberately operates on the already-built list rather than issuing its own
    queries: the oversight page's fixed query cost is the reason it can serve a
    country, and a detector that re-read each activity would undo that.
    """
    today = today or date.today()
    for item in items:
        item.risks = [r.as_dict() for r in risks_for(item, today)]
        _set_next_action_owner(item)
    return items


def risks_for(item, today: date) -> list[PlanningRisk]:
    """Every risk currently true of this item, worst first."""
    found = [
        detector(item, today)
        for detector in (
            _partner_not_scheduled,
            _scheduled_without_cost,
            _overdue,
            _evidence_outstanding,
            _salesforce_missing,
            _returned_by_ia,
            _rescheduled_repeatedly,
        )
    ]
    risks = [r for r in found if r is not None]
    risks.sort(key=lambda r: _SEVERITY_ORDER.get(r.severity, 9))
    return risks


def _set_next_action_owner(item) -> None:
    """Who has to move next.

    An unscheduled handover waits on the partner; everything else waits on the
    member of staff answerable for it. Naming the wrong one turns a supervision
    page into a source of misdirected chasing.
    """
    if item.risks and item.is_awaiting_partner_schedule:
        item.next_action_owner_id = item.partner_id
        item.next_action_owner_name = item.partner_name or "Partner"
    elif item.risks:
        item.next_action_owner_id = item.operational_owner_id
        item.next_action_owner_name = item.operational_owner_name


# ── Detectors ────────────────────────────────────────────────────────────────
def _partner_not_scheduled(item, today: date) -> PlanningRisk | None:
    """Work handed to a partner that the partner has not put a date on.

    Fires only after the grace period, and against the schedule-by date when
    the handover set one — a partner given until the end of the month is not
    late in week one.
    """
    if not item.is_awaiting_partner_schedule:
        return None

    deadline = item.schedule_by_date or (
        (item.assigned_date or today) + timedelta(days=PARTNER_SCHEDULE_GRACE_DAYS)
    )
    if today <= deadline:
        return None

    days = (today - deadline).days
    return PlanningRisk(
        key="partner_not_scheduled",
        severity=HIGH if days > PARTNER_SCHEDULE_GRACE_DAYS else WARNING,
        reason=(
            f"{item.partner_name or 'The partner'} has not scheduled this "
            f"handover; it was due to be scheduled {days} day{'s' if days != 1 else ''} ago."
        ),
        recommended_action="Chase the partner or take the work back",
        route="/partners",
        owner_id=item.managing_staff_id,
        owner_name=item.managing_staff_name,
        due_date=deadline,
    )


def _scheduled_without_cost(item, today: date) -> PlanningRisk | None:
    """Scheduled work carrying no money.

    This is the one that stops a fund request later, so it is caught while
    there is still time to price it rather than at the point of payment.
    """
    if item.is_awaiting_partner_schedule or not item.activity_id:
        return None
    if not (item.cost_missing or item.planned_cost <= 0):
        return None
    return PlanningRisk(
        key="scheduled_without_cost",
        severity=CRITICAL if item.cost_missing else HIGH,
        reason=(
            "This activity is scheduled but has no cost line, so it cannot "
            "enter a fund request or a monthly budget."
        ),
        recommended_action="Add the missing Cost Catalogue configuration",
        route=f"/activities/{item.activity_id}",
        owner_id=item.operational_owner_id,
        owner_name=item.operational_owner_name,
        due_date=item.planned_date,
    )


def _overdue(item, today: date) -> PlanningRisk | None:
    """Its date has passed and the work has not finished."""
    if item.is_awaiting_partner_schedule or not item.planned_date:
        return None
    if item.planned_date >= today or item.is_completed:
        return None
    days = (today - item.planned_date).days
    return PlanningRisk(
        key="activity_overdue",
        severity=CRITICAL if days > 14 else HIGH,
        reason=f"Planned for {item.planned_date:%-d %b} and still not completed ({days} days).",
        recommended_action="Complete the activity or reschedule it",
        route=f"/activities/{item.activity_id}",
        owner_id=item.operational_owner_id,
        owner_name=item.operational_owner_name,
        due_date=item.planned_date,
    )


def _evidence_outstanding(item, today: date) -> PlanningRisk | None:
    """Delivery in flight whose evidence has not arrived.

    Deliberately narrow, in both directions. Work that never started is the
    overdue risk's story, not this one. Work that has *finished* — verified,
    confirmed, closed — has already been through the evidence gate, and asking
    for evidence after the chain has settled is noise: checked against live
    data, the wider reading fired on every single completed activity, which is
    the same as flagging nothing.
    """
    if item.is_awaiting_partner_schedule or not item.planned_date:
        return None
    if item.evidence_status not in ("", "none"):
        return None
    if item.planned_date + timedelta(days=EVIDENCE_GRACE_DAYS) >= today:
        return None
    if item.activity_status not in _EVIDENCE_EXPECTED_STATUSES:
        return None
    return PlanningRisk(
        key="evidence_outstanding",
        severity=HIGH,
        reason="The activity has been delivered but no evidence has been uploaded.",
        recommended_action="Upload the evidence pack",
        route=f"/activities/{item.activity_id}",
        owner_id=item.operational_owner_id,
        owner_name=item.operational_owner_name,
        due_date=item.planned_date + timedelta(days=EVIDENCE_GRACE_DAYS),
    )


def _salesforce_missing(item, today: date) -> PlanningRisk | None:
    """Verified work that never received its Salesforce identifier."""
    if item.salesforce_status == "recorded":
        return None
    if item.activity_status not in _SALESFORCE_EXPECTED_STATUSES:
        return None
    return PlanningRisk(
        key="salesforce_missing",
        severity=WARNING,
        reason="The activity is complete but has no Salesforce Activity ID.",
        recommended_action="Enter the Salesforce Activity ID",
        route=f"/activities/{item.activity_id}",
        owner_id=item.operational_owner_id,
        owner_name=item.operational_owner_name,
    )


def _returned_by_ia(item, today: date) -> PlanningRisk | None:
    """Impact Assessment sent it back and it has not come round again."""
    if item.activity_status != "returned_by_ia" and item.ia_status != "returned":
        return None
    return PlanningRisk(
        key="ia_returned",
        severity=CRITICAL,
        reason="Impact Assessment returned this activity and it has not been resubmitted.",
        recommended_action="Resolve the IA return and resubmit",
        route=f"/activities/{item.activity_id}",
        owner_id=item.operational_owner_id,
        owner_name=item.operational_owner_name,
    )


def _rescheduled_repeatedly(item, today: date) -> PlanningRisk | None:
    """Moved more than twice — a planning problem, not a scheduling one."""
    if item.reschedule_count <= RESCHEDULE_LIMIT:
        return None
    return PlanningRisk(
        key="repeated_reschedule",
        severity=WARNING,
        reason=f"This activity has been rescheduled {item.reschedule_count} times.",
        recommended_action="Review whether the plan is realistic",
        route=f"/activities/{item.activity_id}",
        owner_id=item.operational_owner_id,
        owner_name=item.operational_owner_name,
    )
