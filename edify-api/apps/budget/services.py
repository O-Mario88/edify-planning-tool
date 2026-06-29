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
def list_cost_settings(principal, query: dict) -> dict:
    qs = CostSetting.objects.all().order_by("label")
    if query.get("fy"):
        qs = qs.filter(Q(fy=query["fy"]) | Q(fy__isnull=True))
    settings_list = [
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
    return {
        "settings": settings_list,
        "count": len(settings_list),
    }


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

    active_months = [m for m in by_month if m["amount"] > 0]
    avg_amount = (sum(m["amount"] for m in active_months) / len(active_months)) if active_months else 0
    
    busy_months = []
    slow_months = []
    
    for m in by_month:
        amt = m["amount"]
        if amt > 0:
            if avg_amount > 0 and amt > avg_amount * 1.15:
                busy_months.append({
                    "month": m["month"],
                    "amount": amt,
                    "count": m["count"],
                    "insight": f"{m['label']} is a busy month with above-average scheduled activity."
                })
            elif avg_amount > 0 and amt < avg_amount * 0.85:
                slow_months.append({
                    "month": m["month"],
                    "amount": amt,
                    "count": m["count"],
                    "insight": f"{m['label']} is a slow month with below-average activity."
                })

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
        "busyMonths": busy_months,
        "slowMonths": slow_months,
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
    from django.db.models import Sum, Q, Count
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy

    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    qs = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    
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

    activities = list(qs.prefetch_related("schedule_cost_lines"))

    total_fy = 0
    cost_missing_count = 0
    
    month_data = {}
    category_data = {}
    
    import datetime
    today = datetime.date.today()
    this_week_num = today.isocalendar()[1]
    next_week_num = this_week_num + 1
    
    this_week_total = 0
    next_week_total = 0
    this_month_total = 0
    this_quarter_total = 0
    
    MONTH_NAMES = {
        1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
        7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"
    }

    category_groups = {}
    activity_index = 1

    for a in activities:
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        if not amount and a.est_cost_cents:
            amount = a.est_cost_cents
            
        total_fy += amount
        if a.cost_missing:
            cost_missing_count += 1
            
        m = a.planned_month
        if m:
            if m not in month_data:
                month_data[m] = {"amount": 0, "count": 0}
            month_data[m]["amount"] += amount
            month_data[m]["count"] += 1
            
        cat = a.activity_type.replace("_", " ").title()
        category_data[cat] = category_data.get(cat, 0) + amount
        
        if a.scheduled_date:
            act_date = a.scheduled_date.date()
            if act_date.year == today.year:
                act_wk = act_date.isocalendar()[1]
                if act_wk == this_week_num:
                    this_week_total += amount
                elif act_wk == next_week_num:
                    next_week_total += amount
        
        if a.planned_month:
            if a.planned_month == today.month:
                this_month_total += amount
            
            q_map = {1: "Q1", 2: "Q1", 3: "Q1", 4: "Q2", 5: "Q2", 6: "Q2", 7: "Q3", 8: "Q3", 9: "Q3", 10: "Q4", 11: "Q4", 12: "Q4"}
            this_q = q_map.get(today.month, "Q1")
            if q_map.get(a.planned_month) == this_q:
                this_quarter_total += amount

        if cat not in category_groups:
            category_groups[cat] = []
        
        resp = a.responsible_staff_id or a.assigned_partner_id or "—"
        
        category_groups[cat].append({
            "index": activity_index,
            "activity": a.activity_type.replace("_", " ").title(),
            "schoolCount": 1 if a.school_id else 0,
            "responsible": resp,
            "unitCost": amount,
            "total": amount,
            "costMissing": a.cost_missing,
        })
        activity_index += 1

    by_category = []
    for cat, amt in category_data.items():
        by_category.append({
            "label": cat,
            "amount": amt,
            "pct": round(amt / total_fy * 100) if total_fy else 0
        })
    by_category.sort(key=lambda x: x["amount"], reverse=True)

    by_month = []
    for m in range(1, 13):
        m_info = month_data.get(m, {"amount": 0, "count": 0})
        by_month.append({
            "month": m,
            "label": MONTH_NAMES[m],
            "amount": m_info["amount"],
            "count": m_info["count"]
        })

    grouped = []
    for cat, rows in category_groups.items():
        grouped.append({
            "category": cat,
            "rows": rows
        })

    period_total = total_fy
    req_month = query.get("month")
    req_quarter = query.get("quarter")
    if req_month:
        period_total = month_data.get(int(req_month), {}).get("amount", 0)
    elif req_quarter:
        q_months = {"Q1": [10, 11, 12], "Q2": [1, 2, 3], "Q3": [4, 5, 6], "Q4": [7, 8, 9]}.get(req_quarter, [])
        period_total = sum(month_data.get(m, {}).get("amount", 0) for m in q_months)

    role_str = scope.active_role or "CCEO"
    scope_str = "country" if scope.country_scope else ("team" if scope.can_view_team else "own")
    view_mode_str = "country_summary" if role_str == "RVP" else ("team" if role_str == "CountryProgramLead" else ("own" if role_str == "CCEO" else "country"))

    workflow = [
        { "step": 1, "label": "Plan & cost from catalogue", "detail": "Staff schedule activities; costs auto-calculated." },
        { "step": 2, "label": "CCEO → PL review", "detail": "CCEO plans route to Program Lead." },
        { "step": 3, "label": "PL / IA / Accountant → CD", "detail": "Other roles route to Country Director." },
        { "step": 4, "label": "CD approval + admin cost", "detail": "CD adds administrative costs." },
        { "step": 5, "label": "RVP final approval", "detail": "Country consolidation for RVP sign-off." },
    ]

    return {
        "fy": fy,
        "role": role_str,
        "scope": scope_str,
        "viewMode": view_mode_str,
        "lens": query.get("lens", "month"),
        "lensLabel": f"FY{fy} Budget",
        "period": {
            "month": int(req_month) if req_month else None,
            "quarter": req_quarter,
        },
        "summary": {
            "thisWeek": this_week_total,
            "nextWeek": next_week_total,
            "thisMonth": this_month_total,
            "thisQuarter": this_quarter_total,
            "fiscalYear": total_fy,
            "periodTotal": period_total,
            "activityCount": len(activities),
            "costMissingCount": cost_missing_count,
        },
        "grouped": grouped,
        "byCategory": by_category,
        "byMonth": by_month,
        "workflow": workflow
    }


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
