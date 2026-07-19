"""
Budget service — the cost spine. Ports the legacy budget.service.

CD-owned cost-settings CRUD (with append-only version history), the costing
preview surface, schedule-derived annual budget, weekly fund-request line items,
and the monthly budget board.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.exceptions import BadRequest
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope

from .costing import LEGACY_CLUSTER_ACTIVITY_COST_KEYS, cost_for_activity
from .models import CostSetting, CostSettingHistory
from apps.core.activity_types import TRAINING_TYPES


# ── Rate card ────────────────────────────────────────────────────────────────
def list_cost_settings(principal, query: dict) -> dict:
    # Old broad training/meeting rates stay in the database so historical
    # snapshots remain auditable, but they are no longer configurable for new
    # cluster work.  The four canonical rates are the catalogue surface.
    qs = CostSetting.objects.exclude(
        key__in=LEGACY_CLUSTER_ACTIVITY_COST_KEYS
    ).order_by("label")
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
    if key in LEGACY_CLUSTER_ACTIVITY_COST_KEYS:
        raise BadRequest(
            "This is a historic cluster cost item. Use Participant snacks, "
            "Participant meals, Facilitation fee, or Venue fee instead."
        )
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
            existing.save(
                update_fields=[
                    "label",
                    "unit_cost",
                    "fy",
                    "version",
                    "created_by",
                    "updated_at",
                ]
            )
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
                key=key,
                label=label,
                unit_cost=new_cost,
                fy=fy,
                created_by=principal.user_id,
                version=1,
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
            {
                "label": line.label,
                "key": line.key,
                "unit": line.unit,
                "qty": line.qty,
                "amount": line.amount,
                "missing": line.missing,
            }
            for line in cost.lines
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
    qs = (
        Activity.objects.filter(deleted_at__isnull=True, fy=fy)
        .exclude(status__in=["cancelled", "rejected"])
        .exclude(delivery_type="partner", planned_date__isnull=True)
    )
    if not scope.country_scope:
        if scope.staff_ids:
            qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            qs = qs.none()
    activities = list(qs.prefetch_related("schedule_cost_lines"))

    MONTH_LABELS = {
        1: "Jan",
        2: "Feb",
        3: "Mar",
        4: "Apr",
        5: "May",
        6: "Jun",
        7: "Jul",
        8: "Aug",
        9: "Sep",
        10: "Oct",
        11: "Nov",
        12: "Dec",
    }

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

    for a in activities:
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        # NO est_cost_cents fallback: authoritative totals come from canonical
        # cost lines only. A scheduled activity with no lines is a System
        # Health signal (missing_cost_lines_count), not a number to guess —
        # the estimate could double-count once lines are later snapshotted.
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
        # By month (1-12 calendar month, from the schedule-time snapshot that
        # costing_service.apply_to_activity always writes). The legacy
        # planned_month field is only populated when a caller happens to pass
        # plannedMonth explicitly and silently under-counts otherwise — a.month
        # is set reliably, from the same scheduled_date, every time. No month
        # means unscheduled.
        if a.month:
            by_month_amount[a.month] = by_month_amount.get(a.month, 0) + amount
            by_month_count[a.month] = by_month_count.get(a.month, 0) + 1
            if a.activity_type in TRAINING_TYPES:
                by_month_trainings[a.month] = by_month_trainings.get(a.month, 0) + 1
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
    avg_amount = (
        (sum(m["amount"] for m in active_months) / len(active_months))
        if active_months
        else 0
    )

    busy_months = []
    slow_months = []

    for m in by_month:
        amt = m["amount"]
        if amt > 0:
            if avg_amount > 0 and amt > avg_amount * 1.15:
                busy_months.append(
                    {
                        "month": m["month"],
                        "amount": amt,
                        "count": m["count"],
                        "insight": f"{m['label']} is a busy month with above-average scheduled activity.",
                    }
                )
            elif avg_amount > 0 and amt < avg_amount * 0.85:
                slow_months.append(
                    {
                        "month": m["month"],
                        "amount": amt,
                        "count": m["count"],
                        "insight": f"{m['label']} is a slow month with below-average activity.",
                    }
                )

    return {
        "fy": fy,
        "role": scope.active_role,
        "scope": "country"
        if scope.country_scope
        else ("team" if scope.can_view_team else "own"),
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
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        q = a.quarter
        amt[q] = amt.get(q, 0) + amount
        cnt[q] = cnt.get(q, 0) + 1
    return [
        {"quarter": q, "amount": amt.get(q, 0), "count": cnt.get(q, 0)}
        for q in ("Q1", "Q2", "Q3", "Q4")
        if cnt.get(q, 0)
    ]


def weekly(principal, query: dict) -> dict:
    """Weekly fund-request rollup for a month. Returns the full BeBudgetWeekly contract."""
    from apps.activities.models import Activity

    fy = query.get("fy") or get_operational_fy()
    month_val = query.get("month")
    month = int(month_val) if month_val else 1
    scope = resolve_user_scope(principal)

    qs = (
        Activity.objects.filter(deleted_at__isnull=True, fy=fy, month=month)
        .exclude(status__in=["cancelled", "rejected"])
        .exclude(delivery_type="partner", planned_date__isnull=True)
    )
    if not scope.country_scope:
        if scope.staff_ids:
            qs = qs.filter(responsible_staff_id__in=scope.staff_ids)
        elif scope.partner_ids:
            qs = qs.filter(assigned_partner_id__in=scope.partner_ids)
        else:
            qs = qs.none()

    activities = list(
        qs.select_related("school", "cluster").prefetch_related("schedule_cost_lines")
    )

    lines = []
    total_cents = 0
    cost_missing_count = 0

    # Weeks rollup: weeks 1 to 5
    week_amounts = {w: 0 for w in range(1, 6)}
    week_counts = {w: 0 for w in range(1, 6)}

    for a in activities:
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        total_cents += amount
        if a.cost_missing:
            cost_missing_count += 1

        # planned_week is only populated when a caller happens to pass
        # plannedWeek explicitly (same reliability gap as planned_month) —
        # derive the week-of-month from the reliably-set planned_date instead,
        # using the same formula the rest of the app already uses for this
        # (see apps.activities.services / apps.my_plan.services).
        w = min(5, (a.planned_date.day - 1) // 7 + 1) if a.planned_date else 1
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
                "missing": False,
            }
            for line in a.schedule_cost_lines.all()
        ]

        lines.append(
            {
                "id": a.id,
                "activityType": a.activity_type,
                "deliveryType": a.delivery_type,
                "status": a.status,
                "month": a.month,
                "week": w,
                "scheduledDate": a.scheduled_date.isoformat()
                if a.scheduled_date
                else None,
                "place": a.school.name
                if a.school
                else (a.cluster.name if a.cluster else ""),
                "district": a.school.district.name
                if a.school and a.school.district
                else "",
                "staff": a.responsible_staff_id or "",
                "partner": a.assigned_partner_id or "",
                "amount": amount,
                "costMissing": a.cost_missing,
                "lines": cost_lines,
                "paymentStatus": a.payment_status,
                "iaVerificationStatus": a.ia_verification_status,
            }
        )

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
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy

    fy = query.get("fy") or get_operational_fy()
    scope = resolve_user_scope(principal)
    qs = (
        Activity.objects.filter(deleted_at__isnull=True, fy=fy)
        .exclude(status__in=["cancelled", "rejected"])
        .exclude(delivery_type="partner", planned_date__isnull=True)
    )

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
        1: "Jan",
        2: "Feb",
        3: "Mar",
        4: "Apr",
        5: "May",
        6: "Jun",
        7: "Jul",
        8: "Aug",
        9: "Sep",
        10: "Oct",
        11: "Nov",
        12: "Dec",
    }

    category_groups = {}
    activity_index = 1

    for a in activities:
        amount = sum(line.amount for line in a.schedule_cost_lines.all())
        # NO est_cost_cents fallback — canonical cost lines only (see
        # from_schedule above for the rationale).

        total_fy += amount
        if a.cost_missing:
            cost_missing_count += 1

        m = a.month
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

        if a.month:
            if a.month == today.month:
                this_month_total += amount

            q_map = {
                1: "Q1",
                2: "Q1",
                3: "Q1",
                4: "Q2",
                5: "Q2",
                6: "Q2",
                7: "Q3",
                8: "Q3",
                9: "Q3",
                10: "Q4",
                11: "Q4",
                12: "Q4",
            }
            this_q = q_map.get(today.month, "Q1")
            if q_map.get(a.month) == this_q:
                this_quarter_total += amount

        if cat not in category_groups:
            category_groups[cat] = []

        resp = a.responsible_staff_id or a.assigned_partner_id or "—"

        category_groups[cat].append(
            {
                "index": activity_index,
                "activity": a.activity_type.replace("_", " ").title(),
                "schoolCount": 1 if a.school_id else 0,
                "responsible": resp,
                "unitCost": amount,
                "total": amount,
                "costMissing": a.cost_missing,
            }
        )
        activity_index += 1

    by_category = []
    for cat, amt in category_data.items():
        by_category.append(
            {
                "label": cat,
                "amount": amt,
                "pct": round(amt / total_fy * 100) if total_fy else 0,
            }
        )
    by_category.sort(key=lambda x: x["amount"], reverse=True)

    by_month = []
    for m in range(1, 13):
        m_info = month_data.get(m, {"amount": 0, "count": 0})
        by_month.append(
            {
                "month": m,
                "label": MONTH_NAMES[m],
                "amount": m_info["amount"],
                "count": m_info["count"],
            }
        )

    grouped = []
    for cat, rows in category_groups.items():
        grouped.append(
            {
                "category": cat,
                "rows": rows,
                "amount": category_data.get(cat, 0),
            }
        )

    period_total = total_fy
    req_month = query.get("month")
    req_quarter = query.get("quarter")
    if req_month:
        period_total = month_data.get(int(req_month), {}).get("amount", 0)
    elif req_quarter:
        q_months = {
            "Q1": [10, 11, 12],
            "Q2": [1, 2, 3],
            "Q3": [4, 5, 6],
            "Q4": [7, 8, 9],
        }.get(req_quarter, [])
        period_total = sum(month_data.get(m, {}).get("amount", 0) for m in q_months)

    role_str = scope.active_role or "CCEO"
    scope_str = (
        "country" if scope.country_scope else ("team" if scope.can_view_team else "own")
    )
    view_mode_str = (
        "country_summary"
        if role_str == "RegionalVicePresident"
        else (
            "team"
            if role_str == "Program Lead"
            else ("own" if role_str == "CCEO" else "country")
        )
    )

    workflow = [
        {
            "step": 1,
            "label": "Plan & cost from catalogue",
            "detail": "Staff schedule activities; costs auto-calculated.",
        },
        {
            "step": 2,
            "label": "CCEO → PL review",
            "detail": "CCEO plans route to Program Lead.",
        },
        {
            "step": 3,
            "label": "PL / IA / Accountant → CD",
            "detail": "Other roles route to Country Director.",
        },
        {
            "step": 4,
            "label": "CD approval + admin cost",
            "detail": "CD adds administrative costs.",
        },
        {
            "step": 5,
            "label": "RVP final approval",
            "detail": "Country consolidation for RVP sign-off.",
        },
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
        "workflow": workflow,
    }


# ── My Budget workspace ─────────────────────────────────────────────────────
def _workspace_owner_ids(principal, scope, *, include_team: bool) -> list[str] | None:
    """Return ledger owners for a personal or Program Lead team budget."""
    if scope.country_scope:
        return None

    owner_ids = {getattr(principal, "user_id", None) or getattr(principal, "id", None)}
    if (
        include_team
        and scope.active_role == "Program Lead"
        and scope.supervised_staff_ids
    ):
        from apps.accounts.models import StaffProfile

        owner_ids.update(
            StaffProfile.objects.filter(id__in=scope.supervised_staff_ids).values_list(
                "user_id", flat=True
            )
        )
    return [owner_id for owner_id in owner_ids if owner_id]


def _month_start_for_key(month_key: str | None) -> date | None:
    try:
        year, month = (int(part) for part in (month_key or "").split("-", 1))
        return date(year, month, 1)
    except (TypeError, ValueError):
        return None


def _calendar_periods(fy: str, anchor: date) -> dict[str, dict]:
    """Build the four budget periods around one selected planning date."""
    from apps.core.fy import (
        get_fy_date_range,
        get_quarter_date_range,
        get_quarter_for_date,
    )

    week_start = anchor - timedelta(days=anchor.weekday())
    week_end = week_start + timedelta(days=6)
    month_start = anchor.replace(day=1)
    next_month = (month_start.replace(day=28) + timedelta(days=4)).replace(day=1)
    month_end = next_month - timedelta(days=1)
    quarter = get_quarter_for_date(anchor)
    quarter_start_dt, quarter_end_dt = get_quarter_date_range(fy, quarter)
    fy_start_dt, fy_end_dt = get_fy_date_range(fy)
    quarter_start = quarter_start_dt.date()
    quarter_end = (quarter_end_dt - timedelta(days=1)).date()
    fy_start = fy_start_dt.date()
    fy_end = (fy_end_dt - timedelta(days=1)).date()
    return {
        "week": {
            "key": "week",
            "label": "Week",
            "title": f"Week of {week_start:%d %b} – {week_end:%d %b %Y}",
            "start": week_start,
            "end": week_end,
        },
        "month": {
            "key": "month",
            "label": "Month",
            "title": anchor.strftime("%B %Y"),
            "start": month_start,
            "end": month_end,
        },
        "quarter": {
            "key": "quarter",
            "label": "Quarter",
            "title": f"{quarter} FY {fy} · {quarter_start:%d %b} – {quarter_end:%d %b %Y}",
            "start": quarter_start,
            "end": quarter_end,
        },
        "fy": {
            "key": "fy",
            "label": "Fiscal Year",
            "title": f"FY {fy} · {fy_start:%d %b %Y} – {fy_end:%d %b %Y}",
            "start": fy_start,
            "end": fy_end,
        },
    }


def budget_workspace(principal, query: dict) -> dict:
    """Return the role-scoped, request-backed My Budget ledger.

    Canonical schedule cost lines supply every amount.  Weekly and monthly
    fund requests are snapshots of those lines, so their counts are surfaced
    for traceability but their totals are never added again. This keeps the
    page mathematically correct while still showing that scheduled work has
    reached the funding workflow.
    """
    from apps.accounts.models import User
    from apps.activities.models import ActivityScheduleCostLine
    from apps.fund_requests.models import (
        FundRequest,
        FundRequestPeriod,
        WeeklyFundRequest,
    )
    from apps.monthly_work_plan.models import AdminBudgetLine

    scope = resolve_user_scope(principal)
    try:
        anchor = (
            date.fromisoformat(str(query.get("date"))[:10])
            if query.get("date")
            else None
        )
    except ValueError:
        anchor = None
    anchor = anchor or timezone.localdate()
    fy = query.get("fy") or get_operational_fy(anchor)
    periods = _calendar_periods(fy, anchor)
    selected_period = query.get("period") if query.get("period") in periods else "week"
    selected = periods[selected_period]
    is_program_lead = scope.active_role == "Program Lead"
    budget_scope = (
        "team" if is_program_lead and query.get("budget_scope") == "team" else "my"
    )
    owner_ids = _workspace_owner_ids(
        principal, scope, include_team=budget_scope == "team"
    )
    include_admin = getattr(principal, "active_role", "") in (
        "CountryDirector",
        "Admin",
    )

    base_lines = (
        ActivityScheduleCostLine.objects.filter(
            fiscal_year=fy,
            activity__deleted_at__isnull=True,
            activity__scheduled_date__isnull=False,
        )
        .exclude(activity__status__in=["cancelled", "rejected"])
        .select_related("activity", "partner")
    )
    if owner_ids is not None:
        base_lines = base_lines.filter(responsible_user__in=owner_ids)

    admin_lines = []
    if include_admin:
        admin_lines = list(
            AdminBudgetLine.objects.filter(
                monthly_budget__fy=fy, status="active"
            ).select_related("monthly_budget")
        )

    def admin_total(period):
        # Admin plans are monthly costs. A weekly split would be invented, so
        # show them exactly in the Month, Quarter, and FY where they are planned.
        if not include_admin or period["key"] == "week":
            return 0
        return sum(
            int(line.total_cost or 0)
            for line in admin_lines
            if (planned := _month_start_for_key(line.monthly_budget.month_key))
            and period["start"] <= planned <= period["end"]
        )

    def operational_total(period):
        return int(
            base_lines.filter(
                planned_date__range=(period["start"], period["end"])
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

    comparison = []
    for key in ("week", "month", "quarter", "fy"):
        period = periods[key]
        program_total = operational_total(period)
        admin_amount = admin_total(period)
        comparison.append(
            {
                **period,
                "program_total": program_total,
                "admin_total": admin_amount,
                "total": program_total + admin_amount,
                "selected": key == selected_period,
            }
        )

    selected_lines = list(
        base_lines.filter(planned_date__range=(selected["start"], selected["end"]))
    )
    user_names = dict(
        User.objects.filter(
            id__in={
                line.responsible_user
                for line in selected_lines
                if line.responsible_user
            }
        ).values_list("id", "name")
    )
    # A supervisor needs a quick view of each person's total without having to
    # scan staff names repeated beneath every cost item.  Keep this separate
    # from the activity/item ledger so the detail table stays easy to read.
    team_summary_by_owner: dict[str, dict] = {}
    if budget_scope == "team":
        for line in selected_lines:
            owner_id = line.responsible_user or "unassigned"
            summary = team_summary_by_owner.setdefault(
                owner_id,
                {
                    "name": user_names.get(owner_id, "Unassigned work"),
                    "activity_ids": set(),
                    "total": 0,
                },
            )
            summary["activity_ids"].add(line.activity_id)
            summary["total"] += int(line.amount or 0)
    # A training or meeting is funded by the headcount confirmed at scheduling
    # time.  Actual attendance takes precedence after completion; historical
    # cost lines remain a fallback for pre-headcount records created before the
    # dedicated Activity.expected_participants field was introduced.
    training_types = {
        "training",
        "in_school_training",
        "school_improvement_training",
        "cluster_training",
        "core_training",
        "cluster_training_ssa_collection",
    }
    meeting_types = {"cluster_meeting", "cluster_meeting_ssa_review"}
    participant_line_types = {
        "participant_meals",
        "cluster_meeting_participant_meals",
        "mobilisation",
    }
    participant_setting_keys = {
        "group_training_participant_meal_cost_per_head",
        "cluster_meeting_participant_meal_cost_per_head",
        "meals_per_participant",
        "mobilisation_per_participant",
        "cluster_meeting_cost",
    }

    def table_kind(activity_type: str) -> str:
        if activity_type in meeting_types:
            return "meeting"
        if activity_type in training_types:
            return "training"
        return "standard"

    scheduled_participants: dict[str, int] = {}
    for line in selected_lines:
        activity = line.activity
        activity_type = activity.activity_type
        actual_attendance = sum(
            int(value or 0)
            for value in (
                activity.teachers_attended,
                activity.leaders_attended,
                activity.other_participants,
            )
        )
        if actual_attendance:
            scheduled_participants[activity.id] = actual_attendance
            continue
        if activity.expected_participants:
            scheduled_participants[activity.id] = int(activity.expected_participants)
            continue
        if table_kind(activity_type) in {"training", "meeting"} and (
            line.line_item_type in participant_line_types
            or line.cost_setting_key in participant_setting_keys
        ):
            scheduled_participants[activity.id] = max(
                scheduled_participants.get(activity.id, 0), int(line.quantity or 0)
            )

    groups: dict[str, dict] = {}
    for line in selected_lines:
        activity = line.activity
        activity_label = activity.get_activity_type_display()
        group = groups.setdefault(
            activity_label,
            {
                "label": activity_label,
                "table_kind": table_kind(activity.activity_type),
                "rows": {},
                "total": 0,
                "staff_total": 0,
                "vendor_total": 0,
                "activity_ids": set(),
            },
        )
        item_label = line.label or line.cost_setting_key.replace("_", " ").title()
        row = group["rows"].setdefault(
            item_label,
            {
                "item": item_label,
                "dates": set(),
                "activity_ids": set(),
                "activity_people": {},
                "rates": set(),
                "owners": set(),
                "staff_total": 0,
                "vendor_total": 0,
                "total": 0,
            },
        )
        row["dates"].add(line.planned_date)
        participant_count = scheduled_participants.get(activity.id, 1)
        row["activity_people"].setdefault(activity.id, participant_count)
        row["activity_ids"].add(activity.id)
        row["rates"].add(int(line.unit_cost or 0))
        if line.responsible_user:
            row["owners"].add(user_names.get(line.responsible_user, "Staff"))
        is_vendor = activity.delivery_type == "partner" or line.partner_id is not None
        amount = int(line.amount or 0)
        if is_vendor:
            row["vendor_total"] += amount
            group["vendor_total"] += amount
        else:
            row["staff_total"] += amount
            group["staff_total"] += amount
        row["total"] += amount
        group["total"] += amount
        group["activity_ids"].add(activity.id)

    if include_admin and selected_period != "week":
        admin_group = None
        for line in admin_lines:
            planned = _month_start_for_key(line.monthly_budget.month_key)
            if not planned or not (selected["start"] <= planned <= selected["end"]):
                continue
            if admin_group is None:
                admin_group = {
                    "label": "Country Admin Plan",
                    "table_kind": "admin",
                    "rows": {},
                    "total": 0,
                    "staff_total": 0,
                    "vendor_total": 0,
                    "activity_ids": set(),
                    "is_admin": True,
                }
                groups[admin_group["label"]] = admin_group
            item_label = (
                line.description or line.cost_category.replace("_", " ").title()
            )
            row = admin_group["rows"].setdefault(
                item_label,
                {
                    "item": item_label,
                    "dates": set(),
                    "activity_ids": set(),
                    "activity_people": {},
                    "rates": set(),
                    "owners": {"Country admin"},
                    "staff_total": 0,
                    "vendor_total": 0,
                    "total": 0,
                    "admin_quantity": 0,
                },
            )
            amount = int(line.total_cost or 0)
            row["dates"].add(planned)
            row["rates"].add(int(line.unit_cost or 0))
            row["admin_quantity"] += line.quantity
            row["staff_total"] += amount
            row["total"] += amount
            admin_group["staff_total"] += amount
            admin_group["total"] += amount

    formatted_groups = []
    for group in groups.values():
        rows = []
        for row in group["rows"].values():
            rates = sorted(row["rates"])
            rows.append(
                {
                    "item": row["item"],
                    "days": row.get("admin_quantity") or len(row["dates"]),
                    "activity_count": len(row["activity_ids"]),
                    "people": sum(row["activity_people"].values()) or "—",
                    "rate": rates[0] if len(rates) == 1 else None,
                    "mixed_rate": len(rates) > 1,
                    "owners": ", ".join(sorted(row["owners"])) or "—",
                    "staff_total": row["staff_total"],
                    "vendor_total": row["vendor_total"],
                    "total": row["total"],
                }
            )
        formatted_groups.append(
            {
                "label": group["label"],
                "table_kind": group["table_kind"],
                "rows": sorted(rows, key=lambda item: (-item["total"], item["item"])),
                "total": group["total"],
                "staff_total": group["staff_total"],
                "vendor_total": group["vendor_total"],
                "activity_count": len(group["activity_ids"]),
                "is_admin": group.get("is_admin", False),
            }
        )
    formatted_groups.sort(key=lambda item: (-item["total"], item["label"]))

    weekly_requests = WeeklyFundRequest.objects.filter(
        fy=fy,
        week_start_date__lte=selected["end"],
        week_end_date__gte=selected["start"],
    )
    monthly_requests = FundRequest.objects.filter(
        fy=fy, period=FundRequestPeriod.MONTHLY
    )
    if owner_ids is not None:
        weekly_requests = weekly_requests.filter(responsible_user__in=owner_ids)
        monthly_requests = monthly_requests.filter(submitted_by_user_id__in=owner_ids)
    if selected_period in ("week", "month"):
        monthly_requests = monthly_requests.filter(period_key=f"{fy}-M{anchor.month}")

    selected_program_total = sum(
        group["total"] for group in formatted_groups if not group["is_admin"]
    )
    selected_admin_total = sum(
        group["total"] for group in formatted_groups if group["is_admin"]
    )
    selected_staff_total = sum(group["staff_total"] for group in formatted_groups)
    selected_vendor_total = sum(group["vendor_total"] for group in formatted_groups)
    team_summary = [
        {
            "name": summary["name"],
            "activity_count": len(summary["activity_ids"]),
            "total": summary["total"],
        }
        for summary in team_summary_by_owner.values()
    ]
    team_summary.sort(key=lambda item: (-item["total"], item["name"]))
    return {
        "fy": fy,
        "anchor": anchor,
        "selected_period": selected_period,
        "selected": selected,
        "comparison": comparison,
        "groups": formatted_groups,
        "program_total": selected_program_total,
        "admin_total": selected_admin_total,
        "staff_total": selected_staff_total,
        "vendor_total": selected_vendor_total,
        "total": selected_program_total + selected_admin_total,
        "weekly_request_count": weekly_requests.count(),
        "monthly_request_count": monthly_requests.count(),
        "role": getattr(principal, "active_role", ""),
        "scope_label": "Country"
        if scope.country_scope
        else ("Team" if budget_scope == "team" else "My"),
        "budget_scope": budget_scope,
        "is_program_lead": is_program_lead,
        "team_summary": team_summary,
        "admin_weekly_note": include_admin and selected_period == "week",
    }


# ── Program + admin budget aggregation (monthly / quarterly / FY) ────────────
def _admin_lines_total(fy: str, *, month_key: str | None = None) -> int:
    """Sum CD admin budget lines for a period (FY or a month_key 'YYYY-MM')."""
    from apps.monthly_work_plan.models import AdminBudgetLine

    qs = AdminBudgetLine.objects.filter(monthly_budget__fy=fy)
    if month_key:
        qs = qs.filter(monthly_budget__month_key=month_key)
    return int(qs.aggregate(total=Sum("total_cost"))["total"] or 0)


def get_budget_rollup(
    fy: str, *, quarter: str | None = None, month: int | None = None
) -> dict:
    from django.db.models import Sum, Q
    from apps.activities.models import ActivityScheduleCostLine

    qs = (
        ActivityScheduleCostLine.objects.filter(
            activity__deleted_at__isnull=True, activity__fy=fy
        )
        .exclude(activity__status__in=["cancelled", "rejected"])
        .exclude(activity__delivery_type="partner", activity__planned_date__isnull=True)
    )
    if quarter:
        qs = qs.filter(activity__quarter=quarter)
    if month is not None:
        # `month` here is FY-relative (1=Oct...12=Sep — see monthly_budget()'s
        # callers), but ActivityScheduleCostLine.month is a calendar month
        # (set from planned_date in costing_service.apply_to_activity).
        # Activity.planned_month, which used to be filtered on here, is a
        # separate legacy field only populated when a caller happens to pass
        # plannedMonth explicitly, so it silently under-counted real activity.
        qs = qs.filter(month=_calendar_month_of_fy(fy, month))

    agg = qs.aggregate(
        planned=Sum("amount"),
        requested=Sum(
            "amount",
            filter=Q(
                advance_requests__status__in=[
                    "pending_responsible_confirmation",
                    "confirmed_for_advance",
                    "submitted_to_accountant",
                    "disbursed",
                    "accountability_pending",
                    "accounted",
                ]
            ),
        ),
        approved=Sum(
            "amount",
            filter=Q(
                advance_requests__status__in=[
                    "confirmed_for_advance",
                    "submitted_to_accountant",
                    "disbursed",
                    "accountability_pending",
                    "accounted",
                ]
            ),
        ),
        # Disbursed/accounted report ACTUAL money (AdvanceRequest amounts),
        # not the planned line amount — a partial disbursement previously
        # showed as fully disbursed on every rollup surface.
        disbursed=Sum(
            "advance_requests__disbursed_amount",
            filter=Q(
                advance_requests__status__in=[
                    "disbursed",
                    "accountability_pending",
                    "accounted",
                    "reimbursement_submitted",
                    "reimbursement_disbursed",
                    "reimbursed",
                ]
            ),
        ),
        accounted=Sum(
            "advance_requests__accounted_amount",
            filter=Q(advance_requests__status__in=["accounted", "reimbursed"]),
        ),
    )

    planned = int(agg["planned"] or 0)
    requested = int(agg["requested"] or 0)
    approved = int(agg["approved"] or 0)
    disbursed = int(agg["disbursed"] or 0)
    accounted = int(agg["accounted"] or 0)
    cleared = accounted
    pending = planned - cleared
    variance = planned - cleared

    return {
        "planned": planned,
        "requested": requested,
        "approved": approved,
        "disbursed": disbursed,
        "accounted": accounted,
        "cleared": cleared,
        "pending": pending,
        "variance": variance,
        "activity_count": qs.values("activity_id").distinct().count(),
    }


def monthly_budget(query: dict) -> dict:
    """Monthly budget = program activity budget lines for the month + CD admin
    items for that month. The auto-generated program portion + the CD-added
    administrative portion."""
    fy = query.get("fy") or get_operational_fy()
    month = int(query.get("month") or 1)
    month_key = _month_key(fy, month)
    admin_total = _admin_lines_total(fy, month_key=month_key)
    rollup = get_budget_rollup(fy, month=month)
    return {
        "fy": fy,
        "month": month,
        "monthKey": month_key,
        "programTotal": rollup["planned"],
        "adminTotal": admin_total,
        "total": rollup["planned"] + admin_total,
        "activityCount": rollup["activity_count"],
        "plannedBudget": rollup["planned"],
        "requestedBudget": rollup["requested"],
        "approvedBudget": rollup["approved"],
        "disbursedAmount": rollup["disbursed"],
        "accountedAmount": rollup["accounted"],
        "clearedAmount": rollup["cleared"],
        "pendingAmount": rollup["pending"],
        "variance": rollup["variance"],
    }


def quarterly_budget(query: dict) -> dict:
    """Quarterly budget = program lines + admin items for the quarter."""
    fy = query.get("fy") or get_operational_fy()
    quarter = query.get("quarter") or "Q1"
    # Admin items are monthly; approximate the quarter as the union of its months.
    quarter_months = _quarter_months(quarter)
    admin_total = sum(
        _admin_lines_total(fy, month_key=_month_key(fy, m)) for m in quarter_months
    )
    rollup = get_budget_rollup(fy, quarter=quarter)
    return {
        "fy": fy,
        "quarter": quarter,
        "programTotal": rollup["planned"],
        "adminTotal": admin_total,
        "total": rollup["planned"] + admin_total,
        "activityCount": rollup["activity_count"],
        "plannedBudget": rollup["planned"],
        "requestedBudget": rollup["requested"],
        "approvedBudget": rollup["approved"],
        "disbursedAmount": rollup["disbursed"],
        "accountedAmount": rollup["accounted"],
        "clearedAmount": rollup["cleared"],
        "pendingAmount": rollup["pending"],
        "variance": rollup["variance"],
    }


def fy_budget(query: dict) -> dict:
    """FY budget (RVP summary) = all program lines + all admin items in the FY,
    with by-quarter and by-activity-type breakdowns."""
    from apps.activities.models import ActivityScheduleCostLine

    fy = query.get("fy") or get_operational_fy()
    admin_total = _admin_lines_total(fy)
    rollup = get_budget_rollup(fy)

    by_quarter = {}
    for q in ("Q1", "Q2", "Q3", "Q4"):
        q_rollup = get_budget_rollup(fy, quarter=q)
        by_quarter[q] = q_rollup["planned"]

    by_activity_type = {}
    type_qs = (
        ActivityScheduleCostLine.objects.filter(
            activity__deleted_at__isnull=True, activity__fy=fy
        )
        .values("activity__activity_type")
        .annotate(total=Sum("amount"))
    )
    for row in type_qs:
        by_activity_type[row["activity__activity_type"]] = int(row["total"])

    return {
        "fy": fy,
        "programTotal": rollup["planned"],
        "adminTotal": admin_total,
        "total": rollup["planned"] + admin_total,
        "activityCount": rollup["activity_count"],
        "byQuarter": by_quarter,
        "byActivityType": by_activity_type,
        "plannedBudget": rollup["planned"],
        "requestedBudget": rollup["requested"],
        "approvedBudget": rollup["approved"],
        "disbursedAmount": rollup["disbursed"],
        "accountedAmount": rollup["accounted"],
        "clearedAmount": rollup["cleared"],
        "pendingAmount": rollup["pending"],
        "variance": rollup["variance"],
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


def _calendar_month_of_fy(fy: str, month_of_fy: int) -> int:
    """month_of_fy (1=Oct...12=Sep) -> the calendar month number (1=Jan...12=Dec)
    that ActivityScheduleCostLine.month/Activity.month actually store."""
    return int(_month_key(fy, month_of_fy).split("-")[1])


def _quarter_months(quarter: str) -> list[int]:
    """Quarter → the 3 months-of-fy it spans (1-based, Oct=1)."""
    return {"Q1": [1, 2, 3], "Q2": [4, 5, 6], "Q3": [7, 8, 9], "Q4": [10, 11, 12]}[
        quarter
    ]


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
    "budget_workspace",
]
