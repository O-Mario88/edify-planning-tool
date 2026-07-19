from django.shortcuts import render, redirect
from apps.core.permissions import require_page_permission
from django.contrib import messages
from django.db.models import Q, Sum, Count
from datetime import datetime, date, timedelta
import calendar

from apps.budget.services import budget_workspace
from apps.fund_requests.weekly_service import (
    get_weekly_request,
    request_advance,
    self_funded,
    generate_weekly_fund_request,
    disburse as disburse_weekly,
    approve_weekly_request,
    return_weekly_request,
)
from apps.fund_requests.models import WeeklyFundRequest, AdvanceRequest, FundRequest
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.geography.models import District
from apps.accounts.models import StaffProfile
from apps.core.fy import get_quarter_date_range, get_fy_date_range
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
    context = budget_workspace(
        request.user,
        {
            "fy": request.GET.get("fy"),
            "date": request.GET.get("date"),
            "period": request.GET.get("period"),
            "budget_scope": request.GET.get("budget_scope"),
        },
    )
    return render(request, "pages/budgets/monthly.html", context)


def _scoped_base_querysets(request, fy):
    """Shared role-scoped base querysets for the fund-requests page and its
    actions. Country roles (CD/IA/Accountant/Admin) see everything; a PL sees
    self + supervised team; a plain CCEO sees only their own — the same
    scoping shape used everywhere else in this app."""
    user = request.user
    scope = resolve_user_scope(user)
    district_id = request.GET.get("district", "").strip()
    staff_id = request.GET.get("staff", "").strip()
    status_filter = request.GET.get("status", "").strip()

    wfr_qs = WeeklyFundRequest.objects.all().order_by("-week_start_date")
    activities_qs = Activity.objects.filter(deleted_at__isnull=True)
    budget_qs = ActivityScheduleCostLine.objects.filter(fiscal_year=fy)

    supervised_user_ids = []
    if not scope.country_scope and scope.staff_ids:
        q_scope = Q(responsible_user=user.user_id)
        if scope.supervised_staff_ids:
            supervised_user_ids = list(
                StaffProfile.objects.filter(
                    id__in=scope.supervised_staff_ids
                ).values_list("user_id", flat=True)
            )
            q_scope |= Q(responsible_user__in=supervised_user_ids)
        wfr_qs = wfr_qs.filter(q_scope)
        budget_qs = budget_qs.filter(q_scope)

        q_act_scope = Q(responsible_staff_id=user.user_id)
        if supervised_user_ids:
            q_act_scope |= Q(responsible_staff_id__in=supervised_user_ids)
        activities_qs = activities_qs.filter(q_act_scope)

    # Apply dropdown filters. NOTE: StaffProfile has no `district_id` field —
    # only `primary_district_id` — so this must NOT be `district_id=`.
    if district_id:
        staff_in_district = StaffProfile.objects.filter(
            primary_district_id=district_id
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

    return {
        "scope": scope,
        "wfr_qs": wfr_qs,
        "activities_qs": activities_qs,
        "budget_qs": budget_qs,
        "district_id": district_id,
        "staff_id": staff_id,
        "status_filter": status_filter,
        "supervised_user_ids": supervised_user_ids,
        # Only roles with team/country reach need the District/Staff filters —
        # a plain CCEO only ever has one person's data (their own).
        "show_team_filters": scope.country_scope or bool(scope.supervised_staff_ids),
    }


def _export_weekly_fund_requests_csv(wfr_qs):
    import csv
    from django.http import HttpResponse
    from apps.accounts.models import User

    rows = list(wfr_qs[:5000])
    requester_names = dict(
        User.objects.filter(id__in=[r.responsible_user for r in rows]).values_list(
            "id", "name"
        )
    )
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="weekly_fund_requests.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "Request ID",
            "Week Start",
            "Requested By",
            "Total Amount (UGX)",
            "Disbursed (UGX)",
            "Status",
            "FY",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.id,
                r.week_start_date,
                requester_names.get(r.responsible_user, r.responsible_user),
                r.total_amount or 0,
                r.disbursed_amount or 0,
                r.status,
                r.fy,
            ]
        )
    return response


def _build_fund_requests_context(request):
    """The full Fund Requests page context (weekly card, monthly preview,
    KPIs, insights, breakdown). Shared by the GET page render and by the
    confirm/self-funded actions, so those actions can re-render the exact
    same live state after mutating instead of round-tripping a redirect."""
    user = request.user

    # 1. Filters & Defaults
    fy = request.GET.get("fy", "2026").strip()
    quarter = request.GET.get("quarter", "").strip()
    month_name = request.GET.get("month", "").strip()
    active_tab = request.GET.get("tab", "weekly").strip()
    request_type = request.GET.get("request_type", "").strip()

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
    # 2. Scope & Filter Base Queries
    base = _scoped_base_querysets(request, fy)
    scope = base["scope"]
    wfr_qs = base["wfr_qs"]
    activities_qs = base["activities_qs"]
    budget_qs = base["budget_qs"]
    district_id = base["district_id"]
    staff_id = base["staff_id"]
    status_filter = base["status_filter"]
    supervised_user_ids = base["supervised_user_ids"]

    # Open on the newest scheduled work the user can see.  The old hard-coded
    # April default made a newly scheduled July activity look as though no
    # weekly request or budget existed until the user manually changed filters.
    if month_name:
        month_num = MONTH_MAP.get(month_name.lower(), date.today().month)
    else:
        latest_for_month = (
            activities_qs.filter(fy=fy, scheduled_date__isnull=False)
            .order_by("-scheduled_date")
            .only("scheduled_date")
            .first()
        )
        month_num = (
            latest_for_month.scheduled_date.date().month
            if latest_for_month and latest_for_month.scheduled_date
            else date.today().month
        )
        month_name = calendar.month_name[month_num]
    if not quarter:
        quarter = f"Q{((month_num - 1) // 3) + 1}"
    # This org's FY runs Oct→Sep: Oct-Dec belong to fy-1, Jan-Sep belong to fy
    # (mirrors apps.fund_requests.pl_approval_service._month_end).
    year_num = int(fy) - 1 if month_num >= 10 else int(fy)
    weeks_in_month = get_weeks_of_month(year_num, month_num)

    # Default week selection: week containing the latest scheduled activity
    # IN SCOPE (own + supervised team), or the first week of the month.
    week_param = request.GET.get("week", "").strip()
    selected_week_start = None
    if week_param:
        try:
            selected_week_start = parse_date(week_param)
        except ValueError:
            pass

    if not selected_week_start:
        latest_act = (
            activities_qs.filter(scheduled_date__isnull=False)
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

    # 3. Calculate KPIs — month-scoped WeeklyFundRequest aggregates use the
    # model's own `fy` field, not just the calendar month number, so e.g.
    # "November" isn't blended across every fiscal year that has a November.
    # 3. Calculate KPIs — month-scoped aggregates
    # Total Requested This Month
    requested_this_month = (
        wfr_qs.filter(fy=fy, week_start_date__month=month_num).aggregate(
            total=Sum("total_amount")
        )["total"]
        or 0
    )

    # Delta vs Last Month
    last_month_num = 12 if month_num == 1 else month_num - 1
    requested_last_month = (
        wfr_qs.filter(fy=fy, week_start_date__month=last_month_num).aggregate(
            total=Sum("total_amount")
        )["total"]
        or 0
    )
    if requested_last_month > 0:
        delta_val = int(
            ((requested_this_month - requested_last_month) / requested_last_month) * 100
        )
        direction = "up" if delta_val >= 0 else "down"
        trend = {"direction": direction, "value": f"{abs(delta_val)}%"}
    else:
        trend = {"direction": "up", "value": "12%"}

    # Awaiting Approval
    awaiting_qs = wfr_qs.filter(status__in=["submitted_to_pl", "submitted_to_cd"])
    awaiting_amount = awaiting_qs.aggregate(total=Sum("total_amount"))["total"] or 0
    awaiting_count = awaiting_qs.count()

    # Approved
    approved_qs = wfr_qs.filter(status__in=["confirmed_for_advance", "disbursed"])
    approved_amount = approved_qs.aggregate(total=Sum("total_amount"))["total"] or 0
    approved_count = approved_qs.count()

    # Ready for Disbursement
    ready_qs = wfr_qs.filter(status="confirmed_for_advance")
    ready_amount = ready_qs.aggregate(total=Sum("total_amount"))["total"] or 0
    ready_count = ready_qs.count()

    # Returned for Review
    returned_qs = wfr_qs.filter(
        status__in=["returned_by_pl", "returned_by_cd", "returned_by_accountant"]
    )
    returned_amount = returned_qs.aggregate(total=Sum("total_amount"))["total"] or 0
    returned_count = returned_qs.count()

    # Accountability Pending
    pending_acct_qs = wfr_qs.filter(status="disbursed", accounted_amount__isnull=True)
    pending_acct_amount = (
        pending_acct_qs.aggregate(total=Sum("total_amount"))["total"] or 0
    )
    pending_acct_count = pending_acct_qs.count()

    planned_value = (
        budget_qs.filter(planned_date__month=month_num).aggregate(total=Sum("amount"))[
            "total"
        ]
        or 0
    )

    kpis = {
        "requested_this_month": requested_this_month,
        "awaiting_amount": awaiting_amount,
        "awaiting_count": awaiting_count,
        "approved_amount": approved_amount,
        "approved_count": approved_count,
        "ready_amount": ready_amount,
        "ready_count": ready_count,
        "returned_amount": returned_amount,
        "returned_count": returned_count,
        "pending_acct_amount": pending_acct_amount,
        "pending_acct_count": pending_acct_count,
        "planned_value": planned_value,
    }

    # Format UGX compact helper
    def format_ugx_compact(val):
        if not val:
            return "UGX 0"
        if val >= 1_000_000_000:
            return f"UGX {val / 1_000_000_000:.2f}B"
        if val >= 1_000_000:
            return f"UGX {val / 1_000_000:.2f}M"
        if val >= 1_000:
            return f"UGX {val / 1_000:.2f}K"
        return f"UGX {val}"

    # Construct unified KPI strip items
    kpi_strip_items = [
        {
            "label": "Total Requested This Month",
            "value": format_ugx_compact(requested_this_month),
            "trend": trend,
            "helper": "vs Last Month",
            "icon": "currency",
            "variant": "info",
        },
        {
            "label": "Awaiting Approval",
            "value": format_ugx_compact(awaiting_amount),
            "helper": f"{awaiting_count} request{'s' if awaiting_count != 1 else ''}",
            "icon": "clock",
            "variant": "warning",
        },
        {
            "label": "Approved",
            "value": format_ugx_compact(approved_amount),
            "helper": f"{approved_count} request{'s' if approved_count != 1 else ''}",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Ready for Disbursement",
            "value": format_ugx_compact(ready_amount),
            "helper": f"{ready_count} request{'s' if ready_count != 1 else ''}",
            "icon": "briefcase",
            "variant": "info",
        },
        {
            "label": "Returned for Review",
            "value": format_ugx_compact(returned_amount),
            "helper": f"{returned_count} request{'s' if returned_count != 1 else ''}",
            "icon": "warning",
            "variant": "danger",
        },
        {
            "label": "Accountability Pending",
            "value": format_ugx_compact(pending_acct_amount),
            "helper": f"{pending_acct_count} request{'s' if pending_acct_count != 1 else ''}",
            "icon": "report",
            "variant": "warning",
        },
    ]

    # 4. Weekly Fund Request details
    active_wfr = wfr_qs.filter(week_start_date=selected_week_start).first()
    weekly_lines = []
    weekly_total = 0
    wfr_status = "No Request"
    viewer_can_approve_wfr = False
    if active_wfr:
        # The viewer may act as approver when the request awaits their stage:
        # a PL on a supervised CCEO's submitted_to_pl request, a CD/Admin on
        # submitted_to_cd (or standing in on submitted_to_pl). Never on their
        # own request. The service re-validates all of this server-side.
        if (
            active_wfr.status in ("submitted_to_pl", "submitted_to_cd")
            and active_wfr.responsible_user != user.user_id
        ):
            role = user.active_role
            if role in ("CountryDirector", "Admin"):
                viewer_can_approve_wfr = True
            elif role == "Program Lead" and active_wfr.status == "submitted_to_pl":
                viewer_can_approve_wfr = active_wfr.responsible_user in (
                    supervised_user_ids or []
                )
    if active_wfr:
        owner_profile = (
            StaffProfile.objects.filter(user_id=active_wfr.responsible_user)
            .select_related("user")
            .first()
        )
        active_wfr.owner_name = (
            owner_profile.user.name
            if (owner_profile and owner_profile.user)
            else active_wfr.responsible_user
        )
        wfr_status = active_wfr.status
        weekly_total = active_wfr.total_amount
        for line in active_wfr.lines.select_related("activity_budget_line__activity"):
            adv = (
                line.activity_budget_line.advance_requests.first()
                if line.activity_budget_line
                else None
            )
            status_raw = adv.status if adv else "draft_from_schedule"

            status_labels = {
                "draft_from_schedule": "Draft",
                "pending_responsible_confirmation": "Awaiting Confirmation",
                "confirmed_for_advance": "Ready",
                "self_funded_pending_reimbursement": "Self-funded",
                "disbursed": "Disbursed",
            }
            status_label = status_labels.get(status_raw, "Auto-calculated")

            act = (
                line.activity_budget_line.activity
                if (
                    line.activity_budget_line
                    and getattr(line.activity_budget_line, "activity", None)
                )
                else None
            )
            act_type = act.activity_type if act else None

            source_map = {
                "school_visit": "School Visits",
                "follow_up_visit": "School Visits",
                "coaching_visit": "School Visits",
                "in_school_support": "School Visits",
                "core_visit": "Core Visits",
                "training": "Cluster Training",
                "school_improvement_training": "Cluster Training",
                "cluster_training": "Cluster Training",
                "core_training": "Core Trainings",
                "cluster_meeting": "Cluster Meetings",
                "ssa_activity": "SSA Support",
                "baseline_ssa_visit": "SSA Support",
                "school_visit_ssa_collection": "SSA Support",
                "cluster_training_ssa_collection": "SSA Support",
                "cluster_meeting_ssa_review": "SSA Support",
                "partner_activity": "Partner Activities",
                "project_activity": "Partner Activities",
            }
            source = source_map.get(act_type)
            if not source:
                if act_type == "admin_budget" or (
                    line.description and "admin" in line.description.lower()
                ):
                    source = "Admin Budget"
                else:
                    source = "Other"

            if (
                request_type
                and request_type.lower() != "all"
                and source.lower() != request_type.lower()
            ):
                continue

            weekly_lines.append(
                {
                    "id": line.id,
                    "source": source,
                    "cost_item": line.description,
                    "quantity": line.quantity,
                    "unit_cost": line.unit_cost,
                    "total_cost": line.total_cost,
                    "activity_id": line.activity_budget_line.activity_id
                    if line.activity_budget_line
                    else None,
                    "status": status_label,
                    "status_raw": status_raw,
                }
            )
        if request_type and request_type.lower() != "all":
            weekly_total = sum(line["total_cost"] for line in weekly_lines)

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

    # Monthly Request Status — driven by the REAL monthly FundRequest (the
    # same model/state apps.fund_requests.pl_approval_service and
    # disbursement_dashboard_service use for PL approval + disbursement),
    # not the legacy MonthlyFundRequest row that nothing in this codebase
    # ever writes to (it would otherwise show "Draft" forever — a fake
    # status). CD/RVP are never invoked for this plan (see
    # disbursement_dashboard_service._monthly_chain), so they're always
    # "Not Required" rather than a pending step that will never resolve.
    monthly_fr = FundRequest.objects.filter(
        period="monthly",
        fy=fy,
        period_key=f"{fy}-M{month_num}",
        submitted_by_user_id=user.user_id,
    ).first()

    if monthly_fr and monthly_fr.status == "returned_by_pl":
        monthly_state = "returned_at_pl"
    elif monthly_fr and monthly_fr.status == "returned_by_accountant":
        monthly_state = "returned_at_accountant"
    elif monthly_fr and monthly_fr.status == "disbursed":
        monthly_state = "disbursed"
    elif monthly_fr and monthly_fr.status == "held":
        monthly_state = "held"
    elif monthly_fr and monthly_fr.status == "sent_to_accountant":
        monthly_state = "at_accountant"
    elif month_lines.exists():
        # No FundRequest persisted yet, but the PL's queue already derives
        # this plan live from cost lines — so it's already awaiting PL
        # action, not a manual "draft" the CCEO must submit.
        monthly_state = "awaiting_pl"
    else:
        monthly_state = "draft"

    _step_map = {
        "draft": ("current", "pending", "pending"),
        "awaiting_pl": ("done", "current", "pending"),
        "returned_at_pl": ("done", "returned", "pending"),
        "at_accountant": ("done", "done", "current"),
        "held": ("done", "done", "held"),
        "returned_at_accountant": ("done", "done", "returned"),
        "disbursed": ("done", "done", "done"),
    }
    draft_state, pl_state, accountant_state = _step_map[monthly_state]
    monthly_stepper = {
        "state": monthly_state,
        "steps": [
            {"key": "draft", "label": "Draft", "state": draft_state},
            {"key": "pl", "label": "PL Review", "state": pl_state},
            {"key": "cd", "label": "CD Approval", "state": "not_required"},
            {"key": "rvp", "label": "RVP Approval", "state": "not_required"},
            {
                "key": "accountant",
                "label": "Accountant Queue",
                "state": accountant_state,
            },
        ],
    }

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

    self_funded_qs = AdvanceRequest.objects.filter(
        status="self_funded_pending_reimbursement"
    )
    if not scope.country_scope and scope.staff_ids:
        self_funded_scope_q = Q(responsible_user_id=user.user_id)
        if supervised_user_ids:
            self_funded_scope_q |= Q(responsible_user_id__in=supervised_user_ids)
        self_funded_qs = self_funded_qs.filter(self_funded_scope_q)
    self_funded_count = self_funded_qs.count()

    due_date = date(year_num, month_num, 25)
    days_remaining = (due_date - date.today()).days

    missing_cost_count = activities_qs.filter(
        scheduled_date__month=month_num, cost_missing=True
    ).count()

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
        has_scheduled_this_week = (
            budget_qs.filter(
                planned_date__gte=selected_week_start,
                planned_date__lte=selected_week_end,
            )
            .exclude(activity__status="cancelled")
            .exists()
        )
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
        "self_funded_count": self_funded_count,
        "due_date_str": due_date.strftime("%b %d, %Y"),
        "days_remaining": max(0, days_remaining),
        "missing_cost_count": missing_cost_count,
        "last_checked_label": date.today().strftime("%b %d, %Y"),
        "recommended_action": recommended_action,
        "recommended_desc": recommended_desc,
        "can_take_action": can_take_action,
        "action_type": action_type,
    }

    # 8. Period Breakdown
    def get_wfr_stats(start_d, end_d):
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
        res = qs.aggregate(total=Sum("total_amount"), count=Count("id"))
        return {
            "total": res["total"] or 0,
            "count": res["count"] or 0,
        }

    month_wfr_qs = wfr_qs.filter(fy=fy, week_start_date__month=month_num)
    month_stats = month_wfr_qs.aggregate(total=Sum("total_amount"), count=Count("id"))

    breakdown = {
        "week": get_wfr_stats(selected_week_start, selected_week_start),
        "month": {
            "total": month_stats["total"] or 0,
            "count": month_stats["count"] or 0,
        },
        "quarter": get_wfr_stats(*get_quarter_date_range(fy, quarter)),
        "fy": get_wfr_stats(*get_fy_date_range(fy)),
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

    # Disbursed monthly fund plans awaiting THIS user's receipt confirmation —
    # surfaces the "Funds disbursed → Confirm Receipt" step (auto-clears the
    # matching To-Do once confirmed).
    receipt_pending_plans = list(
        FundRequest.objects.filter(
            submitted_by_user_id=user.user_id,
            period="monthly",
            status="disbursed",
            receipt_confirmed_at__isnull=True,
        ).order_by("-disbursed_at")[:3]
    )

    return {
        "kpis": kpis,
        "kpi_strip_items": kpi_strip_items,
        "active_wfr": active_wfr,
        "viewer_can_approve_wfr": viewer_can_approve_wfr,
        "wfr_status": wfr_status,
        "weekly_lines": weekly_lines,
        "weekly_total": weekly_total,
        "source_activities": source_activities,
        "monthly_weeks": monthly_weeks,
        "monthly_totals_by_type": monthly_totals_by_type,
        "monthly_stepper": monthly_stepper,
        "insights": insights,
        "breakdown": breakdown,
        "districts": districts,
        "staff_profiles": staff_profiles,
        "dropdown_weeks": dropdown_weeks,
        "show_team_filters": base["show_team_filters"],
        "receipt_pending_plans": receipt_pending_plans,
        # Selected states
        "selected_fy": fy,
        "selected_quarter": quarter,
        "selected_month": month_name,
        "selected_week": selected_week_start.isoformat(),
        "selected_week_label": f"{selected_week_start.strftime('%b %d')} – {selected_week_end.strftime('%b %d')}, {selected_week_start.year}",
        "selected_district": district_id,
        "selected_staff": staff_id,
        "selected_status": status_filter,
        "selected_request_type": request_type,
        "active_tab": active_tab,
    }


@require_page_permission("fund_requests")
def weekly_fund_requests_view(request):
    fy = request.GET.get("fy", "2026").strip()

    # CSV export of the currently filtered requests (same pattern as /clusters).
    if request.GET.get("export", "").strip() == "csv":
        base = _scoped_base_querysets(request, fy)
        return _export_weekly_fund_requests_csv(base["wfr_qs"])

    context = _build_fund_requests_context(request)
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/fund_requests/root.html", context)
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
    """Confirm the weekly request for advance disbursement. Re-renders the
    same live context in place (rather than redirecting) so the KPI/insights/
    monthly-preview panels stay in sync in the same swap."""
    action_error = action_ok = None
    if request.method == "POST":
        try:
            request_advance(request_id, request.user)
            action_ok = "Weekly fund request confirmed for advance."
        except Exception as e:
            action_error = str(e)

    context = _build_fund_requests_context(request)
    context["action_error"] = action_error
    context["action_ok"] = action_ok
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/fund_requests/root.html", context)
    return render(request, "pages/fund_requests/weekly.html", context)


@require_page_permission("fund_requests")
def weekly_fund_request_self_funded_action(request, request_id):
    """Elect self-funded reimbursement. Re-renders in place — see confirm
    action above for why (keeps KPIs/insights/monthly preview accurate)."""
    action_error = action_ok = None
    if request.method == "POST":
        try:
            self_funded(request_id, request.user)
            action_ok = "Weekly fund request marked as self-funded."
        except Exception as e:
            action_error = str(e)

    context = _build_fund_requests_context(request)
    context["action_error"] = action_error
    context["action_ok"] = action_ok
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/fund_requests/root.html", context)
    return render(request, "pages/fund_requests/weekly.html", context)


@require_page_permission("fund_requests")
def weekly_fund_request_approve_action(request, request_id):
    """PL approves a supervised CCEO's request; CD approves a PL/PC/IA
    request. Role + supervision enforced in the service layer."""
    action_error = action_ok = None
    if request.method == "POST":
        try:
            approve_weekly_request(request_id, request.user)
            action_ok = "Weekly fund request approved and sent to the Accountant."
        except Exception as e:
            action_error = str(e)

    context = _build_fund_requests_context(request)
    context["action_error"] = action_error
    context["action_ok"] = action_ok
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/fund_requests/root.html", context)
    return render(request, "pages/fund_requests/weekly.html", context)


@require_page_permission("fund_requests")
def weekly_fund_request_return_action(request, request_id):
    """Approver returns the request for correction (reason required)."""
    action_error = action_ok = None
    if request.method == "POST":
        try:
            return_weekly_request(
                request_id, {"reason": request.POST.get("reason", "")}, request.user
            )
            action_ok = "Weekly fund request returned to the owner for correction."
        except Exception as e:
            action_error = str(e)

    context = _build_fund_requests_context(request)
    context["action_error"] = action_error
    context["action_ok"] = action_ok
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/fund_requests/root.html", context)
    return render(request, "pages/fund_requests/weekly.html", context)


@require_page_permission("fund_requests")
def generate_request_action(request):
    if request.method != "POST":
        return redirect("/fund-requests/weekly")

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
