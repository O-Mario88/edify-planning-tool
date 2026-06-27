"""
Budget service — the cost spine. Ports the legacy budget.service.

CD-owned cost-settings CRUD (with append-only version history), the costing
preview surface, schedule-derived annual budget, weekly fund-request line items,
and the monthly budget board.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Q, Sum

from apps.core.exceptions import BadRequest
from apps.core.fy import get_fy_date_range, get_month_date_range, get_operational_fy
from apps.core.scoping import resolve_user_scope

from .costing import cost_for_activity, resolve_activity_cost
from .models import CostSetting, CostSettingHistory


# ── Rate card ────────────────────────────────────────────────────────────────
def list_cost_settings(principal, query: dict) -> list[dict]:
    qs = CostSetting.objects.all().order_by("label")
    if query.get("fy"):
        qs = qs.filter(Q(fy=query["fy"]) | Q(fy__isnull=True))
    return [
        {
            "id": c.id,
            "key": c.key,
            "label": c.label,
            "unitCost": c.unit_cost,
            "fy": c.fy,
            "version": c.version,
        }
        for c in qs
    ]


def upsert_cost_setting(data: dict, principal) -> dict:
    """CD upserts a rate. Bumps version + appends to history on change."""
    key = data.get("key")
    if not key:
        raise BadRequest("key is required.")
    label = data.get("label") or key.replace("_", " ").title()
    new_cost = data.get("unitCost")
    if new_cost is None:
        raise BadRequest("unitCost is required.")
    fy = data.get("fy")

    with transaction.atomic():
        existing = CostSetting.objects.filter(key=key).first()
        if existing:
            old_cost = existing.unit_cost
            existing.label = label
            existing.unit_cost = new_cost
            existing.fy = fy or existing.fy
            existing.version += 1
            existing.created_by = principal.user_id
            existing.save(update_fields=["label", "unit_cost", "fy", "version", "created_by", "updated_at"])
            CostSettingHistory.objects.create(
                key=key,
                label=label,
                old_unit_cost=old_cost,
                new_unit_cost=new_cost,
                version=existing.version,
                fy=fy or existing.fy,
                changed_by_user_id=principal.user_id,
                reason=data.get("reason"),
            )
            setting = existing
        else:
            setting = CostSetting.objects.create(
                key=key, label=label, unit_cost=new_cost, fy=fy, created_by=principal.user_id, version=1
            )
            CostSettingHistory.objects.create(
                key=key,
                label=label,
                old_unit_cost=None,
                new_unit_cost=new_cost,
                version=1,
                fy=fy,
                changed_by_user_id=principal.user_id,
                reason=data.get("reason"),
            )
    return {
        "id": setting.id,
        "key": setting.key,
        "label": setting.label,
        "unitCost": setting.unit_cost,
        "fy": setting.fy,
        "version": setting.version,
    }


def cost_setting_history(key: str, principal) -> list[dict]:
    qs = CostSettingHistory.objects.filter(key=key).order_by("-changed_at")
    return [
        {
            "key": h.key,
            "label": h.label,
            "oldUnitCost": h.old_unit_cost,
            "newUnitCost": h.new_unit_cost,
            "version": h.version,
            "fy": h.fy,
            "changedByUserId": h.changed_by_user_id,
            "reason": h.reason,
            "changedAt": h.changed_at.isoformat() if h.changed_at else None,
        }
        for h in qs
    ]


def _rate_card() -> dict:
    return {c.key: c.unit_cost for c in CostSetting.objects.all()}


# ── Costing preview ──────────────────────────────────────────────────────────
def cost_preview(data: dict, principal) -> dict:
    """Preview the cost of a notional activity from the rate card."""
    rates = _rate_card()
    cost = cost_for_activity(data, rates)
    return {
        "amount": cost.amount,
        "lines": [
            {"label": l.label, "key": l.key, "unit": l.unit, "qty": l.qty, "amount": l.amount, "missing": l.missing}
            for l in cost.lines
        ],
        "costMissing": cost.cost_missing,
        "missingItems": cost.missing_items,
        "canSchedule": not cost.cost_missing,
    }


# ── Schedule-derived budget ──────────────────────────────────────────────────
def from_schedule(principal, query: dict) -> dict:
    """Annual budget derived from the caller's scheduled activities."""
    from apps.activities.models import Activity

    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if not scope.country_scope:
        if scope.staff_ids:
            qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            qs = qs.none()
    rates = _rate_card()
    total = 0.0
    by_type: dict[str, float] = {}
    for a in qs:
        cost = resolve_activity_cost(_activity_to_costable(a), rates, _snapshot_lines(a))
        total += cost.amount
        by_type[a.activity_type] = by_type.get(a.activity_type, 0.0) + cost.amount
    return {
        "fy": fy,
        "total": total,
        "activityCount": qs.count(),
        "byActivityType": by_type,
    }


def weekly(principal, query: dict) -> list[dict]:
    """Weekly fund-request line items for a month."""
    from apps.activities.models import Activity

    fy = query.get("fy") or get_operational_fy()
    month = int(query.get("month") or 1)
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy, planned_month=month)
    if not scope.country_scope and scope.staff_ids:
        qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
    rates = _rate_card()
    out = []
    for a in qs:
        cost = resolve_activity_cost(_activity_to_costable(a), rates, _snapshot_lines(a))
        out.append({
            "activityId": a.id,
            "activityType": a.activity_type,
            "week": a.planned_week or 1,
            "amount": cost.amount,
            "costMissing": cost.cost_missing,
        })
    return out


def board(principal, query: dict) -> dict:
    """The monthly budget board (lens + period filtered)."""
    from apps.activities.models import Activity

    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    if query.get("quarter"):
        qs = qs.filter(quarter=query["quarter"])
    if query.get("month"):
        qs = qs.filter(planned_month=int(query["month"]))
    lens = query.get("lens", "own")
    if not scope.country_scope:
        if lens == "team" and scope.supervised_staff_ids:
            qs = qs.filter(responsible_staff_id__in=scope.supervised_staff_ids)
        elif scope.staff_ids:
            qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            qs = qs.none()
    rates = _rate_card()
    total = 0.0
    rows = []
    for a in qs:
        cost = resolve_activity_cost(_activity_to_costable(a), rates, _snapshot_lines(a))
        total += cost.amount
        rows.append({
            "activityId": a.id,
            "activityType": a.activity_type,
            "status": a.status,
            "amount": cost.amount,
            "costMissing": cost.cost_missing,
            "month": a.planned_month,
        })
    return {"fy": fy, "total": total, "count": len(rows), "items": rows}


def _activity_to_costable(a) -> dict:
    return {
        "activityType": a.activity_type,
        "deliveryType": a.delivery_type,
        "teachersAttended": a.teachers_attended,
        "leadersAttended": a.leaders_attended,
        "otherParticipants": a.other_participants,
        "projectId": a.project_id,
    }


def _snapshot_lines(a) -> list[dict]:
    return [
        {
            "label": line.label,
            "costSettingKey": line.cost_setting_key,
            "unitCost": line.unit_cost,
            "quantity": line.quantity,
            "amount": line.amount,
            "costSettingVersion": line.cost_setting_version,
        }
        for line in a.schedule_cost_lines.all()
    ]


__all__ = [
    "list_cost_settings",
    "upsert_cost_setting",
    "cost_setting_history",
    "cost_preview",
    "from_schedule",
    "weekly",
    "board",
]
