"""Program Lead monthly team-budget submission workflow.

Scheduled activities create the live monthly budget.  They do *not* send money
for approval by themselves.  A Program Lead deliberately refreshes a snapshot
of that budget, checks it, then submits the snapshot to the Country Director.
That snapshot is the only program amount the Country Budget will consolidate.
"""

from __future__ import annotations

from collections import defaultdict

from django.db import transaction
from django.utils import timezone

from apps.activities.models import ActivityScheduleCostLine
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope

from .models import FundRequest, FundRequestItem, FundRequestPeriod, FundRequestStatus
from .pl_approval_service import MONTHS, _category, _ugx


EDITABLE_STATUSES = {
    FundRequestStatus.DRAFT,
    FundRequestStatus.RETURNED_BY_CD,
}


def _period_key(fy: str, month: int) -> str:
    return f"{fy}-M{int(month)}"


def _require_program_lead(principal) -> None:
    if getattr(principal, "active_role", None) != "Program Lead":
        raise Forbidden("Only a Program Lead can prepare a team monthly request.")


def _team_owner_ids(principal) -> list[str]:
    """The PL and the people assigned to that PL's team — never other teams."""
    scope = resolve_user_scope(principal)
    owner_ids = {getattr(principal, "user_id", None) or getattr(principal, "id", None)}
    if scope.supervised_staff_ids:
        from apps.accounts.models import StaffProfile

        owner_ids.update(
            StaffProfile.objects.filter(id__in=scope.supervised_staff_ids).values_list(
                "user_id", flat=True
            )
        )
    return [owner_id for owner_id in owner_ids if owner_id]


def _live_month_lines(principal, fy: str, month: int):
    """Costed, scheduled work included in the same team monthly budget view."""
    return list(
        ActivityScheduleCostLine.objects.filter(
            fiscal_year=fy,
            month=month,
            responsible_user__in=_team_owner_ids(principal),
            activity__deleted_at__isnull=True,
            activity__scheduled_date__isnull=False,
        )
        .exclude(activity__status__in=["cancelled", "rejected"])
        .select_related("activity", "activity__school")
        .order_by("planned_date", "activity__activity_type", "label")
    )


def _team_request(principal, fy: str, month: int, *, lock=False):
    qs = FundRequest.objects.filter(
        submitted_by_user_id=principal.user_id,
        period=FundRequestPeriod.MONTHLY,
        period_key=_period_key(fy, month),
        scope="team",
    )
    return (qs.select_for_update() if lock else qs).first()


def _refresh_locked(principal, fy: str, month: int):
    request = _team_request(principal, fy, month, lock=True)
    if request and request.status not in EDITABLE_STATUSES:
        raise BadRequest(
            "This monthly request has already been sent to the Country Director. "
            "It can only be changed after it is returned."
        )

    lines = _live_month_lines(principal, fy, month)
    if not lines:
        raise BadRequest(
            "There is no scheduled, costed work in your team budget for this month yet."
        )

    total = sum(int(line.amount or 0) for line in lines)
    activity_count = len({line.activity_id for line in lines})
    if request is None:
        request = FundRequest.objects.create(
            fy=fy,
            period=FundRequestPeriod.MONTHLY,
            period_key=_period_key(fy, month),
            scope="team",
            submitted_by_user_id=principal.user_id,
            submitted_by_role="Program Lead",
            total_amount=total,
            activity_count=activity_count,
            status=FundRequestStatus.DRAFT,
        )
    else:
        request.items.all().delete()
        request.fy = fy
        request.submitted_by_role = "Program Lead"
        request.total_amount = total
        request.activity_count = activity_count
        request.status = FundRequestStatus.DRAFT
        request.reviewed_by_user_id = None
        request.reviewed_at = None
        request.review_note = None
        request.save(
            update_fields=[
                "fy",
                "submitted_by_role",
                "total_amount",
                "activity_count",
                "status",
                "reviewed_by_user_id",
                "reviewed_at",
                "review_note",
                "updated_at",
            ]
        )

    FundRequestItem.objects.bulk_create(
        [
            FundRequestItem(
                fund_request=request,
                activity_id=line.activity_id,
                activity_schedule_cost_line_id=line.id,
                amount=int(line.amount or 0),
                period=FundRequestPeriod.MONTHLY,
                period_key=_period_key(fy, month),
            )
            for line in lines
        ]
    )
    return request


def refresh_draft(principal, fy: str, month: int):
    """Explicitly fetch the current Team Budget into an editable request."""
    _require_program_lead(principal)
    with transaction.atomic():
        request = _refresh_locked(principal, fy, month)
    return request


def submit_to_cd(principal, fy: str, month: int):
    """Freeze the refreshed PL team-budget snapshot and route it to the CD."""
    _require_program_lead(principal)
    with transaction.atomic():
        request = _team_request(principal, fy, month, lock=True)
        if request and request.status == FundRequestStatus.SUBMITTED_TO_CD:
            raise BadRequest(
                "This monthly request is already waiting for the Country Director."
            )
        if request and request.status == FundRequestStatus.APPROVED_BY_CD:
            raise BadRequest(
                "This monthly request has already been approved by the Country Director."
            )
        request = _refresh_locked(principal, fy, month)
        request.status = FundRequestStatus.SUBMITTED_TO_CD
        request.reviewed_by_user_id = None
        request.reviewed_at = None
        request.review_note = None
        request.save(
            update_fields=[
                "status",
                "reviewed_by_user_id",
                "reviewed_at",
                "review_note",
                "updated_at",
            ]
        )

    _notify_country_directors(principal, request, month)
    _audit(principal, "monthly_team_request.submit_to_cd", request)
    return request


def _notify_country_directors(principal, request, month: int) -> None:
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        recipients = list(
            User.objects.filter(
                active_role="CountryDirector", is_active=True
            ).values_list("id", flat=True)
        )
        if recipients:
            WorkflowNotificationService.trigger(
                event_type="monthly_team_request_submitted",
                category="finance",
                priority="high",
                title="Program Lead monthly request ready for review",
                body=(
                    f"{MONTHS[month]} {request.fy} team request "
                    f"({_ugx(request.total_amount)}) is ready for Country Director review."
                ),
                context_type="FundRequest",
                context_id=request.id,
                recipients=recipients,
            )
    except Exception:  # noqa: BLE001 - notifications do not block a submission
        pass


def _audit(principal, action: str, request) -> None:
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="FundRequest",
            subject_id=request.id,
            actor_id=principal.user_id,
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload={"total": request.total_amount, "period_key": request.period_key},
        )
    except Exception:  # noqa: BLE001 - audit does not block a submission
        pass


def _status_meta(request):
    if not request:
        return (
            "Ready to review",
            "slate",
            "Fetch a review copy of your latest Team Budget before you submit it.",
        )
    meta = {
        FundRequestStatus.DRAFT: (
            "Draft ready for review",
            "warning",
            "Check this saved copy, then submit it to the Country Director when it is correct.",
        ),
        FundRequestStatus.SUBMITTED_TO_CD: (
            "Waiting for CD review",
            "info",
            "The Country Director will review this request with the other Program Leads' requests.",
        ),
        FundRequestStatus.APPROVED_BY_CD: (
            "Approved by CD",
            "success",
            "This request is included in the Country Director's consolidated budget.",
        ),
        FundRequestStatus.RETURNED_BY_CD: (
            "Returned for changes",
            "danger",
            request.review_note
            or "Refresh the Team Budget, make any plan changes, then submit again.",
        ),
    }
    return meta.get(
        request.status,
        (request.get_status_display(), "slate", "This request is no longer editable."),
    )


def _display_rows(lines):
    from apps.accounts.models import User

    names = dict(
        User.objects.filter(
            id__in={line.responsible_user for line in lines if line.responsible_user}
        ).values_list("id", "name")
    )
    rows = []
    staff_totals = defaultdict(
        lambda: {"name": "Unassigned", "total": 0, "activities": set()}
    )
    category_totals = defaultdict(int)
    cost_groups = {}
    for line in lines:
        activity = line.activity
        owner = line.responsible_user or "unassigned"
        staff_totals[owner]["name"] = names.get(owner, "Unassigned")
        staff_totals[owner]["total"] += int(line.amount or 0)
        staff_totals[owner]["activities"].add(line.activity_id)
        category = _category(activity.activity_type, activity.delivery_type)
        category_totals[category] += int(line.amount or 0)
        row = {
            "item": line.label or line.cost_setting_key.replace("_", " ").title(),
            "activity": activity.get_activity_type_display(),
            "staff": names.get(owner, "Unassigned"),
            "date": line.planned_date or activity.scheduled_date,
            "amount": int(line.amount or 0),
            "amount_fmt": _ugx(line.amount),
        }
        rows.append(row)
        group = cost_groups.setdefault(
            category,
            {"label": category, "rows": [], "total": 0, "activity_ids": set()},
        )
        group["rows"].append(row)
        group["total"] += row["amount"]
        group["activity_ids"].add(line.activity_id)

    rendered_groups = []
    for group in sorted(cost_groups.values(), key=lambda value: -value["total"]):
        rendered_groups.append(
            {
                "label": group["label"],
                "rows": group["rows"],
                "total": group["total"],
                "total_fmt": _ugx(group["total"]),
                "activity_count": len(group["activity_ids"]),
            }
        )
    return {
        "items": rows,
        "cost_groups": rendered_groups,
        "staff_rows": [
            {
                "name": value["name"],
                "activity_count": len(value["activities"]),
                "total": value["total"],
                "total_fmt": _ugx(value["total"]),
            }
            for value in sorted(
                staff_totals.values(), key=lambda value: -value["total"]
            )
        ],
        "category_rows": [
            {"label": key, "total": total, "total_fmt": _ugx(total)}
            for key, total in sorted(category_totals.items(), key=lambda item: -item[1])
        ],
    }


def get_monthly_request(principal, filters=None) -> dict:
    """The Program Lead Monthly Request page context.

    The live Team Budget is always shown before a request is created.  Once a
    draft exists, its frozen items are shown, so the PL and CD see the same
    numbers that will travel through approval.
    """
    _require_program_lead(principal)
    filters = filters or {}
    fy = str(filters.get("fy") or get_operational_fy())
    month = int(filters.get("month") or timezone.localdate().month)
    if month not in range(1, 13):
        raise BadRequest("Choose a valid month.")

    request = _team_request(principal, fy, month)
    live_lines = _live_month_lines(principal, fy, month)
    request_lines = []
    if request:
        source_ids = list(
            request.items.values_list("activity_schedule_cost_line_id", flat=True)
        )
        by_id = {
            line.id: line
            for line in ActivityScheduleCostLine.objects.filter(
                id__in=source_ids
            ).select_related("activity", "activity__school")
        }
        request_lines = [by_id[line_id] for line_id in source_ids if line_id in by_id]
    source_lines = request_lines if request else live_lines
    display = _display_rows(source_lines)
    status_label, status_tone, status_message = _status_meta(request)
    live_total = sum(int(line.amount or 0) for line in live_lines)
    shown_total = int(request.total_amount) if request else live_total
    editable = not request or request.status in EDITABLE_STATUSES
    request_state = request.status if request else "not_fetched"
    needs_refresh = bool(
        request
        and request.status == FundRequestStatus.DRAFT
        and int(request.total_amount or 0) != live_total
    )
    can_fetch = editable and live_total > 0
    can_submit = bool(
        request
        and request.status == FundRequestStatus.DRAFT
        and live_total > 0
        and not needs_refresh
    )
    if request_state == "returned_by_cd":
        fetch_label = "Update request for resubmission"
    elif request_state == "draft":
        fetch_label = "Refresh budget draft"
    else:
        fetch_label = "Fetch & review Team Budget"

    if request_state == "submitted_to_cd":
        action_title = "With the Country Director"
        action_hint = "Your request is safely submitted. The Country Director will now review it with the other Program Lead requests."
    elif request_state == "approved_by_cd":
        action_title = "Included in the country budget"
        action_hint = "The Country Director approved your request. It will now move with the country budget to RVP review."
    elif request_state == "returned_by_cd":
        action_title = "Changes needed before resubmission"
        action_hint = "Read the Country Director's note, update your plan if needed, then prepare a fresh request."
    elif needs_refresh:
        action_title = "Your budget has changed"
        action_hint = "Your planned costs changed after this draft was saved. Refresh the draft before you submit it."
    elif request_state == "draft":
        action_title = "Ready to submit"
        action_hint = "This saved budget matches the latest planned costs. You can now send it to the Country Director."
    else:
        action_title = "Start your monthly review"
        action_hint = (
            "Fetch the latest Team Budget to create the review copy you will submit."
        )
    return {
        "fy": fy,
        "month": month,
        "month_label": MONTHS[month],
        "fy_options": [fy, str(int(fy) - 1)],
        "request": request,
        "request_id": request.id if request else "",
        "status_label": status_label,
        "status_tone": status_tone,
        "status_message": status_message,
        "request_state": request_state,
        "needs_refresh": needs_refresh,
        "action_title": action_title,
        "action_hint": action_hint,
        "can_fetch": can_fetch,
        "can_submit": can_submit,
        "fetch_label": fetch_label,
        "submit_label": "Submit to Country Director",
        "live_total": live_total,
        "live_total_fmt": _ugx(live_total),
        "shown_total": shown_total,
        "shown_total_fmt": _ugx(shown_total),
        "activity_count": len({line.activity_id for line in source_lines}),
        "team_member_count": len(display["staff_rows"]),
        "has_snapshot": bool(request),
        "source_label": "Saved request snapshot" if request else "Current Team Budget",
        **display,
    }


__all__ = ["get_monthly_request", "refresh_draft", "submit_to_cd"]
