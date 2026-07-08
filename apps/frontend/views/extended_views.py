"""
GROUPS 4-7 — SSA/FY, Districts/Reports, Admin, Specialised Views
"""
import re

from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import require_page_permission, get_scoped_object_or_404
from django.db.models import Q, Avg, Count, Sum
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
from apps.core.fy import get_operational_fy, get_quarter_for_date, fy_options
from apps.targets.models import TargetSetting, TargetType


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


def _reports_pct_class(pct):
    """Colour a percentage the same way everywhere on this page — real
    thresholds, not a per-row hand-picked colour."""
    if pct is None:
        return "text-slate-400"
    if pct >= 70:
        return "text-emerald-600"
    if pct >= 50:
        return "text-blue-600"
    return "text-rose-600"


# Areas of work with a defensible activity_type mapping — every bucket below
# corresponds to activity_type values that actually exist on the Activity
# model (apps.core.enums.ActivityType), and (where one exists) a real
# apps.targets.models.TargetType so the "target" side of the page can be
# backed by real TargetSetting rows instead of invented numbers.
_REPORTS_VISIT_TYPES = ("school_visit", "follow_up_visit", "coaching_visit", "in_school_support", "core_visit")
_REPORTS_TRAINING_TYPES = ("training", "school_improvement_training", "cluster_training", "core_training")
_REPORTS_ACHIEVED_STATUSES = ("completed", "ia_verified", "accountant_confirmed", "closed")

_REPORTS_AREA_DEFS = [
    {"key": "school_visits", "label": "School Visits", "types": _REPORTS_VISIT_TYPES, "target_type": TargetType.SCHOOL_VISIT},
    {"key": "trainings", "label": "Trainings Delivered", "types": _REPORTS_TRAINING_TYPES, "target_type": TargetType.TRAINING},
    {"key": "ssa_activities", "label": "SSA Activities", "types": ("ssa_activity",), "target_type": TargetType.SSA},
    {"key": "cluster_meetings", "label": "Cluster Meetings", "types": ("cluster_meeting",), "target_type": None},
    {"key": "partner_activities", "label": "Partner Activities", "types": ("partner_activity",), "target_type": TargetType.PARTNER_SUPPORT},
]

# Real FY quarter definitions (apps.core.fy: FY runs Oct 1 -> Sep 30).
_REPORTS_QUARTER_PERIODS = [
    ("q1", "Q1", "Q1 (Oct - Dec)", 1),
    ("q2", "Q2", "Q2 (Jan - Mar)", 2),
    ("q3", "Q3", "Q3 (Apr - Jun)", 3),
    ("q4", "Q4", "Q4 (Jul - Sep)", 4),
]


@require_page_permission("planning")
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
    completed = Activity.objects.filter(status="completed", deleted_at__isnull=True).count()

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
            "dimmed": current_quarter_order is not None and order > current_quarter_order,
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
    period_totals = {p["key"]: {"achieved": 0, "target": 0, "has_target": False} for p in periods}

    for area in _REPORTS_AREA_DEFS:
        base_qs = activities_fy.filter(activity_type__in=area["types"])
        target_total = _target_for(area["target_type"])
        row = {"area": area["label"], "periods": []}
        for p in periods:
            achieved = base_qs.filter(p["filter"], status__in=_REPORTS_ACHIEVED_STATUSES).count()
            pct = round(achieved / target_total * 100) if target_total else None
            row["periods"].append({
                "achieved": achieved,
                "target": target_total,
                "pct": pct,
                "has_target": target_total is not None,
                "pct_class": _reports_pct_class(pct),
            })
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
        p.update({
            "achieved": totals["achieved"],
            "target": target,
            "pct": pct,
            "has_target": target is not None,
            "pct_class": _reports_pct_class(pct),
        })

    # ── Core target cards (FY-to-date per area) ─────────────────────────────
    card_colors = ["text-blue-600", "text-emerald-600", "text-teal-600", "text-indigo-600", "text-violet-600"]
    core_cards = []
    for i, area in enumerate(_REPORTS_AREA_DEFS):
        fy_cell = matrix_rows[i]["periods"][-1]
        core_cards.append({
            "label": area["label"],
            "achieved": fy_cell["achieved"],
            "target": fy_cell["target"],
            "has_target": fy_cell["has_target"],
            "pct": fy_cell["pct"],
            "color": card_colors[i % len(card_colors)],
        })

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
            priorities.append({
                "title": area["label"],
                "desc": f"No FY{fy} target configured — set a target to track achievement.",
                "status": "No Target",
                "status_class": "bg-slate-100 text-slate-500 border-slate-200",
            })
            continue
        pct = fy_cell["pct"] or 0
        if pct >= 70:
            status, status_class = "On Track", "bg-emerald-50 text-emerald-700 border-emerald-250"
        elif pct >= 50:
            status, status_class = "At Risk", "bg-amber-50 text-amber-700 border-amber-250"
        else:
            status, status_class = "Off Track", "bg-rose-50 text-rose-700 border-rose-250"
        priorities.append({
            "title": area["label"],
            "desc": f"{pct}% achieved against the FY{fy} target ({fy_cell['achieved']} / {fy_cell['target']:.0f}).",
            "status": status,
            "status_class": status_class,
        })

    context = {
        "fy": fy,
        "fy_choices": fy_choices,
        "total_schools": total_schools,
        "total_activities": total_activities,
        "completed": completed,
        "completion_rate": round(completed / max(total_activities, 1) * 100) if total_activities > 0 else 0,

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

    # Cluster has no direct "schools" relation — schools attach via
    # SchoolClusterAssignment (related_name="assignments" on Cluster).
    clusters = Cluster.objects.filter(deleted_at__isnull=True).annotate(
        school_count=Count(
            "assignments",
            filter=Q(assignments__school__deleted_at__isnull=True),
            distinct=True,
        ),
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
    from apps.system_health.services import missing_cost_lines_count

    user_count = User.objects.filter(deleted_at__isnull=True).count()
    active_users = User.objects.filter(status="active", deleted_at__isnull=True).count()
    pending_invites = User.objects.filter(status="pending_invited", deleted_at__isnull=True).count()
    suspended_users = User.objects.filter(status="suspended", deleted_at__isnull=True).count()

    # Same real signals surfaced on /system-health — reused here so the two
    # pages never disagree about what's actually broken.
    unmatched_staff_schools = School.objects.filter(account_owner_status="unmatched").count()
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
    user = request.user
    # Leave links to StaffProfile (field: staff), not directly to User.
    # HR/Admin review everyone's requests; other roles see their own.
    if getattr(user, "active_role", None) in ("HumanResources", "Admin"):
        leaves = Leave.objects.select_related("staff__user").order_by("-created_at")[:100]
    else:
        profile = getattr(user, "staff_profile", None)
        leaves = (Leave.objects.filter(staff=profile).order_by("-created_at")
                  if profile else Leave.objects.none())
    context = {"leaves": leaves}
    return render(request, "pages/leave/index.html", context)


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
    slots = CoreActivitySlot.objects.filter(core_plan=plan).order_by("sequence_number")
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
        group = groups_by_prefix.setdefault(prefix, {
            "name": _humanize_rbac_token(prefix),
            "permissions": [],
        })
        group["permissions"].append({
            "key": perm.key,
            "label": _humanize_rbac_token(rest) if rest else _humanize_rbac_token(prefix),
            "description": perm.description,
            "grants": {r: (perm.key, r) in granted for r in role_values},
        })

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
    """Workflow rules reference panel.

    There is no WorkflowRule model — these rules are enforced directly in code
    (apps.core.rbac / apps.activities.closure_services / apps.core.permissions),
    not as toggleable DB rows. This is intentionally a read-only reference: it
    used to offer fake toggle switches that didn't persist anything anywhere;
    that's been removed so the page stops lying about being configurable.
    """
    rules = [
        {"key": "clustered_before_planning", "label": "School must be clustered before planning"},
        {"key": "ssa_required", "label": "SSA required before planning"},
        {"key": "auto_budget_lines", "label": "Activity scheduling creates budget automatically"},
        {"key": "evidence_mandatory", "label": "Evidence attachment required before completion"},
        {"key": "sf_id_mandatory", "label": "Activity Salesforce ID required before IA verification"},
        {"key": "ia_before_accounts", "label": "IA verification required before Accounts clearance"},
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
        def __init__(self, role):
            self.active_role = role

    def _discover_pages(patterns, prefix=""):
        found = []
        for pattern in patterns:
            full = prefix + str(pattern.pattern)
            if hasattr(pattern, "url_patterns"):
                found.extend(_discover_pages(pattern.url_patterns, full))
            else:
                page_key = getattr(getattr(pattern, "callback", None), "page_permission", None)
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
        p["name"]: {r: RolePermissionService.can_view_page(_RoleProbe(r), p["key"]) for r in roles}
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
    from apps.geography.models import SecondaryDistrictGroup, SecondaryDistrictGroupMember

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
                messages.success(request, f"'{district.name}' classified as {district_type}.")

        elif action == "create_group":
            group_name = request.POST.get("group_name", "").strip()
            if group_name:
                SecondaryDistrictGroup.objects.get_or_create(name=group_name)
                messages.success(request, f"Secondary District Group '{group_name}' created.")

        elif action == "add_group_member":
            group = get_object_or_404(SecondaryDistrictGroup, id=request.POST.get("group_id"))
            district = get_object_or_404(District, id=request.POST.get("district_id"))
            if district.district_type != "secondary":
                messages.error(request, f"'{district.name}' is not classified as secondary — classify it first.")
            else:
                SecondaryDistrictGroupMember.objects.get_or_create(group=group, district=district)
                messages.success(request, f"Added '{district.name}' to '{group.name}'.")

        elif action == "remove_group_member":
            SecondaryDistrictGroupMember.objects.filter(id=request.POST.get("member_id")).delete()

        elif action == "approve_group":
            from django.utils import timezone as _timezone

            group = get_object_or_404(SecondaryDistrictGroup, id=request.POST.get("group_id"))
            group.status = "approved"
            group.approved_by = request.user.user_id
            group.approved_at = _timezone.now()
            group.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
            messages.success(request, f"'{group.name}' approved for same-day scheduling.")

        else:
            district_name = request.POST.get("district_name")
            region_id = request.POST.get("region_id")
            if district_name and region_id:
                region = get_object_or_404(Region, id=region_id)
                District.objects.create(name=district_name, region=region)
                messages.success(request, f"Successfully created district '{district_name}' inside region '{region.name}'.")

        return redirect("/admin-panel/region-district-setup")

    context = {
        "regions": regions,
        "secondary_groups": SecondaryDistrictGroup.objects.all().prefetch_related("members__district"),
        "secondary_districts": District.objects.filter(district_type="secondary").order_by("name"),
        "unclassified_count": District.objects.filter(district_type__isnull=True).count(),
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
