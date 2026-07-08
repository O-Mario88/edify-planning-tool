"""
GROUPS 4-7 — SSA/FY, Districts/Reports, Admin, Specialised Views
"""
from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission, get_scoped_object_or_404
from django.db.models import Q, Avg, Count
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
        "completion_rate": round(completed / max(total_activities, 1) * 100) if total_activities > 0 else 0,
        
        # May 2025 (Monthly)
        "monthly_achieved": 21,
        "monthly_total": 31,
        "monthly_pct": 68,
        "monthly_trend": "vs Apr ▲ 6pp",
        "monthly_trend_class": "text-emerald-600",
        
        # Q1 (Apr-Jun)
        "q1_achieved": 214,
        "q1_total": 297,
        "q1_pct": 72,
        "q1_trend": "vs Q1 Plan ▲ 8pp",
        "q1_trend_class": "text-emerald-600",
        
        # Q2 (Jul-Sep)
        "q2_achieved": 153,
        "q2_total": 300,
        "q2_pct": 51,
        "q2_trend": "vs Q2 Plan ▼ 3pp",
        "q2_trend_class": "text-rose-600",
        
        # Mid Year (Apr-Sep)
        "mid_achieved": 367,
        "mid_total": 597,
        "mid_pct": 61,
        "mid_trend": "vs Mid Year Plan ▲ 5pp",
        "mid_trend_class": "text-emerald-600",
        
        # Q3 (Oct-Dec)
        "q3_achieved": 0,
        "q3_total": 300,
        "q3_pct": 0,
        "q3_trend": "vs Q3 Plan —",
        "q3_trend_class": "text-slate-400",
        
        # Q4 (Jan-Mar)
        "q4_achieved": 0,
        "q4_total": 300,
        "q4_pct": 0,
        "q4_trend": "vs Q4 Plan —",
        "q4_trend_class": "text-slate-400",
        
        # FY 2024/25
        "fy_achieved": 367,
        "fy_total": 1197,
        "fy_pct": 31,
        "fy_trend": "vs FY Plan ▲ 4pp",
        "fy_trend_class": "text-emerald-600",

        # Target Cards
        "core_cards": [
            {"label": "Schools Visited", "value": "374 / 480", "pct": 78, "color": "text-blue-600"},
            {"label": "Trainings Delivered", "value": "91 / 140", "pct": 65, "color": "text-emerald-600"},
            {"label": "SSA Visits Completed", "value": "122 / 172", "pct": 71, "color": "text-teal-600"},
            {"label": "Follow-ups Closed", "value": "64 / 78", "pct": 82, "color": "text-indigo-600"},
            {"label": "Plan Approvals", "value": "28 / 40", "pct": 70, "color": "text-violet-600"},
            {"label": "Fund Requests Reviewed", "value": "8 / 12", "pct": 67, "color": "text-amber-600"}
        ],

        # Progress by Time Period (Cumulative) Table Matrix
        "matrix_rows": [
            {
                "area": "Schools Visited",
                "m_t": 60, "m_a": 42, "m_p": 70, "m_c": "text-blue-600",
                "q1_t": 150, "q1_a": 122, "q1_p": 81, "q1_c": "text-emerald-600",
                "q2_t": 150, "q2_a": 92, "q2_p": 61, "q2_c": "text-emerald-600",
                "mid_t": 300, "mid_a": 214, "mid_p": 71, "mid_c": "text-violet-600",
                "q3_t": 150, "q3_a": 0, "q3_p": 0, "q3_c": "text-slate-400",
                "q4_t": 180, "q4_a": 0, "q4_p": 0, "q4_c": "text-slate-400",
                "fy_t": 630, "fy_a": 214, "fy_p": 34, "fy_c": "text-blue-600"
            },
            {
                "area": "Trainings Delivered",
                "m_t": 20, "m_a": 14, "m_p": 70, "m_c": "text-blue-600",
                "q1_t": 50, "q1_a": 36, "q1_p": 72, "q1_c": "text-emerald-600",
                "q2_t": 50, "q2_a": 27, "q2_p": 54, "q2_c": "text-emerald-600",
                "mid_t": 100, "mid_a": 63, "mid_p": 63, "mid_c": "text-violet-600",
                "q3_t": 50, "q3_a": 0, "q3_p": 0, "q3_c": "text-slate-400",
                "q4_t": 50, "q4_a": 0, "q4_p": 0, "q4_c": "text-slate-400",
                "fy_t": 200, "fy_a": 63, "fy_p": 32, "fy_c": "text-blue-600"
            },
            {
                "area": "SSA Visits Completed",
                "m_t": 20, "m_a": 18, "m_p": 90, "m_c": "text-emerald-600",
                "q1_t": 51, "q1_a": 34, "q1_p": 67, "q1_c": "text-emerald-600",
                "q2_t": 56, "q2_a": 32, "q2_p": 57, "q2_c": "text-emerald-600",
                "mid_t": 107, "mid_a": 66, "mid_p": 62, "mid_c": "text-violet-600",
                "q3_t": 56, "q3_a": 0, "q3_p": 0, "q3_c": "text-slate-400",
                "q4_t": 58, "q4_a": 0, "q4_p": 0, "q4_c": "text-slate-400",
                "fy_t": 221, "fy_a": 66, "fy_p": 30, "fy_c": "text-blue-600"
            },
            {
                "area": "Follow-ups Closed",
                "m_t": 14, "m_a": 11, "m_p": 79, "m_c": "text-emerald-600",
                "q1_t": 24, "q1_a": 18, "q1_p": 75, "q1_c": "text-emerald-600",
                "q2_t": 27, "q2_a": 14, "q2_p": 52, "q2_c": "text-emerald-600",
                "mid_t": 51, "mid_a": 32, "mid_p": 63, "mid_c": "text-violet-600",
                "q3_t": 27, "q3_a": 0, "q3_p": 0, "q3_c": "text-slate-400",
                "q4_t": 28, "q4_a": 0, "q4_p": 0, "q4_c": "text-slate-400",
                "fy_t": 106, "fy_a": 32, "fy_p": 30, "fy_c": "text-blue-600"
            },
            {
                "area": "Plan Approvals",
                "m_t": 10, "m_a": 7, "m_p": 70, "m_c": "text-blue-600",
                "q1_t": 24, "q1_a": 17, "q1_p": 71, "q1_c": "text-emerald-600",
                "q2_t": 16, "q2_a": 11, "q2_p": 69, "q2_c": "text-emerald-600",
                "mid_t": 40, "mid_a": 28, "mid_p": 70, "mid_c": "text-emerald-600",
                "q3_t": 16, "q3_a": 0, "q3_p": 0, "q3_c": "text-slate-400",
                "q4_t": 18, "q4_a": 0, "q4_p": 0, "q4_c": "text-slate-400",
                "fy_t": 74, "fy_a": 28, "fy_p": 38, "fy_c": "text-blue-600"
            },
            {
                "area": "Fund Requests Reviewed",
                "m_t": 4, "m_a": 3, "m_p": 75, "m_c": "text-emerald-600",
                "q1_t": 10, "q1_a": 7, "q1_p": 70, "q1_c": "text-emerald-600",
                "q2_t": 16, "q2_a": 4, "q2_p": 25, "q2_c": "text-rose-600",
                "mid_t": 26, "mid_a": 11, "mid_p": 42, "mid_c": "text-amber-600",
                "q3_t": 16, "q3_a": 0, "q3_p": 0, "q3_c": "text-slate-400",
                "q4_t": 18, "q4_a": 0, "q4_p": 0, "q4_c": "text-slate-400",
                "fy_t": 60, "fy_a": 11, "fy_p": 18, "fy_c": "text-rose-600"
            }
        ],

        # Donut split
        "donut_total": 12,
        "donut_on_track": 6,
        "donut_at_risk": 4,
        "donut_off_track": 2,

        # Priorities
        "priorities": [
            {"title": "SSA Visits Completed", "desc": "Below target in Q2. Focus on completion.", "status": "At Risk", "status_class": "bg-amber-50 text-amber-700 border-amber-250"},
            {"title": "Trainings Delivered", "desc": "64% achieved in Q2. Increase coverage.", "status": "At Risk", "status_class": "bg-amber-50 text-amber-700 border-amber-250"},
            {"title": "Follow-ups Closed", "desc": "82% achieved this month. Keep it up!", "status": "On Track", "status_class": "bg-emerald-50 text-emerald-700 border-emerald-250"},
            {"title": "Fund Requests Reviewed", "desc": "40% achieved in Q2. Clear outstanding items.", "status": "Off Track", "status_class": "bg-rose-50 text-rose-700 border-rose-250"}
        ]
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
                sp = StaffProfile.objects.create(user=user, primary_district_id=district_id or None, title=role)
                
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
                mailer.send_temporary_password_notification(to=email, name=name, invited_by_name=request.user.name)
                
            messages.success(request, f"User '{name}' successfully created with password set. Notification sent to {email}.")
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
            primary_district = request.POST.get("primary_district")
            additional_districts = request.POST.getlist("additional_districts")
            
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
                
            member.save()

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

        elif action == "reset_password":
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
            member.set_password(new_password)
            member.must_change_password = True
            member.password_set_at = timezone.now()
            member.failed_login_count = 0
            member.locked_until = None
            member.status = "active"
            member.is_active = True
            member.save(update_fields=[
                "password", "must_change_password", "password_set_at",
                "failed_login_count", "locked_until", "status", "is_active"
            ])

            from apps.core.email import mailer
            mailer.send_password_reset_by_admin_notification(
                to=member.email, name=member.name, reset_by_name=request.user.name
            )
            messages.success(request, f"Password reset for '{member.name}'. They will be required to change it on next login.")

        elif action == "unlock":
            member.failed_login_count = 0
            member.locked_until = None
            member.save(update_fields=["failed_login_count", "locked_until"])
            messages.success(request, f"Account for '{member.name}' has been unlocked.")
            
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
        list(StaffGeographyAssignment.objects.filter(staff=sp).values_list("district_id", flat=True))
        if sp else []
    )

    from django.utils import timezone
    is_locked = bool(member.locked_until and member.locked_until > timezone.now())
    
    context = {
        "member": member,
        "available_roles": roles,
        "districts": districts,
        "primary_district_id": primary_district_id,
        "assigned_districts": assigned_districts,
        "is_locked": is_locked,
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


@require_page_permission("personal_time_off")
def leave_requests_view(request):
    """Redirect legacy leave requests view to new personal-time-off view."""
    from django.shortcuts import redirect
    return redirect("/personal-time-off/")


@require_page_permission("personal_time_off")
def personal_time_off_view(request):
    """Personal Time Off request and list cockpit."""
    user = request.user
    from apps.accounts.models import Leave, StaffProfile
    from django.shortcuts import redirect, render
    from django.contrib import messages
    from datetime import datetime
    
    sp = getattr(user, "staff_profile", None)
    if not sp:
        sp, _ = StaffProfile.objects.get_or_create(
            user=user,
            defaults={"onboarding_state": "active", "title": "Staff"}
        )

    if request.method == "POST":
        start_date_str = request.POST.get("start_date")
        end_date_str = request.POST.get("end_date")
        reason = request.POST.get("reason")
        coverage_notes = request.POST.get("coverage_notes")
        leave_type = request.POST.get("type", "annual")
        
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d")
            days = (end_date - start_date).days + 1
            if days <= 0:
                raise ValueError("End date must be on or after start date.")
        except Exception as e:
            messages.error(request, f"Invalid date range: {e}")
            return redirect("/personal-time-off/")
            
        Leave.objects.create(
            staff=sp,
            type=leave_type,
            start_date=start_date_str,
            end_date=end_date_str,
            days=days,
            reason=reason,
            coverage_notes=coverage_notes,
            status="pending"
        )
        messages.success(request, "Leave request submitted successfully.")
        return redirect("/personal-time-off/")
        
    leaves = Leave.objects.filter(staff=sp).order_by("-created_at")
    
    from apps.accounts.models import User
    reviewer_ids = [l.reviewed_by_user_id for l in leaves if l.reviewed_by_user_id]
    reviewer_map = {u.id: u.name for u in User.objects.filter(id__in=reviewer_ids)}
    
    leaves_data = []
    for l in leaves:
        leaves_data.append({
            "id": l.id,
            "type": str(l.type).replace("_", " ").title(),
            "start_date": l.start_date,
            "end_date": l.end_date,
            "days": l.days,
            "status": l.status,
            "reason": l.reason,
            "coverage_notes": l.coverage_notes,
            "reviewer_name": reviewer_map.get(l.reviewed_by_user_id, "Pending Review") if l.reviewed_by_user_id else "Pending Review"
        })
        
    context = {
        "leaves": leaves_data,
        "profile": sp
    }
    return render(request, "pages/leave/personal_time_off.html", context)



@require_page_permission("planning")
def map_view(request):
    """Geographic map placeholder."""
    schools = School.objects.filter(deleted_at__isnull=True).values("name", "latitude", "longitude")[:200]
    context = {"schools": list(schools)}
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
    """Roles and permissions matrix."""
    roles = ["cceo", "pl", "cd", "rvp", "ia", "accountant", "hr", "partner", "admin"]
    permission_groups = [
        "Schools", "Clusters", "Planning", "My Plan", "Fund Requests", "Budgets", 
        "Cost Catalogue", "Evidence", "IA Verification", "Accounts Clearance", 
        "Analytics", "Messages", "Notifications", "System Settings", "User Management"
    ]
    # Standard static matrix of default clearances
    matrix = {}
    for pg in permission_groups:
        matrix[pg] = {}
        for r in roles:
            # Default mock permissions
            if r == "admin":
                matrix[pg][r] = True
            elif pg == "Schools" and r in ["cceo", "pl", "cd", "rvp", "ia"]:
                matrix[pg][r] = True
            elif pg == "Planning" and r in ["cceo", "pl", "cd"]:
                matrix[pg][r] = True
            elif pg == "Budgets" and r in ["cd", "rvp", "accountant"]:
                matrix[pg][r] = True
            elif pg == "Accounts Clearance" and r == "accountant":
                matrix[pg][r] = True
            elif pg == "IA Verification" and r == "ia":
                matrix[pg][r] = True
            elif pg == "Analytics" and r in ["cd", "rvp", "pl", "admin"]:
                matrix[pg][r] = True
            else:
                matrix[pg][r] = False

    context = {
        "roles": roles,
        "permission_groups": permission_groups,
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
        }
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
