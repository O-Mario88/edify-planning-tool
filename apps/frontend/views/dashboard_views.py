from apps.core.activity_types import COMPLETED_WORK_STATUSES
import csv
from urllib.parse import urlencode

from django.shortcuts import render, redirect
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta

from apps.activities.models import Activity
from apps.fund_requests.models import WeeklyFundRequest
from apps.command_center import services as cc_services
from apps.command_center.planning_progress import (
    normalise_period as normalise_progress_period,
)
from apps.core.cards import render_card
from apps.core.navigation import get_user_role_slug
from apps.core.permissions import RolePermissionService, require_page_permission
from apps.core.enums import SsaIntervention
from apps.command_center.dashboard_service import DashboardMetricsService
from apps.core.activity_types import VISIT_TYPES
from apps.core.donut import build_rings
from apps.core.metrics import MetricValue, render_kpi_item


def _format_ugx_compact(val):
    """Compact UGX formatting helper (mirrors budget_views.format_ugx_compact)."""
    if not val:
        return "UGX 0"
    if val >= 1_000_000_000:
        return f"UGX {val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"UGX {val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"UGX {val / 1_000:.0f}K"
    return f"UGX {val}"


def _export_hr_dashboard_csv(data, *, fy, month, country, department):
    """Export the same live, role-scoped HR metrics shown on the dashboard."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="hr_dashboard_report.csv"'
    writer = csv.writer(response)
    writer.writerow(["Section", "Metric", "Value", "Context"])
    filters = ", ".join(
        value
        for value in (
            f"FY {fy}" if fy else "",
            f"month {month}" if month else "",
            country or "",
            department or "",
        )
        if value
    )
    for item in data.get("kpi_strip_items", []):
        writer.writerow(
            ["Workforce KPI", item.get("label", ""), item.get("value", ""), filters]
        )
    for item in data.get("pending_actions", []):
        writer.writerow(
            ["Pending action", item.get("label", ""), item.get("count", 0), filters]
        )
    return response


# Activity-type groupings shared by the agenda-building helpers below.
_VISIT_TYPES = {
    "school_visit",
    "follow_up_visit",
    "coaching_visit",
    "core_visit",
    "core_assessment_visit",
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "in_school_support",
    "donor_visit",
    "story_gathering_visit",
    "school_invitation",
    "social_visit",
    "training_follow_up_visit",
    "in_school_coaching_visit",
}
_TRAINING_TYPES = {
    "training",
    "in_school_training",
    "school_improvement_training",
    "cluster_training",
    "cluster_training_ssa_collection",
    "core_training",
}
_MEETING_TYPES = {"cluster_meeting", "cluster_meeting_ssa_review"}
_SSA_TYPES = {"ssa_activity", "partner_ssa_collection"}
_PARTNER_TYPES = {"partner_activity"}
_PROJECT_TYPES = {"project_activity"}


def _agenda_icon(activity_type):
    """Inline SVG line icon per activity family (1em, currentColor — scales
    with the surrounding text and adapts to theme)."""
    from django.utils.safestring import mark_safe

    def svg(path):
        # Every call site below passes an SVG path literal defined in this
        # function. No caller-supplied value, and no request data, ever
        # reaches this string — `activity_type` is only ever compared, never
        # interpolated. Suppressed unqualified because B308 is a blacklist
        # check and ignores a test-id list.
        return mark_safe(  # nosec B308 B703
            '<svg class="inline-block h-[1em] w-[1em] align-[-0.12em]" fill="none" '
            'viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.9" '
            f'aria-hidden="true">{path}</svg>'
        )

    if activity_type in _VISIT_TYPES:
        return svg(
            '<path stroke-linecap="round" stroke-linejoin="round" d="M12 14l9-5-9-5-9 5 9 5zm0 0v7m-5-4v4a5 5 0 0010 0v-4"/>'
        )
    if activity_type in _TRAINING_TYPES:
        return svg(
            '<path stroke-linecap="round" stroke-linejoin="round" d="M12 6.3C10.5 5.3 8.6 5 6.5 5c-1.1 0-2.2.1-3.2.4v13c1-.3 2.1-.4 3.2-.4 2.1 0 4 .3 5.5 1.3 1.5-1 3.4-1.3 5.5-1.3 1.1 0 2.2.1 3.2.4v-13c-1-.3-2.1-.4-3.2-.4-2.1 0-4 .3-5.5 1.3zm0 0V19"/>'
        )
    if activity_type in _MEETING_TYPES:
        return svg(
            '<path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6-2a3 3 0 10-2-5.24"/>'
        )
    if activity_type in _SSA_TYPES:
        return svg(
            '<path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>'
        )
    if activity_type in _PARTNER_TYPES:
        return svg(
            '<path stroke-linecap="round" stroke-linejoin="round" d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m6-1.13a4 4 0 10-4-4 4 4 0 004 4zm6-2a3 3 0 10-2-5.24"/>'
        )
    if activity_type in _PROJECT_TYPES:
        return svg(
            '<path stroke-linecap="round" stroke-linejoin="round" d="M12 21a9 9 0 100-18 9 9 0 000 18zm0-4a5 5 0 100-10 5 5 0 000 10zm0-3a2 2 0 100-4 2 2 0 000 4z"/>'
        )
    return svg(
        '<path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.6L18 7.4V19a2 2 0 01-2 2z"/>'
    )


def _agenda_type_class(activity_type):
    if activity_type in _TRAINING_TYPES:
        return "bg-emerald-50 text-emerald-600"
    if activity_type in _VISIT_TYPES:
        return "edify-primary-soft edify-primary-text"
    if activity_type in _MEETING_TYPES or activity_type in _PARTNER_TYPES:
        return "bg-violet-50 text-violet-600"
    if activity_type in _SSA_TYPES:
        return "bg-amber-50 text-amber-600"
    return "bg-slate-50 text-slate-600"


def _agenda_status_pill(activity, today):
    if activity.status == "completed":
        return "Completed", "bg-emerald-50 text-emerald-700 border-emerald-200"
    if activity.status in ("in_progress", "completion_started"):
        return "In Progress", "bg-amber-50 text-amber-700 border-amber-200"
    if (
        activity.planned_date
        and activity.planned_date < today
        and activity.status not in ("completed", "closed")
    ):
        return "Overdue", "bg-rose-50 text-rose-700 border-rose-200"
    return "Planned", "bg-slate-50 text-slate-500 border-slate-200"


def _agenda_title_and_location(activity):
    """Real title/location strings sourced from the activity's actual school/cluster."""
    title_base = activity.get_activity_type_display()
    if activity.school_id and activity.school:
        title = f"{title_base} — {activity.school.name}"
        district_name = (
            activity.school.district.name if activity.school.district_id else None
        )
        location = (
            f"{activity.school.name} &bull; {district_name} District"
            if district_name
            else activity.school.name
        )
        short_location = (
            f"{district_name} District" if district_name else activity.school.name
        )
    elif activity.cluster_id and activity.cluster:
        title = f"{title_base} — {activity.cluster.name} Cluster"
        district_name = (
            activity.cluster.district.name if activity.cluster.district_id else None
        )
        location = (
            f"{activity.cluster.name} Cluster &bull; {district_name} District"
            if district_name
            else f"{activity.cluster.name} Cluster"
        )
        short_location = (
            f"{district_name} District"
            if district_name
            else f"{activity.cluster.name} Cluster"
        )
    else:
        title = title_base
        location = "Field Activity"
        short_location = "Field Activity"
    return title, location, short_location


def _build_agenda_item(activity, today):
    title, location, _ = _agenda_title_and_location(activity)
    status, status_class = _agenda_status_pill(activity, today)
    item = {
        "title": title,
        "location": location,
        "status": status,
        "status_class": status_class,
        "icon": _agenda_icon(activity.activity_type),
    }
    if activity.salesforce_activity_id:
        item["sf"] = True
    participant_count = (
        (activity.teachers_attended or 0)
        + (activity.leaders_attended or 0)
        + (activity.other_participants or 0)
    )
    if participant_count:
        item["count"] = participant_count
    return item


@require_page_permission("dashboard")
def dashboard_view(request):
    user = request.user
    role = user.active_role

    # The three redirects below need none of the page data, so they come first.
    # They used to sit under it, which meant an Accountant, IA or Partner
    # loading /dashboard paid for the full alerts + today + metrics build and
    # then threw all of it away on the way to another URL.
    if role == "Accountant":
        return redirect("/accounts")

    if role == "ImpactAssessment":
        return redirect("/ia/dashboard/")

    if role in ("PartnerAdmin", "PartnerFieldOfficer"):
        # Partner logins have no StaffProfile/country-cluster scope, so the
        # generic internal-staff dashboard below (schools/clusters/team
        # targets) is meaningless to them. Send them to the existing
        # partner-scoped landing page (their org's today/upcoming activities)
        # instead of building a second parallel dashboard.
        return redirect("/partner/today")

    if role == "BusinessTransformationOfficer":
        # The governed loan dashboard is the operating cockpit for these
        # roles. Sending them through the generic Admin dashboard attempts to
        # render country-admin cards outside their authority and gives them no
        # useful MFI/loan workflow.
        return redirect("/business-transformation/overview")

    if role in ("MfiPartnerAdmin", "MfiLoanOfficer"):
        return redirect("/mfi-portal/dashboard")

    # Fetch common alerts and todays items
    alerts_list = cc_services.alerts(user)
    alerts_summary = cc_services.alerts_summary(user)
    today_context = cc_services.today(user)

    # Get user avatar initials
    names = user.name.split()
    avatar_initials = "".join([n[0].upper() for n in names[:2]]) if names else "US"

    if role == "CountryDirector":
        # Country Director Command Dashboard — the CD's national operating
        # cockpit (what must the CD act on today). Country-wide, oversight-only;
        # all section math reuses CDAnalyticsService so figures never diverge
        # from /analytics/country-director.
        from apps.analytics.cd_dashboard_service import CDDashboardService
        from apps.core.fy import fy_options, get_operational_fy

        fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
        raw_month = (request.GET.get("month") or "").strip()
        month = int(raw_month) if raw_month.isdigit() else None
        data = CDDashboardService.get_dashboard(request.user, fy=fy, month=month)
        _fy_months = [
            "Oct",
            "Nov",
            "Dec",
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
        ]
        context = {
            **data,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "today_context": today_context,
            "fy_options": fy_options(),
            "month_options": [(str(i + 1), lbl) for i, lbl in enumerate(_fy_months)],
            "mobile_primary_action": {
                "label": (
                    (data.get("leadership_attention") or [{}])[0].get("action")
                    or "Open country analytics"
                ),
                "url": (
                    (data.get("leadership_attention") or [{}])[0].get("link")
                    or "/analytics/country-director"
                ),
            },
        }
        if request.headers.get("HX-Request") == "true":
            return render(request, "partials/dashboards/cd/body.html", context)
        return render(request, "pages/dashboards/cd.html", context)

    elif role == "Program Lead":
        # Program Lead Command Dashboard — the PL's supervised-team operating
        # cockpit. Everything is scoped to this PL's supervised CCEOs by
        # ProgramLeadDashboardService (never country-wide, never another PL).
        from apps.analytics.pl_dashboard_service import ProgramLeadDashboardService
        from apps.core.fy import fy_options, get_operational_fy

        fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
        month = (request.GET.get("month") or "").strip() or None
        filters = {"activity_type": request.GET.get("activity_type")}
        raw_urgent_page = (request.GET.get("urgent_page") or "").strip()
        urgent_page = int(raw_urgent_page) if raw_urgent_page.isdigit() else 1
        data = ProgramLeadDashboardService.get_dashboard(
            request.user,
            fy=fy,
            month=month,
            filters=filters,
            urgent_page=urgent_page,
        )
        urgent_pagination_query = {"fy": fy}
        if filters["activity_type"]:
            urgent_pagination_query["activity_type"] = filters["activity_type"]
        leadership_attention = data.get("leadership_attention") or []
        if leadership_attention:
            first_attention = leadership_attention[0]
            attention_link = first_attention.get("link") or "?drill=attention"
            mobile_primary_action = {
                "label": first_attention.get("action") or "Review team attention",
                "url": f"/dashboard/pl-drilldown{attention_link}&fy={fy}",
            }
        else:
            mobile_primary_action = {
                "label": "Open team plan",
                "url": "/my-plan",
            }
        context = {
            **data,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "today_context": today_context,
            "fy_options": fy_options(),
            "urgent_pagination_query": urlencode(urgent_pagination_query),
            "mobile_primary_action": mobile_primary_action,
        }
        if request.headers.get("HX-Request") == "true":
            return render(request, "partials/dashboards/pl/body.html", context)
        return render(request, "pages/dashboards/pl.html", context)

    elif role == "RegionalVicePresident":
        # RVP Dashboard — the regional approval cockpit: country monthly
        # budgets awaiting RVP decision, recent decisions, and a read-only
        # country oversight pulse (PL performance, regional SSA coverage).
        from apps.analytics.rvp_dashboard_service import RVPDashboardService
        from apps.core.fy import fy_options, get_operational_fy

        fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
        data = RVPDashboardService.get_dashboard(request.user, fy=fy)
        context = {
            **data,
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "today_context": today_context,
            "fy_options": fy_options(),
            "mobile_primary_action": {
                "label": (
                    (data.get("attention") or [{}])[0].get("action")
                    or "Open executive reports"
                ),
                "url": "/rvp/approvals"
                if (data.get("attention") or [{}])[0].get("drill") == "approvals"
                else "/reports",
            },
        }
        return render(request, "pages/dashboards/rvp.html", context)

    elif role == "HumanResources":
        # HR People-Operations Dashboard
        from apps.accounts.hr_dashboard_service import HRDashboardService
        from apps.core.fy import fy_options, get_operational_fy

        fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
        month = (request.GET.get("month") or "").strip() or None
        country = (request.GET.get("country") or "").strip() or None
        department = (request.GET.get("department") or "").strip() or None

        data = HRDashboardService.get_dashboard(
            request.user, fy=fy, month=month, country=country, department=department
        )
        if request.GET.get("export") == "csv":
            return _export_hr_dashboard_csv(
                data,
                fy=fy,
                month=month,
                country=country,
                department=department,
            )
        _fy_months = [
            "Oct",
            "Nov",
            "Dec",
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
        ]
        context = {
            **data,
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "today_context": today_context,
            "fy": fy,
            "month": month,
            "country": country,
            "department": department,
            "fy_options": fy_options(),
            "month_options": [(str(i + 1), lbl) for i, lbl in enumerate(_fy_months)],
            "mobile_primary_action": {
                "label": "Review overdue performance"
                if data.get("reviews_due")
                else (
                    "Open recruitment pipeline"
                    if data.get("open_positions")
                    else "Open people directory"
                ),
                "url": "/performance-reviews"
                if data.get("reviews_due")
                else ("/recruitment" if data.get("open_positions") else "/staff"),
            },
        }
        if request.headers.get("HX-Request") == "true":
            return render(request, "partials/dashboards/hr/body.html", context)
        return render(request, "pages/dashboards/hr.html", context)

    elif role == "CCEO":
        # CCEO Field Officer Dashboard Context — all figures are scoped to
        # this CCEO's own activities/fund requests, no fabricated fallbacks.
        today = timezone.now().date()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        # Scope activities to this CCEO across both identifier spaces
        # (responsible_staff_id is stamped as either the StaffProfile or User
        # CUID) plus the partner work they monitor — matches the To-Do queue.
        from apps.core.scoping import resolve_user_scope
        from apps.core.fy import get_operational_fy

        _scope = resolve_user_scope(user)
        _owner_ids = [
            i for i in {*(_scope.staff_ids or []), user.staff_profile_id, user.id} if i
        ]
        cc_activities = Activity.objects.filter(deleted_at__isnull=True).filter(
            Q(responsible_staff_id__in=_owner_ids)
            | Q(monitored_by_staff_id__in=_owner_ids, delivery_type="partner")
        )

        # Owner-scoped urgent-school decision queue. It deliberately reuses
        # the same SSA/activity risk contract as the PL dashboard, then exposes
        # both valid CCEO responses: schedule direct support or hand it to a
        # partner. The drawers enforce object scope and permissions again.
        from apps.analytics.pl_analytics_service import PLScope

        _dashboard_fy = get_operational_fy()
        _risk_scope = PLScope(
            user=user,
            pl_staff_id=user.staff_profile_id,
            responsible_ids=set(_owner_ids),
            school_ids=list(_scope.own_school_ids),
            district_ids=list(_scope.district_ids),
            cluster_ids=list(_scope.cluster_ids),
        )
        # SSA-first, month-scoped, deduplicated — the canonical resolver.
        # risk_list ranked the whole portfolio and would happily label a
        # school "Financial Health — Critical" with no current verified SSA
        # at all; the card now answers only "among the schools planned THIS
        # MONTH, what needs me first", with No SSA outranking everything and
        # suppressing every intervention conclusion.
        from apps.planning.urgent_attention import monthly_urgent_schools

        _urgent = monthly_urgent_schools(user, fy=_dashboard_fy, limit=8)
        urgent_schools = [
            {
                "id": r["school_id"],
                "school_id": r["school_id"],
                "school": r["name"],
                "district": r["where"],
                "issue": r["label"],
                "severity": r["severity"],
                "issue_context": r.get("context") or "",
                "shipping_address": r.get("shipping_address") or "",
                "weakest_intervention": "",
                "weakest_intervention_code": "",
                "recommended_activity_label": r.get("planned") or "",
                "recommended_activity_type": "school_visit",
                "owner_kind": "pl",
                "owner_name": "",
                "action_label": r["action_label"],
                "action_url": r["action_url"],
                # Whether the action opens the scheduling drawer in place or
                # navigates. The planning actions used to link to the Planning
                # PAGE with a school_id it never reads, so "Schedule SSA"
                # landed the user on an unfiltered list with the school to find
                # again. schedule-modal is the endpoint that reads it.
                "action_mode": r.get("action_mode", "link"),
            }
            for r in _urgent["rows"]
        ]
        for row in urgent_schools:
            schedule_query = {
                "school_id": row["id"],
                "recommended_activity_type": row["recommended_activity_type"],
            }
            partner_query = {"school_id": row["id"]}
            if row["weakest_intervention_code"]:
                schedule_query["focus_intervention"] = row["weakest_intervention_code"]
                partner_query["focus_intervention"] = row["weakest_intervention_code"]
            row["schedule_url"] = (
                f"/planning/schedule-modal?{urlencode(schedule_query)}"
            )
            row["partner_url"] = (
                f"/planning/assign-partner-modal?{urlencode(partner_query)}"
            )

        completed_cnt = cc_activities.filter(status__in=COMPLETED_WORK_STATUSES).count()
        in_progress_cnt = cc_activities.filter(
            status__in=["in_progress", "completion_started"]
        ).count()
        planned_cnt = cc_activities.filter(status__in=["scheduled", "planned"]).count()
        overdue_cnt = (
            cc_activities.filter(planned_date__lt=today)
            .exclude(status__in=["completed", "closed"])
            .count()
        )

        total_tasks = completed_cnt + in_progress_cnt + planned_cnt + overdue_cnt

        # A CCEO with nothing scheduled has every share render as 0% -- which
        # on this strip reads as "you have done none of it" rather than "you
        # have nothing". Preserved as-is for now; the honest form is
        # apps.core.metrics.percentage (None) or MetricValue.ratio (NO_DATA).
        from apps.core.metrics import percentage_or_zero

        completed_pct = percentage_or_zero(completed_cnt, total_tasks)
        in_progress_pct = percentage_or_zero(in_progress_cnt, total_tasks)
        planned_pct = percentage_or_zero(planned_cnt, total_tasks)
        overdue_pct = percentage_or_zero(overdue_cnt, total_tasks)

        # ── "This Week's Plan" — three real, actionable operating lists ────────
        _interv = dict(SsaIntervention.choices)
        CLUSTER_TYPES = [
            "cluster_meeting",
            "cluster_training",
            "cluster_training_ssa_collection",
            "cluster_meeting_ssa_review",
            "core_training",
        ]
        DONE_STATUSES = [
            "completed",
            "closed",
            "cancelled",
            "ia_verified",
            "accountant_confirmed",
            "submitted_to_pl",
            "awaiting_ia_verification",
        ]

        # 1) Overdue From Last Week — uncompleted visits + cluster work now past
        #    due (combined into one list), each with a fix/reschedule action.
        overdue_last_week = []
        for a in (
            cc_activities.filter(
                planned_date__lt=today,
                planned_date__gte=today - timedelta(days=21),
            )
            .exclude(status__in=DONE_STATUSES)
            .select_related("school", "school__district", "cluster")
            .order_by("planned_date")[:8]
        ):
            if a.status == "in_progress":
                st, tone, lbl, url, primary = (
                    "Unsuccessful",
                    "warning",
                    "Complete",
                    f"/activities/{a.id}/complete",
                    True,
                )
            elif a.status in ("returned", "returned_by_pl", "returned_by_ia"):
                st, tone, lbl, url, primary = (
                    "Returned",
                    "danger",
                    "Complete",
                    f"/activities/{a.id}/complete",
                    True,
                )
            else:
                st, tone, lbl, url, primary = (
                    "Not Completed",
                    "danger",
                    "Reschedule",
                    f"/my-plan/{a.id}",
                    False,
                )
            overdue_last_week.append(
                {
                    "id": a.id,
                    # The row offers all three routes out of an overdue
                    # activity: finish it, move it, or talk about it. Complete
                    # and Reschedule are drawers; Discuss is the daily debrief
                    # carrying this activity in as its subject.
                    "complete_url": f"/activities/{a.id}/complete",
                    "reschedule_url": f"/my-plan/{a.id}/reschedule-drawer",
                    "discuss_url": f"/debriefs/submit?activity={a.id}",
                    "icon": _agenda_icon(a.activity_type),
                    "activity": a.get_activity_type_display(),
                    "where": a.school.name
                    if a.school_id
                    else (a.cluster.name if a.cluster_id else "—"),
                    "due": a.planned_date.strftime("%b %-d, %Y (%a)"),
                    "status": st,
                    "status_tone": tone,
                    "action_label": lbl,
                    "action_url": url,
                    "action_primary": primary,
                }
            )

        # 2) School Visits — schools scheduled for a visit this week.
        school_visits_week = []
        for a in (
            cc_activities.filter(
                planned_date__range=[today, week_end],
                activity_type__in=VISIT_TYPES,
                school__isnull=False,
            )
            .exclude(status__in=DONE_STATUSES)
            .select_related("school", "school__district")
            .order_by("planned_date")[:8]
        ):
            is_today = a.planned_date == today and a.status == "scheduled"
            school_visits_week.append(
                {
                    "school": a.school.name,
                    "district": a.school.district.name if a.school.district_id else "—",
                    "purpose": a.activity_purpose_text or a.get_activity_type_display(),
                    "date": a.planned_date.strftime("%b %-d, %Y (%a)"),
                    "action_label": "Start Visit" if is_today else "View Details",
                    "action_url": f"/activities/{a.id}/start"
                    if is_today
                    else f"/my-plan/{a.id}",
                    "action_primary": is_today,
                }
            )

        # 3) Cluster Activities This Week — meetings + trainings combined.
        cluster_activities_week = []
        for a in (
            cc_activities.filter(
                planned_date__range=[today, week_end],
                activity_type__in=CLUSTER_TYPES,
                cluster__isnull=False,
            )
            .exclude(status__in=DONE_STATUSES)
            .select_related("cluster")
            .order_by("planned_date")[:8]
        ):
            is_today = a.planned_date == today and a.status == "scheduled"
            is_training = "training" in a.activity_type
            cluster_activities_week.append(
                {
                    "cluster": a.cluster.name,
                    "type_label": a.get_activity_type_display(),
                    "type_tone": "success" if is_training else "info",
                    "focus": _interv.get(a.focus_intervention, "—")
                    if a.focus_intervention
                    else "—",
                    "date": a.scheduled_date.strftime("%b %-d (%a) %-I:%M %p")
                    if a.scheduled_date
                    else a.planned_date.strftime("%b %-d (%a)"),
                    "action_label": "Start" if is_today else "View Details",
                    "action_url": f"/activities/{a.id}/start"
                    if is_today
                    else f"/my-plan/{a.id}",
                    "action_primary": is_today,
                }
            )

        # Rest of the coming week — real activities, not yet done.
        upcoming_qs = (
            cc_activities.filter(
                planned_date__range=[today + timedelta(days=1), week_end],
            )
            .exclude(status__in=["completed", "closed"])
            .select_related(
                "school", "school__district", "cluster", "cluster__district"
            )
            .order_by("planned_date")[:10]
        )

        upcoming_week = []
        for a in upcoming_qs:
            title, _, short_location = _agenda_title_and_location(a)
            upcoming_week.append(
                {
                    "day": a.planned_date.strftime("%a, %b %-d"),
                    "title": title,
                    "desc": short_location,
                    "icon": _agenda_icon(a.activity_type),
                    "type_class": _agenda_type_class(a.activity_type),
                }
            )

        # Pending approvals — this CCEO's own weekly fund requests that need
        # their action (awaiting confirmation, or bounced back for fixes).
        CCEO_ACTION_STATUSES = [
            "pending_responsible_confirmation",
            "returned_by_pl",
            "returned_by_cd",
            "returned_by_rvp",
            "returned_by_accountant",
        ]
        STATUS_LABELS = {
            "pending_responsible_confirmation": "Awaiting",
            "returned_by_pl": "Returned",
            "returned_by_cd": "Returned",
            "returned_by_rvp": "Returned",
            "returned_by_accountant": "Returned",
        }
        wfrs = WeeklyFundRequest.objects.filter(
            responsible_user=user.id,
            status__in=CCEO_ACTION_STATUSES,
        ).order_by("-week_start_date")[:5]

        pending_approvals = []
        for w in wfrs:
            line_count = w.lines.count()
            pending_approvals.append(
                {
                    "title": f"Weekly Fund Request — {w.week_start_date.strftime('%b %-d')}–{w.week_end_date.strftime('%b %-d')}",
                    "desc": f"{_format_ugx_compact(w.total_amount)} &bull; {line_count} item{'s' if line_count != 1 else ''}",
                    "status": STATUS_LABELS.get(w.status, "Awaiting"),
                }
            )

        # Unread notifications, for the header bell badge.
        from apps.notifications.models import Notification

        unread_notifications_count = Notification.objects.filter(
            recipient_id=user.id, status="unread"
        ).count()

        cceo_kpi_items = [
            {
                "label": "Completed Tasks",
                "value": str(completed_cnt),
                "helper": "Activities done",
                "icon": "check",
                "variant": "success",
            },
            {
                "label": "In Progress",
                "value": str(in_progress_cnt),
                "helper": "Being executed",
                "icon": "clock",
                "variant": "info",
            },
            {
                "label": "Planned Tasks",
                "value": str(planned_cnt),
                "helper": "Scheduled ahead",
                "icon": "calendar",
                "variant": "warning",
            },
            {
                "label": "Overdue Tasks",
                "value": str(overdue_cnt),
                "helper": "Past due date",
                "icon": "warning",
                "variant": "danger",
            },
        ]

        # System-generated To-Do operating queue (derived from live workflow
        # state — auto-closes when the underlying action completes).
        from apps.command_center.todo_service import get_todos

        todo_data = get_todos(user)

        if overdue_last_week:
            mobile_primary_action = {
                "label": overdue_last_week[0]["action_label"],
                "url": overdue_last_week[0]["action_url"],
            }
        elif school_visits_week:
            mobile_primary_action = {
                "label": school_visits_week[0]["action_label"],
                "url": school_visits_week[0]["action_url"],
            }
        elif cluster_activities_week:
            mobile_primary_action = {
                "label": cluster_activities_week[0]["action_label"],
                "url": cluster_activities_week[0]["action_url"],
            }
        else:
            mobile_primary_action = {
                "label": "Plan this week",
                "url": "/planning",
            }

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "today": today,
            "current_week_number": today.isocalendar()[1],
            "unread_notifications_count": unread_notifications_count,
            "kpis": {
                "completed": completed_cnt,
                "in_progress": in_progress_cnt,
                "planned": planned_cnt,
                "overdue": overdue_cnt,
                "total": total_tasks,
                "completed_pct": completed_pct,
                "in_progress_pct": in_progress_pct,
                "planned_pct": planned_pct,
                "overdue_pct": overdue_pct,
                "in_progress_offset": -completed_pct,
                "planned_offset": -(completed_pct + in_progress_pct),
                "overdue_offset": -(completed_pct + in_progress_pct + planned_pct),
            },
            # Concentric rings, largest state outermost. Each ring is a share
            # of the total, so the ring lengths are comparable to each other
            # and the centre reads the completion rate.
            "at_a_glance_donut": build_rings(
                [
                    {
                        "key": "completed",
                        "label": "Completed",
                        "value": completed_cnt,
                        "color": "var(--edify-success)",
                    },
                    {
                        "key": "in_progress",
                        "label": "In Progress",
                        "value": in_progress_cnt,
                        "color": "var(--edify-accent)",
                    },
                    {
                        "key": "planned",
                        "label": "Planned",
                        "value": planned_cnt,
                        "color": "var(--edify-warning)",
                    },
                    {
                        "key": "overdue",
                        "label": "Overdue",
                        "value": overdue_cnt,
                        "color": "var(--edify-danger)",
                    },
                ],
                share_of=total_tasks or None,
            ),
            "at_a_glance_subline": (
                f"{total_tasks} activities" if total_tasks else "No activities yet"
            ),
            "overdue_last_week": overdue_last_week,
            "school_visits_week": school_visits_week,
            "cluster_activities_week": cluster_activities_week,
            "week_plan_total": len(overdue_last_week)
            + len(school_visits_week)
            + len(cluster_activities_week),
            "upcoming_week": upcoming_week,
            "pending_approvals": pending_approvals,
            "kpi_strip_items": cceo_kpi_items,
            "todos": todo_data["todos"][:6],
            "todo_counts": todo_data["counts"],
            "todo_total": todo_data["total"],
            "urgent_schools": urgent_schools,
            # Whether to offer "Assign" on each urgent row — handing the visit
            # to a partner is the alternative to doing it yourself, and the
            # same permission governs both.
            "can_assign_partner": RolePermissionService.can_assign_to_partner(
                request.user
            ),
            "mobile_primary_action": mobile_primary_action,
        }
        return render(request, "pages/dashboards/cceo.html", context)

    elif role == "ProjectCoordinator":
        # Special Projects Dashboard Context — sourced entirely from the real
        # Project / ProjectSchoolAssignment / ProjectPartnerAssignment tables.
        # No health scores, teacher-impact counts, budgets, or status/dates are
        # rendered here because the Project model has no such fields yet.
        from apps.projects.models import (
            ProjectSchoolAssignment,
            ProjectPartnerAssignment,
        )

        # The coordinator's own landing page previously listed every project in
        # the country — the single widest scope leak for this role.
        from apps.projects.scoping import scoped_projects

        projects_qs = scoped_projects(request.user).prefetch_related(
            "partner_assignments__partner", "school_assignments"
        )

        portfolio = []
        for p in projects_qs:
            partner_names = [pa.partner.name for pa in p.partner_assignments.all()]
            portfolio.append(
                {
                    "name": p.name,
                    "code": p.code,
                    "category": p.get_category_display(),
                    "partners": ", ".join(partner_names)
                    if partner_names
                    else "Unassigned",
                    "schools_enrolled": len(p.school_assignments.all()),
                }
            )

        # Every count and list below is narrowed to the coordinator's own
        # portfolio via the same scope helper the queryset above uses.
        scoped_ids = list(projects_qs.values_list("id", flat=True))
        schools_in_projects = (
            ProjectSchoolAssignment.objects.filter(project_id__in=scoped_ids)
            .values("school_id")
            .distinct()
            .count()
        )
        partners_assigned = (
            ProjectPartnerAssignment.objects.filter(project_id__in=scoped_ids)
            .values("partner_id")
            .distinct()
            .count()
        )

        # Schools actually assigned to a special project.
        project_schools = [
            {
                "school_name": a.school.name,
                "project_name": a.project.name,
                "district": a.school.district.name if a.school.district_id else "—",
            }
            for a in ProjectSchoolAssignment.objects.filter(project_id__in=scoped_ids)
            .select_related("school", "school__district", "project")
            .order_by("-created_at")[:8]
        ]

        # Partners actually assigned to a special project.
        project_partners = [
            {"partner_name": a.partner.name, "project_name": a.project.name}
            for a in ProjectPartnerAssignment.objects.filter(project_id__in=scoped_ids)
            .select_related("partner", "project")
            .order_by("partner__name")
        ]

        context = {
            "alerts": alerts_list,
            "alerts_summary": alerts_summary,
            "role": role,
            "user_name": user.name,
            "avatar_initials": avatar_initials,
            "portfolio": portfolio,
            "total_projects": len(portfolio),
            "schools_in_projects": schools_in_projects,
            "partners_assigned": partners_assigned,
            "project_schools": project_schools,
            "project_partners": project_partners,
            "mobile_primary_action": {
                "label": "Open project portfolio",
                "url": "/projects",
            },
        }
        return render(request, "pages/dashboards/special_projects.html", context)

    # Every role above returns from its own branch with its own figures, and
    # this is the only reader of `metrics`. Built at the top of the view, it
    # cost 54-62 queries and 73-110 ms that were discarded on every CD, PL,
    # RVP, HR, CCEO and Project Coordinator dashboard load.
    # The Planning Progress card's Week/Month/Quarter/FY switch. Read from the
    # query string so the chosen period survives a reload, a bookmark and a
    # shared link -- and so the tabs can be real links rather than the
    # decorative spans they used to be.
    progress_period = normalise_progress_period(request.GET.get("progress_period"))
    metrics = DashboardMetricsService.get_dashboard_metrics(user, progress_period)

    context = {
        "alerts": alerts_list,
        "alerts_summary": alerts_summary,
        "today_context": today_context,
        "role": role,
        "user_name": user.name,
        "avatar_initials": avatar_initials,
        # Computed metrics
        "kpis": metrics["kpis"],
        "kpi_strip_items": metrics.get("kpi_strip_items", []),
        "signals": metrics["signals"],
        "priorities": metrics["priorities"],
        "weekly_progress": metrics["weekly_progress"],
        "progress_period": metrics["progress_period"],
        "progress_tabs": metrics["progress_tabs"],
        "progress_description": metrics["progress_description"],
        "best_interventions": metrics["best_interventions"],
        "weakest_interventions": metrics["weakest_interventions"],
        "team_targets": metrics["team_targets"],
        "priority_schools": metrics["priority_schools"],
        "cluster_performance": metrics["cluster_performance"],
        "support_overview": metrics["support_overview"],
        "budget_snapshot": metrics["budget_snapshot"],
        "execution_summary": metrics["execution_summary"],
        "upcoming_today": metrics["upcoming_today"],
        "attention_items": metrics.get("attention_items", []),
        "recommended_action": metrics.get("recommended_action"),
        "use_dark_sidebar": False,
    }
    context["country_kpi_items"] = list(context["kpi_strip_items"]) + [
        render_kpi_item(
            "country_schools_needing_attention",
            MetricValue.measured(context["signals"]["needs_attention"]),
            helper="Schools",
            tone="danger",
            drilldown_url="/schools?readiness=attention",
        ),
        render_kpi_item(
            "country_schools_ready_for_action",
            MetricValue.measured(context["signals"]["ready_for_action"]),
            helper="Schools",
            tone="warning",
            drilldown_url="/planning",
        ),
        render_kpi_item(
            "country_operational_health_rate",
            MetricValue.measured(
                context["signals"]["operational_health"], denominator=100
            ),
            helper="System score",
            tone="success",
            drilldown_url="/system-health",
        ),
    ]

    # Registry identities for this page's cards. The bodies below stay as they
    # are; each section takes on its `data-card-key` and its canonical title
    # through `components/registered_card_attrs.html`, so the duplication guard
    # has something to grep and a rename is a one-line change in the registry.
    recommended = metrics.get("recommended_action")
    role_slug = get_user_role_slug(user)
    context["cards"] = {
        name: render_card(key, records, role_slug=role_slug).as_dict()
        for name, key, records in (
            ("todays_priorities", "admin_todays_priorities", metrics["priorities"]),
            (
                "planning_progress",
                "admin_planning_progress",
                metrics["weekly_progress"],
            ),
            (
                "ssa_snapshot",
                "admin_ssa_intervention_extremes",
                [*metrics["best_interventions"], *metrics["weakest_interventions"]],
            ),
            ("team_targets", "admin_team_target_progress", metrics["team_targets"]),
            ("priority_schools", "admin_priority_schools", metrics["priority_schools"]),
            (
                "cluster_performance",
                "admin_cluster_performance",
                metrics["cluster_performance"],
            ),
            (
                "partner_support",
                "admin_partner_support_overview",
                metrics["support_overview"],
            ),
            (
                "budget_snapshot",
                "admin_budget_and_fund_request_snapshot",
                metrics["budget_snapshot"],
            ),
            ("upcoming_today", "admin_upcoming_today", metrics["upcoming_today"]),
            (
                "attention_needed",
                "admin_attention_needed",
                metrics.get("attention_items", []),
            ),
            (
                "recommended_action",
                "admin_next_recommended_action",
                [recommended] if recommended else [],
            ),
            ("quick_actions", "admin_quick_actions", [1]),
            (
                "execution_summary",
                "admin_execution_summary",
                metrics["execution_summary"],
            ),
        )
    }

    if role == "Admin":
        # Admin's home is a Platform Operations command centre, not a country
        # programme dashboard: incidents, tickets, overdue platform work and
        # security alerts come first. The observability sections below stay --
        # Admin still needs to see whether the business surfaces are working --
        # but they are diagnostic context, not Admin's own scorecard.
        from apps.admin_ops.services import AdminOpsDashboardService

        admin_ops = AdminOpsDashboardService.summary(request.user)
        context["admin_ops"] = admin_ops
        context["admin_ops_kpi_items"] = [
            render_kpi_item(
                "admin_critical_incidents",
                MetricValue.measured(admin_ops["critical_incidents"]),
                helper=f"{admin_ops['unacknowledged_incidents']} open and unacknowledged",
                tone="danger" if admin_ops["critical_incidents"] else "success",
                drilldown_url="/admin-ops/incidents",
            ),
            render_kpi_item(
                "admin_open_support_tickets",
                MetricValue.measured(admin_ops["open_tickets"]),
                helper=f"{admin_ops['untriaged_tickets']} awaiting triage",
                tone="warning" if admin_ops["untriaged_tickets"] else "neutral",
                drilldown_url="/admin-ops/support",
            ),
            render_kpi_item(
                "admin_overdue_work",
                MetricValue.measured(admin_ops["overdue_admin_work"]),
                helper=f"{admin_ops['unscheduled_work']} still unscheduled",
                tone="warning" if admin_ops["overdue_admin_work"] else "neutral",
                drilldown_url="/admin-ops/my-plan",
            ),
            render_kpi_item(
                "admin_background_job_incidents",
                MetricValue.measured(admin_ops["job_incidents"]),
                helper="Failed or overdue jobs",
                tone="warning" if admin_ops["job_incidents"] else "neutral",
                drilldown_url="/admin-ops/incidents",
            ),
            render_kpi_item(
                "admin_unhealthy_routes",
                MetricValue.measured(admin_ops["performance_incidents"]),
                helper="Open SLO breaches",
                tone="warning" if admin_ops["performance_incidents"] else "neutral",
                drilldown_url="/admin-ops/incidents",
            ),
            render_kpi_item(
                "admin_security_alerts",
                MetricValue.measured(admin_ops["security_alerts"]),
                helper="Open security incidents",
                tone="danger" if admin_ops["security_alerts"] else "success",
                drilldown_url="/admin-ops/incidents",
            ),
            render_kpi_item(
                "admin_maintenance_due",
                MetricValue.measured(admin_ops["maintenance_due"]),
                helper="Templates at or past their date",
                tone="warning" if admin_ops["maintenance_due"] else "neutral",
                drilldown_url="/admin-ops/maintenance",
            ),
        ]
        context["mobile_primary_action"] = {
            "label": "Resolve critical platform work"
            if admin_ops["critical_now"]
            else "Open admin work plan",
            "url": "/admin-ops/incidents"
            if admin_ops["critical_now"]
            else "/admin-ops/my-plan",
        }

    return render(request, "pages/dashboards/main.html", context)


@require_page_permission("dashboard")
def program_lead_dashboard_view(request):
    """Stable Program Lead dashboard URL for direct links and bookmarks."""
    if request.user.active_role not in ("Program Lead", "Admin"):
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("Program Lead only.")
    return dashboard_view.__wrapped__(request)


# ── Program Lead Command Dashboard — drill-downs + inline approve ────────────
@require_page_permission("dashboard")
def pl_dashboard_drilldown_view(request):
    """Scoped drill-down drawer for the PL Command Dashboard KPIs/backlog cards."""
    if request.user.active_role not in ("Program Lead", "Admin"):
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("Program Lead only.")
    from apps.analytics.pl_dashboard_service import ProgramLeadDashboardService
    from apps.core.fy import get_operational_fy

    drill = (request.GET.get("drill") or "").strip()
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    month = (request.GET.get("month") or "").strip() or None
    payload = ProgramLeadDashboardService.drilldown(
        request.user, drill, fy=fy, month=month
    )
    return render(
        request,
        "partials/dashboards/pl/drilldown.html",
        {"drawer_size": "lg", "fy": fy, **payload},
    )


@require_page_permission("dashboard")
def pl_urgent_schools_page_view(request):
    """Return one compact, role-scoped page of urgent schools for HTMX."""
    from django.http import HttpResponseForbidden

    if request.user.active_role not in ("Program Lead", "Admin"):
        return HttpResponseForbidden("Program Lead only.")

    from apps.analytics.pl_analytics_service import resolve_pl_scope
    from apps.analytics.pl_dashboard_service import ProgramLeadDashboardService
    from apps.core.fy import get_operational_fy

    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    filters = {"activity_type": request.GET.get("activity_type")}
    raw_page = (request.GET.get("urgent_page") or "").strip()
    page = int(raw_page) if raw_page.isdigit() else 1
    pls = resolve_pl_scope(request.user, filters)
    urgent_pagination = ProgramLeadDashboardService.urgent_schools_page(
        request.user, pls, fy, filters, page=page
    )
    pagination_query = {"fy": fy}
    if filters["activity_type"]:
        pagination_query["activity_type"] = filters["activity_type"]
    return render(
        request,
        "partials/dashboards/pl/urgent_schools_page.html",
        {
            "fy": fy,
            "urgent_schools": urgent_pagination["rows"],
            "urgent_pagination": urgent_pagination,
            "urgent_pagination_query": urlencode(pagination_query),
            "can_assign_partner": RolePermissionService.can_assign_to_partner(
                request.user
            ),
        },
    )


@require_page_permission("dashboard")
def pl_dashboard_approve_view(request):
    """Approve a supervised CCEO's weekly fund request straight from the
    dashboard approval queue, then re-render the dashboard body. The service
    enforces that a PL can only approve a supervised CCEO's request (never
    their own — those route to the CD)."""
    if (
        request.user.active_role not in ("Program Lead", "Admin")
        or request.method != "POST"
    ):
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("Not allowed.")
    from apps.analytics.pl_dashboard_service import ProgramLeadDashboardService
    from apps.core.fy import fy_options, get_operational_fy
    from apps.fund_requests.weekly_service import approve_weekly_request

    kind = request.GET.get("kind")
    rid = request.GET.get("id")
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    error = None
    if kind == "weekly_fund" and rid:
        try:
            approve_weekly_request(rid, request.user)
        except Exception as e:  # noqa: BLE001
            error = str(e)
    data = ProgramLeadDashboardService.get_dashboard(request.user, fy=fy)
    context = {
        **data,
        "fy_options": fy_options(),
        "approve_error": error,
        "urgent_pagination_query": urlencode({"fy": fy}),
    }
    return render(request, "partials/dashboards/pl/body.html", context)


@require_page_permission("dashboard")
def pl_send_urgent_action_view(request):
    """Delegate one currently urgent school to the staff member who owns it.

    Every part of the send — the TeamAction, the notification, the message
    thread and the audit event — happens inside `send_action`'s transaction.
    The school leaves the unassigned card because that record now exists, so
    there is no window in which it has been removed from the queue without
    anyone actually having been made responsible for it.
    """
    from django.http import HttpResponseBadRequest, HttpResponseForbidden

    # IA sends the issues assurance finds; PL sends the ones supervision
    # finds. Both are delegating the same condition to the same owner.
    if (
        request.user.active_role
        not in (
            "Program Lead",
            "ImpactAssessment",
            "Admin",
        )
        or request.method != "POST"
    ):
        return HttpResponseForbidden("Program Lead or Impact Assessment only.")

    from apps.core.fy import get_operational_fy
    from apps.core.scoping import resolve_user_scope
    from apps.planning.action_service import ActionError, send_action
    from apps.planning.urgent_attention import resolve_urgent_issue
    from apps.schools.models import School

    school_id = (request.GET.get("school_id") or "").strip()
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    note = (request.POST.get("note") or "").strip()

    scope = resolve_user_scope(request.user)
    # IA has assurance oversight of the whole portfolio; a PL may only
    # delegate within their own span of control.
    permitted = (
        set(scope.school_ids)
        if request.user.active_role in ("ImpactAssessment", "Admin")
        else set(scope.team_school_ids)
    )
    if not school_id or school_id not in permitted:
        return HttpResponseForbidden("This school is not in your scope.")

    school = School.objects.filter(id=school_id).first()
    if not school:
        return HttpResponseBadRequest("School not found.")

    # Re-resolve rather than trusting anything the page posted. The card the
    # user clicked may be minutes stale, and delegating an issue that has
    # since been fixed would put a pointless demand on someone's desk.
    issue = resolve_urgent_issue(school, fy, [])
    supervised = (
        None
        if request.user.active_role in ("ImpactAssessment", "Admin")
        else list(scope.supervised_staff_ids)
    )

    try:
        action = send_action(
            sender=request.user,
            school=school,
            issue=issue,
            fy=fy,
            note=note,
            within_staff_ids=supervised,
        )
    except ActionError as exc:
        # A refusal is information the user needs, not a server error. Rendered
        # into the row so the reason lands where they clicked.
        return render(
            request,
            "partials/dashboards/pl/urgent_action_error.html",
            {"school": school, "error": str(exc)},
            status=200,
        )

    return render(
        request,
        "partials/dashboards/pl/urgent_action_sent.html",
        {
            "owner_name": _action_recipient_name(action),
            "school": school,
            "action": action,
        },
    )


def _action_recipient_name(action) -> str:
    from apps.accounts.models import User

    return (
        User.objects.filter(id=action.recipient_id)
        .values_list("name", flat=True)
        .first()
        or "the school's owner"
    )


@require_page_permission("cd_analytics")
def cd_dashboard_approve_view(request):
    """Approve an escalated weekly fund request straight from the CD command
    dashboard, then re-render the dashboard body. The service enforces that
    only the CD may approve submitted_to_cd requests (and never their own)."""
    if (
        request.user.active_role not in ("CountryDirector", "Admin")
        or request.method != "POST"
    ):
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("Not allowed.")
    from apps.analytics.cd_dashboard_service import CDDashboardService
    from apps.core.fy import fy_options, get_operational_fy
    from apps.fund_requests.weekly_service import approve_weekly_request

    rid = request.GET.get("id")
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    error = None
    if rid:
        try:
            approve_weekly_request(rid, request.user)
        except Exception as e:  # noqa: BLE001
            error = str(e)
    data = CDDashboardService.get_dashboard(request.user, fy=fy)
    context = {
        **data,
        "fy_options": fy_options(),
        "approve_error": error,
        "role": "CountryDirector",
        "user_name": request.user.name,
    }
    return render(request, "partials/dashboards/cd/body.html", context)


@require_page_permission("dashboard")
def planning_progress_fragment_view(request):
    """The Planning Progress chart for one period, for the card's tabs.

    Renders the same partial the full page uses, so the two cannot drift. The
    tabs also carry a plain href, so the period still switches with htmx
    unavailable -- the fragment is an optimisation, not the mechanism.
    """
    period = normalise_progress_period(request.GET.get("progress_period"))
    metrics = DashboardMetricsService.get_dashboard_metrics(request.user, period)
    return render(
        request,
        "partials/dashboards/admin/_planning_progress_body.html",
        {
            "weekly_progress": metrics["weekly_progress"],
            "progress_period": metrics["progress_period"],
            "progress_description": metrics["progress_description"],
        },
    )
