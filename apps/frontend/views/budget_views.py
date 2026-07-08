from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission
from django.contrib import messages
from django.db.models import Q, Sum, Count
from datetime import datetime, date, timedelta
import calendar

from apps.budget.services import board as get_budget_board
from apps.fund_requests.weekly_service import (
    get_weekly_request,
    request_advance,
    self_funded,
    generate_weekly_fund_request,
    disburse as disburse_weekly
)
from apps.fund_requests.models import WeeklyFundRequest
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.geography.models import District
from apps.accounts.models import StaffProfile
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
            weeks.append({
                "index": i + 1,
                "label": f"Week {i + 1}",
                "start": start_date,
                "end": end_date,
                "range_str": f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}"
            })
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
        }
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
    
    MONTH_MAP = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12}
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
        latest_act = Activity.objects.filter(deleted_at__isnull=True, scheduled_date__isnull=False).order_by("-scheduled_date").first()
        if latest_act:
            latest_d = latest_act.scheduled_date.date()
            selected_week_start = latest_d - timedelta(days=latest_d.weekday())
        else:
            selected_week_start = weeks_in_month[0]["start"] if weeks_in_month else date.today()
            
    # Normalize selected_week_start to Monday
    selected_week_start = selected_week_start - timedelta(days=selected_week_start.weekday())
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
            supervised_user_ids = StaffProfile.objects.filter(id__in=scope.supervised_staff_ids).values_list("user_id", flat=True)
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
        staff_in_district = StaffProfile.objects.filter(district_id=district_id).values_list("user_id", flat=True)
        wfr_qs = wfr_qs.filter(responsible_user__in=staff_in_district)
        budget_qs = budget_qs.filter(school__district_id=district_id)
        activities_qs = activities_qs.filter(school__district_id=district_id)
    if staff_id:
        wfr_qs = wfr_qs.filter(responsible_user=staff_id)
        budget_qs = budget_qs.filter(responsible_user=staff_id)
        activities_qs = activities_qs.filter(responsible_staff_id=staff_id)
    if status_filter:
        wfr_qs = wfr_qs.filter(status=status_filter)

    # CSV export of the currently filtered requests (same pattern as /clusters).
    if request.GET.get("export", "").strip() == "csv":
        import csv
        from django.http import HttpResponse
        from apps.accounts.models import User
        rows = list(wfr_qs[:5000])
        requester_names = dict(
            User.objects.filter(id__in=[r.responsible_user for r in rows]).values_list("id", "name")
        )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="weekly_fund_requests.csv"'
        writer = csv.writer(response)
        writer.writerow(["Request ID", "Week Start", "Requested By", "Total Amount (UGX)",
                         "Disbursed (UGX)", "Status", "FY"])
        for r in rows:
            writer.writerow([
                r.id, r.week_start_date, requester_names.get(r.responsible_user, r.responsible_user),
                r.total_amount or 0, r.disbursed_amount or 0, r.status, r.fy,
            ])
        return response

    # 3. Calculate KPIs
    weekly_requests_count = wfr_qs.filter(week_start_date=selected_week_start).count()
    monthly_requests_count = wfr_qs.filter(week_start_date__month=month_num).count()
    draft_count = wfr_qs.filter(status__in=["pending_responsible_confirmation", "not_requested"]).count()
    pending_approval_count = wfr_qs.filter(status__in=["pending_pl_approval", "pending_cd_approval", "pending_rvp_approval"]).count()
    ready_disbursement_count = wfr_qs.filter(status="confirmed_for_advance").count()
    
    planned_value = budget_qs.filter(planned_date__month=month_num).aggregate(total=Sum("amount"))["total"] or 0
    requested_this_month = wfr_qs.filter(week_start_date__month=month_num).aggregate(total=Sum("total_amount"))["total"] or 0
    accountability_pending_count = wfr_qs.filter(status="disbursed", accounted_amount__isnull=True).count()
    
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
        }
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
            
            weekly_lines.append({
                "id": line.id,
                "source": source,
                "cost_item": line.description,
                "quantity": line.quantity,
                "unit_cost": line.unit_cost,
                "total_cost": line.total_cost,
                "activity_id": line.activity_budget_line.activity_id,
                "status": status_label,
                "status_raw": status_raw,
            })
            
    # 5. Source Activities Listing
    source_activities = []
    scoped_acts = activities_qs.filter(
        scheduled_date__date__gte=selected_week_start,
        scheduled_date__date__lte=selected_week_end,
    )
    for act in scoped_acts.select_related("school", "cluster"):
        title = ""
        location = ""
        if act.activity_type in ["school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit"]:
            title = f"{act.school.name} Visit" if act.school else "School Visit"
            location = f"{act.school.district.name} District" if (act.school and act.school.district) else "Unknown District"
        elif act.activity_type == "cluster_meeting":
            title = f"{act.cluster.name} Meeting" if act.cluster else "Cluster Meeting"
            location = f"{act.cluster.district.name} District" if (act.cluster and act.cluster.district) else "Unknown District"
        else:
            title = f"{act.cluster.name} Training" if act.cluster else "Cluster Training"
            location = f"{act.cluster.district.name} District" if (act.cluster and act.cluster.district) else "Unknown District"
            
        source_activities.append({
            "id": act.id,
            "type": act.activity_type,
            "title": title,
            "date_str": act.scheduled_date.strftime("%b %d, %Y") if act.scheduled_date else "Unscheduled",
            "location": location,
            "purpose": act.activity_purpose_text or act.get_purpose_intervention_display() or "Operational Support",
            "status": act.status,
        })
        
    # 6. Monthly Preview
    monthly_weeks = []
    for wk in weeks_in_month:
        wfr = wfr_qs.filter(week_start_date=wk["start"]).first()
        monthly_weeks.append({
            "label": wk["label"],
            "range_str": wk["range_str"],
            "total": wfr.total_amount if wfr else 0,
        })
        
    # Monthly Summary by Activity Type
    month_lines = budget_qs.filter(planned_date__month=month_num)
    
    school_visits_total = month_lines.filter(
        activity__activity_type__in=["school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit"]
    ).aggregate(total=Sum("amount"))["total"] or 0
    
    trainings_total = month_lines.filter(
        activity__activity_type__in=["training", "school_improvement_training", "cluster_training", "core_training"]
    ).aggregate(total=Sum("amount"))["total"] or 0
    
    meetings_total = month_lines.filter(
        activity__activity_type="cluster_meeting"
    ).aggregate(total=Sum("amount"))["total"] or 0
    
    admin_total = month_lines.exclude(
        activity__activity_type__in=["school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit",
                                     "training", "school_improvement_training", "cluster_training", "core_training",
                                     "cluster_meeting"]
    ).aggregate(total=Sum("amount"))["total"] or 0
    
    monthly_totals_by_type = {
        "visits": school_visits_total,
        "trainings": trainings_total,
        "meetings": meetings_total,
        "admin": admin_total,
        "total": school_visits_total + trainings_total + meetings_total + admin_total,
    }
    
    # Stepper state based on MonthlyFundRequest model or defaults
    mfr = MonthlyFundRequest.objects.filter(fy=fy, month=month_num, staff_id=user.user_id).first()
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
    this_week_val = this_week_requests.aggregate(total=Sum("total_amount"))["total"] or 0
    
    attention_wfr = wfr_qs.filter(status__in=["pending_responsible_confirmation", "not_requested"])
    attention_count = attention_wfr.count()
    
    due_date = date(year_num, month_num, 25)
    days_remaining = (due_date - date.today()).days
    
    missing_cost_count = activities_qs.filter(scheduled_date__month=month_num, cost_missing=True).count()
    
    # Scheduling an activity auto-generates its Weekly Fund Request (see
    # activities.services.create/reschedule/partner_schedule ->
    # weekly_service.trigger_generate_for_activity) — there is no manual
    # "Generate" step in the normal flow. active_wfr missing here means
    # either nothing is scheduled this week (nothing to do) or a genuine
    # sync anomaly (pre-existing/legacy activities that bypassed the
    # service layer) — the "generate" action_type only ever covers the
    # latter, as a recovery path.
    if active_wfr:
        if active_wfr.status == "pending_responsible_confirmation":
            recommended_action = "Confirm this week's request"
            recommended_desc = "Verify lines and confirm advance disbursement requests."
            can_take_action = True
            action_type = "confirm"
        else:
            recommended_action = "No immediate action pending"
            recommended_desc = "All weekly requests have been finalized and routed."
            can_take_action = False
            action_type = "none"
    else:
        has_scheduled_this_week = budget_qs.filter(
            planned_date__gte=selected_week_start, planned_date__lte=selected_week_end
        ).exclude(activity__status="cancelled").exists()
        if has_scheduled_this_week:
            recommended_action = "Sync this week's request"
            recommended_desc = "Activities are scheduled but the request hasn't synced yet — this should be automatic; use this to recover."
            can_take_action = True
            action_type = "generate"
        else:
            recommended_action = "No immediate action pending"
            recommended_desc = "No activities scheduled for this week yet."
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
    staff_profiles = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user").order_by("user__name")
    
    # Generate list of weeks in selected month for dropdown filter
    dropdown_weeks = []
    for wk in weeks_in_month:
        dropdown_weeks.append({
            "val": wk["start"].isoformat(),
            "label": f"{wk['start'].strftime('%b %d')} - {wk['end'].strftime('%b %d')}"
        })

    # CCEO Fund Queue for PL layout — real WeeklyFundRequests awaiting PL action
    from apps.accounts.models import User

    pl_awaiting_statuses = ["submitted_to_pl", "pending_pl_approval"]
    pl_queue_qs = wfr_qs.filter(fy=fy, status__in=pl_awaiting_statuses).order_by("-week_start_date").prefetch_related("lines")
    pl_queue_wfrs = list(pl_queue_qs[:20])

    pl_user_ids = [w.responsible_user for w in pl_queue_wfrs]
    pl_users_by_id = {u.id: u for u in User.objects.filter(id__in=pl_user_ids)}
    pl_profiles_by_user_id = {p.user_id: p for p in StaffProfile.objects.filter(user_id__in=pl_user_ids)}
    pl_district_ids = {p.primary_district_id for p in pl_profiles_by_user_id.values() if p.primary_district_id}
    pl_districts_by_id = {d.id: d for d in District.objects.filter(id__in=pl_district_ids).select_related("region")}

    def _count_lines(lines, include=(), exclude=()):
        total = 0
        for l in lines:
            text = f"{l.description or ''} {l.line_item_type or ''}".lower()
            if any(kw in text for kw in include) and not any(kw in text for kw in exclude):
                total += l.quantity or 0
        return total

    pl_queue_items = []
    for w in pl_queue_wfrs:
        user_obj = pl_users_by_id.get(w.responsible_user)
        profile_obj = pl_profiles_by_user_id.get(w.responsible_user)
        district_name = "—"
        region_name = "—"
        if profile_obj and profile_obj.primary_district_id:
            d_obj = pl_districts_by_id.get(profile_obj.primary_district_id)
            if d_obj:
                district_name = d_obj.name
                region_name = d_obj.region.name if d_obj.region else "—"

        lines_all = list(w.lines.all())
        lines_list = [{
            "category": l.description or l.line_item_type,
            "quantity": l.quantity,
            "unit_cost": l.unit_cost,
            "total": l.total_cost,
        } for l in lines_all]

        status_display = "Awaiting Approval"
        status_class = "bg-amber-50 text-amber-700 border-amber-200"
        if w.status.startswith("returned"):
            status_display = "Returned"
            status_class = "bg-rose-50 text-rose-700 border-rose-200"

        pl_queue_items.append({
            "id": w.id,
            "user_name": user_obj.name if user_obj else "System User",
            "district": district_name,
            "region": region_name,
            "requested": w.total_amount,
            "status": status_display,
            "status_class": status_class,
            "visits": _count_lines(lines_all, include=["visit"], exclude=["partner"]),
            "partner": _count_lines(lines_all, include=["partner"]),
            "clusters": _count_lines(lines_all, include=["meeting"]),
            "trainings": _count_lines(lines_all, include=["training"]),
            "lines": lines_list,
            "week_start": w.week_start_date.strftime("%b %d, %Y"),
            "week_end": w.week_end_date.strftime("%b %d, %Y"),
        })

    # PL KPI strip — real aggregates over the scoped queryset
    pl_fy_qs = wfr_qs.filter(fy=fy)
    pl_awaiting_agg = pl_fy_qs.filter(status__in=pl_awaiting_statuses).aggregate(total=Sum("total_amount"), n=Count("id"))
    pl_approved_today_agg = pl_fy_qs.filter(status="approved_by_pl", updated_at__date=date.today()).aggregate(total=Sum("total_amount"), n=Count("id"))
    pl_returned_agg = pl_fy_qs.filter(status="returned_by_pl").aggregate(total=Sum("total_amount"), n=Count("id"))
    pl_kpis = {
        "requested_month": format_ugx_compact(requested_this_month),
        "requested_month_count": monthly_requests_count,
        "awaiting_sum": format_ugx_compact(pl_awaiting_agg["total"] or 0),
        "awaiting_count": pl_awaiting_agg["n"] or 0,
        "approved_today_sum": format_ugx_compact(pl_approved_today_agg["total"] or 0),
        "approved_today_count": pl_approved_today_agg["n"] or 0,
        "returned_sum": format_ugx_compact(pl_returned_agg["total"] or 0),
        "returned_count": pl_returned_agg["n"] or 0,
    }

    # Recent PL approval activity (latest real decisions)
    pl_recent_wfrs = list(pl_fy_qs.filter(status__in=["approved_by_pl", "returned_by_pl"]).order_by("-updated_at")[:3])
    pl_recent_users = {u.id: u.name for u in User.objects.filter(id__in=[w.responsible_user for w in pl_recent_wfrs])}
    pl_recent = [{
        "name": pl_recent_users.get(w.responsible_user, "System User"),
        "approved": w.status == "approved_by_pl",
        "when": w.updated_at.strftime("%d %b %Y, %I:%M %p"),
        "amount": format_ugx_compact(w.total_amount or 0),
    } for w in pl_recent_wfrs]

    # Approval rate donut (selected month, by request count)
    passed_pl_statuses = ["approved_by_pl", "submitted_to_cd", "approved_by_cd", "submitted_to_rvp",
                          "approved_by_rvp", "sent_to_accountant", "disbursed", "accounted", "accountability_pending"]
    month_pl_qs = pl_fy_qs.filter(week_start_date__month=month_num)
    rate_approved = month_pl_qs.filter(status__in=passed_pl_statuses).count()
    rate_returned = month_pl_qs.filter(status="returned_by_pl").count()
    rate_pending = month_pl_qs.filter(status__in=pl_awaiting_statuses).count()
    rate_total = rate_approved + rate_returned + rate_pending
    pl_rate = {
        "total": rate_total,
        "approved_pct": round(rate_approved * 100 / rate_total) if rate_total else 0,
        "returned_pct": round(rate_returned * 100 / rate_total) if rate_total else 0,
        "pending_pct": round(rate_pending * 100 / rate_total) if rate_total else 0,
    }
    pl_rate["returned_offset"] = pl_rate["approved_pct"]
    pl_rate["pending_offset"] = pl_rate["approved_pct"] + pl_rate["returned_pct"]

    # Budget mix (selected month, from the real planned cost-line aggregates above)
    mix_total = monthly_totals_by_type["total"]

    def _mix_part(v):
        return {"amount": format_ugx_compact(v), "pct": round(v * 100 / mix_total, 1) if mix_total else 0}

    pl_budget_mix = {
        "total": mix_total,
        "visits": _mix_part(monthly_totals_by_type["visits"]),
        "trainings": _mix_part(monthly_totals_by_type["trainings"]),
        "meetings": _mix_part(monthly_totals_by_type["meetings"]),
        "admin": _mix_part(monthly_totals_by_type["admin"]),
    }

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
        "pl_kpis": pl_kpis,
        "pl_recent": pl_recent,
        "pl_rate": pl_rate,
        "pl_budget_mix": pl_budget_mix,
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
            messages.success(request, "Weekly fund request confirmed for advance successfully.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            
    active_wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
    return redirect(f"/fund-requests/weekly?week={active_wfr.week_start_date.isoformat()}")

@require_page_permission("fund_requests")
def weekly_fund_request_self_funded_action(request, request_id):
    if request.method == "POST":
        try:
            self_funded(request_id, request.user)
            messages.success(request, "Weekly fund request successfully marked as self-funded.")
        except Exception as e:
            messages.error(request, f"Error: {e}")
            
    active_wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
    return redirect(f"/fund-requests/weekly?week={active_wfr.week_start_date.isoformat()}")

@require_page_permission("fund_requests")
def generate_request_action(request):
    if request.method == "POST":
        week_start_str = request.POST.get("week_start", "").strip()
        user_id = request.POST.get("staff_id", request.user.user_id).strip()
        if not week_start_str:
            messages.error(request, "Week start date is required.")
        else:
            try:
                wfr = generate_weekly_fund_request(user_id, week_start_str)
                if wfr:
                    messages.success(request, f"Successfully generated weekly fund request for {week_start_str}.")
                else:
                    messages.warning(request, "No activities scheduled for this week to generate requests.")
            except Exception as e:
                messages.error(request, f"Error generating request: {e}")
                
    return redirect(f"/fund-requests/weekly?week={week_start_str}")

@require_page_permission("weekly_fund_request_disburse")
def weekly_fund_request_disburse_action(request, request_id):
    if request.user.active_role != "Accountant":
        messages.error(request, "Only the Program Accountant can disburse fund requests.")
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
