"""
GROUPS 4-7 — SSA/FY, Districts/Reports, Admin, Specialised Views
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Avg, Count, Sum
from datetime import date, timedelta

from apps.ssa.models import SsaRecord
from apps.schools.models import School
from apps.activities.models import Activity
from apps.geography.models import District, Region
from apps.accounts.models import User, Leave
from apps.messaging.models import Message, MessageThread
from apps.debriefs.models import DailyDebrief
from apps.projects.models import Project, ProjectSchoolAssignment
from apps.core_schools.models import CorePlan, CoreActivitySlot, CoreSchoolProfile
from apps.audit.models import AuditLog
from apps.flags.models import CdFlag
from apps.clusters.models import Cluster
from apps.core.fy import get_operational_fy


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — SSA, FY & Planning
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url="/login")
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


@login_required(login_url="/login")
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


@login_required(login_url="/login")
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


@login_required(login_url="/login")
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

@login_required(login_url="/login")
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


@login_required(login_url="/login")
def district_detail_view(request, district_id):
    """District detail — schools, SSA, and activities."""
    district = get_object_or_404(District, id=district_id)
    fy = get_operational_fy()
    schools = School.objects.filter(district=district, deleted_at__isnull=True).order_by("name")

    context = {
        "district": district,
        "schools": schools,
        "total_schools": schools.count(),
    }
    return render(request, "pages/districts/detail.html", context)


@login_required(login_url="/login")
def reports_view(request):
    """Reports overview — all roles."""
    fy = get_operational_fy()
    total_schools = School.objects.filter(deleted_at__isnull=True).count()
    total_activities = Activity.objects.filter(deleted_at__isnull=True).count()
    completed = Activity.objects.filter(status="completed", deleted_at__isnull=True).count()

    context = {
        "fy": fy,
        "total_schools": total_schools,
        "total_activities": total_activities,
        "completed": completed,
        "completion_rate": round(completed / max(total_activities, 1) * 100),
    }
    return render(request, "pages/reports/index.html", context)


@login_required(login_url="/login")
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
        school_count=Count("schools", filter=Q(schools__deleted_at__isnull=True)),
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

@login_required(login_url="/login")
def admin_panel_view(request):
    """Admin panel home."""
    user_count = User.objects.filter(deleted_at__isnull=True).count()
    active_users = User.objects.filter(status="active", deleted_at__isnull=True).count()

    context = {
        "user_count": user_count,
        "active_users": active_users,
    }
    return render(request, "pages/admin/index.html", context)


@login_required(login_url="/login")
def admin_users_view(request):
    """User management."""
    search = request.GET.get("q", "").strip()
    users = User.objects.filter(deleted_at__isnull=True).order_by("name")
    if search:
        users = users.filter(Q(name__icontains=search) | Q(email__icontains=search))

    context = {"users": users[:100], "total": users.count(), "search": search}
    return render(request, "pages/admin/users.html", context)


@login_required(login_url="/login")
def admin_user_detail_view(request, user_id):
    """User detail/edit."""
    member = get_object_or_404(User, id=user_id)
    context = {"member": member}
    return render(request, "pages/admin/user_detail.html", context)


@login_required(login_url="/login")
def audit_log_view(request):
    """Audit trail."""
    logs = AuditLog.objects.all().order_by("-created_at")[:100]
    context = {"logs": logs}
    return render(request, "pages/admin/audit_log.html", context)


@login_required(login_url="/login")
def settings_view(request):
    """General settings."""
    context = {"user": request.user}
    return render(request, "pages/settings/index.html", context)


@login_required(login_url="/login")
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


@login_required(login_url="/login")
def messages_list_view(request):
    """Messages inbox."""
    user = request.user
    messages_qs = Message.objects.filter(
        Q(sender_id=user.id) | Q(recipient_id=user.id)
    ).order_by("-created_at")[:50]

    context = {"messages": messages_qs}
    return render(request, "pages/messages/index.html", context)


@login_required(login_url="/login")
def message_detail_view(request, message_id):
    """Message thread."""
    msg = get_object_or_404(Message, id=message_id)
    context = {"message": msg}
    return render(request, "pages/messages/detail.html", context)


@login_required(login_url="/login")
def leave_requests_view(request):
    """Leave requests."""
    user = request.user
    leaves = Leave.objects.filter(user=user).order_by("-created_at")
    context = {"leaves": leaves}
    return render(request, "pages/leave/index.html", context)


@login_required(login_url="/login")
def map_view(request):
    """Geographic map placeholder."""
    schools = School.objects.filter(deleted_at__isnull=True).values("name", "latitude", "longitude")[:200]
    context = {"schools": list(schools)}
    return render(request, "pages/map/index.html", context)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 7 — Specialised & Legacy
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url="/login")
def core_schools_view(request):
    """Core schools programme."""
    plans = CorePlan.objects.all().order_by("-created_at")[:50]
    context = {"plans": plans, "total": plans.count()}
    return render(request, "pages/core_schools/index.html", context)


@login_required(login_url="/login")
def core_school_detail_view(request, plan_id):
    """Core school detail."""
    plan = get_object_or_404(CorePlan, id=plan_id)
    slots = CoreActivitySlot.objects.filter(core_plan=plan).order_by("slot_number")
    context = {"plan": plan, "slots": slots}
    return render(request, "pages/core_schools/detail.html", context)


@login_required(login_url="/login")
def projects_list_view(request):
    """Projects list."""
    projects = Project.objects.filter(deleted_at__isnull=True).order_by("name")
    context = {"projects": projects}
    return render(request, "pages/projects/index.html", context)


@login_required(login_url="/login")
def project_detail_view(request, project_id):
    """Project detail."""
    project = get_object_or_404(Project, id=project_id, deleted_at__isnull=True)
    school_assignments = ProjectSchoolAssignment.objects.filter(project=project).select_related("school")
    context = {"project": project, "school_assignments": school_assignments}
    return render(request, "pages/projects/detail.html", context)


@login_required(login_url="/login")
def debriefs_list_view(request):
    """Debriefs list."""
    debriefs = DailyDebrief.objects.filter(deleted_at__isnull=True).order_by("-created_at")[:50]
    context = {"debriefs": debriefs}
    return render(request, "pages/debriefs/index.html", context)


@login_required(login_url="/login")
def debrief_detail_view(request, debrief_id):
    """Debrief detail."""
    debrief = get_object_or_404(DailyDebrief, id=debrief_id)
    context = {"debrief": debrief}
    return render(request, "pages/debriefs/detail.html", context)


@login_required(login_url="/login")
def completed_activities_view(request):
    """Completed activities history."""
    activities = Activity.objects.filter(
        status="completed",
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("-updated_at")[:60]
    context = {"activities": activities}
    return render(request, "pages/completed_activities/index.html", context)


@login_required(login_url="/login")
def quality_checks_view(request):
    """Quality checks — IA role."""
    flags = CdFlag.objects.all().order_by("-created_at")[:50]
    context = {"flags": flags}
    return render(request, "pages/quality_checks/index.html", context)


@login_required(login_url="/login")
def help_view(request):
    """Help centre home."""
    context = {}
    return render(request, "pages/help/index.html", context)
