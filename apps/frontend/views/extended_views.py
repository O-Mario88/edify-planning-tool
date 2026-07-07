"""
GROUPS 4-7 — SSA/FY, Districts/Reports, Admin, Specialised Views
"""
from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission, get_scoped_object_or_404
from django.db.models import Q, Avg, Count
from django.utils import timezone
from datetime import date

from apps.ssa.models import SsaRecord
from apps.schools.models import School
from apps.activities.models import Activity
from apps.geography.models import District, Region
from apps.accounts.models import User, Leave
from apps.messaging.models import Message
from apps.debriefs.models import DailyDebrief
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.core_schools.models import CorePlan, CoreActivitySlot
from apps.audit.models import AuditLog
from apps.flags.models import CdFlag
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — SSA, FY & Planning
# ═══════════════════════════════════════════════════════════════════════════════

@require_page_permission("ssa")
def ssa_master_view(request):
    """SSA master view — scores overview across all schools."""
    fy = get_operational_fy()
    search = request.GET.get("q", "").strip()

    records = SsaRecord.objects.filter(fy=fy, deleted_at__isnull=True).select_related("school").order_by("average_score")
    if search:
        records = records.filter(school__name__icontains=search)

    records_list = list(records[:100])
    avg_score = sum(r.average_score or 0 for r in records_list) / max(len(records_list), 1)
    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    schools_with_ssa = records.values("school_id").distinct().count()

    context = {
        "records": records_list,
        "avg_score": round(avg_score, 2),
        "total_schools": total_schools,
        "schools_with_ssa": schools_with_ssa,
        "fy": fy,
        "search": search,
    }
    return render(request, "pages/ssa/index.html", context)


@require_page_permission("planning")
def fy_overview_view(request):
    """Fiscal year overview — planning status, readiness, and timeline."""
    fy = get_operational_fy()

    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    ssa_done = SsaRecord.objects.filter(fy=fy, deleted_at__isnull=True).values("school_id").distinct().count()
    total_activities = Activity.objects.filter(deleted_at__isnull=True).count()
    completed_activities = Activity.objects.filter(status="completed", deleted_at__isnull=True).count()

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


@require_page_permission("planning")
def calendar_view(request):
    """Activity calendar — all scheduled activities for the current month."""
    user = request.user
    month = int(request.GET.get("month", date.today().month))
    year = int(request.GET.get("year", date.today().year))

    activities = Activity.objects.filter(
        planned_date__year=year,
        planned_date__month=month,
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("planned_date")

    if user.active_role == "CCEO":
        activities = activities.filter(responsible_staff_id=user.id)

    import calendar
    cal = calendar.monthcalendar(year, month)
    month_name = calendar.month_name[month]

    context = {
        "activities": activities,
        "calendar_weeks": cal,
        "month": month,
        "year": year,
        "month_name": month_name,
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

    activities_qs = Activity.objects.filter(deleted_at__isnull=True).select_related("school", "cluster")
    if user.active_role == "CCEO":
        activities_qs = activities_qs.filter(responsible_staff_id=user.id)

    monthly_summary = activities_qs.values("planned_date__month").annotate(
        total=Count("id"),
        completed=Count("id", filter=Q(status="completed")),
    ).order_by("planned_date__month")

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

        district_data.append({
            "id": d.id,
            "name": d.name,
            "region": d.region.name if d.region else "—",
            "school_count": school_count,
            "avg_ssa": round(avg_ssa, 2) if avg_ssa else None,
        })

    context = {"districts": district_data, "total": len(district_data), "search": search}
    return render(request, "pages/districts/index.html", context)


@require_page_permission("planning")
def district_detail_view(request, district_id):
    """District detail — schools, SSA, and activities."""
    district = get_object_or_404(District, id=district_id)
    fy = get_operational_fy()
    schools = School.objects.filter(district=district, deleted_at__isnull=True).order_by("name")
    from apps.ssa.services import get_ssa_progress_by_fy
    district_progress = get_ssa_progress_by_fy(schools)

    context = {
        "district": district,
        "schools": schools,
        "total_schools": schools.count(),
        "district_progress": district_progress,
    }
    return render(request, "pages/districts/detail.html", context)


@require_page_permission("planning")
def reports_view(request):
    """Reports overview — all roles. Every figure is computed from live
    activity data for the selected FY (achieved = completed vs scheduled)."""
    import csv
    from django.http import HttpResponse as _HttpResponse
    from apps.core.fy import (
        fy_options, get_fy_date_range, get_quarter_date_range,
        get_mid_year_range, get_quarter_for_date, get_cumulative_target_percentage,
    )

    fy = request.GET.get("fy", "").strip() or get_operational_fy()
    if fy not in fy_options():
        fy = get_operational_fy()

    COMPLETED = ["completed", "ia_verified", "closed"]
    AREAS = [
        ("Schools Visited", ["school_visit", "follow_up_visit", "coaching_visit", "core_visit", "in_school_support"]),
        ("Trainings Delivered", ["training", "school_improvement_training", "cluster_training"]),
        ("SSA Activities", ["ssa_activity"]),
        ("Cluster Meetings", ["cluster_meeting"]),
        ("Partner Activities", ["partner_activity"]),
        ("Project Activities", ["project_activity"]),
    ]

    acts = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start.month == 12:
        month_end = month_start.replace(year=month_start.year + 1, month=1)
    else:
        month_end = month_start.replace(month=month_start.month + 1)

    fy_range = get_fy_date_range(fy)
    ranges = {
        "month": (month_start, month_end),
        "Q1": get_quarter_date_range(fy, "Q1"),
        "Q2": get_quarter_date_range(fy, "Q2"),
        "Q3": get_quarter_date_range(fy, "Q3"),
        "Q4": get_quarter_date_range(fy, "Q4"),
        "mid": get_mid_year_range(fy),
        "fy": fy_range,
    }

    def _counts(types, key):
        rng = ranges[key]
        qs = acts.filter(activity_type__in=types, scheduled_date__range=rng)
        total = qs.count()
        achieved = qs.filter(status__in=COMPLETED).count()
        pct = round(achieved / total * 100) if total else 0
        return total, achieved, pct

    def _pct_color(pct):
        if pct >= 70:
            return "text-emerald-600"
        if pct >= 50:
            return "text-amber-600"
        return "text-rose-600"

    matrix_rows = []
    for label, types in AREAS:
        m_t, m_a, m_p = _counts(types, "month")
        q1_t, q1_a, q1_p = _counts(types, "Q1")
        q2_t, q2_a, q2_p = _counts(types, "Q2")
        mid_t, mid_a, mid_p = _counts(types, "mid")
        q3_t, q3_a, q3_p = _counts(types, "Q3")
        q4_t, q4_a, q4_p = _counts(types, "Q4")
        fy_t, fy_a, fy_p = _counts(types, "fy")
        matrix_rows.append({
            "area": label,
            "m_t": m_t, "m_a": m_a, "m_p": m_p, "m_c": _pct_color(m_p),
            "q1_t": q1_t, "q1_a": q1_a, "q1_p": q1_p, "q1_c": _pct_color(q1_p),
            "q2_t": q2_t, "q2_a": q2_a, "q2_p": q2_p, "q2_c": _pct_color(q2_p),
            "mid_t": mid_t, "mid_a": mid_a, "mid_p": mid_p, "mid_c": _pct_color(mid_p),
            "q3_t": q3_t, "q3_a": q3_a, "q3_p": q3_p, "q3_c": _pct_color(q3_p),
            "q4_t": q4_t, "q4_a": q4_a, "q4_p": q4_p, "q4_c": _pct_color(q4_p),
            "fy_t": fy_t, "fy_a": fy_a, "fy_p": fy_p, "fy_c": _pct_color(fy_p),
        })

    if request.GET.get("export") == "csv":
        response = _HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="edify-performance-report-FY{fy}.csv"'
        writer = csv.writer(response)
        writer.writerow(["Target Area"] + [
            f"{p} {c}" for p in ["This Month", "Q1 (Oct-Dec)", "Q2 (Jan-Mar)", "Mid Year", "Q3 (Apr-Jun)", "Q4 (Jul-Sep)", f"FY {fy}"]
            for c in ["Target", "Achieved", "%"]
        ])
        for r in matrix_rows:
            writer.writerow([
                r["area"],
                r["m_t"], r["m_a"], r["m_p"],
                r["q1_t"], r["q1_a"], r["q1_p"],
                r["q2_t"], r["q2_a"], r["q2_p"],
                r["mid_t"], r["mid_a"], r["mid_p"],
                r["q3_t"], r["q3_a"], r["q3_p"],
                r["q4_t"], r["q4_a"], r["q4_p"],
                r["fy_t"], r["fy_a"], r["fy_p"],
            ])
        return response

    def _overall(key):
        rng = ranges[key]
        qs = acts.filter(scheduled_date__range=rng)
        total = qs.count()
        achieved = qs.filter(status__in=COMPLETED).count()
        pct = round(achieved / total * 100) if total else 0
        return total, achieved, pct

    current_q = get_quarter_for_date(now)
    q_labels = {"Q1": "Q1 (Oct – Dec)", "Q2": "Q2 (Jan – Mar)", "Q3": "Q3 (Apr – Jun)", "Q4": "Q4 (Jul – Sep)"}
    period_defs = [
        ("month", now.strftime("%B %Y"), "Monthly", "text-blue-500", True),
        ("Q1", q_labels["Q1"], "Quarter 1", "text-emerald-500", True),
        ("Q2", q_labels["Q2"], "Quarter 2", "text-blue-500", True),
        ("mid", "Mid Year (Oct – Mar)", "Cumulative", "text-violet-500", True),
        ("Q3", q_labels["Q3"], "Quarter 3", "text-teal-500", True),
        ("Q4", q_labels["Q4"], "Quarter 4", "text-slate-400", True),
        ("fy", f"FY {fy}", "Full Year", "text-indigo-600", True),
    ]
    quarter_order = ["Q1", "Q2", "Q3", "Q4"]
    periods = []
    for key, label, sublabel, color, _ in period_defs:
        total, achieved, pct = _overall(key)
        started = True
        if key in quarter_order:
            started = quarter_order.index(key) <= quarter_order.index(current_q)
        periods.append({
            "key": key, "label": label, "sublabel": sublabel, "color": color,
            "total": total, "achieved": achieved, "pct": pct,
            "status": ("On Track" if pct >= 70 else "In Progress") if started and total else ("Not Started" if not achieved else "In Progress"),
            "dim": key in quarter_order and not started,
        })
    overall = {p["key"]: p for p in periods}

    core_cards = []
    for r in matrix_rows:
        core_cards.append({
            "label": r["area"],
            "value": f"{r['fy_a']} / {r['fy_t']}",
            "pct": r["fy_p"],
            "color": _pct_color(r["fy_p"]).replace("emerald", "blue"),
        })

    # Donut: how many target areas are on/at-risk/off track for the FY
    active_rows = [r for r in matrix_rows if r["fy_t"] > 0]
    donut_on = sum(1 for r in active_rows if r["fy_p"] >= 70)
    donut_risk = sum(1 for r in active_rows if 50 <= r["fy_p"] < 70)
    donut_off = sum(1 for r in active_rows if r["fy_p"] < 50)
    donut_total = len(active_rows)

    def _dpct(n):
        return round(n / donut_total * 100) if donut_total else 0

    donut = {
        "total": donut_total,
        "on": donut_on, "on_pct": _dpct(donut_on),
        "risk": donut_risk, "risk_pct": _dpct(donut_risk),
        "off": donut_off, "off_pct": _dpct(donut_off),
        "risk_offset": -_dpct(donut_on),
        "off_offset": -(_dpct(donut_on) + _dpct(donut_risk)),
    }

    # Priorities: worst areas by FY completion (only areas with scheduled work)
    priorities = []
    for r in sorted(active_rows, key=lambda x: x["fy_p"])[:4]:
        if r["fy_p"] < 50:
            status, status_class = "Off Track", "bg-rose-50 text-rose-700 border-rose-200"
        elif r["fy_p"] < 70:
            status, status_class = "At Risk", "bg-amber-50 text-amber-700 border-amber-200"
        else:
            status, status_class = "On Track", "bg-emerald-50 text-emerald-700 border-emerald-200"
        priorities.append({
            "title": r["area"],
            "desc": f"{r['fy_a']} of {r['fy_t']} scheduled completed ({r['fy_p']}%).",
            "status": status,
            "status_class": status_class,
        })

    # Cumulative trend chart points (SVG viewBox 600x200; y: 190=0%, 10=100%)
    trend_keys = [("month", now.strftime("%b")), ("Q1", "Q1"), ("Q2", "Q2"), ("mid", "Mid Year"), ("Q3", "Q3"), ("Q4", "Q4"), ("fy", "FY")]
    target_pcts = {"month": None, "Q1": 25, "Q2": 50, "mid": 50, "Q3": 75, "Q4": 100, "fy": 100}
    trend = []
    xs = [40, 125, 210, 295, 380, 465, 550]
    for (key, short), x in zip(trend_keys, xs):
        pct = overall[key]["pct"]
        tgt = target_pcts[key] if target_pcts[key] is not None else get_cumulative_target_percentage("FY")
        trend.append({
            "x": x,
            "y": round(190 - pct * 1.8),
            "ty": round(190 - tgt * 1.8),
            "label": f"{short} ({pct}%)",
        })
    trend_actual_points = " ".join(f"{t['x']},{t['y']}" for t in trend)
    trend_target_points = " ".join(f"{t['x']},{t['ty']}" for t in trend)

    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    total_activities = acts.count()
    completed = acts.filter(status__in=COMPLETED).count()

    context = {
        "fy": fy,
        "fy_options": fy_options(),
        "total_schools": total_schools,
        "total_activities": total_activities,
        "completed": completed,
        "completion_rate": round(completed / total_activities * 100) if total_activities else 0,
        "periods": periods,
        "current_month_label": now.strftime("%B %Y"),
        "q_labels": q_labels,
        "monthly_pct": overall["month"]["pct"],
        "q1_pct": overall["Q1"]["pct"],
        "q2_pct": overall["Q2"]["pct"],
        "mid_pct": overall["mid"]["pct"],
        "q3_pct": overall["Q3"]["pct"],
        "q4_pct": overall["Q4"]["pct"],
        "fy_pct": overall["fy"]["pct"],
        "core_cards": core_cards,
        "matrix_rows": matrix_rows,
        "donut": donut,
        "priorities": priorities,
        "trend": trend,
        "trend_actual_points": trend_actual_points,
        "trend_target_points": trend_target_points,
    }
    return render(request, "pages/reports/index.html", context)


@require_page_permission("planning")
def coverage_view(request):
    """Coverage overview — CD/IA."""
    fy = get_operational_fy()
    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    visited = Activity.objects.filter(
        activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
        status="completed",
        deleted_at__isnull=True,
    ).values("school_id").distinct().count()

    clusters = Cluster.objects.filter(deleted_at__isnull=True).annotate(
        school_count=Count("assignments", distinct=True),
    ).order_by("name")

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
    user_count = User.objects.filter(deleted_at__isnull=True).count()
    active_users = User.objects.filter(status="active", deleted_at__isnull=True).count()

    context = {
        "user_count": user_count,
        "active_users": active_users,
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
            email = request.POST.get("email", "").lower().strip()
            name = request.POST.get("name", "").strip()
            phone = request.POST.get("phone", "").strip()
            role = request.POST.get("role")
            additional = request.POST.getlist("additional_roles")
            district_id = request.POST.get("primary_district")
            
            if not email or not name or not role:
                messages.error(request, "Name, email, and primary role are required.")
                return redirect("frontend:admin_users")
                
            if User.objects.filter(email=email, deleted_at__isnull=True).exists():
                messages.error(request, "A user with this email already exists.")
                return redirect("frontend:admin_users")
                
            with transaction.atomic():
                user = User.objects.create_user(
                    email=email,
                    name=name,
                    phone=phone,
                    roles=list(dict.fromkeys([role, *additional])),
                    active_role=role,
                    password=None,
                    status="pending_invited",
                    is_active=False
                )
                if district_id:
                    from apps.accounts.models import StaffProfile
                    StaffProfile.objects.create(user=user, primary_district_id=district_id, title=role)
                else:
                    from apps.accounts.models import StaffProfile
                    StaffProfile.objects.create(user=user, title=role)
                    
                # Create invite
                from apps.admin_users.services import _create_invitation
                from apps.core.email import mailer
                token = _create_invitation(user.id, request.user.id)
                mailer.send_invitation(to=email, name=name, invited_by_name=request.user.name, token=token)
                
            messages.success(request, f"User '{name}' successfully created and invitation sent to {email}.")
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
    }
    return render(request, "pages/admin/users.html", context)


@require_page_permission("users")
def admin_user_detail_view(request, user_id):
    """User detail/edit/actions."""
    from django.contrib import messages
    member = get_object_or_404(User, id=user_id)
    
    if request.method == "POST":
        action = request.POST.get("action")
        
        if action == "edit":
            email = request.POST.get("email", "").lower().strip()
            name = request.POST.get("name", "").strip()
            phone = request.POST.get("phone", "").strip()
            primary_role = request.POST.get("role")
            additional = request.POST.getlist("additional_roles")
            
            # Uniqueness check
            if email and email != member.email:
                if User.objects.filter(email=email, deleted_at__isnull=True).exclude(id=member.id).exists():
                    messages.error(request, "A user with this email already exists.")
                    return redirect("frontend:admin_user_detail", user_id=user_id)
                member.email = email
                
            if name:
                member.name = name
            member.phone = phone
            
            if primary_role:
                member.roles = list(dict.fromkeys([primary_role, *additional]))
                member.active_role = primary_role
                from apps.accounts.models import StaffProfile
                sp = StaffProfile.objects.filter(user=member).first()
                if sp:
                    sp.title = primary_role
                    sp.save(update_fields=["title"])
                    
            member.save()
            messages.success(request, f"User '{member.name}' updated successfully.")
            
        elif action == "activate":
            member.status = "active"
            member.is_active = True
            member.save(update_fields=["status", "is_active"])
            messages.success(request, f"User '{member.name}' activated.")
            
        elif action == "deactivate":
            member.status = "disabled"
            member.is_active = False
            member.save(update_fields=["status", "is_active"])
            messages.warning(request, f"User '{member.name}' deactivated.")
            
        elif action == "delete":
            member.soft_delete()
            messages.error(request, f"User '{member.name}' deleted.")
            return redirect("frontend:admin_users")
            
        elif action == "invite":
            # Send invite
            from apps.admin_users.services import _create_invitation
            from apps.core.email import mailer
            
            # Ensure email is valid and not a placeholder before sending invite
            if "pending" in member.email and "@edify.org" in member.email:
                messages.error(request, "Please update the placeholder email to a valid email address before sending the invitation.")
                return redirect("frontend:admin_user_detail", user_id=user_id)
                
            token = _create_invitation(member.id, request.user.id)
            mailer.send_invitation(to=member.email, name=member.name, invited_by_name=request.user.name, token=token)
            
            member.status = "pending_invited"
            member.save(update_fields=["status"])
            messages.success(request, f"Invitation successfully sent to {member.email}.")
            
        return redirect("frontend:admin_user_detail", user_id=user_id)
        
    # Get available roles
    from apps.core.rbac import EdifyRole
    roles = [r.value for r in EdifyRole]
    
    context = {
        "member": member,
        "available_roles": roles,
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


@require_page_permission("planning")
def search_view(request):
    """Global search."""
    q = request.GET.get("q", "").strip()
    results = {"schools": [], "staff": [], "activities": []}
    if q:
        results["schools"] = list(School.objects.filter(name__icontains=q, deleted_at__isnull=True)[:10])
        results["staff"] = list(User.objects.filter(name__icontains=q, deleted_at__isnull=True)[:10])
        results["activities"] = list(Activity.objects.filter(
            Q(school__name__icontains=q) | Q(cluster__name__icontains=q),
            deleted_at__isnull=True,
        ).select_related("school")[:10])

    context = {"q": q, "results": results, "has_results": any(results.values())}
    return render(request, "pages/search/index.html", context)


@require_page_permission("messages")
def messages_list_view(request):
    """Messages inbox."""
    user = request.user
    messages_qs = Message.objects.filter(
        Q(sender_id=user.id) | Q(recipient_id=user.id)
    ).order_by("-created_at")[:50]

    context = {"messages": messages_qs}
    return render(request, "pages/messages/index.html", context)


@require_page_permission("messages")
def message_detail_view(request, message_id):
    """Message thread."""
    msg = get_object_or_404(Message, id=message_id)
    context = {"message": msg}
    return render(request, "pages/messages/detail.html", context)


@require_page_permission("staff")
def leave_requests_view(request):
    """Leave requests."""
    profile = getattr(request.user, "staff_profile", None)
    leaves = Leave.objects.filter(staff=profile).order_by("-created_at") if profile else Leave.objects.none()
    context = {"leaves": leaves}
    return render(request, "pages/leave/index.html", context)


@require_page_permission("planning")
def map_view(request):
    """Geographic coverage map — live region/district rollups plus a
    library-free scatter for schools that have coordinates."""
    from apps.geography.models import Region

    live = School.objects.filter(deleted_at__isnull=True)
    regions = []
    region_rows = Region.objects.order_by("name")
    for r in region_rows:
        districts = []
        d_rows = r.districts.annotate(
            school_count=Count("schools", filter=Q(schools__deleted_at__isnull=True)),
            ssa_avg=Avg("schools__ssa_records__average_score", filter=Q(
                schools__deleted_at__isnull=True,
                schools__ssa_records__deleted_at__isnull=True,
                schools__ssa_records__verification_status="confirmed",
            )),
        ).filter(school_count__gt=0).order_by("name")
        for d in d_rows:
            avg = round(d.ssa_avg, 1) if d.ssa_avg is not None else None
            if avg is None:
                band = "bg-slate-100 text-slate-500"
            elif avg < 5:
                band = "bg-rose-50 text-rose-700"
            elif avg < 7:
                band = "bg-amber-50 text-amber-700"
            else:
                band = "bg-emerald-50 text-emerald-700"
            districts.append({"name": d.name, "school_count": d.school_count, "ssa_avg": avg, "band": band})
        if districts:
            regions.append({
                "name": r.name,
                "school_count": sum(d["school_count"] for d in districts),
                "districts": districts,
            })

    # Geocoded pins (scaled into a 800x600 canvas)
    coords = list(live.exclude(latitude__isnull=True).exclude(longitude__isnull=True)
                  .values("name", "latitude", "longitude")[:500])
    pins = []
    if coords:
        lats = [c["latitude"] for c in coords]
        lngs = [c["longitude"] for c in coords]
        lat_min, lat_max = min(lats), max(lats)
        lng_min, lng_max = min(lngs), max(lngs)
        lat_span = (lat_max - lat_min) or 1
        lng_span = (lng_max - lng_min) or 1
        for c in coords:
            pins.append({
                "name": c["name"],
                "x": round(40 + (c["longitude"] - lng_min) / lng_span * 720),
                "y": round(40 + (lat_max - c["latitude"]) / lat_span * 520),
            })

    context = {
        "regions": regions,
        "pins": pins,
        "total_schools": live.count(),
        "geocoded_count": len(coords),
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
    slots = CoreActivitySlot.objects.filter(core_plan=plan).order_by("slot_number")
    context = {"plan": plan, "slots": slots}
    return render(request, "pages/core_schools/detail.html", context)


@require_page_permission("planning")
def projects_list_view(request):
    """Projects list."""
    projects = Project.objects.filter(deleted_at__isnull=True).order_by("name")
    context = {"projects": projects}
    return render(request, "pages/projects/index.html", context)


@require_page_permission("planning")
def project_detail_view(request, project_id):
    """Project detail."""
    project = get_object_or_404(Project, id=project_id, deleted_at__isnull=True)
    school_assignments = ProjectSchoolAssignment.objects.filter(project=project).select_related("school")
    assigned_count = school_assignments.count()
    kpi_strip_items = [
        {
            "label": "Assigned Schools",
            "value": str(assigned_count),
            "raw_value": assigned_count,
            "helper": "Cohort schools",
            "icon": "school",
            "variant": "primary",
        },
        {
            "label": "Project Status",
            "value": "Active",
            "raw_value": 1,
            "helper": "Execution",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Progress Status",
            "value": "Ongoing",
            "raw_value": 0,
            "helper": "Active tracking",
            "icon": "chart",
            "variant": "info",
        }
    ]
    context = {
        "project": project,
        "school_assignments": school_assignments,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/projects/detail.html", context)


@require_page_permission("debriefs_list")
def debriefs_list_view(request):
    """Debriefs list."""
    debriefs = DailyDebrief.objects.filter(deleted_at__isnull=True).order_by("-created_at")[:50]
    context = {"debriefs": debriefs}
    return render(request, "pages/debriefs/index.html", context)


@require_page_permission("debrief_detail")
def debrief_detail_view(request, debrief_id):
    """Debrief detail."""
    debrief = get_object_or_404(DailyDebrief, id=debrief_id)
    context = {"debrief": debrief}
    return render(request, "pages/debriefs/detail.html", context)


@require_page_permission("planning")
def completed_activities_view(request):
    """Completed activities history."""
    activities = Activity.objects.filter(
        status="completed",
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("-updated_at")[:60]
    context = {"activities": activities}
    return render(request, "pages/completed_activities/index.html", context)


@require_page_permission("quality_checks")
def quality_checks_view(request):
    """Quality checks — IA role."""
    flags = CdFlag.objects.all().order_by("-created_at")[:50]
    context = {"flags": flags}
    return render(request, "pages/quality_checks/index.html", context)


@require_page_permission("help")
def help_view(request):
    """Help centre home."""
    context = {}
    return render(request, "pages/help/index.html", context)


@require_page_permission("roles_permissions")
def admin_roles_permissions_view(request):
    """Roles and permissions matrix — rendered from the canonical RBAC
    matrix (apps.core.rbac.ROLE_PERMISSIONS), the same source enforcement uses."""
    from apps.core.rbac import EdifyRole, Permission, ROLE_PERMISSIONS

    roles = [r.value for r in EdifyRole]
    granted = {role.value: {p.value for p in perms} for role, perms in ROLE_PERMISSIONS.items()}

    matrix = {}
    for perm in Permission:
        matrix[perm.value] = {r: perm.value in granted.get(r, set()) for r in roles}

    context = {
        "roles": roles,
        "permission_groups": [p.value for p in Permission],
        "matrix": matrix,
    }
    return render(request, "pages/admin/roles_permissions.html", context)


@require_page_permission("users")
def admin_staff_setup_queue_view(request):
    """Staff setup queue - matching raw uploaded staff to user profiles."""
    from apps.schools.models import School
    from apps.accounts.models import StaffProfile
    
    # Fetch unmatched schools
    unmatched_schools = School.objects.filter(
        account_owner_status__in=["pending", "unmatched"],
        deleted_at__isnull=True
    ).order_by("name")

    # Fetch available staff to match
    staff_list = StaffProfile.objects.filter(deleted_at__isnull=True).select_related("user")

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
            StaffSchoolAssignment.objects.get_or_create(school_id=school.id, staff=staff)
            from django.contrib import messages
            messages.success(request, f"Successfully matched '{school.name}' to {staff.user.name}.")
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
    
    # Process simulated rollback action
    if request.method == "POST" and "rollback_id" in request.POST:
        batch_id = request.POST.get("rollback_id")
        # Try finding in both batches
        batch = SchoolImportBatch.objects.filter(id=batch_id).first() or \
                SSAImportBatch.objects.filter(id=batch_id).first() or \
                UploadBatch.objects.filter(id=batch_id).first()
        if batch:
            batch.status = "failed" if isinstance(batch, UploadBatch) else "cancelled"
            batch.save()
            from django.contrib import messages
            messages.success(request, f"Successfully rolled back upload batch '{getattr(batch, 'file_name', '') or batch.id}'.")
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
    
    clean_count = School.objects.filter(data_quality_status="Clean", deleted_at__isnull=True).count()
    needs_review_count = School.objects.filter(data_quality_status="Needs Review", deleted_at__isnull=True).count()
    needs_cleanup_count = School.objects.filter(data_quality_status="Needs Cleanup", deleted_at__isnull=True).count()
    duplicate_risk_count = School.objects.filter(data_quality_status="Duplicate Risk", deleted_at__isnull=True).count()
    missing_critical_count = School.objects.filter(data_quality_status="Missing Critical Data", deleted_at__isnull=True).count()

    # Sub-queues issues
    missing_phone = DataQualityIssue.objects.filter(issue_type="missing_phone", status="open").select_related("school")
    missing_contact = DataQualityIssue.objects.filter(issue_type="missing_contact", status="open").select_related("school")
    missing_enrollment = DataQualityIssue.objects.filter(issue_type="missing_enrollment", status="open").select_related("school")
    no_cluster = DataQualityIssue.objects.filter(issue_type="no_cluster", status="open").select_related("school")
    unmatched_staff = DataQualityIssue.objects.filter(issue_type="unmatched_staff", status="open").select_related("school")
    no_ssa = DataQualityIssue.objects.filter(issue_type="no_ssa", status="open").select_related("school")
    unmatched_ssa_count = UnmatchedSSARecord.objects.filter(status__in=["pending", "hold"]).count()

    context = {
        "clean_count": clean_count,
        "needs_review_count": needs_review_count,
        "needs_cleanup_count": needs_cleanup_count,
        "duplicate_risk_count": duplicate_risk_count,
        "missing_critical_count": missing_critical_count,
        
        "missing_phone": missing_phone,
        "missing_contact": missing_contact,
        "missing_enrollment": missing_enrollment,
        "no_cluster": no_cluster,
        "unmatched_staff": unmatched_staff,
        "no_ssa": no_ssa,
        "unmatched_ssa_count": unmatched_ssa_count,
    }
    return render(request, "pages/admin/data_quality_center.html", context)


@require_page_permission("workflow_rules")
def admin_workflow_rules_view(request):
    """Workflow rules & automation toggles."""
    # Simulated rules stored in memory or db
    rules = [
        {"key": "clustered_before_planning", "label": "School must be clustered before planning", "enabled": True},
        {"key": "ssa_required", "label": "SSA required before planning", "enabled": True},
        {"key": "auto_budget_lines", "label": "Activity scheduling creates budget automatically", "enabled": True},
        {"key": "evidence_mandatory", "label": "Evidence attachment required before completion", "enabled": True},
        {"key": "sf_id_mandatory", "label": "Activity Salesforce ID required before IA verification", "enabled": False},
        {"key": "ia_before_accounts", "label": "IA verification required before Accounts clearance", "enabled": True},
    ]
    
    if request.method == "POST":
        rule_key = request.POST.get("rule_key")
        from django.contrib import messages
        messages.success(request, f"Workflow rule status updated for '{rule_key}'.")
        return redirect("/admin-panel/workflow-rules")

    context = {
        "rules": rules,
    }
    return render(request, "pages/admin/workflow_rules.html", context)


@require_page_permission("page_access_matrix")
def admin_page_access_matrix_view(request):
    """Matrix displaying user page routing permissions."""
    roles = ["CCEO", "PL", "CD", "RVP", "IA", "Accountant", "HR", "Partner", "Admin"]
    pages = [
        {"name": "Dashboard", "path": "/dashboard"},
        {"name": "School Directory", "path": "/schools"},
        {"name": "Planning Dashboard", "path": "/planning"},
        {"name": "My Plan", "path": "/my-plan"},
        {"name": "Monthly Budget Setup", "path": "/budgets/monthly"},
        {"name": "Fund Requests advance", "path": "/fund-requests"},
        {"name": "NetSuite Disbursements", "path": "/disbursements"},
        {"name": "Analytics Dashboard", "path": "/analytics"},
        {"name": "System Health", "path": "/system-health"},
        {"name": "Audit Log logs", "path": "/admin/audit-log"},
    ]
    
    matrix = {}
    for p in pages:
        matrix[p["name"]] = {}
        for r in roles:
            if r == "Admin":
                matrix[p["name"]][r] = True
            elif p["name"] in ["Dashboard", "My Plan", "School Directory"]:
                matrix[p["name"]][r] = True
            elif p["name"] == "Planning Dashboard" and r in ["CCEO", "PL", "CD"]:
                matrix[p["name"]][r] = True
            elif p["name"] == "NetSuite Disbursements" and r == "Accountant":
                matrix[p["name"]][r] = True
            elif p["name"] == "System Health" and r == "Admin":
                matrix[p["name"]][r] = True
            else:
                matrix[p["name"]][r] = False

    context = {
        "roles": roles,
        "pages": pages,
        "matrix": matrix,
    }
    return render(request, "pages/admin/page_access_matrix.html", context)


@require_page_permission("region_district_setup")
def admin_region_district_setup_view(request):
    """District/Region management page."""
    regions = Region.objects.all().prefetch_related("districts")
    
    if request.method == "POST":
        district_name = request.POST.get("district_name")
        region_id = request.POST.get("region_id")
        if district_name and region_id:
            region = get_object_or_404(Region, id=region_id)
            District.objects.create(name=district_name, region=region)
            from django.contrib import messages
            messages.success(request, f"Successfully created district '{district_name}' inside region '{region.name}'.")
        return redirect("/admin-panel/region-district-setup")

    context = {
        "regions": regions,
    }
    return render(request, "pages/admin/region_district_setup.html", context)


@require_page_permission("notifications_mgmt")
def admin_notifications_mgmt_view(request):
    """Notification management logs."""
    from apps.notifications.models import Notification
    logs = Notification.objects.all().order_by("-created_at")[:50]
    
    if request.method == "POST" and "resend_id" in request.POST:
        notif_id = request.POST.get("resend_id")
        notif = get_object_or_404(Notification, id=notif_id)
        # Simulate resending notification
        from django.contrib import messages
        messages.success(request, f"Successfully resent notification '{notif.title}' to recipient '{notif.recipient_id}'.")
        return redirect("/admin-panel/notifications-mgmt")

    context = {
        "logs": logs,
    }
    return render(request, "pages/admin/notifications_mgmt.html", context)


@require_page_permission("data_quality_center")
def duplicate_review_view(request):
    from apps.schools.models import DataQualityIssue
    from django.contrib import messages
    
    issues = DataQualityIssue.objects.filter(issue_type="duplicate_risk", status="open").select_related("school")
    
    if request.method == "POST":
        issue_id = request.POST.get("issue_id")
        action = request.POST.get("action")
        issue = get_object_or_404(DataQualityIssue, id=issue_id) if issue_id else None
        
        if issue and action == "resolve_unique":
            school = issue.school
            school.duplicate_status = "not_duplicate"
            school.save()
            messages.success(request, f"School '{school.name}' marked as unique. Duplicate issue resolved.")
            return redirect("/data-quality/duplicates")
            
    context = {
        "issues": issues,
    }
    return render(request, "pages/admin/duplicate_review.html", context)


@require_page_permission("data_quality_center")
def unmatched_ssa_queue_view(request):
    from apps.schools.models import School, UnmatchedSSARecord
    from apps.ssa.models import SsaRecord, SsaScore
    from apps.core.enums import SsaCollectorType, VerificationStatus
    from django.contrib import messages
    from django.utils import timezone
    
    records = UnmatchedSSARecord.objects.filter(status__in=["pending", "hold"]).order_by("-created_at")
    schools_list = School.objects.filter(deleted_at__isnull=True).order_by("name")
    
    if request.method == "POST":
        record_id = request.POST.get("record_id")
        action = request.POST.get("action")
        rec = get_object_or_404(UnmatchedSSARecord, id=record_id)
        
        if action == "match":
            school_pk = request.POST.get("school_id")
            school = get_scoped_object_or_404(School, request.user, id=school_pk, deleted_at__isnull=True)
            
            # Create SsaRecord
            date_parsed = timezone.now()
            if rec.date_of_ssa:
                try:
                    from datetime import datetime
                    date_parsed = datetime.fromisoformat(rec.date_of_ssa.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        date_parsed = datetime.strptime(rec.date_of_ssa, "%Y-%m-%d")
                    except ValueError:
                        pass
            
            avg = sum(rec.scores.values()) / max(1, len(rec.scores))
            
            record = SsaRecord.objects.create(
                school=school,
                date_of_ssa=date_parsed,
                fy=get_operational_fy(date_parsed),
                quarter="Q1",
                average_score=avg,
                verification_status=VerificationStatus.CONFIRMED.value,
                collector_type=SsaCollectorType.STAFF.value,
                uploaded_by=request.user.user_id
            )
            
            scores_to_create = [
                SsaScore(ssa_record=record, intervention=k, score=v)
                for k, v in rec.scores.items()
            ]
            SsaScore.objects.bulk_create(scores_to_create)
            
            rec.status = "matched"
            rec.save()
            
            # Update school status
            from apps.ssa.services import _recompute_readiness
            _recompute_readiness(school)
            
            messages.success(request, f"Successfully matched SSA report to '{school.name}'.")
            return redirect("/ssa/unmatched")
            
        elif action == "create_school":
            # Extract and create a new school record
            school_id_numeric = ''.join(c for c in rec.school_id if c.isdigit())
            if not school_id_numeric:
                messages.error(request, "Cannot create school: raw school ID must contain numeric digits.")
                return redirect("/ssa/unmatched")
                
            from apps.geography.models import District
            
            # Lookup district by name
            district_obj = None
            if rec.district_raw:
                district_obj = District.objects.filter(name__icontains=rec.district_raw).first()
            if not district_obj:
                district_obj = District.objects.first()
                
            from apps.geography.models import Region
            region_obj = district_obj.region if district_obj else Region.objects.first()
            
            # Create school
            school = School.objects.create(
                school_id=school_id_numeric,
                name=rec.school_name_raw or f"School {school_id_numeric}",
                district=district_obj,
                region=region_obj,
                school_type="client",
                current_fy_ssa_status="done",
            )
            
            # Parse date
            date_parsed = timezone.now()
            if rec.date_of_ssa:
                try:
                    from datetime import datetime
                    date_parsed = datetime.fromisoformat(rec.date_of_ssa.replace("Z", "+00:00"))
                except ValueError:
                    try:
                        date_parsed = datetime.strptime(rec.date_of_ssa, "%Y-%m-%d")
                    except ValueError:
                        pass
                        
            avg = sum(rec.scores.values()) / max(1, len(rec.scores))
            record = SsaRecord.objects.create(
                school=school,
                date_of_ssa=date_parsed,
                fy=get_operational_fy(date_parsed),
                quarter="Q1",
                average_score=avg,
                verification_status=VerificationStatus.CONFIRMED.value,
                collector_type=SsaCollectorType.STAFF.value,
                uploaded_by=request.user.user_id
            )
            
            scores_to_create = [
                SsaScore(ssa_record=record, intervention=k, score=v)
                for k, v in rec.scores.items()
            ]
            SsaScore.objects.bulk_create(scores_to_create)
            
            rec.status = "matched"
            rec.save()
            
            # Update school status
            from apps.ssa.services import _recompute_readiness
            _recompute_readiness(school)
            
            messages.success(request, f"Successfully created school '{school.name}' and matched SSA.")
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
            
    # Compute suggested matches based on closest raw name matches
    suggested_matches = {}
    for r in records:
        if r.school_name_raw:
            s_match = School.objects.filter(name__icontains=r.school_name_raw, deleted_at__isnull=True).first()
            if s_match:
                suggested_matches[r.id] = s_match
                
    context = {
        "records": records,
        "schools": schools_list,
        "suggested_matches": suggested_matches
    }
    return render(request, "pages/admin/unmatched_ssa_queue.html", context)
