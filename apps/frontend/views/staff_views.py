"""
GROUP 1 — Core Operations Views
Staff Directory, Staff Profile, Today, Visits, Trainings, Evidence, Targets, My-Team, Notifications, Profile
"""

from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission
from django.db.models import Q, Count
from django.utils import timezone
from datetime import date, timedelta

from apps.accounts.models import User, StaffProfile
from apps.activities.models import Activity
from apps.evidence.models import EvidenceRecord
from apps.notifications.models import Notification
from apps.ssa.models import SsaRecord
from apps.core.fy import get_operational_fy
from apps.core.enums import EvidenceKind


# ─── STAFF DIRECTORY ──────────────────────────────────────────────────────────


@require_page_permission("staff_directory")
def staff_directory_view(request):
    """Staff directory — all users in the system with role, district, and school count."""
    get_operational_fy()
    search = request.GET.get("q", "").strip()
    active_tab = request.GET.get("tab", "all")

    staff_qs = (
        User.objects.filter(
            status="active",
            deleted_at__isnull=True,
        )
        .prefetch_related("staff_profile")
        .order_by("name")
    )

    if search:
        staff_qs = staff_qs.filter(
            Q(name__icontains=search) | Q(email__icontains=search)
        )

    if active_tab == "cceo":
        staff_qs = staff_qs.filter(roles__contains=["CCEO"])
    elif active_tab == "pl":
        staff_qs = staff_qs.filter(roles__contains=["ProgramLead"])
    elif active_tab == "admin":
        staff_qs = staff_qs.exclude(roles__contains=["CCEO"]).exclude(
            roles__contains=["ProgramLead"]
        )

    staff_list = []

    # KPIs calculation across all active staff (not filtered by tab)
    all_staff_qs = User.objects.filter(
        status="active", deleted_at__isnull=True
    ).prefetch_related("staff_profile")
    total_active = all_staff_qs.count()
    pending_onboarding = 0
    high_risk_count = 0

    # We will need to compute this during the loop, but since we are looping filtered list, we should do it separately for the full list if needed, but for performance, we can just do it on the whole list or just approximate.
    pending_onboarding = StaffProfile.objects.exclude(
        onboarding_state__in=["active", "complete"]
    ).count()

    # Coverage gap: share of active schools with no matched account owner.
    from apps.schools.models import School

    _schools_total = School.objects.filter(deleted_at__isnull=True).count()
    _schools_unowned = (
        School.objects.filter(deleted_at__isnull=True)
        .exclude(account_owner_status="matched")
        .count()
    )
    average_coverage_gap = (
        round(_schools_unowned / _schools_total * 100, 1) if _schools_total else 0
    )

    # High risk (overdue > 3) - let's count for all staff
    today = date.today()
    overdue_counts = (
        Activity.objects.filter(
            planned_date__lt=today,
            status__in=["scheduled", "started"],
            deleted_at__isnull=True,
        )
        .values("responsible_staff_id")
        .annotate(overdue_count=Count("id"))
    )
    high_risk_count = sum(1 for item in overdue_counts if item["overdue_count"] > 3)

    from apps.geography.models import District

    district_names = dict(District.objects.values_list("id", "name"))

    for u in staff_qs:
        profile = getattr(u, "staff_profile", None)
        # Count schools assigned to this staff member
        school_count = (
            Activity.objects.filter(
                responsible_staff_id=u.id,
                deleted_at__isnull=True,
                activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
            )
            .values("school_id")
            .distinct()
            .count()
        )

        completed_visits = Activity.objects.filter(
            responsible_staff_id=u.id,
            status="completed",
            activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
            deleted_at__isnull=True,
        ).count()

        staff_list.append(
            {
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "roles": u.roles or [],
                "active_role": u.active_role,
                "district": district_names.get(profile.primary_district_id, "—")
                if profile
                else "—",
                "status": u.status,
                "profile_id": profile.id if profile else None,
                "onboarding_state": getattr(profile, "onboarding_state", "unknown")
                if profile
                else "no_profile",
                "school_count": school_count,
                "completed_visits": completed_visits,
                "initials": u.name[:2].upper() if u.name else "??",
            }
        )

    kpis = {
        "total_active": total_active,
        "pending_onboarding": pending_onboarding,
        "average_coverage_gap": average_coverage_gap,
        "high_risk": high_risk_count,
    }

    context = {
        "staff": staff_list,
        "total": total_active,
        "search": search,
        "active_tab": active_tab,
        "kpis": kpis,
    }
    return render(request, "pages/staff/index.html", context)


# ─── STAFF PROFILE DETAIL ─────────────────────────────────────────────────────


@require_page_permission("staff")
def staff_profile_view(request, user_id):
    """Full staff 360° profile — activities, visits, evidence, SSA coverage."""
    member = get_object_or_404(User, id=user_id, deleted_at__isnull=True)
    get_operational_fy()
    now = date.today()

    # Activities this FY
    activities = (
        Activity.objects.filter(
            responsible_staff_id=member.id,
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("-planned_date")[:50]
    )

    completed = [a for a in activities if a.status == "completed"]
    overdue = [
        a
        for a in activities
        if a.planned_date
        and a.planned_date < now
        and a.status in ("scheduled", "started")
    ]
    upcoming = [
        a
        for a in activities
        if a.planned_date and a.planned_date >= now and a.status == "scheduled"
    ]

    # Schools covered
    schools_covered = (
        Activity.objects.filter(
            responsible_staff_id=member.id,
            status="completed",
            activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
            deleted_at__isnull=True,
        )
        .values("school_id", "school__name")
        .distinct()
    )

    profile = getattr(member, "staff_profile", None)

    from apps.schools.models import School
    from apps.ssa.services import get_ssa_progress_by_fy

    assigned_schools = School.objects.filter(
        account_owner_id=member.id, deleted_at__isnull=True
    )
    staff_progress = get_ssa_progress_by_fy(assigned_schools)

    context = {
        "member": member,
        "profile": profile,
        "activities": activities,
        "completed_count": len(completed),
        "overdue_count": len(overdue),
        "upcoming": upcoming[:5],
        "schools_covered": list(schools_covered)[:10],
        "initials": member.name[:2].upper() if member.name else "??",
        "staff_progress": staff_progress,
    }
    return render(request, "pages/staff/detail.html", context)


# ─── TODAY VIEW ───────────────────────────────────────────────────────────────


@require_page_permission("dashboard")
def today_view(request):
    """Today's command center — overdue, today, upcoming, and pending actions."""
    user = request.user
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    # Overdue activities (past due, not yet completed)
    overdue = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            planned_date__lt=today,
            status__in=["scheduled", "started"],
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("planned_date")
    )

    # Today's activities
    today_activities = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            planned_date=today,
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("activity_type")
    )

    # This week remaining
    upcoming_week = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            planned_date__range=[today + timedelta(days=1), week_end],
            status="scheduled",
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("planned_date")
    )

    # Evidence missing (completed but no evidence)
    evidence_gap = Activity.objects.filter(
        responsible_staff_id=user.id,
        status="completed",
        evidence__isnull=True,
        deleted_at__isnull=True,
    ).select_related("school")[:5]

    # Unread notifications
    notifications = Notification.objects.filter(
        recipient_id=user.id,
        status="unread",
    ).order_by("-created_at")[:5]

    context = {
        "overdue": overdue,
        "today_activities": today_activities,
        "upcoming_week": upcoming_week,
        "evidence_gap": evidence_gap,
        "notifications": notifications,
        "today": today,
        "week_start": week_start,
        "week_end": week_end,
    }
    return render(request, "pages/today/index.html", context)


# ─── VISITS LOG ───────────────────────────────────────────────────────────────


@require_page_permission("planning")
def visits_log_view(request):
    """All school visits for the current user — filterable by status."""
    user = request.user
    today = date.today()
    status_filter = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()

    VISIT_TYPES = [
        "school_visit",
        "follow_up_visit",
        "coaching_visit",
        "core_visit",
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
    ]

    visits_qs = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            activity_type__in=VISIT_TYPES,
            deleted_at__isnull=True,
        )
        .select_related("school", "school__district", "school__sub_county", "cluster")
        .order_by("-planned_date")
    )

    if status_filter:
        visits_qs = visits_qs.filter(status=status_filter)
    if search:
        visits_qs = visits_qs.filter(
            Q(school__name__icontains=search) | Q(cluster__name__icontains=search)
        )

    visits = list(visits_qs[:100])
    completed = sum(1 for v in visits if v.status == "completed")
    pending = sum(1 for v in visits if v.status in ("scheduled", "in_progress"))

    from apps.my_plan.services import serialize_activity_row
    from apps.partners.models import Partner

    partners_map = {p.id: p.name for p in Partner.objects.all()}
    users_map = {u.id: u.name for u in User.objects.all()}
    visit_rows = [
        serialize_activity_row(v, today, partners_map, users_map) for v in visits
    ]

    kpi_strip_items = [
        {
            "label": "Total Visits",
            "value": str(len(visits)),
            "raw_value": len(visits),
            "helper": "most recent 100",
            "icon": "school",
            "variant": "info",
        },
        {
            "label": "Completed",
            "value": str(completed),
            "raw_value": completed,
            "helper": "of shown visits",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Scheduled / In Progress",
            "value": str(pending),
            "raw_value": pending,
            "helper": "not yet completed",
            "icon": "clock",
            "variant": "warning",
        },
    ]

    context = {
        "visits": visit_rows,
        "total": len(visits),
        "completed": completed,
        "pending": pending,
        "status_filter": status_filter,
        "search": search,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/visits/index.html", context)


# ─── TRAININGS LOG ────────────────────────────────────────────────────────────


@require_page_permission("planning")
def trainings_log_view(request):
    """All group training sessions for the current user."""
    user = request.user
    today = date.today()
    status_filter = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()

    # Real ActivityType choices — "group_training" / "teachers_training" were
    # never valid values, so trainings silently never matched them.
    TRAINING_TYPES = [
        "training",
        "school_improvement_training",
        "cluster_training",
        "core_training",
        "cluster_training_ssa_collection",
    ]

    trainings_qs = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            activity_type__in=TRAINING_TYPES,
            deleted_at__isnull=True,
        )
        .select_related("school", "school__district", "school__sub_county", "cluster")
        .order_by("-planned_date")
    )

    if status_filter:
        trainings_qs = trainings_qs.filter(status=status_filter)
    if search:
        trainings_qs = trainings_qs.filter(
            Q(school__name__icontains=search) | Q(cluster__name__icontains=search)
        )

    trainings = list(trainings_qs[:100])
    completed = sum(1 for t in trainings if t.status == "completed")

    from apps.my_plan.services import serialize_activity_row
    from apps.partners.models import Partner

    partners_map = {p.id: p.name for p in Partner.objects.all()}
    users_map = {u.id: u.name for u in User.objects.all()}
    training_rows = [
        serialize_activity_row(t, today, partners_map, users_map) for t in trainings
    ]

    kpi_strip_items = [
        {
            "label": "Total Sessions",
            "value": str(len(trainings)),
            "raw_value": len(trainings),
            "helper": "most recent 100",
            "icon": "target",
            "variant": "info",
        },
        {
            "label": "Completed",
            "value": str(completed),
            "raw_value": completed,
            "helper": "of shown sessions",
            "icon": "check",
            "variant": "success",
        },
    ]

    context = {
        "trainings": training_rows,
        "total": len(trainings),
        "completed": completed,
        "status_filter": status_filter,
        "search": search,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/trainings/index.html", context)


# ─── EVIDENCE GALLERY ─────────────────────────────────────────────────────────


@require_page_permission("planning")
def evidence_gallery_view(request):
    """Evidence gallery — all submitted photos/reports for user's activities."""
    user = request.user
    kind_filter = request.GET.get("kind", "")

    # Get activities for this user
    user_activity_ids = Activity.objects.filter(
        responsible_staff_id=user.id,
        deleted_at__isnull=True,
    ).values_list("id", flat=True)

    evidence_qs = (
        EvidenceRecord.objects.filter(
            activity__in=user_activity_ids,
        )
        .select_related("activity", "activity__school")
        .order_by("-created_at")
    )

    if kind_filter:
        evidence_qs = evidence_qs.filter(kind=kind_filter)

    evidence_list = list(evidence_qs[:100])

    # Activities pending evidence (completed but no evidence)
    pending_evidence = Activity.objects.filter(
        responsible_staff_id=user.id,
        status="completed",
        evidence__isnull=True,
        deleted_at__isnull=True,
    ).select_related("school")[:10]

    kind_field_options = [
        {"value": "", "label": "All Kinds", "selected": not kind_filter}
    ] + [
        {"value": value, "label": label, "selected": kind_filter == value}
        for value, label in EvidenceKind.choices
    ]

    kpi_strip_items = [
        {
            "label": "Evidence Packets",
            "value": str(len(evidence_list)),
            "icon": "file",
            "variant": "info",
            "helper": "most recent 100",
        },
        {
            "label": "Pending Uploads",
            "value": str(pending_evidence.count()),
            "icon": "warning",
            "variant": "warning",
            "helper": "completed, no evidence",
        },
    ]

    context = {
        "mode": "gallery",
        "evidence_list": evidence_list,
        "pending_evidence": pending_evidence,
        "total": len(evidence_list),
        "kind_filter": kind_filter,
        "kind_field_options": kind_field_options,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/evidence/index.html", context)


# ─── MY TARGETS ───────────────────────────────────────────────────────────────


@require_page_permission("planning")
def my_targets_view(request):
    """Personal targets & KPIs for the signed-in field staff (CCEO/Program
    Lead/Project Coordinator). Every figure is a real queryset aggregate;
    annual targets come from StaffTargetProfile when CD/HR has configured
    one for this FY, and are shown as "not set" (never a guessed number)
    otherwise. Period targets are the real annual target divided evenly
    across the period — the same proportional-target convention used by
    the Analytics dashboard and Reports pages."""
    from apps.accounts.models import StaffTargetProfile
    from apps.core.scoping import resolve_user_scope
    from apps.core.fy import (
        fy_options,
        get_fy_date_range,
        get_quarter_date_range,
        get_mid_year_range,
    )

    user = request.user
    fy = request.GET.get("fy", "").strip() or get_operational_fy()
    if fy not in fy_options():
        fy = get_operational_fy()

    COMPLETED = ["completed", "ia_verified", "closed", "accountant_confirmed"]
    # Canonical activity_type values (apps.core.enums.ActivityType) — the
    # previous version of this view filtered on "group_training" and
    # "teachers_training", which are not real activity types and silently
    # matched nothing.
    VISIT_TYPES = [
        "school_visit",
        "follow_up_visit",
        "coaching_visit",
        "core_visit",
        "in_school_support",
    ]
    TRAINING_TYPES = [
        "training",
        "school_improvement_training",
        "cluster_training",
        "core_training",
    ]

    scope = resolve_user_scope(user)
    total_schools = len(scope.school_ids)

    staff_profile_id = user.staff_profile_id
    target_profile = None
    if staff_profile_id:
        target_profile = StaffTargetProfile.objects.filter(
            staff_id=staff_profile_id, fy=fy
        ).first()
    visits_target = target_profile.visits_target if target_profile else 0
    trainings_target = (
        target_profile.group_trainings_target if target_profile else 0
    ) or (target_profile.trainings_target if target_profile else 0)
    ssa_target = (target_profile.ssa_target if target_profile else 0) or total_schools

    acts = Activity.objects.filter(
        responsible_staff_id=user.id, deleted_at__isnull=True, fy=fy
    )

    # Schools with SSA done this FY (cumulative — not period-sliced)
    ssa_done = (
        SsaRecord.objects.filter(
            school_id__in=scope.school_ids,
            fy=fy,
            deleted_at__isnull=True,
        )
        .values("school_id")
        .distinct()
        .count()
    )

    # Evidence gap — completed activities with no evidence uploaded yet
    evidence_gap = acts.filter(status__in=COMPLETED, evidence__isnull=True).count()

    kpi_strip_items = [
        {
            "label": "School Visits",
            "value": f"{acts.filter(activity_type__in=VISIT_TYPES, status__in=COMPLETED).count()}"
            + (f" / {visits_target}" if visits_target else ""),
            "helper": "this FY" if visits_target else "no target set",
            "icon": "school",
            "variant": "info",
        },
        {
            "label": "Trainings Delivered",
            "value": f"{acts.filter(activity_type__in=TRAINING_TYPES, status__in=COMPLETED).count()}"
            + (f" / {trainings_target}" if trainings_target else ""),
            "helper": "this FY" if trainings_target else "no target set",
            "icon": "target",
            "variant": "warning",
        },
        {
            "label": "SSA Completed",
            "value": f"{ssa_done} / {total_schools}"
            if total_schools
            else str(ssa_done),
            "helper": "assigned schools",
            "icon": "chart",
            "variant": "success",
        },
        {
            "label": "Evidence Gap",
            "value": str(evidence_gap),
            "helper": "completed, no evidence yet",
            "icon": "warning",
            "variant": "danger" if evidence_gap else "success",
        },
    ]

    # ── Real per-period matrix (Month / Q1 / Q2 / Mid Year / Q3 / Q4 / FY) ──
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)
    ranges = {
        "month": (month_start, month_end),
        "Q1": get_quarter_date_range(fy, "Q1"),
        "Q2": get_quarter_date_range(fy, "Q2"),
        "mid": get_mid_year_range(fy),
        "Q3": get_quarter_date_range(fy, "Q3"),
        "Q4": get_quarter_date_range(fy, "Q4"),
        "fy": get_fy_date_range(fy),
    }
    period_fraction = {
        "month": 1 / 12,
        "Q1": 1 / 4,
        "Q2": 1 / 4,
        "mid": 1 / 2,
        "Q3": 1 / 4,
        "Q4": 1 / 4,
        "fy": 1,
    }
    period_labels = {
        "month": now.strftime("%b %Y"),
        "Q1": "Q1",
        "Q2": "Q2",
        "mid": "Mid Year",
        "Q3": "Q3",
        "Q4": "Q4",
        "fy": f"FY {fy}",
    }

    def _period_row(label, types, annual_target):
        row = {"area": label, "has_target": annual_target > 0}
        for key, rng in ranges.items():
            ach = acts.filter(
                activity_type__in=types, scheduled_date__range=rng, status__in=COMPLETED
            ).count()
            tgt = round(annual_target * period_fraction[key]) if annual_target else 0
            pct = round(ach / tgt * 100) if tgt else 0
            row[f"{key}_a"] = ach
            row[f"{key}_t"] = tgt
            row[f"{key}_p"] = pct
        return row

    matrix_rows = [
        _period_row("School Visits", VISIT_TYPES, visits_target),
        _period_row("Trainings Delivered", TRAINING_TYPES, trainings_target),
    ]
    active_rows = [r for r in matrix_rows if r["has_target"]]

    overall_pct = {}
    for key in ranges:
        tgt_sum = sum(r[f"{key}_t"] for r in active_rows)
        ach_sum = sum(r[f"{key}_a"] for r in active_rows)
        overall_pct[key] = round(ach_sum / tgt_sum * 100) if tgt_sum else 0

    # Trend chart — actual cumulative % vs the cumulative plan %
    trend_target_pcts = {
        "month": None,
        "Q1": 25,
        "Q2": 50,
        "mid": 50,
        "Q3": 75,
        "Q4": 100,
        "fy": 100,
    }
    trend_labels = [period_labels[k] for k in ranges]
    trend_actual = [overall_pct[k] for k in ranges]
    trend_plan = [trend_target_pcts[k] or 0 for k in ranges]
    trend_chart_has_data = bool(active_rows) and any(r["fy_a"] for r in active_rows)
    trend_chart_options = {
        "chart": {
            "type": "line",
            "height": 240,
            "toolbar": {"show": False},
            "fontFamily": "inherit",
        },
        "series": [
            {"name": "Actual %", "data": trend_actual},
            {"name": "Cumulative Plan %", "data": trend_plan},
        ],
        "stroke": {"width": [3, 2], "curve": "smooth", "dashArray": [0, 6]},
        "colors": ["#3b82f6", "#94a3b8"],
        "xaxis": {"categories": trend_labels},
        "yaxis": {"max": 100, "min": 0},
        "grid": {"borderColor": "#f1f5f9"},
        "legend": {"position": "top", "horizontalAlign": "right"},
        "dataLabels": {"enabled": False},
        "markers": {"size": 4},
        "tooltip": {"theme": "light"},
    }

    # Performance distribution donut — FY completion per tracked area
    on_track = sum(1 for r in active_rows if r["fy_p"] >= 70)
    at_risk = sum(1 for r in active_rows if 40 <= r["fy_p"] < 70)
    off_track = sum(1 for r in active_rows if r["fy_p"] < 40)
    donut_chart_has_data = bool(active_rows)
    donut_chart_options = {
        "chart": {"type": "donut", "fontFamily": "inherit"},
        "labels": ["On Track (≥70%)", "At Risk (40-69%)", "Off Track (<40%)"],
        "series": [on_track, at_risk, off_track],
        "colors": ["#10b981", "#f59e0b", "#f43f5e"],
        "legend": {"show": False},
        "dataLabels": {"enabled": False},
        "stroke": {"width": 2, "colors": ["#ffffff"]},
        "plotOptions": {
            "pie": {
                "donut": {
                    "size": "72%",
                    "labels": {
                        "show": True,
                        "total": {"show": True, "label": "Areas", "color": "#1e293b"},
                    },
                }
            }
        },
    }

    focus_areas = [
        r for r in sorted(active_rows, key=lambda r: r["fy_p"]) if r["fy_p"] < 70
    ][:2]

    if request.GET.get("export") == "csv":
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="my-targets-FY{fy}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(["My Targets Snapshot", f"FY {fy}", user.email])
        writer.writerow([])
        writer.writerow(["Metric", "Value"])
        for item in kpi_strip_items:
            writer.writerow([item["label"], item["value"]])
        writer.writerow([])
        writer.writerow(["Area"] + [f"{period_labels[k]} Sched." for k in ranges])
        for row in matrix_rows:
            writer.writerow(
                [row["area"]] + [f"{row[f'{k}_a']}/{row[f'{k}_t']}" for k in ranges]
            )
        return response

    context = {
        "fy": fy,
        "fy_options": fy_options(),
        "kpi_strip_items": kpi_strip_items,
        "matrix_rows": matrix_rows,
        "has_any_target": bool(active_rows),
        "period_labels": period_labels,
        "trend_chart_options": trend_chart_options,
        "trend_chart_has_data": trend_chart_has_data,
        "donut_chart_options": donut_chart_options,
        "donut_chart_has_data": donut_chart_has_data,
        "on_track": on_track,
        "at_risk": at_risk,
        "off_track": off_track,
        "focus_areas": focus_areas,
        "overall_fy_pct": overall_pct["fy"],
        "donut_footer_note": f"Overall FY completion: {overall_pct['fy']}%",
        "ssa_done": ssa_done,
        "ssa_target": ssa_target,
        "total_schools": total_schools,
        "evidence_gap": evidence_gap,
    }
    return render(request, "pages/targets/index.html", context)


# ─── MY TEAM (PL VIEW) ────────────────────────────────────────────────────────


@require_page_permission("my_team")
def my_team_view(request):
    """Program Lead team overview — all CCEOs under the PL with their activity stats."""
    today = date.today()

    # Get all CCEOs in the system
    cceos = User.objects.filter(
        roles__contains=["CCEO"],
        status="active",
        deleted_at__isnull=True,
    ).order_by("name")

    team_data = []
    for cceo in cceos:
        completed = Activity.objects.filter(
            responsible_staff_id=cceo.id,
            status="completed",
            deleted_at__isnull=True,
        ).count()
        overdue = Activity.objects.filter(
            responsible_staff_id=cceo.id,
            planned_date__lt=today,
            status__in=["scheduled", "started"],
            deleted_at__isnull=True,
        ).count()
        evidence_gap = Activity.objects.filter(
            responsible_staff_id=cceo.id,
            status="completed",
            evidence__isnull=True,
            deleted_at__isnull=True,
        ).count()
        team_data.append(
            {
                "id": cceo.id,
                "name": cceo.name,
                "email": cceo.email,
                "initials": cceo.name[:2].upper() if cceo.name else "??",
                "completed": completed,
                "overdue": overdue,
                "evidence_gap": evidence_gap,
                "risk": "high" if overdue > 3 else "medium" if overdue > 0 else "low",
            }
        )

    total_cceos = len(team_data)
    with_overdue = sum(1 for m in team_data if m["overdue"] > 0)
    all_caught_up = total_cceos - with_overdue

    kpi_strip_items = [
        {
            "label": "Total CCEOs",
            "value": str(total_cceos),
            "raw_value": total_cceos,
            "helper": "On your team",
            "icon": "users",
            "variant": "primary",
        },
        {
            "label": "With Overdue",
            "value": str(with_overdue),
            "raw_value": with_overdue,
            "helper": "CCEOs",
            "icon": "warning",
            "variant": "danger" if with_overdue > 0 else "success",
        },
        {
            "label": "All Caught Up",
            "value": str(all_caught_up),
            "raw_value": all_caught_up,
            "helper": "CCEOs",
            "icon": "check",
            "variant": "success",
        },
    ]

    context = {
        "team": team_data,
        "total": total_cceos,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/my_team/index.html", context)


# ─── NOTIFICATIONS ────────────────────────────────────────────────────────────


@require_page_permission("dashboard")
def notification_drawer_view(request):
    """Notification drawer view — loaded via HTMX when clicking notification bell."""
    user = request.user
    notifs_qs = Notification.objects.filter(recipient_id=user.id).order_by(
        "-created_at"
    )
    notifs = list(notifs_qs[:20])  # Limit to 20 recent
    unread_count = Notification.objects.filter(
        recipient_id=user.id, status="unread"
    ).count()

    context = {
        "notifications": notifs,
        "unread_count": unread_count,
        "drawer_type": "right_top",
        "drawer_size": "sm",
    }
    return render(request, "partials/notifications/notification_drawer.html", context)


@require_page_permission("dashboard")
def mark_all_notifications_read(request):
    """Mark all unread notifications for the user as read."""
    if request.method == "POST":
        Notification.objects.filter(
            recipient_id=request.user.id, status="unread"
        ).update(
            status="read",
            read_at=timezone.now(),
        )
    if request.headers.get("HX-Request") == "true":
        user = request.user
        notifs = list(
            Notification.objects.filter(recipient_id=user.id).order_by("-created_at")[
                :20
            ]
        )
        return render(
            request,
            "partials/notifications/notification_drawer_list.html",
            {
                "notifications": notifs,
                "unread_count": 0,
            },
        )
    return redirect("/")


@require_page_permission("dashboard")
def mark_notification_read(request, notif_id):
    """Mark a single notification as read."""
    Notification.objects.filter(id=notif_id, recipient_id=request.user.id).update(
        status="read",
        read_at=timezone.now(),
    )
    if request.method == "POST" and request.headers.get("HX-Request") == "true":
        user = request.user
        notifs = list(
            Notification.objects.filter(recipient_id=user.id).order_by("-created_at")[
                :20
            ]
        )
        unread_count = Notification.objects.filter(
            recipient_id=user.id, status="unread"
        ).count()
        return render(
            request,
            "partials/notifications/notification_drawer_list.html",
            {
                "notifications": notifs,
                "unread_count": unread_count,
            },
        )

    redirect_to = request.GET.get("redirect") or request.POST.get("redirect") or "/"
    return redirect(redirect_to)


@require_page_permission("dashboard")
def notification_badge_view(request):
    """Return only the notification badge count HTML."""
    unread_count = Notification.objects.filter(
        recipient_id=request.user.id, status="unread"
    ).count()
    return render(
        request,
        "partials/notifications/notification_badge.html",
        {"unread_notifications_count": unread_count},
    )


# ─── USER PROFILE ─────────────────────────────────────────────────────────────


@require_page_permission("dashboard")
def profile_view(request):
    """User profile — role info, stats, recent activity."""
    user = request.user
    fy = get_operational_fy()

    profile = getattr(user, "staff_profile", None)

    # Activity stats
    total_activities = Activity.objects.filter(
        responsible_staff_id=user.id,
        deleted_at__isnull=True,
    ).count()
    completed = Activity.objects.filter(
        responsible_staff_id=user.id,
        status="completed",
        deleted_at__isnull=True,
    ).count()

    recent = (
        Activity.objects.filter(
            responsible_staff_id=user.id,
            deleted_at__isnull=True,
        )
        .select_related("school")
        .order_by("-updated_at")[:5]
    )

    context = {
        "member": user,
        "profile": profile,
        "fy": fy,
        "total_activities": total_activities,
        "completed": completed,
        "completion_rate": round(completed / total_activities * 100)
        if total_activities
        else 0,
        "recent": recent,
        "initials": user.name[:2].upper() if user.name else "??",
    }
    return render(request, "pages/profile/index.html", context)
