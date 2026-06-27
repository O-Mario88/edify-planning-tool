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
    """Annual budget derived from the caller's scheduled activities.

    Sums the persisted ActivityScheduleCostLine amounts (the authoritative
    schedule-time snapshot) with a single prefetch — no per-activity line query.
    Activities flagged cost-missing still contribute their snapshot total so the
    number matches what a fund request would raise; the UI marks them blocked."""
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
    activities = list(qs.prefetch_related("schedule_cost_lines"))

    total = 0
    by_type: dict[str, int] = {}
    for a in activities:
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        # Fall back to the stored estimate if no lines were ever snapshotted.
        if not amount and a.est_cost_cents:
            amount = a.est_cost_cents
        total += amount
        by_type[a.activity_type] = by_type.get(a.activity_type, 0) + amount
    return {
        "fy": fy,
        "total": total,
        "activityCount": len(activities),
        "byActivityType": by_type,
    }


def weekly(principal, query: dict) -> list[dict]:
    """Weekly fund-request line items for a month. Sums the persisted schedule
    cost lines (prefetched) instead of re-deriving per activity."""
    from apps.activities.models import Activity

    fy = query.get("fy") or get_operational_fy()
    month = int(query.get("month") or 1)
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy, planned_month=month)
    if not scope.country_scope and scope.staff_ids:
        qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
    out = []
    for a in qs.prefetch_related("schedule_cost_lines"):
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        if not amount and a.est_cost_cents:
            amount = a.est_cost_cents
        out.append({
            "activityId": a.id,
            "activityType": a.activity_type,
            "week": a.planned_week or 1,
            "amount": amount,
            "costMissing": a.cost_missing,
        })
    return out


def board(principal, query: dict) -> dict:
    """The monthly budget board (lens + period filtered). Sums the persisted
    budget lines per activity (prefetched) — the authoritative cost snapshot."""
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
    total = 0
    rows = []
    for a in qs.prefetch_related("schedule_cost_lines"):
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        if not amount and a.est_cost_cents:
            amount = a.est_cost_cents
        total += amount
        rows.append({
            "activityId": a.id,
            "activityType": a.activity_type,
            "status": a.status,
            "amount": amount,
            "costMissing": a.cost_missing,
            "month": a.planned_month,
        })
    return {"fy": fy, "total": total, "count": len(rows), "items": rows}


# ── Program + admin budget aggregation (monthly / quarterly / FY) ────────────
def _program_lines_total(fy: str, *, quarter: str | None = None, month: int | None = None) -> tuple[int, int]:
    """Sum persisted ActivityScheduleCostLine amounts + count distinct activities
    for a period. Returns (total, activity_count). Single aggregation query."""
    from apps.activities.models import ActivityScheduleCostLine

    qs = ActivityScheduleCostLine.objects.filter(
        activity__deleted_at__isnull=True, activity__fy=fy
    )
    if quarter:
        qs = qs.filter(activity__quarter=quarter)
    if month is not None:
        qs = qs.filter(activity__planned_month=month)
    agg = qs.aggregate(total=Sum("amount"))
    count = qs.values("activity_id").distinct().count()
    return int(agg["total"] or 0), count


def _admin_lines_total(fy: str, *, month_key: str | None = None) -> int:
    """Sum CD admin budget lines for a period (FY or a month_key 'YYYY-MM')."""
    from apps.monthly_work_plan.models import AdminBudgetLine

    qs = AdminBudgetLine.objects.filter(monthly_budget__fy=fy)
    if month_key:
        qs = qs.filter(monthly_budget__month_key=month_key)
    return int(qs.aggregate(total=Sum("total_cost"))["total"] or 0)


def monthly_budget(query: dict) -> dict:
    """Monthly budget = program activity budget lines for the month + CD admin
    items for that month. The auto-generated program portion + the CD-added
    administrative portion."""
    fy = query.get("fy") or get_operational_fy()
    month = int(query.get("month") or 1)
    program_total, activity_count = _program_lines_total(fy, month=month)
    month_key = _month_key(fy, month)
    admin_total = _admin_lines_total(fy, month_key=month_key)
    return {
        "fy": fy, "month": month, "monthKey": month_key,
        "programTotal": program_total, "adminTotal": admin_total,
        "total": program_total + admin_total, "activityCount": activity_count,
    }


def quarterly_budget(query: dict) -> dict:
    """Quarterly budget = program lines + admin items for the quarter."""
    fy = query.get("fy") or get_operational_fy()
    quarter = query.get("quarter") or "Q1"
    program_total, activity_count = _program_lines_total(fy, quarter=quarter)
    # Admin items are monthly; approximate the quarter as the union of its months.
    quarter_months = _quarter_months(quarter)
    admin_total = sum(
        _admin_lines_total(fy, month_key=_month_key(fy, m)) for m in quarter_months
    )
    return {
        "fy": fy, "quarter": quarter,
        "programTotal": program_total, "adminTotal": admin_total,
        "total": program_total + admin_total, "activityCount": activity_count,
    }


def fy_budget(query: dict) -> dict:
    """FY budget (RVP summary) = all program lines + all admin items in the FY,
    with by-quarter and by-activity-type breakdowns."""
    from apps.activities.models import ActivityScheduleCostLine

    fy = query.get("fy") or get_operational_fy()
    program_total, activity_count = _program_lines_total(fy)
    admin_total = _admin_lines_total(fy)

    by_quarter = {}
    for q in ("Q1", "Q2", "Q3", "Q4"):
        q_total, _ = _program_lines_total(fy, quarter=q)
        by_quarter[q] = q_total

    by_activity_type = {}
    type_qs = ActivityScheduleCostLine.objects.filter(
        activity__deleted_at__isnull=True, activity__fy=fy
    ).values("activity__activity_type").annotate(total=Sum("amount"))
    for row in type_qs:
        by_activity_type[row["activity__activity_type"]] = int(row["total"])

    return {
        "fy": fy,
        "programTotal": program_total,
        "adminTotal": admin_total,
        "total": program_total + admin_total,
        "activityCount": activity_count,
        "byQuarter": by_quarter,
        "byActivityType": by_activity_type,
    }


# month_of_fy (1=Oct) → calendar month; quarter → its months-of-fy.
_FY_START_MONTH = 10  # October

def _month_key(fy: str, month_of_fy: int) -> str:
    """month_of_fy (1=Oct) → 'YYYY-MM' calendar key."""
    fy_int = int(fy)
    cal_month = _FY_START_MONTH + (month_of_fy - 1)
    cal_year = fy_int - 1
    while cal_month > 12:
        cal_month -= 12
        cal_year += 1
    return f"{cal_year:04d}-{cal_month:02d}"


def _quarter_months(quarter: str) -> list[int]:
    """Quarter → the 3 months-of-fy it spans (1-based, Oct=1)."""
    return {"Q1": [1, 2, 3], "Q2": [4, 5, 6], "Q3": [7, 8, 9], "Q4": [10, 11, 12]}[quarter]


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
