"""Sending a corrective action from an oversight page.

Both directions — a Program Lead asking a CCEO to fix one record, a Country
Director asking a Program Lead to clear a team backlog — go through
`action_service.send_action`, which writes the TeamAction, the notification,
the contextual message and the audit event in one transaction. Nothing here
creates or edits an Activity: supervision is the ability to ask, not the
ability to do it for them.
"""

from __future__ import annotations

from apps.planning.action_service import (
    ActionError,
    OVERSIGHT_RISK_KEYS,
    TEAM_OVERSIGHT_KEYS,
    oversight_condition_key,
    send_action,
)


def send_risk_to_owner(
    *, sender, item, risk_key: str, note: str = "", within_staff_ids=None
):
    """Ask the person answerable for one record to resolve one risk on it.

    The recipient is resolved from the school's assignment inside the sender's
    own span of control, so a Program Lead always delegates to a member of
    their own team. Where the item has no school — cluster and programme work —
    the send is refused rather than guessing at an owner, which is the same
    rule the school cards follow.
    """
    if risk_key not in OVERSIGHT_RISK_KEYS:
        raise ActionError(f"'{risk_key}' is not a planning-oversight risk.")

    risk = next((r for r in item.risks if r["key"] == risk_key), None)
    if risk is None:
        raise ActionError(
            "That condition is no longer true of this record, so there is "
            "nothing to send."
        )

    if not item.school_id:
        raise ActionError(
            "This work has no school, so there is no assigned owner to hold "
            "responsible. Raise it with the team directly."
        )

    from apps.schools.models import School

    school = School.objects.filter(id=item.school_id).first()
    if school is None:
        raise ActionError("The school on this record no longer exists.")

    issue = {
        "key": risk_key,
        "condition_key": oversight_condition_key(
            risk_key,
            activity_id=item.activity_id,
            assignment_id=item.partner_assignment_id,
        ),
        "severity": risk["severity"],
        "detail": risk["reason"],
        "related_activity_id": item.activity_id,
    }

    return send_action(
        sender=sender,
        school=school,
        issue=issue,
        fy=item.fy or "",
        note=note,
        month_of_fy=item.month,
        within_staff_ids=within_staff_ids,
    )


def send_team_action_to_program_lead(
    *, sender, program_lead_staff, issue_key: str, school, fy: str, note: str = ""
):
    """Ask a Program Lead to act on a condition across their team.

    The recipient is named rather than resolved from a school, because the ask
    is about a body of work rather than one record. A school is still required
    — TeamAction is school-scoped — so the caller passes the school the
    condition was most clearly observed at, and the message names the team.
    """
    if issue_key not in TEAM_OVERSIGHT_KEYS:
        raise ActionError(f"'{issue_key}' is not a team-level oversight ask.")
    if program_lead_staff is None or not getattr(program_lead_staff, "user_id", None):
        raise ActionError(
            "That team has no Program Lead on record, so there is nobody to "
            "hold responsible."
        )
    if school is None:
        raise ActionError(
            "This team has no planned school work in the period, so there is "
            "no record to attach the ask to."
        )

    issue = {
        "key": issue_key,
        "condition_key": f"oversight|{issue_key}|team|{program_lead_staff.id}|{fy}",
        "severity": "high",
        "detail": "",
    }

    return send_action(
        sender=sender,
        school=school,
        issue=issue,
        fy=fy,
        recipient_staff=program_lead_staff,
        note=note,
    )
