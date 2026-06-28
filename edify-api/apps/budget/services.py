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
    Returns the full contract the frontend monthly/quarterly/FY budget views need:
    per-month totals + counts (every activity type: visits, training, cluster
    meetings), per-type, per-delivery, and cost-missing counts."""
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

    MONTH_LABELS = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                     7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}

    total = 0
    scheduled_total = 0
    cost_missing_count = 0
    unscheduled_count = 0
    unscheduled_amount = 0
    by_type: dict[str, int] = {}
    by_type_count: dict[str, int] = {}
    by_month_amount: dict[int, int] = {}
    by_month_count: dict[int, int] = {}
    by_month_trainings: dict[int, int] = {}
    staff_amount = staff_count = 0
    partner_amount = partner_count = 0

    TRAINING_TYPES = {"training", "school_improvement_training", "cluster_training", "core_training", "cluster_meeting"}

    for a in activities:
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        # Fall back to the stored estimate if no lines were ever snapshotted.
        if not amount and a.est_cost_cents:
            amount = a.est_cost_cents
        total += amount
        if a.cost_missing:
            cost_missing_count += 1
        if not a.scheduled_date:
            unscheduled_count += 1
            unscheduled_amount += amount
        else:
            scheduled_total += amount
        # By activity type.
        by_type[a.activity_type] = by_type.get(a.activity_type, 0) + amount
        by_type_count[a.activity_type] = by_type_count.get(a.activity_type, 0) + 1
        # By month (1-12 calendar month). Only activities with a planned month
        # roll into a month bucket; an activity with no planned_month is unscheduled.
        if a.planned_month:
            by_month_amount[a.planned_month] = by_month_amount.get(a.planned_month, 0) + amount
            by_month_count[a.planned_month] = by_month_count.get(a.planned_month, 0) + 1
            if a.activity_type in TRAINING_TYPES:
                by_month_trainings[a.planned_month] = by_month_trainings.get(a.planned_month, 0) + 1
        # By delivery.
        if a.delivery_type == "partner":
            partner_amount += amount
            partner_count += 1
        else:
            staff_amount += amount
            staff_count += 1

    by_month = [
        {
            "month": m,
            "label": MONTH_LABELS.get(m, str(m)),
            "amount": by_month_amount.get(m, 0),
            "count": by_month_count.get(m, 0),
            "trainings": by_month_trainings.get(m, 0),
        }
        for m in range(1, 13)
        if by_month_count.get(m, 0) > 0
    ]
    by_type_list = [
        {"type": t, "amount": amt, "count": by_type_count.get(t, 0)}
        for t, amt in by_type.items()
    ]

    return {
        "fy": fy,
        "role": scope.active_role,
        "scope": "country" if scope.country_scope else ("team" if scope.can_view_team else "own"),
        "total": total,
        "scheduledTotal": scheduled_total,
        "activityCount": len(activities),
        "costMissingCount": cost_missing_count,
        "unscheduledCount": unscheduled_count,
        "unscheduledAmount": unscheduled_amount,
        "byMonth": by_month,
        "byQuarter": _by_quarter_from_activities(activities),
        "byType": by_type_list,
        "byActivityType": by_type,  # legacy field kept for older consumers
        "byDelivery": {
            "staff": {"amount": staff_amount, "count": staff_count},
            "partner": {"amount": partner_amount, "count": partner_count},
        },
        "avgMonthlyCost": round(total / 12) if total else 0,
    }


def _by_quarter_from_activities(activities) -> list[dict]:
    """Per-quarter amount + count across all activity types."""
    amt: dict[str, int] = {}
    cnt: dict[str, int] = {}
    for a in activities:
        amount = sum(line.amount for line in a.schedule_cost_lines.all()) or a.est_cost_cents
        q = a.quarter
        amt[q] = amt.get(q, 0) + amount
        cnt[q] = cnt.get(q, 0) + 1
    return [{"quarter": q, "amount": amt.get(q, 0), "count": cnt.get(q, 0)} for q in ("Q1", "Q2", "Q3", "Q4") if cnt.get(q, 0)]


def weekly(principal, query: dict) -> dict:
    """Weekly fund-request rollup for a month. Returns the full BeBudgetWeekly contract."""
    from apps.activities.models import Activity
    
    fy = query.get("fy") or get_operational_fy()
    month_val = query.get("month")
    month = int(month_val) if month_val else 1
    scope = resolve_user_scope(principal)
    
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy, planned_month=month)
    if not scope.country_scope:
        if scope.staff_ids:
            qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            qs = qs.none()
            
    activities = list(qs.select_related("school", "cluster").prefetch_related("schedule_cost_lines"))
    
    lines = []
    total_cents = 0
    cost_missing_count = 0
    
    # Weeks rollup: weeks 1 to 5
    week_amounts = {w: 0 for w in range(1, 6)}
    week_counts = {w: 0 for w in range(1, 6)}
    
    for a in activities:
        amount = sum(line.amount for line in a.schedule_cost_lines.all()) or a.est_cost_cents
        total_cents += amount
        if a.cost_missing:
            cost_missing_count += 1
            
        w = a.planned_week or 1
        if w in week_amounts:
            week_amounts[w] += amount
            week_counts[w] += 1
            
        # Serialize cost lines
        cost_lines = [
            {
                "label": line.label,
                "key": line.cost_setting_key,
                "unit": line.unit_cost,
                "qty": line.qty,
                "amount": line.amount,
                "missing": False
            }
            for line in a.schedule_cost_lines.all()
        ]
        
        lines.append({
            "id": a.id,
            "activityType": a.activity_type,
            "deliveryType": a.delivery_type,
            "status": a.status,
            "month": a.planned_month,
            "week": a.planned_week,
            "scheduledDate": a.scheduled_date.isoformat() if a.scheduled_date else None,
            "place": a.school.name if a.school else (a.cluster.name if a.cluster else ""),
            "district": a.school.district.name if a.school and a.school.district else "",
            "staff": a.responsible_staff_id or "",
            "partner": a.assigned_partner_id or "",
            "amount": amount,
            "costMissing": a.cost_missing,
            "lines": cost_lines,
            "paymentStatus": a.payment_status,
            "iaVerificationStatus": a.ia_verification_status,
        })
        
    weeks = [
        {
            "key": f"W{w}",
            "month": month,
            "week": w,
            "amount": week_amounts[w],
            "count": week_counts[w],
        }
        for w in range(1, 6)
    ]
    
    return {
        "fy": fy,
        "role": scope.active_role or "",
        "total": total_cents,
        "count": len(activities),
        "costMissingCount": cost_missing_count,
        "weeks": weeks,
        "lines": lines,
    }


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
