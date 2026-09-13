"""Flags service — CD→PL flag handoff (CD raises; assigned PL acts).

The loop closes both ways (Program Lead alignment, owner 2026-09-13: the PL
"partners with … country directors to align goals"). The Country Director
raises a flag to a Programme Lead in their own country; the PL acknowledges it
and later resolves it with a note saying what was done; each step tells the
Country Director, and each step closes the notice it answers, so neither side
carries a stale "Respond to Flag" row once the other has acted.
"""

from __future__ import annotations

from django.utils import timezone

from apps.accounts.models import User
from apps.audit.services import log as audit_log
from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.rbac import EdifyRole

from .models import CdFlag, CdFlagStatus

# The conditions this channel announces, named so the transition that answers
# one can close it (apps.notifications.services.resolve_condition).
FLAG_RAISED = "cd_flag_raised"
FLAG_ACKNOWLEDGED = "cd_flag_acknowledged"
FLAG_RESOLVED = "cd_flag_resolved"


def raise_flag(data: dict, principal) -> dict:
    # Only the CD raises flags.
    if principal.active_role not in (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.ADMIN.value,
    ):
        raise BadRequest("Only the Country Director may raise flags.")
    assigned_to = data.get("assignedToUserId")
    if not assigned_to:
        raise BadRequest("assignedToUserId is required.")
    # The picker only offers the Programme Leads in the director's country;
    # the same rule is enforced here, so a hand-edited form cannot hand a flag
    # to a Programme Lead in another country (or to someone who is not one).
    if str(assigned_to) not in {row["id"] for row in program_leads(principal)}:
        raise BadRequest("Choose a Programme Lead in your country.")
    flag = CdFlag.objects.create(
        raised_by_user_id=principal.user_id,
        raised_by_name=principal.name,
        assigned_to_user_id=assigned_to,
        category=data.get("category", "general"),
        scope_type=data.get("scopeType"),
        scope_id=data.get("scopeId"),
        scope_name=data.get("scopeName"),
        note=data.get("note", ""),
        recommended_action=data.get("recommendedAction"),
        priority=data.get("priority", "normal"),
        due_date=data.get("dueDate"),
    )
    # The flag is the CD's way of asking a PL to act; it used to be raised in
    # silence, and the PL learned of it only by opening the page.
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=FLAG_RAISED,
            category="leadership",
            priority="high" if flag.priority == "high" else "normal",
            title="Flag from the Country Director",
            body=(
                flag.note or flag.recommended_action or "Please respond to this flag."
            )[:500],
            context_type="CdFlag",
            context_id=flag.id,
            recipients=[assigned_to],
        )
    except Exception:  # noqa: BLE001 - never fail the flag over a notice
        pass
    return _serialize(flag)


def program_leads(principal) -> list[dict]:
    """The assignable actors for a CD flag.

    Restricted to the roles that can actually raise one: this is a picker, and
    it previously returned every Program Lead's name and email to any caller
    holding analytics.view — a staff directory by side door. Email is dropped
    entirely; assignment needs an id and a name, nothing more.

    A Country Director assigns within their own country (the country on their
    staff profile, the platform's country boundary — apps.core.scoping
    person_country_q). The picker listed every Programme Lead in the
    deployment, so a second country's leads were one click away. Admin, and a
    director with no country on file, keep the deployment-wide list.
    """
    role = getattr(principal, "active_role", "")
    if role not in (EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.ADMIN.value):
        raise Forbidden("Only the Country Director assigns flags to a Program Lead.")
    from apps.core.scoping import person_country_q, resolve_user_scope

    users = User.objects.filter(
        deleted_at__isnull=True,
        status="active",
        roles__contains=[EdifyRole.COUNTRY_PROGRAM_LEAD.value],
    )
    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        users = users.filter(person_country_q(resolve_user_scope(principal), "id"))
    return [{"id": u.id, "name": u.name} for u in users.order_by("name")]


# Roles allowed to read the whole flag board rather than just their own rows.
# IA/Admin keep global read-only monitoring; the CD sees what they raised and
# the PL sees what was assigned to them (both handled by the row filter below).
_FLAG_MONITOR_ROLES = (
    EdifyRole.IMPACT_ASSESSMENT.value,
    EdifyRole.ADMIN.value,
)


def _actor_id(principal) -> str | None:
    """The acting user's id. The API passes an AuthPrincipal (`.user_id`); the
    server-rendered views pass the User model itself (`.id`)."""
    return getattr(principal, "user_id", None) or getattr(principal, "id", None)


def flags_visible_to(principal):
    """The flag queryset a principal may read.

    Mirrors the quality-checks page rule: a CD sees the flags they raised, the
    assigned PL sees the flags routed to them, IA/Admin monitor everything, and
    nobody else sees any. Without this the API returned every flag to any
    authenticated caller.
    """
    qs = CdFlag.objects.all().order_by("-created_at")
    role = getattr(principal, "active_role", "")
    if role in _FLAG_MONITOR_ROLES:
        return qs
    user_id = _actor_id(principal)
    if not user_id:
        return qs.none()
    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        return qs.filter(raised_by_user_id=user_id)
    if role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        return qs.filter(assigned_to_user_id=user_id)
    return qs.none()


def list_flags(query: dict, principal) -> list[dict]:
    qs = flags_visible_to(principal)
    if query.get("status"):
        qs = qs.filter(status=query["status"])
    return [_serialize(f) for f in qs]


def update_flag(flag_id: str, data: dict, principal) -> dict:
    """The assigned Programme Lead acknowledges or resolves a flag.

    Resolving requires a note — the Country Director raised the flag to get
    something done, and a flag closed with no word on what was done teaches
    them to stop raising flags. Both steps notify the raiser and close the
    notice the step answers.
    """
    # Re-derive from the readable set: taking the id straight from the request
    # would let a caller act on a flag they can't see.
    flag = flags_visible_to(principal).filter(id=flag_id).first()
    if not flag:
        raise NotFoundError("Flag not found.")
    role = getattr(principal, "active_role", "")
    is_assignee = flag.assigned_to_user_id == _actor_id(principal)
    if not (is_assignee or role == EdifyRole.ADMIN.value):
        raise Forbidden("Only the assigned Program Lead may act on this flag.")
    action = data.get("action", "acknowledge")
    if action not in ("acknowledge", "resolve"):
        raise BadRequest("Unknown flag action.")
    if flag.status == CdFlagStatus.RESOLVED:
        raise BadRequest("This flag is already resolved.")
    note = (data.get("note") or "").strip()
    if action == "acknowledge":
        if flag.status != CdFlagStatus.OPEN:
            raise BadRequest("This flag has already been acknowledged.")
        flag.status = CdFlagStatus.ACKNOWLEDGED
    else:
        if not note:
            raise BadRequest(
                "Add a resolution note saying what was done — the Country "
                "Director reads it."
            )
        flag.status = CdFlagStatus.RESOLVED
        flag.resolved_at = timezone.now()
        flag.resolution_note = note
    if note and not flag.resolution_note:
        flag.resolution_note = note
    flag.save()
    audit_log(
        action=f"flag_{action}",
        subject_kind="CdFlag",
        subject_id=flag.id,
        actor_id=_actor_id(principal),
        actor_role=role,
        payload={"status": flag.status},
    )
    _close_the_loop(flag, action, principal, note)
    return _serialize(flag)


def _close_the_loop(flag: CdFlag, action: str, principal, note: str) -> None:
    """Tell the raising Country Director, and close what this step answers.

    Acknowledging answers the Programme Lead's "Respond to Flag" notice;
    resolving answers it too (a flag can be resolved straight from open) and
    also the director's "acknowledged" notice, which was waiting for this.
    Never fails the flag over a notice.
    """
    try:
        from apps.notifications.services import (
            WorkflowNotificationService,
            resolve_condition,
        )

        answered = [FLAG_RAISED]
        if action == "resolve":
            answered.append(FLAG_ACKNOWLEDGED)
        resolve_condition(answered, "CdFlag", flag.id)
        if not flag.raised_by_user_id:
            return
        actor = getattr(principal, "name", None) or "The Programme Lead"
        about = flag.scope_name or flag.category or "your flag"
        if action == "acknowledge":
            title = f"{actor} acknowledged your flag"
            body = f"{about}: {flag.note or ''}"
            event = FLAG_ACKNOWLEDGED
        else:
            title = f"{actor} resolved your flag"
            body = f"{about}: {note}"
            event = FLAG_RESOLVED
        WorkflowNotificationService.trigger(
            event_type=event,
            category="leadership",
            priority="normal",
            title=title,
            body=body[:500],
            context_type="CdFlag",
            context_id=flag.id,
            recipients=[flag.raised_by_user_id],
        )
    except Exception:  # noqa: BLE001 - never fail the flag over a notice
        pass


def _serialize(f: CdFlag) -> dict:
    return {
        "id": f.id,
        "raisedByUserId": f.raised_by_user_id,
        "raisedByName": f.raised_by_name,
        "assignedToUserId": f.assigned_to_user_id,
        "category": f.category,
        "scopeType": f.scope_type,
        "scopeId": f.scope_id,
        "scopeName": f.scope_name,
        "note": f.note,
        "recommendedAction": f.recommended_action,
        "priority": f.priority,
        "dueDate": f.due_date,
        "status": f.status,
        "resolutionNote": f.resolution_note,
        "resolvedAt": f.resolved_at.isoformat() if f.resolved_at else None,
    }
