"""What a Program Lead can actually do about partner-delivered work.

Supervision here is narrower than on staff work, and deliberately so. The
partner controls their own schedule; the CCEO owns the school relationship and
the evidence handoff; the Program Lead's whole instrument is the ability to
ask the right person. So there are exactly three sends, and which one is
available is decided by who the risk names as responsible — not by the person
looking at the page.

    the partner is responsible  → remind the partner
    a role queue is             → nudge Impact Assessment or the Accountant
    a named staff member is     → send a TeamAction to the managing CCEO
    asking has not worked       → escalate to the Country Director

Nothing here edits a partner's schedule, and nothing here creates a TeamAction
against a CCEO for work a partner has not done. A TeamAction is a staff
accountability record; opening one against the wrong person is worse than
opening none, because the queue then says a CCEO is late when they are not.
"""

from __future__ import annotations

from apps.planning.action_service import (
    ActionError,
    PARTNER_OVERSIGHT_RISK_KEYS,
    ROLE_QUEUES,
    notify_role_queue,
    partner_oversight_condition_key,
    send_action,
)

# Risks the partner themself has to clear. These have no staff recipient, so
# they are sent over the notification channel rather than as a TeamAction.
PARTNER_ADDRESSED_RISKS = frozenset(
    {
        "partner_schedule_overdue",
        "partner_schedule_approaching",
        "partner_delivery_overdue",
        "partner_evidence_overdue",
    }
)

# Risks a member of staff clears, mapped to the playbook key the TeamAction is
# opened under. `salesforce_overdue` is renamed on the way in: the staff
# workflow already has a condition of that name, and two different conditions
# sharing one issue_type would let one sweep close the other's actions.
CCEO_ADDRESSED_RISKS = {
    "assignment_returned": "assignment_returned",
    "evidence_submission_stalled": "evidence_submission_stalled",
    "salesforce_overdue": "partner_salesforce_overdue",
}

ESCALATION_KEY = "partner_delivery_escalation"


def _risk_on(item, risk_key: str) -> dict:
    risk = next((r for r in item.risks if r["key"] == risk_key), None)
    if risk is None:
        raise ActionError(
            "That condition is no longer true of this assignment, so there is "
            "nothing to send."
        )
    return risk


def remind_partner(*, sender, item, risk_key: str, note: str = ""):
    """Ask the partner to do the thing only they can do.

    Returns the Notification. No TeamAction: the partner is not a member of
    staff, so there is no supervisory relationship for one to record, and the
    accountability that does exist — the CCEO's, for the handover — is not
    what this reminder is about.
    """
    if risk_key not in PARTNER_ADDRESSED_RISKS:
        raise ActionError(
            f"'{risk_key}' is not something the partner can resolve. Send it to "
            "the managing CCEO instead."
        )
    risk = _risk_on(item, risk_key)

    from apps.partners.models import Partner

    partner = Partner.objects.filter(id=item.partner_id).first()
    if partner is None:
        raise ActionError("That partner record no longer exists.")
    if not partner.user_id:
        raise ActionError(
            f"{partner.name} has no login account on the system, so a reminder "
            "cannot reach them here. Contact them directly."
        )

    from apps.audit.services import log
    from apps.messaging.services import workflow_message
    from apps.notifications.models import Notification

    sender_name = getattr(sender, "name", None) or "A Program Lead"
    body = (
        f"{sender_name} asked about {item.school_name or 'an assigned school'}: "
        f"{risk['reason']} {risk['recommended_action']}."
    )
    if note.strip():
        body = f"{body}\n\n{note.strip()}"

    # One reminder per condition per assignment, refreshed rather than
    # repeated: three nudges about the same unscheduled visit is noise the
    # partner learns to ignore, which costs the next real one its urgency.
    notification, _ = Notification.objects.update_or_create(
        recipient_id=partner.user_id,
        context_type="PartnerAssignment",
        context_id=item.partner_assignment_id,
        source_event_type=f"partner_reminder.{risk_key}",
        defaults={
            "recipient_role": "Partner",
            "title": f"Reminder: {item.school_name or 'assigned school'}",
            "body": body,
            "category": "planning",
            "target_route": "/partner/assignments",
            "action_label": risk["recommended_action"],
            "action_required": True,
            "priority": "high" if risk["severity"] != "warning" else "normal",
            "status": "unread",
            "read_at": None,
        },
    )

    workflow_message(
        context_type="PartnerAssignment",
        context_id=item.partner_assignment_id,
        subject=f"{item.school_name or 'Assignment'} — {risk['recommended_action']}",
        body=body,
        recipient_ids=[partner.user_id],
        category="planning",
        sender_id=getattr(sender, "id", None),
    )

    log(
        action="partner_oversight.reminder_sent",
        subject_kind="PartnerAssignment",
        subject_id=item.partner_assignment_id,
        actor_id=getattr(sender, "id", None),
        actor_role=getattr(sender, "active_role", None),
        payload={
            "risk": risk_key,
            "partner_id": item.partner_id,
            "school_id": item.school_id,
            "recipient_id": partner.user_id,
        },
    )
    return notification


def send_to_managing_cceo(*, sender, item, risk_key: str, note: str = ""):
    """Hold the CCEO who manages this handover to the part that is theirs.

    The recipient is the CCEO named on the assignment, not whoever holds the
    school assignment today. On partner work those can differ, and the person
    who handed the school over is the one who agreed to manage it.
    """
    issue_key = CCEO_ADDRESSED_RISKS.get(risk_key)
    if issue_key is None:
        raise ActionError(
            f"'{risk_key}' is not a condition the managing CCEO can clear."
        )
    if issue_key not in PARTNER_OVERSIGHT_RISK_KEYS:  # pragma: no cover — guard
        raise ActionError(f"'{issue_key}' is not registered as a partner condition.")
    risk = _risk_on(item, risk_key)

    if not item.school_id:
        raise ActionError(
            "This assignment has no school, so there is no school record to "
            "attach the ask to."
        )

    from apps.accounts.models import StaffProfile
    from apps.schools.models import School

    school = School.objects.filter(id=item.school_id).first()
    if school is None:
        raise ActionError("The school on this assignment no longer exists.")

    cceo = StaffProfile.objects.filter(id=item.responsible_cceo_id).first()
    if cceo is None and item.responsible_cceo_id:
        cceo = StaffProfile.objects.filter(user_id=item.responsible_cceo_id).first()
    if cceo is None or not cceo.user_id:
        raise ActionError(
            "This assignment records no managing CCEO, so there is nobody to "
            "hold responsible for it."
        )

    return send_action(
        sender=sender,
        school=school,
        issue={
            "key": issue_key,
            "condition_key": partner_oversight_condition_key(
                issue_key, assignment_id=item.partner_assignment_id
            ),
            "severity": risk["severity"],
            "detail": risk["reason"],
            "related_activity_id": item.partner_activity_id,
        },
        fy=item.financial_year or "",
        recipient_staff=cceo,
        note=note,
        month_of_fy=item.month,
    )


def escalate_to_country_director(*, sender, item, note: str = ""):
    """Hand a stalled handover upward when asking has not moved it.

    Escalation is the honest end of a Program Lead's authority: they cannot
    replace the partner, cancel the contract or reprice the work, and the
    person who can is the Country Director. It closes by judgement rather than
    by query, because what settles it is somebody deciding the intervention
    worked.
    """
    if not note.strip():
        raise ActionError(
            "An escalation needs a note saying what has already been tried."
        )
    if not item.school_id:
        raise ActionError("This assignment has no school to escalate against.")

    from apps.accounts.models import StaffProfile
    from apps.core.rbac import EdifyRole
    from apps.schools.models import School

    school = School.objects.filter(id=item.school_id).first()
    if school is None:
        raise ActionError("The school on this assignment no longer exists.")

    director = (
        StaffProfile.objects.filter(
            user__active_role=EdifyRole.COUNTRY_DIRECTOR.value, user__is_active=True
        )
        .select_related("user")
        .order_by("created_at")
        .first()
    )
    if director is None or not director.user_id:
        raise ActionError(
            "There is no active Country Director on the system to escalate to."
        )

    return send_action(
        sender=sender,
        school=school,
        issue={
            "key": ESCALATION_KEY,
            "condition_key": partner_oversight_condition_key(
                ESCALATION_KEY, assignment_id=item.partner_assignment_id
            ),
            "severity": "high",
            "detail": (
                f"{item.partner_name or 'The partner'} at {school.name}: "
                f"{item.next_action}."
            ),
            "related_activity_id": item.partner_activity_id,
        },
        fy=item.financial_year or "",
        recipient_staff=director,
        note=note,
        month_of_fy=item.month,
    )


def nudge_role_queue(*, sender, item, risk_key: str, note: str = ""):
    """Ask Impact Assessment or the Accountant to clear one partner record.

    This is the step an unpaid partner is actually waiting on, and until now
    the page named the queue and offered nothing. Returns the ids notified —
    no TeamAction, because neither queue assigns a particular record to a
    particular officer.
    """
    risk = _risk_on(item, risk_key)
    role = risk.get("responsible_role") or ""
    if role not in ROLE_QUEUES:
        raise ActionError(
            f"'{risk_key}' is not something {ROLE_QUEUES.get(role, 'a queue')} "
            "can resolve."
        )

    where = item.school_name or "a partner assignment"
    asker = getattr(sender, "name", None) or "A supervisor"
    body = (
        f"{asker} asked about {item.partner_name or 'a partner'} at {where}: "
        f"{risk['reason']}"
    )
    if note.strip():
        body = f"{body}\n\n{note.strip()}"

    return notify_role_queue(
        sender=sender,
        role=role,
        subject=f"{risk['recommended_action']} — {where}",
        body=body,
        context_type="PartnerAssignment",
        context_id=item.partner_assignment_id,
        event_key=f"partner_oversight_nudge.{risk_key}",
        route=risk.get("route") or "/partner-oversight/",
        action_label=risk["recommended_action"],
        priority="high" if risk.get("severity") == "critical" else "normal",
    )
