"""The Decision Log — the audit trail, made useful to the people it governs.

A tamper-evident, hash-chained audit service already existed, but no leadership
role could open any surface that reads it: the audit log is Admin-only, the HR
log is HR-only, and finance approval history is Accountant-only. So the roles
holding the most consequential powers — approving a country's money, locking an
annual baseline, closing a project — had the least visibility into what had
been decided and by whom.

This is deliberately *not* the raw audit log. It is the subset that represents
a decision somebody made, grouped into the vocabulary leadership actually
thinks in, and scoped so a Country Director sees their country's decisions
rather than every row in the system.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core.rbac import EdifyRole

from .models import AuditLog


# Actions that represent a human decision, grouped for the filter chips. Kept
# explicit rather than pattern-matched: an audit stream contains a great deal
# of machinery, and a log that shows everything gets read by nobody.
DECISION_ACTIONS = {
    "Money": [
        "country_budget_approved_by_rvp",
        "country_budget_returned_by_rvp",
        "country_budget_submitted_to_rvp",
        "country_budget_sent_to_accountant",
        "country_budget_disbursed",
        "country_budget_closed",
        "rvp_annual_approve",
        "rvp_annual_return",
        "finance_partner_payment_clear",
        "accountability_submitted",
    ],
    "People": [
        "pd_supervisor_approve",
        "pd_supervisor_return",
        "pd_hr_approve",
        "pd_hr_return",
        "pd_hr_reject",
        "leave.approved",
        "leave.rejected",
        "hr.coverage_granted",
        "hr.coverage_reassigned",
        "hr.coverage_revoked",
    ],
    "Programme": [
        "project_create",
        "special_project",
        "strategy_note",
        "plan_approve",
        "plan_return",
        "school.assign_project",
        "school.bulk_assign_project",
    ],
    "Quality": [
        "ssa_verify",
        "ssa_return",
        "ia_verify_completion",
        "ia_return_completion",
        "pl_approve_completion",
        "pl_return_completion",
        "flag_acknowledge",
        "flag_resolve",
    ],
    "Escalation": [
        "escalation_raise",
        "escalation_acknowledge",
        "escalation_resolve",
    ],
}

# Human labels. An audit action name is a developer's word; a decision log is
# read by directors.
ACTION_LABELS = {
    "country_budget_approved_by_rvp": "Approved the country monthly budget",
    "country_budget_returned_by_rvp": "Returned the country monthly budget",
    "country_budget_submitted_to_rvp": "Submitted the country budget to the RVP",
    "country_budget_sent_to_accountant": "Handed the budget to the Accountant",
    "country_budget_disbursed": "Marked the country budget disbursed",
    "country_budget_closed": "Closed the country budget month",
    "rvp_annual_approve": "Approved and locked the annual baseline",
    "rvp_annual_return": "Returned the annual budget",
    "finance_partner_payment_clear": "Cleared a partner payment",
    "accountability_submitted": "Submitted accountability",
    "pd_supervisor_approve": "Approved a development request (supervisor)",
    "pd_supervisor_return": "Returned a development request (supervisor)",
    "pd_hr_approve": "Approved a development request (HR stage)",
    "pd_hr_return": "Returned a development request (HR stage)",
    "pd_hr_reject": "Rejected a development request",
    "leave.approved": "Approved leave",
    "leave.rejected": "Rejected leave",
    "hr.coverage_granted": "Granted cover",
    "hr.coverage_reassigned": "Reassigned cover",
    "hr.coverage_revoked": "Revoked cover",
    "project_create": "Created a special project",
    "special_project": "Made a strategic project decision",
    "strategy_note": "Issued strategic guidance",
    "plan_approve": "Approved a monthly plan",
    "plan_return": "Returned a monthly plan",
    "school.assign_project": "Assigned a school to a project",
    "school.bulk_assign_project": "Bulk-assigned schools to a project",
    "ssa_verify": "Confirmed an SSA record",
    "ssa_return": "Returned an SSA record",
    "ia_verify_completion": "Verified an activity",
    "ia_return_completion": "Returned an activity",
    "pl_approve_completion": "Confirmed an activity",
    "pl_return_completion": "Returned an activity",
    "flag_acknowledge": "Acknowledged a quality flag",
    "flag_resolve": "Resolved a quality flag",
    "escalation_raise": "Escalated to the RVP",
    "escalation_acknowledge": "Acknowledged an escalation",
    "escalation_resolve": "Decided an escalation",
}

ALL_DECISION_ACTIONS = [a for group in DECISION_ACTIONS.values() for a in group]

# Who may read whose decisions.
GLOBAL_READERS = {EdifyRole.ADMIN.value, EdifyRole.REGIONAL_VICE_PRESIDENT.value}
COUNTRY_READERS = {EdifyRole.COUNTRY_DIRECTOR.value}


def decision_log(principal, query: dict | None = None) -> dict:
    query = query or {}
    role = getattr(principal, "active_role", "")

    rows = AuditLog.objects.filter(action__in=ALL_DECISION_ACTIONS)

    group = query.get("group")
    if group and group in DECISION_ACTIONS:
        rows = rows.filter(action__in=DECISION_ACTIONS[group])

    days = _int(query.get("days"), 30)
    rows = rows.filter(created_at__gte=timezone.now() - timedelta(days=days))

    if role in GLOBAL_READERS:
        pass  # the RVP oversees the whole deployment
    elif role in COUNTRY_READERS:
        rows = _country_filtered(rows, principal)
    else:
        # Everyone else sees only what they themselves decided — useful, and
        # never a window into a peer's record.
        rows = rows.filter(actor_id=getattr(principal, "id", None))

    if query.get("actor"):
        rows = rows.filter(actor_id=query["actor"])

    rows = rows.select_related().order_by("-created_at")[:200]

    serialized = [_serialize(r) for r in rows]
    return {
        "rows": serialized,
        "groups": list(DECISION_ACTIONS),
        "activeGroup": group or "",
        "days": days,
        "dayOptions": [7, 30, 90],
        "total": len(serialized),
        "scopeLabel": _scope_label(role),
    }


def _country_filtered(rows, principal):
    """A CD sees decisions taken by people in their country.

    Audit rows carry no country column, so this resolves the actor set once
    rather than trying to infer geography from each payload.
    """
    from apps.accounts.models import StaffProfile

    sp = StaffProfile.objects.filter(user=principal).only("country").first()
    country = getattr(sp, "country", None)
    if not country:
        return rows.filter(actor_id=getattr(principal, "id", None))
    actor_ids = list(
        StaffProfile.objects.filter(country=country).values_list("user_id", flat=True)
    )
    return rows.filter(actor_id__in=[a for a in actor_ids if a])


def _scope_label(role: str) -> str:
    if role in GLOBAL_READERS:
        return "All decisions across the deployment"
    if role in COUNTRY_READERS:
        return "Decisions taken in your country"
    return "Your own decisions"


def _serialize(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "action": row.action,
        "label": ACTION_LABELS.get(row.action, row.action.replace("_", " ").capitalize()),
        "group": _group_for(row.action),
        "actorRole": row.actor_role,
        "actorId": row.actor_id,
        "subjectKind": row.subject_kind,
        "subjectId": row.subject_id,
        "reason": row.reason,
        "success": row.success,
        "at": row.created_at,
        "detail": _detail(row),
    }


def _group_for(action: str) -> str:
    for name, actions in DECISION_ACTIONS.items():
        if action in actions:
            return name
    return "Other"


def _detail(row: AuditLog) -> str:
    """A one-line human summary drawn from whatever the payload carries."""
    payload = row.payload if isinstance(row.payload, dict) else {}
    for key in (
        "staffName",
        "schoolName",
        "projectName",
        "name",
        "subject",
        "course",
        "monthKey",
    ):
        if payload.get(key):
            return str(payload[key])
    if payload.get("decision"):
        return str(payload["decision"]).replace("_", " ").capitalize()
    return row.subject_id or "—"


def _int(value, default: int) -> int:
    try:
        return max(1, min(365, int(value)))
    except (TypeError, ValueError):
        return default


__all__ = ["decision_log", "DECISION_ACTIONS", "ACTION_LABELS"]
