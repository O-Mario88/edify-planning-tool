"""Risks on partner-delivered work.

Same shape as `risk_service`, and deliberately a separate module: the partner
lifecycle has a handover phase that staff work does not, and the conditions
that matter there — nobody has scheduled, the partner handed it back, the
managing CCEO has not reviewed the evidence — have no staff equivalent.

Each risk names the actor who has to move. On partner work that is rarely the
person reading the page: a Program Lead's whole job here is to know who to ask.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

CRITICAL = "critical"
HIGH = "high"
WARNING = "warning"

# How long a partner has to put a date on a handover before it is stalled.
SCHEDULE_GRACE_DAYS = 7
# How close to the schedule-by date counts as "approaching".
APPROACHING_DAYS = 3
# How long evidence, a managing-staff review or a payment may sit.
EVIDENCE_GRACE_DAYS = 3
# How long a partner's completion may sit in the Impact Assessment queue.
IA_VERIFICATION_GRACE_DAYS = 5
REVIEW_GRACE_DAYS = 5
PAYMENT_GRACE_DAYS = 14

_SEVERITY_ORDER = {CRITICAL: 0, HIGH: 1, WARNING: 2}


@dataclass(frozen=True)
class PartnerRisk:
    key: str
    severity: str
    reason: str
    responsible: str
    recommended_action: str
    route: str
    due_date: date | None = None
    # Set when the actor is a role queue rather than a named person. Impact
    # Assessment and the Accountant hold no per-record assignment, so the send
    # path nudges the queue instead of opening a TeamAction against whichever
    # officer is listed first.
    responsible_role: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "severity": self.severity,
            "reason": self.reason,
            "responsible": self.responsible,
            "recommended_action": self.recommended_action,
            "route": self.route,
            "due_date": self.due_date,
            "responsible_role": self.responsible_role,
        }


def annotate(items, *, today: date | None = None):
    today = today or date.today()
    for item in items:
        item.risks = [r.as_dict() for r in risks_for(item, today)]
    return items


def risks_for(item, today: date) -> list[PartnerRisk]:
    found = [
        detector(item, today)
        for detector in (
            _schedule_overdue,
            _schedule_approaching,
            _returned,
            _delivery_overdue,
            _missing_rate,
            _evidence_overdue,
            _review_overdue,
            _salesforce_overdue,
            _ia_verification_overdue,
            _payment_overdue,
        )
    ]
    risks = [r for r in found if r is not None]
    risks.sort(key=lambda r: _SEVERITY_ORDER.get(r.severity, 9))
    return risks


def _deadline(item, today: date) -> date:
    return item.schedule_by_date or (
        (item.assignment_date or today) + timedelta(days=SCHEDULE_GRACE_DAYS)
    )


def _schedule_overdue(item, today: date) -> PartnerRisk | None:
    if item.stage != "awaiting_schedule":
        return None
    deadline = _deadline(item, today)
    if today <= deadline:
        return None
    days = (today - deadline).days
    return PartnerRisk(
        key="partner_schedule_overdue",
        severity=HIGH if days > SCHEDULE_GRACE_DAYS else WARNING,
        reason=f"{item.partner_name or 'The partner'} has not scheduled this, {days} day(s) past due.",
        responsible=item.partner_name or "Partner",
        recommended_action="Remind the partner, or take the work back",
        route="/partner-oversight/",
        due_date=deadline,
    )


def _schedule_approaching(item, today: date) -> PartnerRisk | None:
    """Warn before it is late, which is the only point at which it is cheap."""
    if item.stage != "awaiting_schedule":
        return None
    deadline = _deadline(item, today)
    if not (today <= deadline <= today + timedelta(days=APPROACHING_DAYS)):
        return None
    return PartnerRisk(
        key="partner_schedule_approaching",
        severity=WARNING,
        reason=f"Schedule-by date is {deadline:%-d %b} and no date has been set.",
        responsible=item.partner_name or "Partner",
        recommended_action="Remind the partner",
        route="/partner-oversight/",
        due_date=deadline,
    )


def _returned(item, today: date) -> PartnerRisk | None:
    if item.stage != "returned":
        return None
    return PartnerRisk(
        key="assignment_returned",
        severity=HIGH,
        reason=(
            f"{item.partner_name or 'The partner'} returned this"
            + (f": {item.return_reason}" if item.return_reason else ".")
        ),
        responsible=item.responsible_cceo_name or "CCEO",
        recommended_action="Reassign, schedule as staff work, or cancel",
        route="/planning",
    )


def _delivery_overdue(item, today: date) -> PartnerRisk | None:
    if not item.is_scheduled or not item.scheduled_date:
        return None
    if item.scheduled_date >= today:
        return None
    if item.activity_status in (
        "ia_verified",
        "accountant_confirmed",
        "completed",
        "closed",
    ):
        return None
    if item.evidence_status not in ("", "none"):
        return None
    days = (today - item.scheduled_date).days
    return PartnerRisk(
        key="partner_delivery_overdue",
        severity=CRITICAL if days > 14 else HIGH,
        reason=f"Scheduled for {item.scheduled_date:%-d %b} with no evidence yet ({days} days).",
        responsible=item.partner_name or "Partner",
        recommended_action="Ask the partner to deliver or reschedule",
        route="/partner-oversight/",
        due_date=item.scheduled_date,
    )


def _missing_rate(item, today: date) -> PartnerRisk | None:
    """Scheduled partner work with no cost — the catalogue had no partner rate.

    Distinct from the handover case, where absent cost is correct. Here the
    partner has committed to a date and the work still cannot enter a budget.
    """
    if not item.is_scheduled:
        return None
    if item.planned_cost:
        return None
    return PartnerRisk(
        key="partner_rate_missing",
        severity=CRITICAL,
        reason="Scheduled, but no partner rate was found in the cost catalogue.",
        responsible="Country Director",
        recommended_action="Add the partner rate to the Cost Catalogue",
        route="/cost-settings",
    )


def _evidence_overdue(item, today: date) -> PartnerRisk | None:
    if not item.is_scheduled or not item.scheduled_date:
        return None
    if item.evidence_status not in ("", "none"):
        return None
    if item.activity_status not in ("in_progress", "completion_started"):
        return None
    if item.scheduled_date + timedelta(days=EVIDENCE_GRACE_DAYS) >= today:
        return None
    return PartnerRisk(
        key="partner_evidence_overdue",
        severity=HIGH,
        reason="Delivery began but no evidence has been uploaded.",
        responsible=item.partner_name or "Partner",
        recommended_action="Ask the partner to upload the evidence pack",
        route="/partner-oversight/",
        due_date=item.scheduled_date + timedelta(days=EVIDENCE_GRACE_DAYS),
    )


def _review_overdue(item, today: date) -> PartnerRisk | None:
    """Evidence is in and the managing CCEO has not looked at it."""
    if item.evidence_status != "uploaded":
        return None
    if not item.scheduled_date:
        return None
    if item.scheduled_date + timedelta(days=REVIEW_GRACE_DAYS) >= today:
        return None
    return PartnerRisk(
        key="cceo_review_overdue",
        severity=HIGH,
        reason="The partner's evidence is waiting on the managing CCEO's review.",
        responsible=item.responsible_cceo_name or "CCEO",
        recommended_action="Review the partner's evidence",
        route="/my-plan",
        due_date=item.scheduled_date + timedelta(days=REVIEW_GRACE_DAYS),
    )


def _salesforce_overdue(item, today: date) -> PartnerRisk | None:
    if item.activity_status != "salesforce_id_required":
        return None
    if item.salesforce_status == "recorded":
        return None
    return PartnerRisk(
        key="salesforce_overdue",
        severity=WARNING,
        reason="Evidence is accepted but no Salesforce Activity ID has been entered.",
        responsible=item.responsible_cceo_name or "CCEO",
        recommended_action="Enter the Salesforce Activity ID",
        route="/my-plan",
    )


def _payment_overdue(item, today: date) -> PartnerRisk | None:
    if item.activity_status not in ("ia_verified", "accountant_confirmed"):
        return None
    if item.payment_status not in ("", "none", "pending"):
        return None
    if not item.scheduled_date:
        return None
    if item.scheduled_date + timedelta(days=PAYMENT_GRACE_DAYS) >= today:
        return None
    return PartnerRisk(
        key="partner_payment_overdue",
        severity=HIGH,
        reason="Verified by Impact Assessment and still unpaid.",
        responsible="Accountant",
        recommended_action="Pay the partner",
        route="/accounts/partner-payments",
        responsible_role="Accountant",
        due_date=item.scheduled_date + timedelta(days=PAYMENT_GRACE_DAYS),
    )


def _ia_verification_overdue(item, today: date) -> PartnerRisk | None:
    """A partner's completion sitting unverified in the Impact Assessment queue.

    On partner work this is the step that gates payment, so it is the one an
    unpaid partner is actually waiting on — and the one a Program Lead chasing
    "why has Partner X not been paid" needs named. The actor is the queue: no
    officer is assigned a particular verification.
    """
    if not item.submitted_to_ia_at:
        return None
    if item.ia_status in ("confirmed", "returned", "flagged"):
        return None

    due = item.submitted_to_ia_at + timedelta(days=IA_VERIFICATION_GRACE_DAYS)
    if today <= due:
        return None

    waiting = (today - item.submitted_to_ia_at).days
    return PartnerRisk(
        key="ia_verification_overdue",
        severity=HIGH if waiting > 2 * IA_VERIFICATION_GRACE_DAYS else WARNING,
        reason=(
            f"Submitted for verification {waiting} day(s) ago. The partner "
            "cannot be paid until it is verified."
        ),
        responsible="Impact Assessment",
        recommended_action="Verify the partner's submission",
        route="/ia/verification-queue",
        responsible_role="ImpactAssessment",
        due_date=due,
    )
