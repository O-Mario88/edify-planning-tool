"""
GROUPS 4-7 — SSA/FY, Districts/Reports, Admin, Specialised Views
"""

import calendar
import re
from collections import defaultdict

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from apps.core.permissions import (
    require_page_permission,
    get_scoped_object_or_404,
    RolePermissionService,
)
from apps.core.scoping import resolve_user_scope, school_queryset
from django.db import transaction
from django.db.models import Q, Avg, Count, Sum
from datetime import date, timedelta

from apps.ssa.models import SsaRecord
from apps.schools.models import School
from apps.activities.models import Activity
from apps.geography.models import District, Region
from apps.accounts.models import (
    CalendarBlock,
    Leave,
    PublicHoliday,
    StaffProfile,
    User,
)
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.core_schools.models import CorePlan, CoreActivitySlot
from apps.audit.models import AuditLog
from apps.flags.models import CdFlag
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy, get_quarter_for_date, fy_options
from apps.targets.models import TargetSetting, TargetType
from apps.core.rbac import EdifyRole


# ═══════════════════════════════════════════════════════════════════════════════
# Calendar reference dates supplied for the Edify operations calendar. These
# are deliberate organisation-calendar observances, not an attempt to maintain
# the Government of Uganda's legal public-holiday register. Government-declared
# one-off holidays (including a Presidential Inauguration) stay data-driven in
# PublicHoliday/CalendarBlock and are shown only when an authorised user adds
# them for the applicable year.
_CALENDAR_REFERENCE_HOLIDAYS = (
    (1, 2, "New Year"),
    (1, 17, "Election Day Holiday"),
    (1, 27, "Liberation Day"),
    (2, 17, "Remembrance of Archbishop Janani Luwum"),
    (2, 19, "Ramadan Start"),
    (3, 9, "International Women's Day"),
    (3, 21, "Eid al-Fitr"),
    (4, 4, "Good Friday"),
    (4, 6, "Easter Sunday"),
    (4, 7, "Easter Monday"),
    (5, 2, "Labour Day"),
    (5, 11, "Mother's Day"),
    (5, 28, "Eid al-Adha"),
    (6, 4, "Martyrs' Day"),
    (6, 10, "National Heroes Day"),
    (6, 22, "Father's Day"),
    (9, 23, "September Equinox"),
    (10, 10, "Independence Day"),
    (12, 22, "December Solstice"),
    (12, 26, "Christmas Day"),
    (12, 27, "Boxing Day"),
)


def _reference_holidays_for_year(year: int) -> list[dict]:
    """Return the recurring organisation observances shown in Calendar.

    A Presidential Inauguration intentionally is not in this list: it is a
    government-declared, once-every-five-years event and must be entered in
    PublicHoliday or CalendarBlock for the year in which it applies.
    """

    return [
        {"date": date(year, month, day), "title": title}
        for month, day, title in _CALENDAR_REFERENCE_HOLIDAYS
    ]


# Calendar visibility is intentionally narrower than country-level reporting.
# A leadership calendar reveals future staff movements and absences, so it
# follows the operational reporting line rather than the broader analytics
# scope used elsewhere in the platform.
_CALENDAR_ROLE_AUDIENCES = {
    EdifyRole.COUNTRY_DIRECTOR.value: (
        EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        EdifyRole.PROGRAM_ACCOUNTANT.value,
        EdifyRole.IMPACT_ASSESSMENT.value,
    ),
    EdifyRole.REGIONAL_VICE_PRESIDENT.value: (
        EdifyRole.COUNTRY_DIRECTOR.value,
        EdifyRole.HUMAN_RESOURCES.value,
    ),
}


def _calendar_staff_audience(user) -> tuple[list[str] | None, list[str] | None]:
    """Return activity-owner and leave staff ids visible in Calendar.

    Activity ownership is a legacy dual-id field, so each visible staff member
    contributes both their StaffProfile id and User id. Leave always uses the
    canonical StaffProfile id. ``None`` means unrestricted (Admin only).
    """

    if user.active_role == EdifyRole.ADMIN.value:
        return None, None

    own_staff_id = user.staff_profile_id
    activity_owner_ids = {value for value in (user.id, own_staff_id) if value}
    leave_staff_ids = {own_staff_id} if own_staff_id else set()

    visible_staff = StaffProfile.objects.none()
    if user.active_role == EdifyRole.COUNTRY_PROGRAM_LEAD.value and own_staff_id:
        # A PL sees only the CCEOs explicitly assigned to them, never another
        # PL's field team.
        visible_staff = StaffProfile.objects.filter(
            deleted_at__isnull=True,
            user__is_active=True,
            user__active_role=EdifyRole.CCEO.value,
            supervisor_links__supervisor_id=own_staff_id,
        )
    elif target_roles := _CALENDAR_ROLE_AUDIENCES.get(user.active_role):
        # CD and RVP schedule views are role-specific and country-bounded.
        # Do not borrow the broader country analytics scope here.
        visible_staff = StaffProfile.objects.filter(
            deleted_at__isnull=True,
            user__is_active=True,
            user__active_role__in=target_roles,
        )
        if own_staff_id:
            viewer_country = (
                StaffProfile.objects.filter(id=own_staff_id)
                .values_list("country", flat=True)
                .first()
            )
            if viewer_country:
                visible_staff = visible_staff.filter(country=viewer_country)

    for staff_id, staff_user_id in visible_staff.values_list("id", "user_id"):
        leave_staff_ids.add(staff_id)
        activity_owner_ids.update(value for value in (staff_id, staff_user_id) if value)

    return sorted(activity_owner_ids), sorted(leave_staff_ids)


# GROUP 4 — SSA, FY & Planning
# ═══════════════════════════════════════════════════════════════════════════════


@require_page_permission("ssa")
def ssa_master_view(request):
    """SSA master view — scores overview across all schools."""
    fy = get_operational_fy()
    search = request.GET.get("q", "").strip()

    records = (
        SsaRecord.objects.filter(fy=fy, deleted_at__isnull=True)
        .select_related("school")
        .order_by("average_score")
    )
    if search:
        records = records.filter(school__name__icontains=search)

    records_list = list(records[:100])
    avg_score = sum(r.average_score or 0 for r in records_list) / max(
        len(records_list), 1
    )
    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    schools_with_ssa = records.values("school_id").distinct().count()

    context = {
        "records": records_list,
        "avg_score": round(avg_score, 2),
        "total_schools": total_schools,
        "schools_with_ssa": schools_with_ssa,
        "fy": fy,
        "search": search,
        "topbar_search": {
            "placeholder": "Search school…",
            "value": search,
            "action": "/ssa",
        },
    }
    return render(request, "pages/ssa/index.html", context)


@require_page_permission("planning")
def fy_overview_view(request):
    """Fiscal year overview — planning status, readiness, and timeline."""
    fy = get_operational_fy()

    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    ssa_done = (
        SsaRecord.objects.filter(fy=fy, deleted_at__isnull=True)
        .values("school_id")
        .distinct()
        .count()
    )
    total_activities = Activity.objects.filter(deleted_at__isnull=True).count()
    completed_activities = Activity.objects.filter(
        status="completed", deleted_at__isnull=True
    ).count()

    context = {
        "fy": fy,
        "total_schools": total_schools,
        "ssa_done": ssa_done,
        "ssa_pending": total_schools - ssa_done,
        "total_activities": total_activities,
        "completed_activities": completed_activities,
        "completion_rate": round(completed_activities / max(total_activities, 1) * 100),
    }
    return render(request, "pages/fy/index.html", context)


@require_page_permission("calendar")
def calendar_view(request):
    """Role-scoped operations calendar for activities, leave, and holidays."""
    from apps.core.clock import ClockService

    user = request.user
    today = ClockService.today()
    try:
        month = int(request.GET.get("month", today.month))
        year = int(request.GET.get("year", today.year))
    except (TypeError, ValueError):
        month, year = today.month, today.year
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        month, year = today.month, today.year

    month_start = date(year, month, 1)
    month_end = date(
        year + (1 if month == 12 else 0), 1 if month == 12 else month + 1, 1
    ) - timedelta(days=1)

    activities = (
        Activity.objects.filter(deleted_at__isnull=True)
        .filter(
            Q(scheduled_date__date__range=(month_start, month_end))
            | Q(
                scheduled_date__isnull=True,
                planned_date__range=(month_start, month_end),
            )
        )
        .exclude(status__in=["cancelled", "rejected"])
        .select_related("school", "cluster")
        .order_by("planned_date", "scheduled_date", "created_at")
    )

    scope = resolve_user_scope(user)
    activity_owner_ids, leave_staff_ids = _calendar_staff_audience(user)
    project_scope = request.GET.get("project_scope", "")
    selected_project = request.GET.get("project", "")
    if project_scope == "special":
        projects_qs = Project.objects.filter(deleted_at__isnull=True)
        if not scope.country_scope:
            if user.active_role == "ProjectCoordinator" and user.staff_profile_id:
                projects_qs = projects_qs.filter(manager_staff_id=user.staff_profile_id)
            elif scope.school_ids:
                projects_qs = projects_qs.filter(
                    school_assignments__school_id__in=scope.school_ids
                ).distinct()
            else:
                projects_qs = projects_qs.none()
        project_ids = list(projects_qs.values_list("id", flat=True))
        if selected_project in project_ids:
            project_ids = [selected_project]
        activities = activities.filter(project_id__in=project_ids)
        # projects_qs above is already scoped to what this user may see -- the
        # coordinator's own projects, or the projects covering their schools --
        # so project membership IS the entitlement here. Layering the staff
        # ownership filter on top as well hid partner-delivered work from the
        # coordinator running the project, because a partner activity has no
        # responsible staff and is only reachable through monitored_by_staff_id.
        activity_owner_ids = None
    if activity_owner_ids is not None:
        activities = activities.filter(
            Q(responsible_staff_id__in=activity_owner_ids)
            | Q(
                monitored_by_staff_id__in=activity_owner_ids,
                delivery_type="partner",
            )
        )

    events_by_date: dict[date, list[dict]] = defaultdict(list)
    event_counts = {"activity": 0, "leave": 0, "holiday": 0}

    for activity in activities:
        activity_date = (
            activity.scheduled_date.date()
            if activity.scheduled_date
            else activity.planned_date
        )
        if not activity_date or not month_start <= activity_date <= month_end:
            continue
        place = (
            activity.school.name
            if activity.school_id
            else (activity.cluster.name if activity.cluster_id else "Edify activity")
        )
        events_by_date[activity_date].append(
            {
                "kind": "activity",
                "title": activity.get_activity_type_display(),
                "meta": place,
                "href": f"/my-plan/{activity.id}",
                "status": activity.status.replace("_", " ").title(),
            }
        )
        event_counts["activity"] += 1

    # Approved leave is visible to the viewer's operational scope. A pending
    # request is private to its requester, so it appears only on their own
    # calendar and never exposes a colleague's pending absence.
    leave_qs = Leave.objects.filter(
        status__in=["approved", "pending"],
        start_date__lte=month_end.isoformat(),
        end_date__gte=month_start.isoformat(),
    ).select_related("staff__user")
    if leave_staff_ids is not None:
        if leave_staff_ids:
            leave_qs = leave_qs.filter(staff_id__in=leave_staff_ids)
        else:
            leave_qs = leave_qs.none()

    for leave in leave_qs:
        is_own_pending = (
            leave.status == "pending" and leave.staff_id == user.staff_profile_id
        )
        if leave.status == "pending" and not is_own_pending:
            continue
        try:
            leave_start = date.fromisoformat(leave.start_date)
            leave_end = date.fromisoformat(leave.end_date)
        except (TypeError, ValueError):
            continue
        current_date = max(leave_start, month_start)
        final_date = min(leave_end, month_end)
        label = leave.type.replace("_", " ").title()
        staff_name = (
            "Your" if leave.staff_id == user.staff_profile_id else leave.staff.user.name
        )
        while current_date <= final_date:
            events_by_date[current_date].append(
                {
                    "kind": "leave",
                    "title": f"{staff_name} leave",
                    "meta": f"{label}{' · Awaiting approval' if is_own_pending else ''}",
                    "href": "/personal-time-off",
                    "status": leave.status.title(),
                }
            )
            event_counts["leave"] += 1
            current_date += timedelta(days=1)

    # PublicHoliday/CalendarBlock are the authoritative place for a
    # government-declared, non-recurring date. The recurring organisation
    # observances above fill out the planning calendar without changing the
    # scheduling policy or manufacturing database records.
    holiday_keys: set[tuple[date, str]] = set()

    def add_holiday(holiday_date: date, title: str, detail: str = "Holiday"):
        key = (holiday_date, title.strip().casefold())
        if key in holiday_keys or not month_start <= holiday_date <= month_end:
            return
        holiday_keys.add(key)
        events_by_date[holiday_date].append(
            {
                "kind": "holiday",
                "title": title,
                "meta": detail,
                "href": "",
                "status": "Holiday",
            }
        )
        event_counts["holiday"] += 1

    for holiday in PublicHoliday.objects.filter(date__range=(month_start, month_end)):
        add_holiday(holiday.date, holiday.name, "Public holiday")
    for block in CalendarBlock.objects.filter(
        is_active=True,
        block_type="PUBLIC_HOLIDAY",
        start_date__lte=month_end,
        end_date__gte=month_start,
    ):
        current_date = max(block.start_date, month_start)
        final_date = min(block.end_date, month_end)
        while current_date <= final_date:
            add_holiday(current_date, block.title, "Public holiday")
            current_date += timedelta(days=1)
    for holiday in _reference_holidays_for_year(year):
        add_holiday(holiday["date"], holiday["title"], "Edify calendar holiday")

    event_order = {"holiday": 0, "leave": 1, "activity": 2}
    for day_events in events_by_date.values():
        day_events.sort(key=lambda event: (event_order[event["kind"]], event["title"]))

    calendar_weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdatescalendar(year, month):
        calendar_weeks.append(
            [
                {
                    "date": day,
                    "events": events_by_date.get(day, []),
                    "is_current_month": day.month == month,
                    "is_today": day == today,
                }
                for day in week
            ]
        )

    context = {
        "activities": activities,
        "calendar_weeks": calendar_weeks,
        "month": month,
        "year": year,
        "today": today,
        "month_name": calendar.month_name[month],
        "month_last_day": month_end,
        "weekday_labels": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
        "event_counts": event_counts,
        "event_total": sum(event_counts.values()),
        "project_scope": project_scope,
        "selected_project": selected_project,
        "prev_month": month - 1 if month > 1 else 12,
        "prev_year": year if month > 1 else year - 1,
        "next_month": month + 1 if month < 12 else 1,
        "next_year": year if month < 12 else year + 1,
    }
    return render(request, "pages/calendar/index.html", context)


@require_page_permission("planning")
def work_plan_view(request):
    """Full year work plan."""
    user = request.user
    fy = get_operational_fy()

    activities_qs = Activity.objects.filter(deleted_at__isnull=True).select_related(
        "school", "cluster"
    )
    if user.active_role == "CCEO":
        activities_qs = activities_qs.filter(responsible_staff_id=user.id)

    monthly_summary = (
        activities_qs.values("planned_date__month")
        .annotate(
            total=Count("id"),
            completed=Count("id", filter=Q(status="completed")),
        )
        .order_by("planned_date__month")
    )

    context = {
        "monthly_summary": monthly_summary,
        "fy": fy,
        "total": activities_qs.count(),
        "completed": activities_qs.filter(status="completed").count(),
    }
    return render(request, "pages/work_plan/index.html", context)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — Districts, Reports & Analytics
# ═══════════════════════════════════════════════════════════════════════════════


@require_page_permission("planning")
def districts_list_view(request):
    """Districts list — geographic view."""
    search = request.GET.get("q", "").strip()
    fy = get_operational_fy()
    districts = District.objects.all().order_by("name")
    if search:
        districts = districts.filter(name__icontains=search)

    district_data = []
    for d in districts:
        schools = School.objects.filter(district=d, deleted_at__isnull=True)
        school_count = schools.count()
        avg_ssa = SsaRecord.objects.filter(
            school__district=d, fy=fy, deleted_at__isnull=True
        ).aggregate(avg=Avg("average_score"))["avg"]

        district_data.append(
            {
                "id": d.id,
                "name": d.name,
                "region": d.region.name if d.region else "—",
                "school_count": school_count,
                "avg_ssa": round(avg_ssa, 2) if avg_ssa else None,
            }
        )

    context = {
        "districts": district_data,
        "total": len(district_data),
        "search": search,
        "topbar_search": {
            "placeholder": "Search districts…",
            "value": search,
            "action": "/districts",
        },
    }
    return render(request, "pages/districts/index.html", context)


@require_page_permission("planning")
def district_detail_view(request, district_id):
    """District detail — schools, SSA, and activities."""
    district = get_object_or_404(District, id=district_id)
    schools = School.objects.filter(
        district=district, deleted_at__isnull=True
    ).order_by("name")
    from apps.ssa.services import get_ssa_progress_by_fy

    district_progress = get_ssa_progress_by_fy(schools)

    context = {
        "district": district,
        "schools": schools,
        "total_schools": schools.count(),
        "district_progress": district_progress,
    }
    return render(request, "pages/districts/detail.html", context)


def _reports_pct_class(pct):
    """Colour a percentage the same way everywhere on this page — real
    thresholds, not a per-row hand-picked colour."""
    if pct is None:
        return "text-slate-400"
    if pct >= 70:
        return "text-emerald-600"
    if pct >= 50:
        return "edify-primary-text"
    return "text-rose-600"


# Areas of work with a defensible activity_type mapping — every bucket below
# corresponds to activity_type values that actually exist on the Activity
# model (apps.core.enums.ActivityType), and (where one exists) a real
# apps.targets.models.TargetType so the "target" side of the page can be
# backed by real TargetSetting rows instead of invented numbers.
_REPORTS_VISIT_TYPES = (
    "school_visit",
    "follow_up_visit",
    "coaching_visit",
    "in_school_support",
    "core_visit",
)
_REPORTS_TRAINING_TYPES = (
    "training",
    "school_improvement_training",
    "cluster_training",
    "core_training",
)
_REPORTS_ACHIEVED_STATUSES = (
    "completed",
    "ia_verified",
    "accountant_confirmed",
    "closed",
)

_REPORTS_AREA_DEFS = [
    {
        "key": "school_visits",
        "label": "School Visits",
        "types": _REPORTS_VISIT_TYPES,
        "target_type": TargetType.SCHOOL_VISIT,
    },
    {
        "key": "trainings",
        "label": "Trainings Delivered",
        "types": _REPORTS_TRAINING_TYPES,
        "target_type": TargetType.TRAINING,
    },
    {
        "key": "ssa_activities",
        "label": "SSA Activities",
        "types": ("ssa_activity",),
        "target_type": TargetType.SSA,
    },
    {
        "key": "cluster_meetings",
        "label": "Cluster Meetings",
        "types": ("cluster_meeting",),
        "target_type": None,
    },
    {
        "key": "partner_activities",
        "label": "Partner Activities",
        "types": ("partner_activity",),
        "target_type": TargetType.PARTNER_SUPPORT,
    },
]

# Real FY quarter definitions (apps.core.fy: FY runs Oct 1 -> Sep 30).
_REPORTS_QUARTER_PERIODS = [
    ("q1", "Q1", "Q1 (Oct - Dec)", 1),
    ("q2", "Q2", "Q2 (Jan - Mar)", 2),
    ("q3", "Q3", "Q3 (Apr - Jun)", 3),
    ("q4", "Q4", "Q4 (Jul - Sep)", 4),
]


@require_page_permission("reports")
def reports_view(request):
    """Reports overview — all roles.

    Achieved-vs-target figures are built from real Activity records against
    real apps.targets.models.TargetSetting rows for the selected FY. Where no
    TargetSetting row exists for a given area, the target/percentage are left
    unset (None) and the template renders an honest "no target configured"
    state instead of a made-up percentage.
    """
    operational_fy = get_operational_fy()
    fy_choices = fy_options()
    requested_fy = request.GET.get("fy")
    fy = requested_fy if requested_fy in fy_choices else operational_fy

    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    total_activities = Activity.objects.filter(deleted_at__isnull=True).count()
    completed = Activity.objects.filter(
        status="completed", deleted_at__isnull=True
    ).count()

    activities_fy = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    today = date.today()
    current_quarter = get_quarter_for_date(today) if fy == operational_fy else None
    quarter_order = {q[1]: q[3] for q in _REPORTS_QUARTER_PERIODS}
    current_quarter_order = quarter_order.get(current_quarter)

    # ── Period definitions (chevron row + matrix columns), in chronological
    # order: current Month -> Q1 -> Q2 -> Mid Year (Q1+Q2) -> Q3 -> Q4 -> FY.
    quarter_periods_by_key = {
        key: {
            "key": key,
            "chevron_label": label,
            "kind_label": f"Quarter {order}",
            "filter": Q(quarter=quarter_code),
            "dimmed": current_quarter_order is not None
            and order > current_quarter_order,
        }
        for key, quarter_code, label, order in _REPORTS_QUARTER_PERIODS
    }
    periods = [
        {
            "key": "month",
            "chevron_label": today.strftime("%b %Y"),
            "kind_label": "Monthly",
            "filter": Q(month=today.month),
            "dimmed": fy != operational_fy,
        },
        quarter_periods_by_key["q1"],
        quarter_periods_by_key["q2"],
        {
            "key": "mid",
            "chevron_label": "Mid Year (Oct - Mar)",
            "kind_label": "Cumulative",
            "filter": Q(quarter__in=["Q1", "Q2"]),
            "dimmed": current_quarter_order is not None and current_quarter_order < 2,
        },
        quarter_periods_by_key["q3"],
        quarter_periods_by_key["q4"],
        {
            "key": "fy",
            "chevron_label": f"FY {fy}",
            "kind_label": "Full Year",
            "filter": Q(),
            "dimmed": False,
        },
    ]

    def _target_for(target_type):
        if not target_type:
            return None
        return TargetSetting.objects.filter(
            fy=fy, target_type=target_type, is_active=True
        ).aggregate(s=Sum("target_value"))["s"]

    matrix_rows = []
    # Running totals across all areas, per period — backs the chevron row and
    # the "Overall Progress" summary line.
    period_totals = {
        p["key"]: {"achieved": 0, "target": 0, "has_target": False} for p in periods
    }

    for area in _REPORTS_AREA_DEFS:
        base_qs = activities_fy.filter(activity_type__in=area["types"])
        target_total = _target_for(area["target_type"])
        row = {"area": area["label"], "periods": []}
        for p in periods:
            achieved = base_qs.filter(
                p["filter"], status__in=_REPORTS_ACHIEVED_STATUSES
            ).count()
            pct = round(achieved / target_total * 100) if target_total else None
            row["periods"].append(
                {
                    "achieved": achieved,
                    "target": target_total,
                    "pct": pct,
                    "has_target": target_total is not None,
                    "pct_class": _reports_pct_class(pct),
                }
            )
            period_totals[p["key"]]["achieved"] += achieved
            if target_total:
                period_totals[p["key"]]["target"] += target_total
                period_totals[p["key"]]["has_target"] = True
        matrix_rows.append(row)

    # ── Chevron summary row (Monthly / Q1 .. Q4 / Mid Year / FY) ────────────
    for p in periods:
        totals = period_totals[p["key"]]
        target = totals["target"] if totals["has_target"] else None
        pct = round(totals["achieved"] / target * 100) if target else None
        p.update(
            {
                "achieved": totals["achieved"],
                "target": target,
                "pct": pct,
                "has_target": target is not None,
                "pct_class": _reports_pct_class(pct),
            }
        )

    # ── Core target cards (FY-to-date per area) ─────────────────────────────
    card_colors = [
        "edify-primary-text",
        "text-emerald-600",
        "text-teal-600",
        "edify-primary-text",
        "text-violet-600",
    ]
    core_cards = []
    for i, area in enumerate(_REPORTS_AREA_DEFS):
        fy_cell = matrix_rows[i]["periods"][-1]
        core_cards.append(
            {
                "label": area["label"],
                "achieved": fy_cell["achieved"],
                "target": fy_cell["target"],
                "has_target": fy_cell["has_target"],
                "pct": fy_cell["pct"],
                "color": card_colors[i % len(card_colors)],
            }
        )

    # ── Achievement vs target donut — only areas with a real FY target can
    # honestly be classified as on/at-risk/off-track. ─────────────────────
    donut_on_track = donut_at_risk = donut_off_track = 0
    for i, area in enumerate(_REPORTS_AREA_DEFS):
        fy_cell = matrix_rows[i]["periods"][-1]
        if not fy_cell["has_target"]:
            continue
        pct = fy_cell["pct"] or 0
        if pct >= 70:
            donut_on_track += 1
        elif pct >= 50:
            donut_at_risk += 1
        else:
            donut_off_track += 1
    donut_total = donut_on_track + donut_at_risk + donut_off_track

    # ── Priorities — one real card per area, driven by the same FY figures
    # as the matrix/cards above. Areas with no configured target say so
    # honestly instead of inventing an achievement narrative. ──────────────
    priorities = []
    for i, area in enumerate(_REPORTS_AREA_DEFS):
        fy_cell = matrix_rows[i]["periods"][-1]
        if not fy_cell["has_target"]:
            priorities.append(
                {
                    "title": area["label"],
                    "desc": f"No FY{fy} target configured — set a target to track achievement.",
                    "status": "No Target",
                    "status_class": "bg-slate-100 text-slate-500 border-slate-200",
                }
            )
            continue
        pct = fy_cell["pct"] or 0
        if pct >= 70:
            status, status_class = (
                "On Track",
                "bg-emerald-50 text-emerald-700 border-emerald-250",
            )
        elif pct >= 50:
            status, status_class = (
                "At Risk",
                "bg-amber-50 text-amber-700 border-amber-250",
            )
        else:
            status, status_class = (
                "Off Track",
                "bg-rose-50 text-rose-700 border-rose-250",
            )
        priorities.append(
            {
                "title": area["label"],
                "desc": f"{pct}% achieved against the FY{fy} target ({fy_cell['achieved']} / {fy_cell['target']:.0f}).",
                "status": status,
                "status_class": status_class,
            }
        )

    context = {
        "fy": fy,
        "fy_choices": fy_choices,
        "total_schools": total_schools,
        "total_activities": total_activities,
        "completed": completed,
        "completion_rate": round(completed / max(total_activities, 1) * 100)
        if total_activities > 0
        else 0,
        "periods": periods,
        "core_cards": core_cards,
        "matrix_rows": matrix_rows,
        "donut_total": donut_total,
        "donut_on_track": donut_on_track,
        "donut_at_risk": donut_at_risk,
        "donut_off_track": donut_off_track,
        "priorities": priorities,
    }
    return render(request, "pages/reports/index.html", context)


@require_page_permission("coverage")
def coverage_view(request):
    """Coverage overview — CD/IA."""
    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    visited = (
        Activity.objects.filter(
            activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
            status="completed",
            deleted_at__isnull=True,
        )
        .values("school_id")
        .distinct()
        .count()
    )

    # School.cluster_id is the canonical cluster membership source. Build the
    # counts in one aggregate query instead of reading the legacy assignment
    # projection, which could diverge after an interrupted update.
    clusters = list(Cluster.objects.filter(deleted_at__isnull=True).order_by("name"))
    school_counts = {
        row["cluster_id"]: row["count"]
        for row in School.objects.filter(deleted_at__isnull=True)
        .exclude(cluster_id__isnull=True)
        .exclude(cluster_id="")
        .values("cluster_id")
        .annotate(count=Count("id"))
    }
    for cluster in clusters:
        cluster.school_count = school_counts.get(cluster.id, 0)

    context = {
        "total_schools": total_schools,
        "visited": visited,
        "unvisited": total_schools - visited,
        "coverage_pct": round(visited / max(total_schools, 1) * 100),
        "clusters": clusters,
    }
    return render(request, "pages/coverage/index.html", context)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 6 — Admin, Settings, Messages, Search
# ═══════════════════════════════════════════════════════════════════════════════


@require_page_permission("admin_dashboard")
def admin_panel_view(request):
    """Admin panel home."""
    from apps.system_health.services import missing_cost_lines_count

    user_count = User.objects.filter(deleted_at__isnull=True).count()
    active_users = User.objects.filter(status="active", deleted_at__isnull=True).count()
    pending_invites = User.objects.filter(
        status="pending_invited", deleted_at__isnull=True
    ).count()
    suspended_users = User.objects.filter(
        status="suspended", deleted_at__isnull=True
    ).count()

    # Same real signals surfaced on /system-health — reused here so the two
    # pages never disagree about what's actually broken.
    unmatched_staff_schools = School.objects.filter(
        account_owner_status="unmatched"
    ).count()
    missing_cost_lines = missing_cost_lines_count()

    context = {
        "user_count": user_count,
        "active_users": active_users,
        "pending_invites": pending_invites,
        "suspended_users": suspended_users,
        "unmatched_staff_schools": unmatched_staff_schools,
        "missing_cost_lines": missing_cost_lines,
    }
    return render(request, "pages/admin/index.html", context)


@require_page_permission("users")
def admin_users_view(request):
    """User management."""
    from django.contrib import messages
    from apps.geography.models import District
    from apps.core.rbac import EdifyRole

    if request.method == "POST":
        from django.db import transaction

        action = request.POST.get("action")
        if action == "create":
            from django.utils import timezone

            email = request.POST.get("email", "").lower().strip()
            name = request.POST.get("name", "").strip()
            phone = request.POST.get("phone", "").strip()
            role = request.POST.get("role")
            additional = request.POST.getlist("additional_roles")
            district_id = request.POST.get("primary_district")
            additional_districts = request.POST.getlist("additional_districts")
            password = request.POST.get("password", "").strip()

            if not email or not name or not role:
                messages.error(request, "Name, email, and primary role are required.")
                return redirect("frontend:admin_users")

            if not password:
                messages.error(request, "Password is required when creating a user.")
                return redirect("frontend:admin_users")

            if User.objects.filter(email=email, deleted_at__isnull=True).exists():
                messages.error(request, "A user with this email already exists.")
                return redirect("frontend:admin_users")

            from apps.core.security import validate_password

            violations = validate_password(password, email)
            if violations:
                messages.error(request, " ".join(violations))
                return redirect("frontend:admin_users")

            # Same Admin-grant guard the canonical service applies. This is a
            # hand-rolled copy of create(), and it inherited none of the
            # service's protections -- an HR user could create an active
            # account carrying role='Admin' from this page.
            from apps.admin_users.services import assert_may_administer
            from apps.core.exceptions import BadRequest

            try:
                assert_may_administer(
                    None,
                    request.user,
                    requested_roles=list(dict.fromkeys([role, *additional])),
                )
            except BadRequest as exc:
                messages.error(request, str(getattr(exc, "detail", exc)))
                return redirect("frontend:admin_users")

            with transaction.atomic():
                user = User.objects.create_user(
                    email=email,
                    name=name,
                    phone=phone,
                    roles=list(dict.fromkeys([role, *additional])),
                    active_role=role,
                    password=password,
                    status="active",
                    is_active=True,
                    password_set_at=timezone.now(),
                    must_change_password=True,
                )
                from apps.accounts.models import StaffProfile, StaffGeographyAssignment

                sp = StaffProfile.objects.create(
                    user=user, primary_district_id=district_id or None, title=role
                )

                selected_districts = []
                if district_id:
                    selected_districts.append(district_id)
                for ad in additional_districts:
                    if ad:
                        selected_districts.append(ad)
                selected_districts = list(dict.fromkeys(selected_districts))

                for d_id in selected_districts:
                    StaffGeographyAssignment.objects.create(staff=sp, district_id=d_id)

                from apps.core.email import mailer

                mailer.send_temporary_password_notification(
                    to=email, name=name, invited_by_name=request.user.name
                )

            messages.success(
                request,
                f"User '{name}' successfully created with password set. Notification sent to {email}.",
            )
            return redirect("frontend:admin_users")

    search = request.GET.get("q", "").strip()
    users = User.objects.filter(deleted_at__isnull=True).order_by("name")
    if search:
        users = users.filter(Q(name__icontains=search) | Q(email__icontains=search))

    districts = District.objects.all().order_by("name")
    roles = [r.value for r in EdifyRole]

    context = {
        "users": users[:100],
        "total": users.count(),
        "search": search,
        "districts": districts,
        "available_roles": roles,
        "topbar_search": {
            "placeholder": "Search users by name, email, or role…",
            "value": search,
            "action": reverse("frontend:admin_users"),
        },
    }
    return render(request, "pages/admin/users.html", context)


@require_page_permission("users")
def admin_user_detail_view(request, user_id):
    """User detail/edit/actions."""
    from django.contrib import messages

    member = get_object_or_404(User, id=user_id, deleted_at__isnull=True)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "edit":
            email = request.POST.get("email", "").lower().strip()
            name = request.POST.get("name", "").strip()
            phone = request.POST.get("phone", "").strip()
            primary_role = request.POST.get("role")
            additional = request.POST.getlist("additional_roles")
            primary_district = request.POST.get("primary_district")
            additional_districts = request.POST.getlist("additional_districts")

            # Delegate identity/role mutation to the canonical service — it
            # holds the Admin-only guards against granting the Admin role or
            # touching another Admin's account, and self-role-change denial,
            # which a second hand-rolled copy here would silently diverge
            # from (that divergence is exactly how this hole was found).
            from apps.admin_users.services import update_user
            from apps.core.exceptions import BadRequest, ConflictError

            try:
                update_user(
                    member.id,
                    {
                        "email": email,
                        "name": name,
                        "phone": phone,
                        "role": primary_role,
                        "additionalRoles": additional,
                    },
                    request.user,
                )
            except (BadRequest, ConflictError) as exc:
                messages.error(request, str(exc.detail))
                return redirect("frontend:admin_user_detail", user_id=user_id)
            member.refresh_from_db()

            from apps.accounts.models import StaffProfile, StaffGeographyAssignment

            sp, _ = StaffProfile.objects.get_or_create(user=member)
            sp.primary_district_id = primary_district or None
            if primary_role:
                sp.title = primary_role
            sp.save()

            # Sync assignments
            selected_districts = []
            if primary_district:
                selected_districts.append(primary_district)
            for ad in additional_districts:
                if ad:
                    selected_districts.append(ad)
            selected_districts = list(dict.fromkeys(selected_districts))

            StaffGeographyAssignment.objects.filter(staff=sp).delete()
            for d_id in selected_districts:
                StaffGeographyAssignment.objects.create(staff=sp, district_id=d_id)

            messages.success(request, f"User '{member.name}' updated successfully.")

        elif action == "activate":
            from apps.admin_users.services import reactivate

            reactivate(member.id, request.user)
            member.refresh_from_db()
            messages.success(request, f"User '{member.name}' activated.")

        elif action == "deactivate":
            # Delegates to the canonical service, which also revokes live
            # refresh tokens (SEC-03 — a disabled user's refresh tokens must
            # not be able to mint new access tokens even during the window
            # before their current access token naturally expires) and
            # writes the audit event.
            from apps.admin_users.services import disable

            disable(member.id, request.user)
            member.refresh_from_db()
            messages.warning(request, f"User '{member.name}' deactivated.")

        elif action == "delete":
            from apps.admin_users.services import delete_user
            from apps.core.exceptions import BadRequest

            try:
                delete_user(member.id, request.user)
            except BadRequest as exc:
                messages.error(request, str(exc.detail))
                return redirect("frontend:admin_user_detail", user_id=user_id)
            messages.warning(
                request,
                f"User '{member.name}' deleted. Their access has been revoked; "
                "history and audit logs are retained.",
            )
            return redirect("frontend:admin_users")

        elif action == "invite":
            # Ensure email is valid and not a placeholder before sending invite
            if "pending" in member.email and "@edify.org" in member.email:
                messages.error(
                    request,
                    "Please update the placeholder email to a valid email address before sending the invitation.",
                )
                return redirect("frontend:admin_user_detail", user_id=user_id)

            from apps.admin_users.services import resend_invite

            resend_invite(member.id, request.user)
            member.status = "pending_invited"
            member.save(update_fields=["status"])
            messages.success(
                request, f"Invitation successfully sent to {member.email}."
            )

        elif action == "reset_password":
            # Setting a password IS taking the account over, so it needs the
            # same Admin-only guard the sibling "edit" action delegates to.
            # Without it any USER_MANAGE holder (CountryDirector, HR) could
            # set a password on a sitting Admin -- reproduced against the dev
            # database as hr@edify.org before this guard existed.
            from apps.admin_users.services import assert_may_administer
            from apps.core.exceptions import BadRequest

            try:
                assert_may_administer(member, request.user)
            except BadRequest as exc:
                messages.error(
                    request, str(exc.detail if hasattr(exc, "detail") else exc)
                )
                return redirect("frontend:admin_user_detail", user_id=user_id)

            new_password = request.POST.get("new_password", "").strip()
            if not new_password:
                messages.error(request, "Password cannot be empty.")
                return redirect("frontend:admin_user_detail", user_id=user_id)

            from apps.core.security import validate_password

            violations = validate_password(new_password, member.email)
            if violations:
                messages.error(request, " ".join(violations))
                return redirect("frontend:admin_user_detail", user_id=user_id)

            from django.utils import timezone

            from apps.accounts.lockout_service import AuthenticationLockoutService

            member.set_password(new_password)
            member.must_change_password = True
            member.password_set_at = timezone.now()
            member.status = "active"
            member.is_active = True
            member.save(
                update_fields=[
                    "password",
                    "must_change_password",
                    "password_set_at",
                    "status",
                    "is_active",
                ]
            )
            # Delegate lock-clearing to the ONE canonical service — an admin
            # password reset must fully clear lockout state (including
            # escalation), not just the two fields a hand-rolled reset used
            # to touch, which used to leave lockout_escalated=True accounts
            # still unable to log in after their "reset".
            AuthenticationLockoutService.admin_unlock(member.id, actor=request.user)

            # A credential reset is exactly the moment old sessions should
            # stop working — revoke live refresh tokens the same way
            # self-service reset_password and the API's force_password_reset
            # do.
            from apps.accounts.models import RefreshToken

            RefreshToken.objects.filter(
                user_id=member.id, revoked_at__isnull=True
            ).update(revoked_at=timezone.now())

            from apps.core.email import mailer

            mailer.send_password_reset_by_admin_notification(
                to=member.email, name=member.name, reset_by_name=request.user.name
            )

            from apps.audit.services import log as audit_log

            audit_log(
                action="admin.password_reset_direct",
                subject_kind="user",
                subject_id=member.id,
                actor_id=request.user.id,
                actor_role=getattr(request.user, "active_role", None),
                payload={"email": member.email},
            )
            messages.success(
                request,
                f"Password reset for '{member.name}'. They will be required to change it on next login.",
            )

        elif action == "unlock":
            from apps.accounts.lockout_service import AuthenticationLockoutService

            AuthenticationLockoutService.admin_unlock(member.id, actor=request.user)
            messages.success(request, f"Account for '{member.name}' has been unlocked.")

        elif action == "lock":
            from apps.accounts.lockout_service import AuthenticationLockoutService

            reason = request.POST.get("reason", "").strip()
            AuthenticationLockoutService.admin_lock(
                member.id, actor=request.user, reason=reason
            )
            messages.success(request, f"Account for '{member.name}' has been locked.")

        return redirect("frontend:admin_user_detail", user_id=user_id)

    # Get available roles & districts
    from apps.core.rbac import EdifyRole
    from apps.geography.models import District
    from apps.accounts.models import StaffProfile, StaffGeographyAssignment

    roles = [r.value for r in EdifyRole]
    districts = District.objects.all().order_by("name")

    sp = StaffProfile.objects.filter(user=member).first()
    primary_district_id = sp.primary_district_id if sp else None
    assigned_districts = (
        list(
            StaffGeographyAssignment.objects.filter(staff=sp).values_list(
                "district_id", flat=True
            )
        )
        if sp
        else []
    )

    from django.utils import timezone

    is_locked = bool(
        member.lockout_escalated
        or (member.locked_until and member.locked_until > timezone.now())
    )

    from apps.core.navigation import get_user_role_slug

    context = {
        "member": member,
        "available_roles": roles,
        "districts": districts,
        "primary_district_id": primary_district_id,
        "assigned_districts": assigned_districts,
        "is_locked": is_locked,
        # The users page is shared with CD/HR, but deletion is Admin-only
        # (the service enforces it; this only controls the button).
        "can_delete_users": get_user_role_slug(request.user) == "ADMIN",
    }
    return render(request, "pages/admin/user_detail.html", context)


@require_page_permission("audit_log")
def audit_log_view(request):
    """Audit trail."""
    logs = AuditLog.objects.all().order_by("-created_at")[:100]
    context = {"logs": logs}
    return render(request, "pages/admin/audit_log.html", context)


@require_page_permission("settings")
def settings_view(request):
    """General settings."""
    context = {"user": request.user}
    return render(request, "pages/settings/index.html", context)


@require_page_permission("search")
def search_view(request):
    """Global search — open to every authenticated role (the topbar renders
    the search box everywhere), with each section scope-constrained:

      • Schools: same `school_queryset(scope)` the school directory applies —
        a CCEO/PL only ever matches their own portfolio, never national rows.
      • Staff: rows deep-link to /staff/<id>, which only the staff-directory
        roles (HR/PL/CD/RVP/Admin) may open — other roles get no staff section
        instead of a national staff listing.
      • Activities: reuses the canonical scope-constrained list
        (apps.activities.services.list_activities).
    """
    from apps.activities.services import list_activities

    q = request.GET.get("q", "").strip()
    results = {"schools": [], "staff": [], "activities": []}
    if q:
        scope = resolve_user_scope(request.user)
        results["schools"] = list(
            school_queryset(scope).filter(name__icontains=q, deleted_at__isnull=True)[
                :10
            ]
        )
        if RolePermissionService.can_view_page(request.user, "staff_directory"):
            results["staff"] = list(
                User.objects.filter(name__icontains=q, deleted_at__isnull=True)[:10]
            )
        results["activities"] = list(
            list_activities({}, request.user)
            .filter(Q(school__name__icontains=q) | Q(cluster__name__icontains=q))
            .select_related("school", "cluster")[:10]
        )

    context = {"q": q, "results": results, "has_results": any(results.values())}
    return render(request, "pages/search/index.html", context)


@require_page_permission("personal_time_off")
def leave_requests_view(request):
    """Redirect legacy leave requests view to new personal-time-off view."""
    from django.shortcuts import redirect

    return redirect("/personal-time-off/")


@require_page_permission("schools")
def map_view(request):
    """Geographic map — plots every IN-SCOPE school with real coordinates
    (verified SchoolGeoPoint overrides first, then upload lat/lng). The base
    queryset is scope-constrained exactly like the school directory, so a
    CCEO/PL only ever plots their own portfolio. Schools without coordinates
    are counted honestly and routed to location cleanup."""
    import json

    scope = resolve_user_scope(request.user)
    schools = list(
        school_queryset(scope)
        .filter(deleted_at__isnull=True)
        .select_related("district", "sub_county")
        .values(
            "id", "name", "latitude", "longitude", "district__name", "sub_county__name"
        )
    )
    try:
        from apps.routes.models import SchoolGeoPoint

        overrides = {
            g.school_id: (g.latitude, g.longitude) for g in SchoolGeoPoint.objects.all()
        }
    except Exception:  # noqa: BLE001
        overrides = {}

    points = []
    for s in schools:
        lat, lng = overrides.get(s["id"], (s["latitude"], s["longitude"]))
        if lat is not None and lng is not None:
            points.append(
                {
                    "name": s["name"],
                    "lat": lat,
                    "lng": lng,
                    "district": s["district__name"] or "",
                    "sub_county": s["sub_county__name"] or "",
                }
            )
    context = {
        "points_json": json.dumps(points),
        "with_coords": len(points),
        "without_coords": len(schools) - len(points),
        "total": len(schools),
    }
    return render(request, "pages/map/index.html", context)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 7 — Specialised & Legacy
# ═══════════════════════════════════════════════════════════════════════════════


@require_page_permission("planning")
def core_schools_view(request):
    """Core schools programme."""
    plans = CorePlan.objects.all().order_by("-created_at")[:50]
    context = {"plans": plans, "total": plans.count()}
    return render(request, "pages/core_schools/index.html", context)


@require_page_permission("planning")
def core_school_detail_view(request, plan_id):
    """Core school detail."""
    plan = get_object_or_404(CorePlan, id=plan_id)
    slots = CoreActivitySlot.objects.filter(core_plan=plan).order_by("sequence_number")
    context = {"plan": plan, "slots": slots}
    return render(request, "pages/core_schools/detail.html", context)


@require_page_permission("projects")
def projects_list_view(request):
    """Special Projects command center — scoped to the caller's projects.

    Every figure is computed live from the engine (Project / assignments /
    Activity / ActivityScheduleCostLine) by `dashboard_service`; no mock data.
    """
    from apps.projects.dashboard_service import get_dashboard

    context = get_dashboard(request.user, request.GET.get("project"))
    # Project creation stays on the existing governance workflow. Only roles
    # that already have create authority see a "New Project" action; everyone
    # else gets the role-appropriate "Add Eligible Schools" action.
    context["can_create_projects"] = request.user.active_role in (
        "Admin",
        "CountryDirector",
    )
    return render(request, "pages/projects/index.html", context)


@require_page_permission("projects")
def special_projects_analytics_view(request):
    """Special Project Impact Intelligence — verified SSA movement, partner
    performance, classification and recommendations, all computed live."""
    import csv

    from django.http import HttpResponse

    from apps.projects.impact_service import get_analytics

    query = {
        key: request.GET.get(key)
        for key in (
            "fy",
            "region",
            "district",
            "project",
            "partner",
            "intervention",
            "impact_status",
            "q",
        )
        if request.GET.get(key)
    }
    context = get_analytics(request.user, query)
    context["is_htmx"] = request.headers.get("HX-Request") == "true"

    export_kind = request.GET.get("export")
    if export_kind in {"csv", "snapshot"}:
        response = HttpResponse(content_type="text/csv")
        filename = (
            "special-project-impact-snapshot.csv"
            if export_kind == "snapshot"
            else "special-project-impact-matrix.csv"
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        writer = csv.writer(response)
        if export_kind == "snapshot":
            writer.writerow(
                ["Special Project Impact Snapshot", f"FY {context['selected']['fy']}"]
            )
            writer.writerow([])
            writer.writerow(["Metric", "Value", "Definition"])
            for item in context["kpis"]:
                writer.writerow([item["label"], item["value"], item["helper"]])
            writer.writerow([])
            writer.writerow(
                [
                    "Data provenance",
                    "IA-confirmed annual SSA and project-stamped verified activity workflow",
                ]
            )
        else:
            writer.writerow(
                [
                    "Project",
                    "Associated Interventions",
                    "Schools Assigned",
                    "Schools Supported",
                    "Verified Delivery Rate",
                    "Measurable Schools",
                    "Baseline Average",
                    "Latest Average",
                    "Annual SSA Delta",
                    "Impact Classification",
                    "Recommendation",
                    "Budget Used",
                    "Cost per Improved School",
                ]
            )
            for row in context["matrix"]:
                writer.writerow(
                    [
                        row["name"],
                        row["interventions"],
                        row["schools_assigned"],
                        row["schools_supported"],
                        f"{row['delivery_rate']}%",
                        row["measurable_schools"],
                        row["baseline_avg"] if row["baseline_avg"] is not None else "",
                        row["latest_avg"] if row["latest_avg"] is not None else "",
                        row["delta"] if row["delta"] is not None else "",
                        row["classification"],
                        row["recommendation"],
                        row["budget"],
                        row["cost_per_improved"],
                    ]
                )
        return response

    if context["is_htmx"]:
        return render(request, "partials/projects/analytics_workspace.html", context)
    return render(request, "pages/projects/analytics.html", context)


@require_page_permission("projects")
def special_projects_planning_view(request):
    """Special Projects Planning — coordinator-scoped project schools with
    readiness + schedule / assign-to-partner (project-stamped) actions."""
    import csv

    from django.http import HttpResponse

    from apps.projects.planning_service import get_planning

    query = {
        key: request.GET.get(key)
        for key in (
            "fy",
            "quarter",
            "region",
            "district",
            "staff",
            "project",
            "project_type",
            "partner_type",
            "activity_type",
            "tab",
            "q",
            "selected",
            "page",
            "per_page",
        )
        if request.GET.get(key)
    }
    context = get_planning(request.user, query)
    context["is_htmx"] = request.headers.get("HX-Request") == "true"

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="special-project-planning.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "School ID",
                "School",
                "Region",
                "District",
                "Project",
                "Project Type",
                "Baseline / SSA",
                "Planning Readiness",
                "Weakest Intervention",
                "SSA Average",
                "Recommended Action",
                "Partner",
            ]
        )
        for row in context["export_rows"]:
            writer.writerow(
                [
                    row["school_id"],
                    row["school_name"],
                    row["region"],
                    row["district"],
                    row["project_name"],
                    row["project_type"],
                    row["baseline_status"],
                    row["readiness"],
                    row["weakest"],
                    row["average"] if row["average"] is not None else "",
                    row["action"],
                    row["partner"],
                ]
            )
        return response

    if context["is_htmx"]:
        return render(request, "partials/projects/planning_workspace.html", context)
    return render(request, "pages/projects/planning.html", context)


@require_page_permission("projects")
def special_projects_my_plan_view(request):
    """Special-project My Plan — the coordinator's scheduled project activities
    (staff-owned actionable; partner-planned read-only monitoring)."""
    import csv

    from django.http import HttpResponse

    from apps.projects.my_plan_service import get_my_plan

    query = {
        key: request.GET.get(key)
        for key in (
            "fy",
            "quarter",
            "month",
            "week",
            "region",
            "district",
            "project",
            "partner",
            "activity_type",
            "status",
            "period",
            "q",
        )
        if request.GET.get(key)
    }
    context = get_my_plan(request.user, query)
    context["is_htmx"] = request.headers.get("HX-Request") == "true"
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="special_project_my_plan.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "Activity ID",
                "School / Cluster",
                "District",
                "Project",
                "Planned Date",
                "Purpose",
                "Partner",
                "Status",
                "Evidence",
                "Finance",
            ]
        )
        for row in (
            context["visits"] + context["trainings"] + context["partner_activities"]
        ):
            writer.writerow(
                [
                    row["id"],
                    row["school"],
                    row["district"],
                    row["project"],
                    row["planned_date"] or "",
                    row["purpose"],
                    row["partner"],
                    row["status"],
                    row["evidence"],
                    row["finance"],
                ]
            )
        return response
    if context["is_htmx"]:
        return render(request, "partials/projects/my_plan_workspace.html", context)
    return render(request, "pages/projects/my_plan.html", context)


@require_page_permission("todos")
def todos_view(request):
    """The dedicated To-Do operating queue — system-generated, role-scoped,
    auto-closing action items derived live from workflow state."""
    from apps.command_center.todo_service import get_todos

    return render(request, "pages/todos/index.html", get_todos(request.user))


@require_page_permission("fund_approvals")
def pl_fund_approvals_view(request):
    """PL Fund Approval — team-scoped fund plans derived from supervised CCEOs'
    scheduled activities. HTMX re-renders the root on filter/select/action."""
    from apps.fund_requests.pl_approval_service import get_pl_fund_approvals

    filters = {
        k: request.GET.get(k)
        for k in ("fy", "month", "cceo", "status", "q")
        if request.GET.get(k)
    }
    ctx = get_pl_fund_approvals(request.user, filters)
    if request.headers.get("HX-Target") == "fund-approval-root":
        return render(request, "partials/fund_approvals/root.html", ctx)
    return render(request, "pages/fund_approvals/index.html", ctx)


@require_page_permission("fund_approvals")
def pl_fund_detail_view(request):
    """Just the selected detail panel for a selected CCEO — a light HTMX swap so
    clicking a CCEO in the queue instantly switches the funding breakdown without
    re-rendering the whole page."""
    from apps.fund_requests.pl_approval_service import get_pl_fund_approvals

    filters = {
        k: request.GET.get(k) for k in ("fy", "month", "cceo") if request.GET.get(k)
    }
    ctx = get_pl_fund_approvals(request.user, filters)
    return render(request, "partials/fund_approvals/detail.html", ctx)


@require_page_permission("fund_approvals")
def pl_fund_return_modal_view(request):
    """The Return-for-review drawer (reason + comment)."""
    return render(
        request,
        "partials/fund_approvals/return_drawer.html",
        {
            "cceo": request.GET.get("cceo", ""),
            "name": request.GET.get("name", "this CCEO"),
            "fy": request.GET.get("fy", ""),
            "month": request.GET.get("month", ""),
            "reasons": [
                "Cost mismatch",
                "Unplanned activity included",
                "Partner visit not linked to planned school",
                "Cluster participant count missing",
                "Training cost unclear",
                "Duplicate budget line",
                "Activity date outside selected period",
                "School not assigned to this CCEO",
                "Needs plan correction",
                "Other",
            ],
        },
    )


@require_page_permission("fund_approvals")
def pl_fund_action_view(request):
    """Approve / Return / Approve-All — mutate then re-render the root."""
    from django.http import HttpResponse

    from apps.core.exceptions import BadRequest, Forbidden
    from apps.core.fy import get_operational_fy
    from apps.fund_requests import pl_approval_service as svc

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    action = request.POST.get("action")
    fy = request.POST.get("fy") or get_operational_fy()
    try:
        month = int(request.POST.get("month"))
    except (TypeError, ValueError):
        month = None
    error = None
    try:
        if action == "approve":
            svc.approve(request.user, request.POST.get("cceo"), fy, month)
        elif action == "return":
            svc.return_request(
                request.user,
                request.POST.get("cceo"),
                fy,
                month,
                {
                    "reason": request.POST.get("reason"),
                    "comment": request.POST.get("comment"),
                },
            )
        elif action == "approve_all":
            svc.approve_all_valid(request.user, fy, month)
    except (BadRequest, Forbidden) as e:
        error = str(e)

    ctx = svc.get_pl_fund_approvals(
        request.user,
        {"fy": fy, "month": month, "cceo": request.POST.get("cceo")},
    )
    ctx["action_error"] = error
    resp = render(request, "partials/fund_approvals/root.html", ctx)
    resp["HX-Trigger"] = "close-drawer"
    return resp


@require_page_permission("projects")
def project_detail_view(request, project_id):
    """Project detail."""
    project = get_object_or_404(Project, id=project_id, deleted_at__isnull=True)
    school_assignments = ProjectSchoolAssignment.objects.filter(
        project=project
    ).select_related("school")
    assigned_count = school_assignments.count()
    # NOTE: Project has no status field in the schema — the fake "Project
    # Status: Active" / "Progress Status: Ongoing" tiles that used to sit here
    # were hardcoded for every project and have been removed rather than show
    # a status that isn't real.
    kpi_strip_items = [
        {
            "label": "Assigned Schools",
            "value": str(assigned_count),
            "raw_value": assigned_count,
            "helper": "Cohort schools",
            "icon": "school",
            "variant": "primary",
        },
    ]
    context = {
        "project": project,
        "school_assignments": school_assignments,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/projects/detail.html", context)


@require_page_permission("completed_activities")
def completed_activities_view(request):
    """Completed activities history."""
    activities = (
        Activity.objects.filter(
            status="completed",
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("-updated_at")[:60]
    )
    context = {"activities": activities}
    return render(request, "pages/completed_activities/index.html", context)


@require_page_permission("quality_checks")
def quality_checks_view(request):
    """Quality checks — the CD-raised / PL-assigned flag handoff (apps.flags).
    IA/Admin get the global monitoring view; the CD sees (and raises) the
    flags they raised; the PL sees (and acts on) the flags assigned to them.
    Reuses apps.flags.services — the same logic the /api/flags/* endpoints
    use — rather than re-implementing the raise/acknowledge/resolve rules."""
    from django.contrib import messages
    from apps.flags import services as flag_services
    from apps.core.rbac import EdifyRole
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError

    role = request.user.active_role
    is_cd = role in (EdifyRole.COUNTRY_DIRECTOR.value, EdifyRole.ADMIN.value)
    is_pl = role in (EdifyRole.COUNTRY_PROGRAM_LEAD.value, EdifyRole.ADMIN.value)

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "raise":
                if not is_cd:
                    raise Forbidden("Only the Country Director may raise flags.")
                flag_services.raise_flag(
                    {
                        "assignedToUserId": request.POST.get("assigned_to_user_id"),
                        "category": request.POST.get("category", "general"),
                        "note": request.POST.get("note", ""),
                        "recommendedAction": request.POST.get("recommended_action"),
                        "priority": request.POST.get("priority", "normal"),
                        "dueDate": request.POST.get("due_date"),
                    },
                    request.user,
                )
                messages.success(
                    request, "Flag raised and assigned to the Program Lead."
                )
            elif action in ("acknowledge", "resolve"):
                flag_id = request.POST.get("flag_id")
                flag = CdFlag.objects.filter(id=flag_id).first()
                if not flag or (
                    flag.assigned_to_user_id != request.user.id
                    and role != EdifyRole.ADMIN.value
                ):
                    messages.error(
                        request, "You may only act on flags assigned to you."
                    )
                else:
                    flag_services.update_flag(
                        flag_id,
                        {"action": action, "note": request.POST.get("note")},
                        request.user,
                    )
                    messages.success(request, f"Flag {action}d.")
        except (BadRequest, Forbidden, NotFoundError) as exc:
            messages.error(request, str(exc))
        return redirect("frontend:quality_checks")

    qs = CdFlag.objects.all().order_by("-created_at")
    if role == EdifyRole.COUNTRY_DIRECTOR.value:
        qs = qs.filter(raised_by_user_id=request.user.id)
    elif role == EdifyRole.COUNTRY_PROGRAM_LEAD.value:
        qs = qs.filter(assigned_to_user_id=request.user.id)
    # IA / Admin: unfiltered — the global monitoring audience.

    context = {
        "flags": qs[:50],
        "can_raise": is_cd,
        "can_act": is_pl,
        "program_leads": flag_services.program_leads(request.user) if is_cd else [],
        "current_user_id": request.user.id,
    }
    return render(request, "pages/quality_checks/index.html", context)


@require_page_permission("help")
def help_view(request):
    """Help centre — the operating-flow guide, role playbooks and FAQs."""
    faqs = [
        (
            "Why can't I schedule a visit in some districts?",
            "Every district must be classified primary or secondary by the CD/Admin before visits can be "
            "scheduled there — daily visit costing and route rules depend on it. Ask the CD to classify the "
            "district under Region & District Setup.",
        ),
        (
            "Why does scheduling ask me for a reason?",
            "The CD sets a required number of school visits per day. Planning fewer schools than the target "
            "raises the cost per school, so the system records your justification with the day's batch.",
        ),
        (
            "What makes a route 'Risky' or 'Not Feasible'?",
            "Route Intelligence scores each visit day 0–100 from sub-county grouping, coordinates (when they "
            "exist), the 8-hour working day, the CD daily target and district rules. Spread-out schools or an "
            "overloaded day lower the score; mixing primary and secondary districts blocks the day entirely.",
        ),
        (
            "Why is my completed activity not counted as verified?",
            "Completed work must pass IA verification (evidence review) before it counts as verified impact. "
            "Track it in My Plan; returned items show what to fix.",
        ),
        (
            "When do SSA numbers change?",
            "SSA impact is measured on verified annual cycles — the latest confirmed assessment per school "
            "compared to the previous cycle. Monthly filters only narrow operational data, never SSA movement.",
        ),
        (
            "Where does my weekly fund request go after I confirm it?",
            "CCEO requests go to your Program Lead; PL/PC/IA requests go to the Country Director. Approved "
            "requests move to the accountant for disbursement, and NetSuite accountability closes the loop.",
        ),
    ]
    return render(request, "pages/help/index.html", {"faqs": faqs})


def _humanize_rbac_token(token):
    """'budgetIntelligence' -> 'Budget Intelligence', 'resolve_duplicate' -> 'Resolve Duplicate'."""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", token).replace("_", " ").strip()
    return spaced[:1].upper() + spaced[1:] if spaced else token


@require_page_permission("roles_permissions")
def admin_roles_permissions_view(request):
    """Roles and permissions matrix, built from the real RBAC tables
    (accounts.Permission / accounts.RolePermission)."""
    from apps.accounts.models import Permission, RolePermission
    from apps.core.rbac import EdifyRole

    db_roles = set(RolePermission.objects.values_list("role", flat=True).distinct())
    # Order roles as declared in EdifyRole (Admin last); append any unknown extras.
    role_values = [r.value for r in EdifyRole if r.value in db_roles]
    role_values += sorted(db_roles - set(role_values))
    roles = [{"value": r, "label": _humanize_rbac_token(r)} for r in role_values]

    granted = set(RolePermission.objects.values_list("permission__key", "role"))

    # Group permissions by their key namespace ("school.view" -> "School").
    groups_by_prefix = {}
    for perm in Permission.objects.order_by("key"):
        prefix, _, rest = perm.key.partition(".")
        group = groups_by_prefix.setdefault(
            prefix,
            {
                "name": _humanize_rbac_token(prefix),
                "permissions": [],
            },
        )
        group["permissions"].append(
            {
                "key": perm.key,
                "label": _humanize_rbac_token(rest)
                if rest
                else _humanize_rbac_token(prefix),
                "description": perm.description,
                "grants": {r: (perm.key, r) in granted for r in role_values},
            }
        )

    permission_groups = [groups_by_prefix[p] for p in sorted(groups_by_prefix)]

    context = {
        "roles": roles,
        "permission_groups": permission_groups,
    }
    return render(request, "pages/admin/roles_permissions.html", context)


@require_page_permission("users")
def admin_staff_setup_queue_view(request):
    """Staff setup queue - matching raw uploaded staff to user profiles."""
    from apps.schools.models import School
    from apps.accounts.models import StaffProfile

    # Fetch unmatched schools
    unmatched_schools = School.objects.filter(
        account_owner_status__in=["pending", "unmatched"], deleted_at__isnull=True
    ).order_by("name")

    # Fetch available staff to match
    staff_list = StaffProfile.objects.filter(deleted_at__isnull=True).select_related(
        "user"
    )

    if request.method == "POST":
        school_id = request.POST.get("school_id")
        staff_id = request.POST.get("staff_id")
        action = request.POST.get("action")

        school = get_scoped_object_or_404(School, request.user, id=school_id)
        if action == "match" and staff_id:
            staff = get_object_or_404(StaffProfile, id=staff_id)
            school.account_owner_id = staff.id
            school.account_owner_name_raw = staff.user.name
            school.account_owner_status = "matched"
            school.save()
            from apps.accounts.models import StaffSchoolAssignment

            StaffSchoolAssignment.objects.get_or_create(
                school_id=school.id, staff=staff
            )
            from django.contrib import messages

            messages.success(
                request, f"Successfully matched '{school.name}' to {staff.user.name}."
            )
        elif action == "ignore":
            school.account_owner_status = "unmatched"
            school.save()
            from django.contrib import messages

            messages.success(request, f"Ignored matching for school '{school.name}'.")

        return redirect("/admin-panel/staff-setup-queue")

    context = {
        "unmatched_schools": unmatched_schools,
        "staff_list": staff_list,
    }
    return render(request, "pages/admin/staff_setup_queue.html", context)


@require_page_permission("upload_history")
def admin_school_upload_history_view(request):
    """School and SSA upload history batches."""
    from apps.schools.models import SchoolImportBatch, SSAImportBatch, UploadBatch

    # Flags a batch as failed/cancelled for bookkeeping only — this does NOT
    # delete or revert any School row the batch created or updated. A real
    # data-reverting rollback would need to (a) delete schools this batch
    # newly created and (b) replay SchoolChangeLog in reverse for schools it
    # updated, which is a substantial feature with real data-integrity
    # implications (cascading School-dependent records) that needs explicit
    # product scoping, not a same-turn implementation. The UI/copy here must
    # not claim more than this actually does.
    if request.method == "POST" and "rollback_id" in request.POST:
        batch_id = request.POST.get("rollback_id")
        # Try finding in both batches
        batch = (
            SchoolImportBatch.objects.filter(id=batch_id).first()
            or SSAImportBatch.objects.filter(id=batch_id).first()
            or UploadBatch.objects.filter(id=batch_id).first()
        )
        if batch:
            batch.status = "failed" if isinstance(batch, UploadBatch) else "cancelled"
            batch.save()
            from django.contrib import messages

            messages.success(
                request,
                f"Marked upload batch '{getattr(batch, 'file_name', '') or batch.id}' as failed. "
                "This flags the batch record only — schools it already created or "
                "updated are NOT reverted. Correct affected schools directly in "
                "the School Directory if needed.",
            )
        return redirect("/admin-panel/school-upload-history")

    batches = UploadBatch.objects.all().order_by("-created_at")[:50]

    context = {
        "batches": batches,
    }
    return render(request, "pages/admin/school_upload_history.html", context)


@require_page_permission("data_quality_center")
def admin_data_quality_center_view(request):
    """Data quality issues dashboard."""
    from apps.schools.models import School, DataQualityIssue, UnmatchedSSARecord

    clean_count = School.objects.filter(
        data_quality_status="Clean", deleted_at__isnull=True
    ).count()
    needs_review_count = School.objects.filter(
        data_quality_status="Needs Review", deleted_at__isnull=True
    ).count()
    needs_cleanup_count = School.objects.filter(
        data_quality_status="Needs Cleanup", deleted_at__isnull=True
    ).count()
    duplicate_risk_count = School.objects.filter(
        data_quality_status="Duplicate Risk", deleted_at__isnull=True
    ).count()
    missing_critical_count = School.objects.filter(
        data_quality_status="Missing Critical Data", deleted_at__isnull=True
    ).count()

    # Sub-queues issues
    missing_phone = DataQualityIssue.objects.filter(
        issue_type="missing_phone", status="open"
    ).select_related("school")
    missing_contact = DataQualityIssue.objects.filter(
        issue_type="missing_contact", status="open"
    ).select_related("school")
    missing_enrollment = DataQualityIssue.objects.filter(
        issue_type="missing_enrollment", status="open"
    ).select_related("school")
    no_cluster = DataQualityIssue.objects.filter(
        issue_type="no_cluster", status="open"
    ).select_related("school")
    unmatched_staff = DataQualityIssue.objects.filter(
        issue_type="unmatched_staff", status="open"
    ).select_related("school")
    no_ssa = DataQualityIssue.objects.filter(
        issue_type="no_ssa", status="open"
    ).select_related("school")
    unmatched_ssa_count = UnmatchedSSARecord.objects.filter(
        status__in=["pending", "hold"]
    ).count()

    kpi_items = [
        {
            "label": "Clean Schools",
            "value": str(clean_count),
            "helper": "Fully complete verified roster",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Needs Review",
            "value": str(needs_review_count),
            "helper": "Minor operational gaps",
            "icon": "chat",
            "variant": "info",
        },
        {
            "label": "Needs Cleanup",
            "value": str(needs_cleanup_count),
            "helper": "Moderate gaps present",
            "icon": "warning",
            "variant": "warning",
        },
        {
            "label": "Duplicate Risk",
            "value": str(duplicate_risk_count),
            "helper": "Potential duplicate entries",
            "icon": "danger",
            "variant": "danger",
        },
        {
            "label": "Missing Critical Data",
            "value": str(missing_critical_count),
            "helper": "Missing owner/cluster info",
            "icon": "danger",
            "variant": "red",
        },
    ]

    context = {
        "clean_count": clean_count,
        "needs_review_count": needs_review_count,
        "needs_cleanup_count": needs_cleanup_count,
        "duplicate_risk_count": duplicate_risk_count,
        "missing_critical_count": missing_critical_count,
        "kpi_strip_items": kpi_items,
        "missing_phone": missing_phone,
        "missing_contact": missing_contact,
        "missing_enrollment": missing_enrollment,
        "no_cluster": no_cluster,
        "unmatched_staff": unmatched_staff,
        "no_ssa": no_ssa,
        "unmatched_ssa_count": unmatched_ssa_count,
    }
    return render(request, "pages/admin/data_quality_center.html", context)


@require_page_permission("data_quality_center")
def data_quality_issue_action_view(request, issue_id):
    """Resolve or assign a single Data Quality Center issue.

    POST action=resolve -> writes status="resolved" + resolved_at (and claims
    assigned_to if nobody had it yet), audit-logged.
    POST action=assign  -> writes assigned_to=request.user.id, audit-logged.

    Returns the re-rendered row partial so the calling `hx-post` swaps the
    row in place (HTMX partial refresh) rather than reloading the page.
    Re-saving the owning School regenerates a fresh "open" issue if the
    underlying data problem is still present (see
    apps.schools.models.create_data_quality_issues) — resolving here is an
    explicit human acknowledgement, not a guarantee the data got fixed.
    """
    from django.http import HttpResponseNotAllowed
    from django.utils import timezone
    from django.db import transaction
    from apps.schools.models import DataQualityIssue
    from apps.audit.services import log as audit_log

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    issue = get_object_or_404(DataQualityIssue, id=issue_id)
    action = request.POST.get("action")
    assignee_name = None

    if action == "resolve" and issue.status == "open":
        with transaction.atomic():
            issue.status = "resolved"
            issue.resolved_at = timezone.now()
            if not issue.assigned_to:
                issue.assigned_to = str(request.user.id)
            issue.save(update_fields=["status", "resolved_at", "assigned_to"])
            audit_log(
                action="data_quality_issue.resolve",
                subject_kind="DataQualityIssue",
                subject_id=issue.id,
                actor_id=str(request.user.id),
                actor_role=getattr(request.user, "active_role", None),
                success=True,
                payload={"issue_type": issue.issue_type, "school_id": issue.school_id},
            )
    elif action == "assign" and issue.status == "open":
        with transaction.atomic():
            issue.assigned_to = str(request.user.id)
            issue.save(update_fields=["assigned_to"])
            audit_log(
                action="data_quality_issue.assign",
                subject_kind="DataQualityIssue",
                subject_id=issue.id,
                actor_id=str(request.user.id),
                actor_role=getattr(request.user, "active_role", None),
                success=True,
                payload={
                    "issue_type": issue.issue_type,
                    "school_id": issue.school_id,
                    "assigned_to": str(request.user.id),
                },
            )
        assignee_name = getattr(request.user, "name", None)

    context = {"issue": issue, "assignee_name": assignee_name}
    return render(request, "partials/data_quality/issue_row.html", context)


@require_page_permission("workflow_rules")
def admin_workflow_rules_view(request):
    """Workflow rules reference panel.

    There is no WorkflowRule model — these rules are enforced directly in code
    (apps.core.rbac / apps.activities.closure_services / apps.core.permissions),
    not as toggleable DB rows. This is intentionally a read-only reference: it
    used to offer fake toggle switches that didn't persist anything anywhere;
    that's been removed so the page stops lying about being configurable.
    """
    rules = [
        {
            "key": "clustered_before_planning",
            "label": "School must be clustered before planning",
        },
        {"key": "ssa_required", "label": "SSA required before planning"},
        {
            "key": "auto_budget_lines",
            "label": "Activity scheduling creates budget automatically",
        },
        {
            "key": "evidence_mandatory",
            "label": "Evidence attachment required before completion",
        },
        {
            "key": "sf_id_mandatory",
            "label": "Activity Salesforce ID required before IA verification",
        },
        {
            "key": "ia_before_accounts",
            "label": "IA verification required before Accounts clearance",
        },
    ]

    context = {
        "rules": rules,
    }
    return render(request, "pages/admin/workflow_rules.html", context)


@require_page_permission("page_access_matrix")
def admin_page_access_matrix_view(request):
    """Matrix displaying user page routing permissions.

    Built entirely from real data: the routed pages are discovered by walking
    the URL config for views wrapped in @require_page_permission (same
    decorator enforcing access on every request — see apps.core.permissions),
    and every cell is a live call to
    RolePermissionService.can_view_page(user, page), the same function that
    actually gates the route. No page names, role lists, or grants are
    hand-typed here, mirroring how admin_roles_permissions_view above builds
    its matrix from the real RolePermission table.
    """
    from django.urls import get_resolver
    from apps.core.rbac import EdifyRole
    from apps.core.permissions import RolePermissionService

    class _RoleProbe:
        """Minimal stand-in for a user — can_view_page only reads active_role."""

        is_authenticated = True

        def __init__(self, role):
            self.active_role = role

    def _discover_pages(patterns, prefix=""):
        found = []
        for pattern in patterns:
            full = prefix + str(pattern.pattern)
            if hasattr(pattern, "url_patterns"):
                found.extend(_discover_pages(pattern.url_patterns, full))
            else:
                page_key = getattr(
                    getattr(pattern, "callback", None), "page_permission", None
                )
                if page_key:
                    found.append((page_key, full))
        return found

    # Dedupe by page key, keeping the first (shortest-prefix) route seen for
    # display purposes.
    pages_by_key = {}
    for page_key, path in _discover_pages(get_resolver().url_patterns):
        pages_by_key.setdefault(page_key, "/" + path.lstrip("/"))

    roles = [r.value for r in EdifyRole]

    pages = [
        {"key": key, "name": _humanize_rbac_token(key), "path": path}
        for key, path in sorted(pages_by_key.items(), key=lambda kv: kv[1])
    ]

    matrix = {
        p["name"]: {
            r: RolePermissionService.can_view_page(_RoleProbe(r), p["key"])
            for r in roles
        }
        for p in pages
    }

    context = {
        "roles": roles,
        "pages": pages,
        "matrix": matrix,
    }
    return render(request, "pages/admin/page_access_matrix.html", context)


@require_page_permission("region_district_setup")
def admin_region_district_setup_view(request):
    """District/Region management page.

    Also the CD/Admin's classification surface for Daily Visit Batch costing:
    every district needs a primary/secondary district_type before staff school
    visits there can be scheduled (see apps.daily_visit_batches), and nearby
    secondary districts can only be combined on the same day's batch once
    grouped here into an approved SecondaryDistrictGroup.
    """
    from django.contrib import messages
    from apps.geography.models import (
        SecondaryDistrictGroup,
        SecondaryDistrictGroupMember,
    )

    regions = Region.objects.all().prefetch_related("districts")

    if request.method == "POST":
        action = request.POST.get("action", "create_district")

        if action == "classify_district":
            district_id = request.POST.get("district_id")
            district_type = request.POST.get("district_type")
            district = get_object_or_404(District, id=district_id)
            if district_type in ("primary", "secondary"):
                district.district_type = district_type
                district.save(update_fields=["district_type", "updated_at"])
                messages.success(
                    request, f"'{district.name}' classified as {district_type}."
                )

        elif action == "create_group":
            group_name = request.POST.get("group_name", "").strip()
            if group_name:
                SecondaryDistrictGroup.objects.get_or_create(name=group_name)
                messages.success(
                    request, f"Secondary District Group '{group_name}' created."
                )

        elif action == "add_group_member":
            group = get_object_or_404(
                SecondaryDistrictGroup, id=request.POST.get("group_id")
            )
            district = get_object_or_404(District, id=request.POST.get("district_id"))
            if district.district_type != "secondary":
                messages.error(
                    request,
                    f"'{district.name}' is not classified as secondary — classify it first.",
                )
            else:
                SecondaryDistrictGroupMember.objects.get_or_create(
                    group=group, district=district
                )
                messages.success(request, f"Added '{district.name}' to '{group.name}'.")

        elif action == "remove_group_member":
            SecondaryDistrictGroupMember.objects.filter(
                id=request.POST.get("member_id")
            ).delete()

        elif action == "approve_group":
            from django.utils import timezone as _timezone

            group = get_object_or_404(
                SecondaryDistrictGroup, id=request.POST.get("group_id")
            )
            group.status = "approved"
            group.approved_by = request.user.user_id
            group.approved_at = _timezone.now()
            group.save(
                update_fields=["status", "approved_by", "approved_at", "updated_at"]
            )
            messages.success(
                request, f"'{group.name}' approved for same-day scheduling."
            )

        else:
            district_name = request.POST.get("district_name")
            region_id = request.POST.get("region_id")
            if district_name and region_id:
                region = get_object_or_404(Region, id=region_id)
                District.objects.create(name=district_name, region=region)
                messages.success(
                    request,
                    f"Successfully created district '{district_name}' inside region '{region.name}'.",
                )

        return redirect("/admin-panel/region-district-setup")

    context = {
        "regions": regions,
        "secondary_groups": SecondaryDistrictGroup.objects.all().prefetch_related(
            "members__district"
        ),
        "secondary_districts": District.objects.filter(
            district_type="secondary"
        ).order_by("name"),
        "unclassified_count": District.objects.filter(
            district_type__isnull=True
        ).count(),
    }
    return render(request, "pages/admin/region_district_setup.html", context)


@require_page_permission("notifications_mgmt")
def admin_notifications_mgmt_view(request):
    """Notification management logs.

    Read-only log view. There used to be a POST "resend" action here, but
    apps.notifications has no send/resend/dispatch service — it only supports
    mark_read/mark_all_read/resolve on notifications a user already has. The
    fake resend button (which just flashed a success message without sending
    anything) has been removed rather than pretend to resend.
    """
    from apps.notifications.models import Notification

    logs = Notification.objects.all().order_by("-created_at")[:50]

    context = {
        "logs": logs,
    }
    return render(request, "pages/admin/notifications_mgmt.html", context)


@require_page_permission("data_quality_center")
def duplicate_review_view(request):
    from apps.schools.models import DataQualityIssue
    from django.contrib import messages

    issues = DataQualityIssue.objects.filter(
        issue_type="duplicate_risk", status="open"
    ).select_related("school")

    if request.method == "POST":
        issue_id = request.POST.get("issue_id")
        action = request.POST.get("action")
        issue = get_object_or_404(DataQualityIssue, id=issue_id) if issue_id else None

        if issue and action == "resolve_unique":
            school = issue.school
            school.duplicate_status = "not_duplicate"
            school.save()
            messages.success(
                request,
                f"School '{school.name}' marked as unique. Duplicate issue resolved.",
            )
            return redirect("/data-quality/duplicates")

    context = {
        "issues": issues,
    }
    return render(request, "pages/admin/duplicate_review.html", context)


@require_page_permission("data_quality_center")
def unmatched_ssa_queue_view(request):
    from apps.schools.models import School, UnmatchedSSARecord
    from django.contrib import messages
    from django.utils import timezone
    from apps.ssa import unmatched_service
    from apps.ssa.services import upload as upload_ssa
    from apps.core.exceptions import BadRequest

    def record_matched_ssa(rec, school):
        """Send unmatched-row resolution through the canonical SSA writer.

        This path formerly constructed ``SsaRecord`` / ``SsaScore`` rows in
        the view, which skipped score completeness, provenance, current-FY
        readiness recomputation and timezone normalisation.  Resolution is
        now an ordinary staff SSA upload with the original unmatched date and
        scores, so it agrees with every other SSA source.
        """
        return upload_ssa(
            {
                "schoolId": school.school_id,
                "dateOfSsa": rec.date_of_ssa or timezone.now().isoformat(),
                "scores": [
                    {"intervention": intervention, "score": score}
                    for intervention, score in (rec.scores or {}).items()
                ],
                "collectorType": "staff",
            },
            request.user,
        )

    if request.method == "POST":
        record_id = request.POST.get("record_id")
        action = request.POST.get("action")
        rec = get_object_or_404(UnmatchedSSARecord, id=record_id)

        if action == "match":
            school_pk = request.POST.get("school_id")
            school = get_scoped_object_or_404(
                School, request.user, id=school_pk, deleted_at__isnull=True
            )

            try:
                record_matched_ssa(rec, school)
            except BadRequest as exc:
                messages.error(request, f"Cannot match SSA record: {exc}")
                return redirect("/ssa/unmatched")

            rec.status = "matched"
            rec.save()

            messages.success(
                request, f"Successfully matched SSA report to '{school.name}'."
            )
            return redirect("/ssa/unmatched")

        elif action == "create_school":
            # Extract and create a new school record
            school_id_numeric = "".join(c for c in rec.school_id if c.isdigit())
            if not school_id_numeric:
                messages.error(
                    request,
                    "Cannot create school: raw school ID must contain numeric digits.",
                )
                return redirect("/ssa/unmatched")

            from apps.geography.models import District

            # Lookup district by name — never fall back to an arbitrary
            # District/Region row: on a sparse database that silently filed
            # the school under whichever district happened to sort first
            # (or null geography on an empty one), corrupting the directory.
            district_obj = None
            if rec.district_raw:
                district_obj = District.objects.filter(
                    name__icontains=rec.district_raw
                ).first()
            if not district_obj:
                messages.error(
                    request,
                    f"Cannot create school: district '{rec.district_raw or '—'}' "
                    "does not match any District in the directory. Create or "
                    "correct the district first, then retry.",
                )
                return redirect("/ssa/unmatched")

            region_obj = district_obj.region

            # A failed canonical SSA validation must not leave behind a
            # seemingly-onboarded school with no valid baseline record.
            try:
                with transaction.atomic():
                    school = School.objects.create(
                        school_id=school_id_numeric,
                        name=rec.school_name_raw or f"School {school_id_numeric}",
                        district=district_obj,
                        region=region_obj,
                        school_type="client",
                        current_fy_ssa_status="not_done",
                    )
                    record_matched_ssa(rec, school)
                    rec.status = "matched"
                    rec.save(update_fields=["status", "updated_at"])
            except BadRequest as exc:
                messages.error(request, f"Cannot create school from SSA record: {exc}")
                return redirect("/ssa/unmatched")

            messages.success(
                request, f"Successfully created school '{school.name}' and matched SSA."
            )
            return redirect("/ssa/unmatched")

        elif action == "hold":
            rec.status = "hold"
            rec.save()
            messages.info(request, "Unmatched SSA record held for review.")
            return redirect("/ssa/unmatched")

        elif action == "ignore":
            rec.status = "ignored"
            rec.save()
            messages.info(request, "Unmatched SSA record marked as ignored.")
            return redirect("/ssa/unmatched")

    # Suggested matches are computed ONCE at upload time (apps.ssa
    # .unmatched_service.compute_suggested_match, called from
    # apps.ssa.upload_service.import_ssa_batch) and stored on
    # UnmatchedSSARecord.suggested_school/match_confidence — no per-row
    # matching query here, just select_related (see get_unmatched_queue).
    filters = {
        "status": request.GET.get("status", ""),
        "batch": request.GET.get("batch", ""),
        "district": request.GET.get("district", ""),
        "school_id": request.GET.get("school_id", ""),
        "min_confidence": request.GET.get("min_confidence", ""),
        "date_from": request.GET.get("date_from", ""),
        "date_to": request.GET.get("date_to", ""),
    }
    try:
        page_number = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page_number = 1

    records_page = unmatched_service.get_unmatched_queue(filters, page=page_number)
    schools_list = School.objects.filter(deleted_at__isnull=True).order_by("name")

    context = {
        "records_page": records_page,
        "records": records_page.object_list,
        "schools": schools_list,
        "filters": filters,
        "batch_options": unmatched_service.batch_options(),
        "status_choices": UnmatchedSSARecord.STATUSES,
    }
    return render(request, "pages/admin/unmatched_ssa_queue.html", context)
