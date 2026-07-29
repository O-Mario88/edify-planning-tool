from django.utils import timezone
from django.shortcuts import render, redirect
from apps.core.exceptions import BadRequest
from apps.core.metrics import format_ugx_compact
from apps.core.redirects import local_redirect
from apps.core.permissions import require_page_permission
from django.contrib import messages
from django.db.models import Q, Sum, Count
from datetime import datetime, date, timedelta
import calendar

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
from apps.core.fy import (
    get_fy_date_range,
    get_quarter_date_range,
    get_quarter_for_date,
)
from apps.core.scoping import resolve_user_scope


def parse_date(d_str: str) -> date:
    if isinstance(d_str, (date, datetime)):
        return d_str.date() if isinstance(d_str, datetime) else d_str
    try:
        return datetime.strptime(d_str[:10], "%Y-%m-%d").date()
    except Exception as exc:
        raise BadRequest(f"Invalid date format: {d_str}") from exc


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
    """Redirect retired monthly-budget bookmarks to the canonical workflow."""
    if request.user.active_role in (
        "CountryDirector",
        "ImpactAssessment",
        "Accountant",
        "Admin",
    ):
        return redirect("/country-budget/")
    if request.user.active_role == "Program Lead":
        return redirect("/accounts/monthly-request/")
    return redirect("/fund-requests/weekly")


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
    # `and scope.staff_ids` made this fail OPEN: a principal without a
    # StaffProfile has an empty staff_ids, skipped the narrowing entirely and
    # fell through to the unfiltered .all() — every weekly fund request in the
    # country, export included. Narrow unconditionally for non-country roles,
    # to an impossible id when the set is empty (the idiom in
    # apps/clusters/services.py, which documents this same bug class).
    if not scope.country_scope:
        q_scope = Q(responsible_user=user.user_id or "__none__")
        if scope.supervised_staff_ids:
            supervised_user_ids = list(
                StaffProfile.objects.filter(
                    id__in=scope.supervised_staff_ids
                ).values_list("user_id", flat=True)
            )
            q_scope |= Q(responsible_user__in=supervised_user_ids)
        wfr_qs = wfr_qs.filter(q_scope)
        budget_qs = budget_qs.filter(q_scope)

        # `Activity.responsible_staff_id` holds a StaffProfile CUID or a User
        # CUID depending on which the scheduler had -- activities.services
        # .create() prefers the StaffProfile and falls back to the User. This
        # matched only the User id, so a CCEO whose work was stamped with their
        # StaffProfile saw almost none of it: 13 activities out of 213 for the
        # account this was found on.
        #
        # The page then opened on "the newest scheduled activity it could see",
        # which was April, and the monthly, quarterly and annual budgets came
        # back empty because the cost lines behind them were invisible too. The
        # month label was never wrong; the scope beneath it was.
        #
        # Both identity spaces, the same way my_plan.services.get covers them.
        own_identities = {user.user_id}
        own_identities.update(scope.staff_ids or [])
        own_identities.discard(None)

        q_act_scope = Q(responsible_staff_id__in=own_identities or {"__none__"})
        if supervised_user_ids:
            q_act_scope |= Q(responsible_staff_id__in=supervised_user_ids)
        if scope.supervised_staff_ids:
            q_act_scope |= Q(responsible_staff_id__in=scope.supervised_staff_ids)
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


def _monthly_summary_band(totals: dict) -> list[dict]:
    """Registry-built items for the monthly summary band."""
    from apps.core.metrics import MetricValue, render_metric, render_strip

    pairs = (
        ("fund_request_monthly_visits_budget", totals["visits"]),
        ("fund_request_monthly_trainings_budget", totals["trainings"]),
        ("fund_request_monthly_meetings_budget", totals["meetings"]),
        ("fund_request_monthly_admin_budget", totals["admin"]),
        ("fund_request_monthly_total", totals["total"]),
    )
    return render_strip(
        [render_metric(key, MetricValue.measured(value)) for key, value in pairs]
    )


def _weekly_status_label(weekly_request) -> str:
    """The canonical stage label for one weekly request, or "" if there is none."""
    if not weekly_request:
        return ""
    from apps.fund_requests.disbursement_dashboard_service import (
        weekly_status_buckets,
    )

    return weekly_status_buckets([weekly_request]).get(weekly_request.id, "")


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
    # Which budget horizon the period card is showing. The week is the default
    # because it is the one that moves money.
    _role = getattr(request.user, "active_role", "")
    # A Country Director's own plan is the monthly admin plan -- admin lines
    # are planned by month and never estimated into a week -- so their card
    # opens on the month. Field staff open on the week, which moves the money.
    _default_tab = "month" if _role in ("CountryDirector", "Admin") else "week"
    period_tab = request.GET.get("period_tab", _default_tab).strip().lower()
    if period_tab not in ("week", "month", "quarter", "fy"):
        period_tab = _default_tab

    # Which slice of the budget the card reads. PLs read their team (the plan
    # they approve). CDs read their admin plan by default -- "CD majorly has
    # admin and monitoring plans" (the owner) -- with a one-click switch to
    # the country field view for the monitoring half. budget_workspace itself
    # validates who may hold which scope, so an unauthorised value in the URL
    # falls back to "my" there rather than being trusted here.
    if _role == "Program Lead":
        _default_scope = "team"
    elif _role in ("CountryDirector", "Admin"):
        _default_scope = "admin"
    else:
        _default_scope = ""
    card_budget_scope = request.GET.get("budget_scope", _default_scope).strip().lower()
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
            # Same local-date rule as the week selection below.
            timezone.localtime(latest_for_month.scheduled_date).date().month
            if latest_for_month and latest_for_month.scheduled_date
            else date.today().month
        )
        month_name = calendar.month_name[month_num]
    # This org's FY runs Oct→Sep: Oct-Dec belong to fy-1, Jan-Sep belong to fy
    # (mirrors apps.fund_requests.pl_approval_service._month_end).
    year_num = int(fy) - 1 if month_num >= 10 else int(fy)
    if not quarter:
        # Calendar quarters are not fiscal quarters. `((month-1)//3)+1` is off
        # by one for all twelve months here — it labelled October "Q4", and the
        # label was then fed to get_quarter_date_range(), so the page silently
        # reported a Jul–Oct window while claiming to show Oct–Dec.
        quarter = get_quarter_for_date(date(year_num, month_num, 1))
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
            # Local date, never the raw UTC one. An activity at local midnight
            # is stored as 21:00 UTC the previous day, and `.date()` on that
            # picks the previous day -- for a Monday activity that is a Sunday,
            # whose Monday-of is a week early, so the page opened on the wrong
            # week with the wrong (empty) budget. The fourth appearance of
            # this timezone class in this codebase; see also the cost-line
            # drift health check and the reminder dedupe.
            latest_d = timezone.localtime(latest_act.scheduled_date).date()
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

    # Money formatting comes from apps.core.metrics.money. This function used
    # to be defined here with two decimals at every scale, so the same UGX
    # 1,234,567 read as "UGX 1.23M" on this page and "UGX 1.2M" on the finance
    # and PL approval pages.
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

    # Monthly summary, from the canonical budget builder.
    #
    # This block used to run four hand-written type-bucket aggregations over
    # budget_qs. Two defects, both live: an activity type outside the four
    # hard-coded lists fell out of every bucket AND out of the total, so a
    # month of core visits summed to zero; and the buckets scoped differently
    # from the My Budget card beside them, so a Program Lead's band said
    # 548,000 while the month tab said 0. One source now -- budget_workspace,
    # split by the same table_kind the budget tables group by. A Program Lead's
    # band reads their team (the plan they approve); everyone else reads their
    # own scope.
    # Still read directly for one thing only: "does this month have any cost
    # lines at all", which drives the monthly request's derived status below.
    month_lines = budget_qs.filter(planned_date__month=month_num)

    from apps.budget.services import budget_workspace as _band_builder

    _band_workspace = _band_builder(
        user,
        {
            "period": "month",
            "fy": fy,
            "date": date(year_num, month_num, 1).isoformat(),
            **({"budget_scope": card_budget_scope} if card_budget_scope else {}),
        },
    )
    _band_kind_totals = {"training": 0, "meeting": 0, "admin": 0, "standard": 0}
    for _group in _band_workspace["groups"]:
        _kind = _group.get("table_kind")
        _band_kind_totals[_kind if _kind in _band_kind_totals else "standard"] += (
            _group.get("total") or 0
        )
    monthly_totals_by_type = {
        "visits": _band_kind_totals["standard"],
        "trainings": _band_kind_totals["training"],
        "meetings": _band_kind_totals["meeting"],
        "admin": _band_kind_totals["admin"],
        "total": _band_workspace["total"],
    }

    from urllib.parse import urlencode

    _period_tab_query = urlencode(
        {
            key: value
            for key, value in request.GET.items()
            if value and key != "period_tab"
        }
    )
    if _period_tab_query:
        _period_tab_query += "&"

    # The budget at the chosen horizon, from the canonical builder.
    #
    # An earlier version of this card computed week/month/quarter/FY sums here,
    # by hand, from budget_qs. Those numbers could disagree with the My Budget
    # page over quarter boundaries and scope, and a card that argues with the
    # page it links to is worse than no card. budget_workspace is the one
    # source: same scoping (resolve_user_scope), same period arithmetic, and
    # the same `groups` the reference budget table renders -- so the card can
    # show the full breakdown, not just a headline.
    from apps.budget.services import budget_workspace

    if period_tab == "week":
        _budget_anchor = selected_week_start
    else:
        # The month the page has open, so the Month/Quarter tabs follow the
        # month filter rather than silently resetting to today.
        _budget_anchor = date(year_num, month_num, 1)

    period_workspace = budget_workspace(
        user,
        {
            "period": period_tab,
            "fy": fy,
            "date": _budget_anchor.isoformat(),
            **({"budget_scope": card_budget_scope} if card_budget_scope else {}),
        },
    )

    from urllib.parse import urlencode

    _period_tab_query = urlencode(
        {
            key: value
            for key, value in request.GET.items()
            if value and key != "period_tab"
        }
    )
    if _period_tab_query:
        _period_tab_query += "&"

    period_budgets = {
        "active": period_tab,
        "selected": period_workspace["selected"],
        "total": period_workspace["total"],
        "staff_total": period_workspace["staff_total"],
        "groups": period_workspace["groups"],
        "workspace_title": period_workspace["workspace_title"],
        "budget_scope": period_workspace["budget_scope"],
        "empty_title": period_workspace["empty_title"],
        "empty_help": period_workspace["empty_help"],
        "tabs": [
            {"key": "week", "label": "Week", "submits": True},
            {"key": "month", "label": "Month", "submits": False},
            {"key": "quarter", "label": "Quarter", "submits": False},
            {"key": "fy", "label": "FY", "submits": False},
        ],
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
    # `and scope.staff_ids` made this fail OPEN: a principal without a
    # StaffProfile has an empty staff_ids, skipped the narrowing entirely and
    # fell through to the unfiltered .all() — every weekly fund request in the
    # country, export included. Narrow unconditionally for non-country roles,
    # to an impossible id when the set is empty (the idiom in
    # apps/clusters/services.py, which documents this same bug class).
    if not scope.country_scope:
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
        # Narrow unconditionally for non-country roles — see the note on
        # `_scoped_base_querysets`; gating on a truthy staff_ids failed open.
        if not scope.country_scope:
            q_scope = Q(responsible_user=user.user_id or "__none__")
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
        # The five-tile monthly band, built through the metric registry so
        # each tile carries its registered key, definition and finance stage
        # (PLANNED). The hand-written label/value dicts this replaces were
        # invisible to the duplication and denominator guards -- the KPI
        # inventory's ratchet caught them the same day they were written.
        "monthly_summary_band": _monthly_summary_band(monthly_totals_by_type),
        "period_budgets": period_budgets,
        # The week's request, for the submit control on the week tab. Only an
        # owner-confirmable request may be submitted; anything already in the
        # approval chain says so instead of offering the button again.
        "active_wfr_id": getattr(active_wfr, "id", None),
        "active_wfr_can_submit": getattr(active_wfr, "status", None)
        == "pending_responsible_confirmation",
        # WeeklyFundRequest.status carries no `choices`, so there is no
        # get_status_display. `weekly_status_buckets` is the canonical label
        # for a weekly request's stage -- the same one the Disbursement
        # Dashboard and the Accountant home read -- so this page cannot
        # describe a request differently from the pages that act on it.
        "active_wfr_status_label": _weekly_status_label(active_wfr),
        "period_tab_query": _period_tab_query,
        # The CD's two hats: their own admin plan, and monitoring the country's
        # field budget. Rendered as a switch on the card only when the role
        # actually holds both scopes.
        "card_scope_switch": (
            [
                {"key": "admin", "label": "Admin plan"},
                {"key": "country", "label": "Country (monitoring)"},
            ]
            if _role in ("CountryDirector", "Admin")
            else []
        ),
        "card_budget_scope": period_workspace["budget_scope"],
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
    context["topbar_search"] = {
        "placeholder": "Search schools, clusters, activities…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/fund-requests/weekly",
        "hx_target": "#fund-requests-page-root",
        "hx_trigger": "keyup changed delay:250ms, search",
        "hx_include": "#filters-form",
    }
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
    context["topbar_search"] = {
        "placeholder": "Search schools, clusters, activities…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/fund-requests/weekly",
        "hx_target": "#fund-requests-page-root",
        "hx_trigger": "keyup changed delay:250ms, search",
        "hx_include": "#filters-form",
    }
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
    context["topbar_search"] = {
        "placeholder": "Search schools, clusters, activities…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/fund-requests/weekly",
        "hx_target": "#fund-requests-page-root",
        "hx_trigger": "keyup changed delay:250ms, search",
        "hx_include": "#filters-form",
    }
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
    context["topbar_search"] = {
        "placeholder": "Search schools, clusters, activities…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/fund-requests/weekly",
        "hx_target": "#fund-requests-page-root",
        "hx_trigger": "keyup changed delay:250ms, search",
        "hx_include": "#filters-form",
    }
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
    context["topbar_search"] = {
        "placeholder": "Search schools, clusters, activities…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/fund-requests/weekly",
        "hx_target": "#fund-requests-page-root",
        "hx_trigger": "keyup changed delay:250ms, search",
        "hx_include": "#filters-form",
    }
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

    return local_redirect(f"/fund-requests/weekly?week={week_start_str}")


@require_page_permission("weekly_fund_request_disburse")
def weekly_fund_request_disburse_action(request, request_id):
    if request.user.active_role != "Accountant":
        messages.error(
            request, "Only the Program Accountant can disburse fund requests."
        )
        return local_redirect(f"/fund-requests/weekly/{request_id}")

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

    return local_redirect(f"/fund-requests/weekly/{request_id}")
