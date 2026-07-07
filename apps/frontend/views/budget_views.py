from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission
from django.contrib import messages
from django.db.models import Q, Sum
from datetime import datetime, date, timedelta
import calendar

from apps.budget.services import board as get_budget_board
from apps.fund_requests.weekly_service import (
    get_weekly_request,
    request_advance,
    self_funded,
    generate_weekly_fund_request,
    disburse as disburse_weekly,
)
from apps.fund_requests.models import WeeklyFundRequest
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.geography.models import District
from apps.accounts.models import StaffProfile, User
from apps.budget.models import MonthlyFundRequest
from apps.core.fy import get_operational_fy, get_quarter_date_range, get_fy_date_range
from apps.core.scoping import resolve_user_scope


def parse_date(d_str: str) -> date:
    if isinstance(d_str, (date, datetime)):
        return d_str.date() if isinstance(d_str, datetime) else d_str
    try:
        return datetime.strptime(d_str[:10], "%Y-%m-%d").date()
    except Exception as exc:
        raise ValueError(f"Invalid date format: {d_str}") from exc


def get_weeks_of_month(year, month):
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdatescalendar(year, month)
    weeks = []
    for i, week in enumerate(month_days):
        start_date = week[0]
        end_date = week[-1]
        if start_date.month == month or end_date.month == month:
            weeks.append(
                {
                    "index": i + 1,
                    "label": f"Week {i + 1}",
                    "start": start_date,
                    "end": end_date,
                    "range_str": f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}",
                }
            )
    return weeks


@require_page_permission("monthly_budget")
def monthly_budget_view(request):
    fy = get_operational_fy()
    board_data = get_budget_board(request.user, {"fy": fy})

    # Format UGX compact helper
    def format_ugx_compact(val):
        if not val:
            return "UGX 0"
        if val >= 1_000_000_000:
            return f"UGX {val / 1_000_000_000:.1f}B"
        if val >= 1_000_000:
            return f"UGX {val / 1_000_000:.1f}M"
        if val >= 1_000:
            return f"UGX {val / 1_000:.0f}K"
        return f"UGX {val}"

    summary = board_data.get("summary", {})
    total_fy = summary.get("fiscalYear", 0)
    this_week_total = summary.get("thisWeek", 0)
    this_month_total = summary.get("thisMonth", 0)
    this_quarter_total = summary.get("thisQuarter", 0)

    kpi_strip_items = [
        {
            "label": "This Week's Budget",
            "value": format_ugx_compact(this_week_total),
            "raw_value": int(this_week_total),
            "helper": "Planned",
            "icon": "calendar",
            "variant": "info",
        },
        {
            "label": "This Month's Budget",
            "value": format_ugx_compact(this_month_total),
            "raw_value": int(this_month_total),
            "helper": "Planned",
            "icon": "chart",
            "variant": "blue",
        },
        {
            "label": "This Quarter's Budget",
            "value": format_ugx_compact(this_quarter_total),
            "raw_value": int(this_quarter_total),
            "helper": "Planned",
            "icon": "finance",
            "variant": "warning",
        },
        {
            "label": "Annual FY Total",
            "value": format_ugx_compact(total_fy),
            "raw_value": int(total_fy),
            "helper": f"FY {fy} Total",
            "icon": "currency",
            "variant": "finance",
        },
    ]

    context = {
        "board": board_data,
        "fy": fy,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/budgets/monthly.html", context)


@require_page_permission("fund_requests")
def weekly_fund_requests_view(request):
    user = request.user
    scope = resolve_user_scope(user)

    # 1. Filters & Defaults
    fy = request.GET.get("fy", "2026").strip()
    quarter = request.GET.get("quarter", "Q2").strip()
    month_name = request.GET.get("month", "April").strip()
    district_id = request.GET.get("district", "").strip()
    staff_id = request.GET.get("staff", "").strip()
    status_filter = request.GET.get("status", "").strip()

    MONTH_MAP = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    month_num = MONTH_MAP.get(month_name.lower(), 4)
    year_num = 2025 if month_num >= 10 else 2026

    # Find all weeks in selected month
    weeks_in_month = get_weeks_of_month(year_num, month_num)

    # Default week selection: week containing the latest scheduled activity, or latest fund request, or first week of month
    week_param = request.GET.get("week", "").strip()
    selected_week_start = None
    if week_param:
        try:
            selected_week_start = parse_date(week_param)
        except ValueError:
            pass

    if not selected_week_start:
        # Find latest request/activity week start
        latest_act = (
            Activity.objects.filter(
                deleted_at__isnull=True, scheduled_date__isnull=False
            )
            .order_by("-scheduled_date")
            .first()
        )
        if latest_act:
            latest_d = latest_act.scheduled_date.date()
            selected_week_start = latest_d - timedelta(days=latest_d.weekday())
        else:
            selected_week_start = (
                weeks_in_month[0]["start"] if weeks_in_month else date.today()
            )

    # Normalize selected_week_start to Monday
    selected_week_start = selected_week_start - timedelta(
        days=selected_week_start.weekday()
    )
    selected_week_end = selected_week_start + timedelta(days=6)

    # Tab selector (Weekly vs Monthly)
    active_tab = request.GET.get("tab", "weekly").strip()

    # 2. Scope & Filter Base Queries
    wfr_qs = WeeklyFundRequest.objects.all().order_by("-week_start_date")
    activities_qs = Activity.objects.filter(deleted_at__isnull=True)
    budget_qs = ActivityScheduleCostLine.objects.filter(fiscal_year=fy)

    if not scope.country_scope and scope.staff_ids:
        q_scope = Q(responsible_user=user.user_id)
        if scope.supervised_staff_ids:
            supervised_user_ids = StaffProfile.objects.filter(
                id__in=scope.supervised_staff_ids
            ).values_list("user_id", flat=True)
            q_scope |= Q(responsible_user__in=supervised_user_ids)
        wfr_qs = wfr_qs.filter(q_scope)
        budget_qs = budget_qs.filter(q_scope)

        # Scoped activities
        q_act_scope = Q(responsible_staff_id=user.user_id)
        if scope.supervised_staff_ids:
            q_act_scope |= Q(responsible_staff_id__in=supervised_user_ids)
        activities_qs = activities_qs.filter(q_act_scope)

    # Apply dropdown filters
    if district_id:
        staff_in_district = StaffProfile.objects.filter(
            district_id=district_id
        ).values_list("user_id", flat=True)
        wfr_qs = wfr_qs.filter(responsible_user__in=staff_in_district)
        budget_qs = budget_qs.filter(school__district_id=district_id)
        activities_qs = activities_qs.filter(school__district_id=district_id)
    if staff_id:
        wfr_qs = wfr_qs.filter(responsible_user=staff_id)
        budget_qs = budget_qs.filter(responsible_user=staff_id)
        activities_qs = activities_qs.filter(responsible_staff_id=staff_id)
    if status_filter:
        wfr_qs = wfr_qs.filter(status=status_filter)

    # 3. Calculate KPIs
    weekly_requests_count = wfr_qs.filter(week_start_date=selected_week_start).count()
    monthly_requests_count = wfr_qs.filter(week_start_date__month=month_num).count()
    draft_count = wfr_qs.filter(
        status__in=["pending_responsible_confirmation", "not_requested"]
    ).count()
    pending_approval_count = wfr_qs.filter(
        status__in=[
            "pending_pl_approval",
            "pending_cd_approval",
            "pending_rvp_approval",
        ]
    ).count()
    ready_disbursement_count = wfr_qs.filter(status="confirmed_for_advance").count()

    planned_value = (
        budget_qs.filter(planned_date__month=month_num).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )
    requested_this_month = (
        wfr_qs.filter(week_start_date__month=month_num).aggregate(
            total=Sum("total_amount")
        )["total"]
        or 0
    )
    accountability_pending_count = wfr_qs.filter(
        status="disbursed", accounted_amount__isnull=True
    ).count()

    kpis = {
        "weekly_requests": weekly_requests_count,
        "monthly_requests": monthly_requests_count,
        "draft": draft_count,
        "pending_approval": pending_approval_count,
        "ready_disbursement": ready_disbursement_count,
        "planned_value": planned_value,
        "requested_this_month": requested_this_month,
        "accountability_pending": accountability_pending_count,
    }

    # Format UGX compact helper
    def format_ugx_compact(val):
        if not val:
            return "UGX 0"
        if val >= 1_000_000_000:
            return f"UGX {val / 1_000_000_000:.1f}B"
        if val >= 1_000_000:
            return f"UGX {val / 1_000_000:.1f}M"
        if val >= 1_000:
            return f"UGX {val / 1_000:.0f}K"
        return f"UGX {val}"

    # Construct unified KPI strip items
    kpi_strip_items = [
        {
            "label": "Weekly Requests",
            "value": str(weekly_requests_count),
            "raw_value": weekly_requests_count,
            "helper": "This Week",
            "icon": "calendar",
            "variant": "info",
        },
        {
            "label": "Monthly Requests",
            "value": str(monthly_requests_count),
            "raw_value": monthly_requests_count,
            "helper": "This Month",
            "icon": "report",
            "variant": "blue",
        },
        {
            "label": "Draft Requests",
            "value": str(draft_count),
            "raw_value": draft_count,
            "helper": "Total Draft",
            "icon": "file",
            "variant": "neutral",
        },
        {
            "label": "Pending Approval",
            "value": str(pending_approval_count),
            "raw_value": pending_approval_count,
            "helper": "Total Pending",
            "icon": "clock",
            "variant": "warning",
        },
        {
            "label": "Ready for Disbursement",
            "value": str(ready_disbursement_count),
            "raw_value": ready_disbursement_count,
            "helper": "Total Ready",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Total Planned Value",
            "value": format_ugx_compact(planned_value),
            "raw_value": int(planned_value),
            "helper": "This Month",
            "icon": "currency",
            "variant": "finance",
        },
        {
            "label": "Total Requested",
            "value": format_ugx_compact(requested_this_month),
            "raw_value": int(requested_this_month),
            "helper": "This Month",
            "icon": "finance",
            "variant": "finance",
        },
        {
            "label": "Accountability Pending",
            "value": str(accountability_pending_count),
            "raw_value": accountability_pending_count,
            "helper": "Requests",
            "icon": "warning",
            "variant": "danger",
        },
    ]

    # 4. Weekly Fund Request details
    active_wfr = wfr_qs.filter(week_start_date=selected_week_start).first()
    weekly_lines = []
    weekly_total = 0
    wfr_status = "No Request"
    if active_wfr:
        wfr_status = active_wfr.status
        weekly_total = active_wfr.total_amount
        for line in active_wfr.lines.select_related("activity_budget_line__activity"):
            adv = line.activity_budget_line.advance_requests.first()
            status_raw = adv.status if adv else "draft_from_schedule"

            status_labels = {
                "draft_from_schedule": "Draft",
                "pending_responsible_confirmation": "Awaiting Confirmation",
                "confirmed_for_advance": "Ready",
                "self_funded_pending_reimbursement": "Self-funded",
                "disbursed": "Disbursed",
            }
            status_label = status_labels.get(status_raw, "Auto-calculated")

            act_type = line.activity_budget_line.activity.activity_type
            source_map = {
                "school_visit": "School Visits",
                "follow_up_visit": "School Visits",
                "coaching_visit": "School Visits",
                "in_school_support": "School Visits",
                "core_visit": "School Visits",
                "training": "Cluster Training",
                "school_improvement_training": "Cluster Training",
                "cluster_training": "Cluster Training",
                "core_training": "Cluster Training",
                "cluster_meeting": "Cluster Meeting",
            }
            source = source_map.get(act_type, "Other")

            weekly_lines.append(
                {
                    "id": line.id,
                    "source": source,
                    "cost_item": line.description,
                    "quantity": line.quantity,
                    "unit_cost": line.unit_cost,
                    "total_cost": line.total_cost,
                    "activity_id": line.activity_budget_line.activity_id,
                    "status": status_label,
                    "status_raw": status_raw,
                }
            )

    # 5. Source Activities Listing
    source_activities = []
    scoped_acts = activities_qs.filter(
        scheduled_date__date__gte=selected_week_start,
        scheduled_date__date__lte=selected_week_end,
    )
    for act in scoped_acts.select_related("school", "cluster"):
        title = ""
        location = ""
        if act.activity_type in [
            "school_visit",
            "follow_up_visit",
            "coaching_visit",
            "in_school_support",
            "core_visit",
        ]:
            title = f"{act.school.name} Visit" if act.school else "School Visit"
            location = (
                f"{act.school.district.name} District"
                if (act.school and act.school.district)
                else "Unknown District"
            )
        elif act.activity_type == "cluster_meeting":
            title = f"{act.cluster.name} Meeting" if act.cluster else "Cluster Meeting"
            location = (
                f"{act.cluster.district.name} District"
                if (act.cluster and act.cluster.district)
                else "Unknown District"
            )
        else:
            title = (
                f"{act.cluster.name} Training" if act.cluster else "Cluster Training"
            )
            location = (
                f"{act.cluster.district.name} District"
                if (act.cluster and act.cluster.district)
                else "Unknown District"
            )

        source_activities.append(
            {
                "id": act.id,
                "type": act.activity_type,
                "title": title,
                "date_str": act.scheduled_date.strftime("%b %d, %Y")
                if act.scheduled_date
                else "Unscheduled",
                "location": location,
                "purpose": act.activity_purpose_text
                or act.get_purpose_intervention_display()
                or "Operational Support",
                "status": act.status,
            }
        )

    # 6. Monthly Preview
    monthly_weeks = []
    for wk in weeks_in_month:
        wfr = wfr_qs.filter(week_start_date=wk["start"]).first()
        monthly_weeks.append(
            {
                "label": wk["label"],
                "range_str": wk["range_str"],
                "total": wfr.total_amount if wfr else 0,
            }
        )

    # Monthly Summary by Activity Type
    month_lines = budget_qs.filter(planned_date__month=month_num)

    school_visits_total = (
        month_lines.filter(
            activity__activity_type__in=[
                "school_visit",
                "follow_up_visit",
                "coaching_visit",
                "in_school_support",
                "core_visit",
            ]
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )

    trainings_total = (
        month_lines.filter(
            activity__activity_type__in=[
                "training",
                "school_improvement_training",
                "cluster_training",
                "core_training",
            ]
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )

    meetings_total = (
        month_lines.filter(activity__activity_type="cluster_meeting").aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )

    admin_total = (
        month_lines.exclude(
            activity__activity_type__in=[
                "school_visit",
                "follow_up_visit",
                "coaching_visit",
                "in_school_support",
                "core_visit",
                "training",
                "school_improvement_training",
                "cluster_training",
                "core_training",
                "cluster_meeting",
            ]
        ).aggregate(total=Sum("amount"))["total"]
        or 0
    )

    monthly_totals_by_type = {
        "visits": school_visits_total,
        "trainings": trainings_total,
        "meetings": meetings_total,
        "admin": admin_total,
        "total": school_visits_total + trainings_total + meetings_total + admin_total,
    }

    # Stepper state based on MonthlyFundRequest model or defaults
    mfr = MonthlyFundRequest.objects.filter(
        fy=fy, month=month_num, staff_id=user.user_id
    ).first()
    mfr_status = mfr.status if mfr else "draft"
    step_active = 1
    if mfr_status in ["submitted", "submitted_to_pl"]:
        step_active = 2
    elif mfr_status in ["approved_by_pl", "submitted_to_cd"]:
        step_active = 3
    elif mfr_status in ["approved_by_cd", "submitted_to_rvp"]:
        step_active = 4
    elif mfr_status in ["approved_by_rvp", "sent_to_accountant", "disbursed"]:
        step_active = 5

    # 7. Insights Panel
    this_week_requests = wfr_qs.filter(week_start_date=selected_week_start)
    this_week_count = this_week_requests.count()
    this_week_val = (
        this_week_requests.aggregate(total=Sum("total_amount"))["total"] or 0
    )

    attention_wfr = wfr_qs.filter(
        status__in=["pending_responsible_confirmation", "not_requested"]
    )
    attention_count = attention_wfr.count()

    due_date = date(year_num, month_num, 25)
    days_remaining = (due_date - date.today()).days

    missing_cost_count = activities_qs.filter(
        scheduled_date__month=month_num, cost_missing=True
    ).count()

    recommended_action = "Generate this week's requests"
    recommended_desc = "Compile fund requests from scheduled My Plan activities."
    can_take_action = True
    action_type = "generate"
    if active_wfr:
        if active_wfr.status == "pending_responsible_confirmation":
            recommended_action = "Confirm this week's request"
            recommended_desc = "Verify lines and confirm advance disbursement requests."
            action_type = "confirm"
        else:
            recommended_action = "No immediate action pending"
            recommended_desc = "All weekly requests have been finalized and routed."
            can_take_action = False
            action_type = "none"

    insights = {
        "this_week_count": this_week_count,
        "this_week_val": this_week_val,
        "attention_count": attention_count,
        "due_date_str": due_date.strftime("%b %d, %Y"),
        "days_remaining": max(0, days_remaining),
        "missing_cost_count": missing_cost_count,
        "recommended_action": recommended_action,
        "recommended_desc": recommended_desc,
        "can_take_action": can_take_action,
        "action_type": action_type,
    }

    # 8. Period Breakdown
    def get_wfr_sum(start_d, end_d):
        qs = WeeklyFundRequest.objects.filter(fy=fy)
        if start_d:
            qs = qs.filter(week_start_date__gte=start_d)
        if end_d:
            qs = qs.filter(week_start_date__lte=end_d)
        if not scope.country_scope and scope.staff_ids:
            q_scope = Q(responsible_user=user.user_id)
            if scope.supervised_staff_ids:
                q_scope |= Q(responsible_user__in=supervised_user_ids)
            qs = qs.filter(q_scope)
        return qs.aggregate(total=Sum("total_amount"))["total"] or 0

    breakdown = {
        "week": get_wfr_sum(selected_week_start, selected_week_start),
        "month": requested_this_month,
        "quarter": get_wfr_sum(*get_quarter_date_range(fy, quarter)),
        "fy": get_wfr_sum(*get_fy_date_range(fy)),
    }

    # Dropdowns options
    districts = District.objects.all().order_by("name")
    staff_profiles = (
        StaffProfile.objects.filter(deleted_at__isnull=True)
        .select_related("user")
        .order_by("user__name")
    )

    # Generate list of weeks in selected month for dropdown filter
    dropdown_weeks = []
    for wk in weeks_in_month:
        dropdown_weeks.append(
            {
                "val": wk["start"].isoformat(),
                "label": f"{wk['start'].strftime('%b %d')} - {wk['end'].strftime('%b %d')}",
            }
        )

    # PL fund queue — the supervised team's real weekly requests for the selected week
    import json

    _status_display = {
        "pending_responsible_confirmation": (
            "Awaiting Confirmation",
            "bg-amber-50 text-amber-700 border-amber-200",
        ),
        "confirmed_for_advance": (
            "Ready",
            "bg-emerald-50 text-emerald-700 border-emerald-200",
        ),
        "disbursed": ("Disbursed", "bg-blue-50 text-blue-700 border-blue-200"),
        "paid": ("Paid", "bg-blue-50 text-blue-700 border-blue-200"),
        "closed": ("Closed", "bg-emerald-50 text-emerald-700 border-emerald-200"),
        "cleared": ("Cleared", "bg-emerald-50 text-emerald-700 border-emerald-200"),
        "cancelled": ("Cancelled", "bg-slate-50 text-slate-500 border-slate-200"),
        "not_requested": (
            "Not Requested",
            "bg-slate-50 text-slate-500 border-slate-200",
        ),
        "self_funded": (
            "Self Funded",
            "bg-indigo-50 text-indigo-700 border-indigo-200",
        ),
        "self_funded_pending_reimbursement": (
            "Pending Reimbursement",
            "bg-indigo-50 text-indigo-700 border-indigo-200",
        ),
    }
    pl_week_qs = wfr_qs.filter(week_start_date=selected_week_start).prefetch_related(
        "lines"
    )
    _pl_user_ids = [w.responsible_user for w in pl_week_qs]
    _pl_users = {u.id: u for u in User.objects.filter(id__in=_pl_user_ids)}
    _pl_profiles = {
        sp.user_id: sp for sp in StaffProfile.objects.filter(user_id__in=_pl_user_ids)
    }
    _pl_districts = dict(District.objects.values_list("id", "name"))

    pl_queue_items = []
    for w in pl_week_qs:
        u = _pl_users.get(w.responsible_user)
        sp = _pl_profiles.get(w.responsible_user)
        lines_list, counts = (
            [],
            {"visits": 0, "partner": 0, "clusters": 0, "trainings": 0},
        )
        for line in w.lines.all():
            lines_list.append(
                {
                    "category": line.description or line.line_item_type,
                    "quantity": line.quantity,
                    "unit_cost": line.unit_cost,
                    "total": line.total_cost,
                }
            )
            lt = (line.line_item_type or "").lower()
            if "partner" in lt:
                counts["partner"] += line.quantity
            elif "training" in lt:
                counts["trainings"] += line.quantity
            elif "meeting" in lt or "cluster" in lt:
                counts["clusters"] += line.quantity
            elif "visit" in lt:
                counts["visits"] += line.quantity
        status_label, status_class = _status_display.get(
            w.status,
            (
                w.status.replace("_", " ").title(),
                "bg-slate-50 text-slate-500 border-slate-200",
            ),
        )
        pl_queue_items.append(
            {
                "id": w.id,
                "user_name": (u.name if u else "—")
                + (" (My Own Plan)" if w.responsible_user == user.user_id else ""),
                "district": _pl_districts.get(sp.primary_district_id, "—")
                if sp
                else "—",
                "region": (sp.portfolio if sp and sp.portfolio else "—"),
                "requested": w.total_amount,
                "status": status_label,
                "status_class": status_class,
                "visits": counts["visits"],
                "partner": counts["partner"],
                "clusters": counts["clusters"],
                "trainings": counts["trainings"],
                "lines": lines_list,
            }
        )

    # PL header KPI strip — live sums over the scoped queue
    month_wfrs = wfr_qs.filter(
        week_start_date__year=year_num, week_start_date__month=month_num
    )
    _m_total = month_wfrs.aggregate(v=Sum("total_amount"))["v"] or 0
    _m_count = month_wfrs.count()
    _wait_qs = month_wfrs.filter(status="pending_responsible_confirmation")
    _ready_qs = month_wfrs.filter(status="confirmed_for_advance")
    pl_kpis = {
        "month_total": format_ugx_compact(_m_total),
        "awaiting_total": format_ugx_compact(
            _wait_qs.aggregate(v=Sum("total_amount"))["v"] or 0
        ),
        "awaiting_count": _wait_qs.count(),
        "ready_total": format_ugx_compact(
            _ready_qs.aggregate(v=Sum("total_amount"))["v"] or 0
        ),
        "ready_count": _ready_qs.count(),
        "disbursed_total": format_ugx_compact(
            month_wfrs.aggregate(v=Sum("disbursed_amount"))["v"] or 0
        ),
        "fy_total": format_ugx_compact(breakdown["fy"]),
        "avg_per_request": format_ugx_compact(
            round(_m_total / _m_count) if _m_count else 0
        ),
        "request_count": _m_count,
    }

    # Recent approval/return activity across the scoped queue (latest status changes)
    pl_recent = []
    for w in wfr_qs.exclude(status="pending_responsible_confirmation").order_by(
        "-updated_at"
    )[:3]:
        u = _pl_users.get(w.responsible_user)
        if u is None:
            u = User.objects.filter(id=w.responsible_user).first()
        status_label, _cls = _status_display.get(
            w.status, (w.status.replace("_", " ").title(), "")
        )
        pl_recent.append(
            {
                "who": u.name if u else "—",
                "what": f"Week of {w.week_start_date.strftime('%d %b')} — {status_label}",
                "when": w.updated_at.strftime("%d %b, %I:%M %p")
                if w.updated_at
                else "—",
                "amount": w.total_amount,
                "positive": w.status
                in ["confirmed_for_advance", "disbursed", "paid", "closed", "cleared"],
            }
        )

    pl_queue_items_json = json.dumps(pl_queue_items)

    context = {
        "kpis": kpis,
        "kpi_strip_items": kpi_strip_items,
        "active_wfr": active_wfr,
        "wfr_status": wfr_status,
        "weekly_lines": weekly_lines,
        "weekly_total": weekly_total,
        "source_activities": source_activities,
        "monthly_weeks": monthly_weeks,
        "monthly_totals_by_type": monthly_totals_by_type,
        "step_active": step_active,
        "insights": insights,
        "breakdown": breakdown,
        "districts": districts,
        "staff_profiles": staff_profiles,
        "dropdown_weeks": dropdown_weeks,
        # Selected states
        "selected_fy": fy,
        "selected_quarter": quarter,
        "selected_month": month_name,
        "selected_week": selected_week_start.isoformat(),
        "selected_week_label": f"{selected_week_start.strftime('%b %d')} – {selected_week_end.strftime('%b %d')}, {selected_week_start.year}",
        "selected_district": district_id,
        "selected_staff": staff_id,
        "selected_status": status_filter,
        "active_tab": active_tab,
        # PL Specific Data
        "is_pl": (request.user.active_role == "Program Lead"),
        "pl_queue_items": pl_queue_items,
        "pl_queue_items_json": pl_queue_items_json,
        "pl_recent": pl_recent,
        "pl_kpis": pl_kpis,
        "month_options": [
            "October", "November", "December", "January", "February", "March",
            "April", "May", "June", "July", "August", "September",
        ],
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/fund_requests/htmx_response.html", context)

    return render(request, "pages/fund_requests/weekly.html", context)


@require_page_permission("fund_requests")
def weekly_fund_request_detail_view(request, request_id):
    req = get_weekly_request(request_id, request.user)
    context = {
        "req": req,
    }
    return render(request, "pages/fund_requests/detail.html", context)


@require_page_permission("fund_requests")
def weekly_fund_request_confirm_action(request, request_id):
    if request.method == "POST":
        try:
            request_advance(request_id, request.user)
            messages.success(
                request, "Weekly fund request confirmed for advance successfully."
            )
        except Exception as e:
            messages.error(request, f"Error: {e}")

    active_wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
    return redirect(
        f"/fund-requests/weekly?week={active_wfr.week_start_date.isoformat()}"
    )


@require_page_permission("fund_requests")
def weekly_fund_request_self_funded_action(request, request_id):
    if request.method == "POST":
        try:
            self_funded(request_id, request.user)
            messages.success(
                request, "Weekly fund request successfully marked as self-funded."
            )
        except Exception as e:
            messages.error(request, f"Error: {e}")

    active_wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
    return redirect(
        f"/fund-requests/weekly?week={active_wfr.week_start_date.isoformat()}"
    )


@require_page_permission("fund_requests")
def generate_request_action(request):
    week_start_str = ""
    if request.method == "POST":
        week_start_str = request.POST.get("week_start", "").strip()
        user_id = request.POST.get("staff_id", request.user.user_id).strip()
        if not week_start_str:
            messages.error(request, "Week start date is required.")
        else:
            try:
                wfr = generate_weekly_fund_request(user_id, week_start_str)
                if wfr:
                    messages.success(
                        request,
                        f"Successfully generated weekly fund request for {week_start_str}.",
                    )
                else:
                    messages.warning(
                        request,
                        "No activities scheduled for this week to generate requests.",
                    )
            except Exception as e:
                messages.error(request, f"Error generating request: {e}")

    return redirect(f"/fund-requests/weekly?week={week_start_str}")


@require_page_permission("weekly_fund_request_disburse")
def weekly_fund_request_disburse_action(request, request_id):
    if request.user.active_role != "Accountant":
        messages.error(
            request, "Only the Program Accountant can disburse fund requests."
        )
        return redirect(f"/fund-requests/weekly/{request_id}")

    if request.method == "POST":
        amount = request.POST.get("amount", "")
        method = request.POST.get("method", "mobile_money")
        reference = request.POST.get("reference", "").strip()

        payload = {
            "method": method,
            "reference": reference,
        }
        if amount:
            payload["amount"] = int(amount)

        try:
            disburse_weekly(request_id, payload, request.user)
            messages.success(request, "Weekly fund request disbursed successfully.")
        except Exception as e:
            messages.error(request, f"Error disbursing funds: {e}")

    return redirect(f"/fund-requests/weekly/{request_id}")
