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
    asking has not worked       → escalate one level up (a PL to the Country
                                  Director) through the escalation channel

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

# The playbook key escalations were once opened under as TeamActions. New
# escalations go through the escalation channel (escalate_to_country_director);
# the key stays so TeamActions opened before 2026-09-13 keep their label and
# route (apps.planning.action_service).
ESCALATION_KEY = "partner_delivery_escalation"

# The escalation channel's scope for a partner handover, so an open escalation
# is found again and not raised twice.
ESCALATION_SCOPE = "PartnerAssignment"


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

    Recorded through the escalation channel (apps.flags.escalation_service),
    not as a TeamAction (Program Lead alignment, 2026-09-13). The TeamAction
    went to the deployment's first Country Director on file — in a
    multi-country deployment, possibly another country's — and sat in that
    director's Actions queue, invisible on /escalations where the director
    decides everything else raised to them. The channel resolves the addressee
    from the raiser's reporting line (their supervisor holding the Country
    Director role), else addresses the Country Director role in the raiser's
    country, carries the decision back to the raiser, and runs the SLA sweep.
    One level up, as the channel always is: a Programme Lead's escalation goes
    to the Country Director; an officer's goes to their Programme Lead.

    Returns the LeadershipEscalation.
    """
    if not note.strip():
        raise ActionError(
            "An escalation needs a note saying what has already been tried."
        )
    if not item.school_id and not item.cluster_name:
        raise ActionError("This assignment has no school to escalate against.")

    from apps.core.exceptions import BadRequest, Forbidden
    from apps.flags import escalation_service
    from apps.flags.models import EscalationStatus, LeadershipEscalation

    sender_id = getattr(sender, "user_id", None) or getattr(sender, "id", None)
    already = (
        LeadershipEscalation.objects.filter(
            raised_by_user_id=sender_id,
            scope_type=ESCALATION_SCOPE,
            scope_id=item.partner_assignment_id,
        )
        .exclude(status=EscalationStatus.RESOLVED)
        .exists()
    )
    if already:
        raise ActionError(
            "Already escalated: this handover has an open escalation. Follow it "
            "on Escalations."
        )

    partner = item.partner_name or "The partner"
    place = item.school_name or item.cluster_name or "the assigned school"
    try:
        return escalation_service.raise_escalation(
            {
                "category": "partner_performance",
                "severity": "high",
                "subject": f"{partner} at {place}: {item.next_action}"[:255],
                "detail": (
                    f"Partner-delivered work has stalled and asking has not moved it. "
                    f"{item.next_action} ({item.next_action_owner}).\n\n"
                    f"What has been tried: {note.strip()}"
                ),
                "requested_decision": (
                    f"Decide how {partner}'s delivery at {place} is recovered — "
                    "a firm deadline, reassignment or a contract conversation."
                ),
                "scope_type": ESCALATION_SCOPE,
                "scope_id": item.partner_assignment_id,
                "scope_name": f"{partner} · {place}",
            },
            sender,
        )
    except (BadRequest, Forbidden) as exc:
        raise ActionError(str(getattr(exc, "detail", exc))) from exc


def escalation_addressee_label(sender) -> str:
    """Who the Escalate button reaches for this reader, in words: the named
    Country Director (or Programme Lead) when the reporting line names one,
    else the role. Empty when the reader cannot escalate."""
    from apps.flags import escalation_service

    level, _user_id, name = escalation_service.resolve_addressee(sender)
    if not level:
        return ""
    role = escalation_service.ADDRESSEE_LABELS.get(level, "")
    return f"{name} ({role})" if name else role


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
