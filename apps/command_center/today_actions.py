"""Decisions taken on the Today queue without leaving it (owner, 2026-09-14).

"Today should allow the CCEO, PL, IA and every role to take tangible actions.
Right now it looks like a page to read." The queue rows came from the derived
To-Do engine (apps.command_center.todo_service) as links: every decision cost a
page load, a hunt for the record, and a trip back. This module turns the rows
that ARE a single decision into buttons on the row.

The rule that keeps it safe: Today never decides anything itself. Each action
calls the same domain service the record's own page calls, so the authority
check, the state machine, the notification and the audit row are the service's
— Today adds only a record of who cleared what from Today
(TodayActionRecord), which is what "cleared today" counts.

A row is actionable when its To-Do id names an adapter here. Everything else
keeps its link, and every row can be snoozed (TodoSnooze), which hides it from
Today until the chosen day without touching the work itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse
from datetime import timedelta
from typing import Callable

from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

#: The snooze choices a row offers, in days.
SNOOZE_DAYS = {"tomorrow": 1, "next_week": 7}


@dataclass(frozen=True)
class Operation:
    key: str
    label: str
    tone: str = "secondary"  # primary | secondary | danger
    #: "" when the decision needs no words; "required" when the service refuses
    #: without them (a return, a decline, a rejection); "optional" for a note.
    reason: str = ""
    reason_label: str = ""
    #: An attestation the person must tick before the service is called.
    attest: str = ""
    #: A short text the service needs, as (field name, label).
    field: tuple[str, str] | None = None
    #: Opens the record's own form in the drawer instead of deciding inline;
    #: built from (record id, To-Do row).
    drawer: Callable[[str, dict], str] | None = None


@dataclass(frozen=True)
class Adapter:
    pattern: re.Pattern
    kind: str
    operations: tuple[Operation, ...]
    perform: Callable[..., str] | None = None
    #: Only rows whose link matches (the same id shape can mean two things).
    url_contains: str = ""


def _role(principal) -> str:
    return getattr(principal, "active_role", "") or ""


# ── The decisions ───────────────────────────────────────────────────────────


def _pl_completion(principal, record_id, op, reason, attested, fields) -> str:
    from apps.pl_review import services

    if op == "confirm":
        services.confirm(record_id, principal)
        return "Completion confirmed and sent to Impact Assessment."
    services.return_activity(record_id, {"reason": reason}, principal)
    return "Completion returned to the officer with your reason."


def _weekly_approval(principal, record_id, op, reason, attested, fields) -> str:
    from apps.fund_requests import pl_approval_service
    from apps.fund_requests.models import WeeklyFundRequest

    if _role(principal) != "Program Lead":
        raise Forbidden("Open the request to decide it.")
    wfr = WeeklyFundRequest.objects.filter(id=record_id).first()
    if wfr is None:
        raise NotFoundError("Fund request not found.")
    week = wfr.week_start_date.isoformat()
    if op == "approve":
        pl_approval_service.approve(principal, wfr.responsible_user, week)
        return (
            f"Approved UGX {wfr.total_amount:,} for the week of "
            f"{wfr.week_start_date:%-d %b}; the Accountant can now disburse it."
        )
    pl_approval_service.return_request(
        principal, wfr.responsible_user, week, {"reason": reason}
    )
    return "Fund request returned to the officer with your reason."


def _leave(principal, record_id, op, reason, attested, fields) -> str:
    from apps.hr.leave_services import LeaveApprovalService
    from apps.hr.models import Leave

    leave = Leave.objects.filter(id=record_id).select_related("staff").first()
    if leave is None:
        raise NotFoundError("Leave request not found.")
    if _role(principal) == "Program Lead":
        # The approvals page's own rule: a lead decides their team's leave.
        from apps.accounts.models import StaffSupervisorAssignment

        if not StaffSupervisorAssignment.objects.filter(
            supervisee=leave.staff, supervisor__user_id=principal.id
        ).exists():
            raise Forbidden("You can only decide leave for your own team members.")
    if op == "approve":
        LeaveApprovalService.approve_request(record_id, principal)
        return "Leave approved; the team is told who covers."
    LeaveApprovalService.reject_request(record_id, principal, reason)
    return "Leave request declined; the staff member is told why."


def _visit_request(principal, record_id, op, reason, attested, fields) -> str:
    from apps.planning import visit_requests

    if op == "approve":
        visit_requests.approve(record_id, principal, reason)
        return "Visit request approved; it is now scheduled work."
    visit_requests.decline(record_id, principal, reason)
    return "Visit request declined; the requester is told why."


def _weekly_receipt(principal, record_id, op, reason, attested, fields) -> str:
    from apps.fund_requests.weekly_service import confirm_receipt

    confirm_receipt(record_id, principal, bank_message_received=attested)
    return "Receipt confirmed; you can now account for the week's spend."


def _monthly_receipt(principal, record_id, op, reason, attested, fields) -> str:
    from apps.fund_requests.disbursement_dashboard_service import confirm_receipt

    if not attested:
        raise BadRequest(
            "Confirm only after receiving the bank message and checking the funds arrived."
        )
    confirm_receipt(principal, record_id)
    return "Receipt confirmed."


def _ssa_verification(principal, record_id, op, reason, attested, fields) -> str:
    from apps.ssa.models import SsaRecord
    from apps.ssa.services import return_record, verify_record

    record = (
        SsaRecord.objects.filter(id=record_id, deleted_at__isnull=True)
        .select_related("school")
        .first()
    )
    if record is None:
        raise NotFoundError("SSA record not found.")
    if op == "confirm":
        verify_record(record, principal)
        return f"SSA for {record.school.name} confirmed; it now informs planning."
    return_record(record, principal, reason)
    return f"SSA for {record.school.name} returned to its collector with your reason."


def _weekly_request(principal, record_id, op, reason, attested, fields) -> str:
    from apps.fund_requests.weekly_service import request_advance

    request_advance(record_id, principal)
    return "Sent to your Program Lead for approval."


def _partner_evidence(principal, record_id, op, reason, attested, fields) -> str:
    from apps.activities.models import Activity
    from apps.activities.services import ia_confirm, is_partner_ssa_support_activity
    from apps.core.scoping import activity_country_q, resolve_user_scope

    activity = (
        Activity.objects.filter(id=record_id, deleted_at__isnull=True)
        .filter(activity_country_q(resolve_user_scope(principal)))
        .first()
    )
    if activity is None:
        raise NotFoundError("Activity not found.")
    if activity.delivery_type != "partner":
        raise BadRequest("Staff work is verified against its checklist; open it.")
    if is_partner_ssa_support_activity(activity):
        raise BadRequest("Open the evidence to record this partner's SSA completion.")
    ia_confirm(
        activity.id,
        {
            "salesforceId": (fields or {}).get("salesforce_id", ""),
            "verificationNote": reason,
        },
        principal,
    )
    return "Partner evidence confirmed; the activity is verified."


def _query(row: dict) -> dict[str, str]:
    return {
        k: v[0]
        for k, v in parse_qs(urlparse(row.get("action_url") or "").query).items()
    }


_CONFIRM = Operation("confirm", "Confirm", tone="primary")
_APPROVE = Operation("approve", "Approve", tone="primary")


def _return(label="Return", reason_label="What needs correcting") -> Operation:
    return Operation(
        "return", label, tone="secondary", reason="required", reason_label=reason_label
    )


_RECEIPT = Operation(
    "confirm",
    "Confirm receipt",
    tone="primary",
    attest="I received the bank message and the funds arrived",
)


def _open(key: str, label: str, url: Callable[[str, dict], str], tone="primary"):
    return Operation(key, label, tone=tone, drawer=url)


ADAPTERS: tuple[Adapter, ...] = (
    Adapter(
        re.compile(r"^plrev-(?P<id>.+)$"),
        "completion_review",
        (
            _CONFIRM,
            _return(),
            _open(
                "review",
                "Review evidence",
                lambda rid, row: f"/pl/review-queue/{rid}/drawer",
                tone="ghost",
            ),
        ),
        _pl_completion,
    ),
    Adapter(
        re.compile(r"^wfr-appr-(?P<id>.+)$"),
        "weekly_fund_approval",
        (_APPROVE, _return(reason_label="Why the request goes back")),
        _weekly_approval,
    ),
    Adapter(
        re.compile(r"^wfrreceipt-(?P<id>.+)$"),
        "weekly_receipt",
        (_RECEIPT,),
        _weekly_receipt,
    ),
    Adapter(
        re.compile(r"^frreceipt-(?P<id>.+)$"),
        "monthly_receipt",
        (_RECEIPT,),
        _monthly_receipt,
    ),
    Adapter(
        re.compile(r"^wfr-(?P<id>[^-]+)$"),
        "weekly_fund_request",
        (Operation("send", "Send for approval", tone="primary"),),
        _weekly_request,
    ),
    Adapter(
        re.compile(r"^leave-(?P<id>.+)$"),
        "leave_approval",
        (
            _APPROVE,
            Operation(
                "reject",
                "Decline",
                reason="required",
                reason_label="Why the leave is declined",
            ),
        ),
        _leave,
    ),
    Adapter(
        re.compile(r"^visitreq-(?P<id>.+)$"),
        "visit_request",
        (
            Operation(
                "approve",
                "Approve",
                tone="primary",
                reason="optional",
                reason_label="Note for the requester (optional)",
            ),
            Operation(
                "decline",
                "Decline",
                reason="required",
                reason_label="Why the visit is declined",
            ),
        ),
        _visit_request,
    ),
    Adapter(
        re.compile(r"^ssa-next-(?P<id>.+)$"),
        "ssa_verification",
        (_CONFIRM, _return(reason_label="What the collector must correct")),
        _ssa_verification,
    ),
    Adapter(
        re.compile(r"^ia-(?P<id>[a-z0-9]{20,})$"),
        "partner_evidence",
        (
            Operation(
                "confirm",
                "Confirm",
                tone="primary",
                reason="optional",
                reason_label="Verification note (optional)",
                field=("salesforce_id", "Salesforce activity ID"),
            ),
            _open(
                "return",
                "Return",
                lambda rid, row: f"/ia/partner-evidence/{rid}/return-drawer",
                tone="secondary",
            ),
        ),
        _partner_evidence,
        url_contains="/ia/partner-evidence/",
    ),
    Adapter(
        re.compile(r"^sch-(?P<id>.+)-contact$"),
        "school_contact",
        (_open("fix", "Fix contact", lambda rid, row: f"/schools/{rid}/edit-drawer"),),
    ),
    Adapter(
        re.compile(r"^sch-(?P<id>.+)-ssa$"),
        "ssa_visit",
        (
            _open(
                "schedule",
                "Schedule SSA visit",
                lambda rid, row: f"/planning/schedule-modal?school_id={rid}",
            ),
        ),
    ),
    Adapter(
        re.compile(r"^coaching-(?P<id>.+)$"),
        "coaching",
        (
            _open(
                "log",
                "Log it",
                lambda rid, row: "/team/coaching/new?"
                + "&".join(
                    f"{k}={v}" for k, v in _query(row).items() if k not in ("open",)
                ),
            ),
        ),
    ),
)


#: An activity's next step is already a drawer form: a row that links to one
#: opens it in place, whatever produced the row (My Plan's next-action rows).
_ACTIVITY_DRAWER = re.compile(
    r"^/activities/[^/?#]+/(start|complete|partner-ssa-complete|evidence|"
    r"salesforce-id|submit|attendance|ssa-upload)$"
)


def _link_operations(row: dict) -> list[dict]:
    url = row.get("action_url") or ""
    if not _ACTIVITY_DRAWER.match(url):
        return []
    return [
        {
            "key": "open_form",
            "label": row.get("action_label") or "Open",
            "tone": "primary",
            "reason": "",
            "reason_label": "",
            "attest": "",
            "field": None,
            "drawer_url": url,
            "needs_form": False,
        }
    ]


def adapter_for(todo_id: str, row: dict | None = None) -> tuple[Adapter | None, str]:
    for adapter in ADAPTERS:
        match = adapter.pattern.match(todo_id or "")
        if not match:
            continue
        # The link tells two rows with one id shape apart; a decision posted
        # without its row is refused by the service when the shape was wrong.
        if (
            row is not None
            and adapter.url_contains
            and adapter.url_contains not in (row.get("action_url") or "")
        ):
            continue
        return adapter, match.group("id")
    return None, ""


# ── Rows ────────────────────────────────────────────────────────────────────


def row_slug(todo_id: str) -> str:
    """An element id for the row, stable across the swap that replaces it."""
    import hashlib

    return (
        "today-"
        + hashlib.sha1(todo_id.encode(), usedforsecurity=False).hexdigest()[:12]
    )


def _amounts(rows) -> dict[str, int]:
    """UGX on the money rows, in one read per register."""
    from apps.fund_requests.models import FundRequest, WeeklyFundRequest

    weekly, monthly = set(), set()
    for row in rows:
        adapter, record_id = adapter_for(row.get("id", ""))
        if adapter and adapter.kind in ("weekly_fund_approval", "weekly_receipt"):
            weekly.add(record_id)
        elif adapter and adapter.kind == "monthly_receipt":
            monthly.add(record_id)
    out: dict[str, int] = {}
    if weekly:
        for rid, total, disbursed in WeeklyFundRequest.objects.filter(
            id__in=weekly
        ).values_list("id", "total_amount", "disbursed_amount"):
            out[rid] = disbursed or total or 0
    if monthly:
        for rid, total in FundRequest.objects.filter(id__in=monthly).values_list(
            "id", "total_amount"
        ):
            out[rid] = total or 0
    return out


def decorate(rows, principal) -> list[dict]:
    """Each row with `today`: its element id and, when it is one decision, the
    operations the row offers. The rows themselves are not changed."""
    amounts = _amounts(rows)
    out = []
    for row in rows:
        adapter, record_id = adapter_for(row.get("id", ""), row)
        operations = []
        for operation in adapter.operations if adapter else ():
            operations.append(
                {
                    "key": operation.key,
                    "label": operation.label,
                    "tone": operation.tone,
                    "reason": operation.reason,
                    "reason_label": operation.reason_label,
                    "attest": operation.attest,
                    "field": operation.field,
                    "drawer_url": (
                        operation.drawer(record_id, row) if operation.drawer else ""
                    ),
                    # Anything more than one press opens a small form first.
                    "needs_form": bool(
                        operation.reason or operation.attest or operation.field
                    ),
                }
            )
        if not operations:
            operations = _link_operations(row)
        today = {
            "slug": row_slug(row.get("id", "")),
            "kind": adapter.kind if adapter else ("record_form" if operations else ""),
            "operations": operations,
            "amount": amounts.get(record_id),
        }
        out.append({**row, "today": today})
    return out


def perform(
    principal, todo_id: str, op_key: str, *, reason="", attested=False, fields=None
) -> str:
    """Take one decision from Today through its domain service."""
    from apps.audit.services import log as audit_log
    from apps.command_center.models import TodayActionRecord

    adapter, record_id = adapter_for(todo_id or "")
    if adapter is None or adapter.perform is None:
        raise BadRequest("This item is decided on its own page.")
    operation = next(
        (o for o in adapter.operations if o.key == op_key and o.drawer is None), None
    )
    if operation is None:
        raise BadRequest("That decision is not available for this item.")
    fields = {k: (v or "").strip()[:128] for k, v in (fields or {}).items()}
    if operation.field and not fields.get(operation.field[0]):
        raise BadRequest(f"{operation.field[1]} is required.")
    reason = (reason or "").strip()
    if operation.reason == "required" and not reason:
        raise BadRequest(f"{operation.reason_label or 'A reason'} is required.")
    if len(reason) > 2000:
        raise BadRequest("Keep the reason under 2,000 characters.")
    if operation.attest and not attested:
        raise BadRequest(f"Tick “{operation.attest}” first.")
    message = adapter.perform(
        principal, record_id, op_key, reason, bool(attested), fields
    )
    TodayActionRecord.objects.create(
        user_id=str(principal.id),
        todo_id=todo_id[:128],
        kind=adapter.kind,
        operation=op_key,
        record_id=record_id[:64],
        reason=reason,
    )
    audit_log(
        action="today.decision",
        subject_kind=adapter.kind,
        subject_id=record_id,
        actor_id=str(principal.id),
        actor_role=_role(principal),
        success=True,
        reason=reason or None,
        payload={"operation": op_key, "todo_id": todo_id},
    )
    forget_queue(principal)
    return message


def forget_queue(principal) -> None:
    """Drop the principal's cached queue so the next read reflects the change."""
    from apps.command_center.todo_service import todo_snapshot_key
    from django.core.cache import cache

    try:
        cache.delete(todo_snapshot_key(principal))
    except Exception:  # noqa: BLE001 - the cache is an optimisation only
        pass


# ── Snoozing ────────────────────────────────────────────────────────────────


def snooze(principal, todo_id: str, choice: str, *, title: str = ""):
    from apps.command_center.models import TodoSnooze

    days = SNOOZE_DAYS.get(choice)
    if not todo_id or days is None:
        raise BadRequest("Choose when the item comes back.")
    until = timezone.localdate() + timedelta(days=days)
    snoozed, _ = TodoSnooze.objects.update_or_create(
        user_id=str(principal.id),
        todo_id=todo_id[:128],
        defaults={"until": until, "title": (title or "")[:255]},
    )
    return snoozed


def unsnooze(principal, todo_id: str) -> None:
    from apps.command_center.models import TodoSnooze

    TodoSnooze.objects.filter(user_id=str(principal.id), todo_id=todo_id).delete()


def snoozed_ids(principal) -> set[str]:
    from apps.command_center.models import TodoSnooze

    return set(
        TodoSnooze.objects.filter(
            user_id=str(principal.id), until__gt=timezone.localdate()
        ).values_list("todo_id", flat=True)
    )


def cleared_today(principal) -> int:
    from apps.command_center.models import TodayActionRecord

    return TodayActionRecord.objects.filter(
        user_id=str(principal.id), created_at__date=timezone.localdate()
    ).count()


# ── Impact Assessment: the next SSA to verify ───────────────────────────────


def next_ssa_row(principal) -> dict | None:
    """The oldest SSA this verifier may decide, as a queue row with its scores,
    so a verifier works the queue from Today one record at a time."""
    from apps.activities.ia_todos import pending_ssa_for_verifier
    from apps.core.permissions import has_permission
    from apps.core.rbac import Permission
    from apps.core.scoping import resolve_user_scope

    if not has_permission(principal, Permission.IA_VERIFY.value):
        return None
    records = pending_ssa_for_verifier(principal, resolve_user_scope(principal))
    total = records.count()
    record = (
        records.select_related("school")
        .prefetch_related("scores")
        .order_by("created_at", "id")
        .first()
    )
    if record is None:
        return None
    scores = sorted(
        ((s.intervention, s.score) for s in record.scores.all()), key=lambda p: p[1]
    )
    return {
        "id": f"ssa-next-{record.id}",
        "title": "Verify SSA",
        "description": (
            f"{record.school.name} · assessed {record.date_of_ssa:%-d %b %Y}"
            + (f" · average {record.average_score:.1f}" if record.average_score else "")
        ),
        "category": "SSA Verification",
        "priority": "high",
        "status_key": "waiting_me",
        "status_label": "Waiting on Me",
        "status_tone": "info",
        "due_label": f"{total} waiting" if total > 1 else "Last one",
        "due_tone": "neutral",
        "linked": record.school.name,
        "action_label": "Open queue",
        "action_url": "/ssa/verification/",
        "actionable": True,
        "source": "SSA verification",
        "ssa_scores": [
            {"label": str(intervention).replace("_", " ").title(), "score": score}
            for intervention, score in scores
        ],
    }
