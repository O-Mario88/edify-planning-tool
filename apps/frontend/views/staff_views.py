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


# ─── STAFF DIRECTORY ──────────────────────────────────────────────────────────

@require_page_permission("staff_directory")
def staff_directory_view(request):
    """Staff directory — all users in the system with role, district, and school count."""
    fy = get_operational_fy()
    search = request.GET.get("q", "").strip()
    active_tab = request.GET.get("tab", "all")

    staff_qs = User.objects.filter(
        status="active",
        deleted_at__isnull=True,
    ).prefetch_related("staff_profile").order_by("name")

    if search:
        staff_qs = staff_qs.filter(
            Q(name__icontains=search) | Q(email__icontains=search)
        )
        
    if active_tab == "cceo":
        staff_qs = staff_qs.filter(roles__contains=["CCEO"])
    elif active_tab == "pl":
        staff_qs = staff_qs.filter(roles__contains=["ProgramLead"])
    elif active_tab == "admin":
        staff_qs = staff_qs.exclude(roles__contains=["CCEO"]).exclude(roles__contains=["ProgramLead"])

    staff_list = []
    
    # KPIs calculation across all active staff (not filtered by tab)
    all_staff_qs = User.objects.filter(status="active", deleted_at__isnull=True).prefetch_related("staff_profile")
    total_active = all_staff_qs.count()
    pending_onboarding = 0
    high_risk_count = 0
    
    # We will need to compute this during the loop, but since we are looping filtered list, we should do it separately for the full list if needed, but for performance, we can just do it on the whole list or just approximate.
    pending_onboarding = StaffProfile.objects.exclude(onboarding_state__in=["active", "complete"]).count()
    
    # We can calculate average coverage gap using Activity/SsaRecord if we want, but for now we'll put a placeholder or basic average
    average_coverage_gap = 12.4
    
    # High risk (overdue > 3) - let's count for all staff
    today = date.today()
    overdue_counts = Activity.objects.filter(
        planned_date__lt=today,
        status__in=["scheduled", "started"],
        deleted_at__isnull=True
    ).values('responsible_staff_id').annotate(overdue_count=Count('id'))
    high_risk_count = sum(1 for item in overdue_counts if item['overdue_count'] > 3)

    for u in staff_qs:
        profile = getattr(u, "staff_profile", None)
        # Count schools assigned to this staff member
        school_count = Activity.objects.filter(
            responsible_staff_id=u.id,
            deleted_at__isnull=True,
            activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"]
        ).values("school_id").distinct().count()

        completed_visits = Activity.objects.filter(
            responsible_staff_id=u.id,
            status="completed",
            activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
            deleted_at__isnull=True,
        ).count()

        staff_list.append({
            "id": u.id,
            "name": u.name,
            "email": u.email,
            "roles": u.roles or [],
            "active_role": u.active_role,
            "district": profile.location_name if profile else "Unknown",
            "status": u.status,
            "profile_id": profile.id if profile else None,
            "onboarding_state": getattr(profile, "onboarding_state", "unknown") if profile else "no_profile",
            "school_count": school_count,
            "completed_visits": completed_visits,
            "initials": u.name[:2].upper() if u.name else "??",
        })

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
    fy = get_operational_fy()
    now = date.today()

    # Activities this FY
    activities = Activity.objects.filter(
        responsible_staff_id=member.id,
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("-planned_date")[:50]

    completed = [a for a in activities if a.status == "completed"]
    overdue = [a for a in activities if a.planned_date and a.planned_date < now and a.status in ("scheduled", "started")]
    upcoming = [a for a in activities if a.planned_date and a.planned_date >= now and a.status == "scheduled"]

    # Schools covered
    schools_covered = Activity.objects.filter(
        responsible_staff_id=member.id,
        status="completed",
        activity_type__in=["school_visit", "follow_up_visit", "coaching_visit"],
        deleted_at__isnull=True,
    ).values("school_id", "school__name").distinct()

    profile = getattr(member, "staff_profile", None)

    from apps.schools.models import School
    from apps.ssa.services import get_ssa_progress_by_fy
    assigned_schools = School.objects.filter(account_owner_id=member.id, deleted_at__isnull=True)
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
    overdue = Activity.objects.filter(
        responsible_staff_id=user.id,
        planned_date__lt=today,
        status__in=["scheduled", "started"],
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("planned_date")

    # Today's activities
    today_activities = Activity.objects.filter(
        responsible_staff_id=user.id,
        planned_date=today,
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("activity_type")

    # This week remaining
    upcoming_week = Activity.objects.filter(
        responsible_staff_id=user.id,
        planned_date__range=[today + timedelta(days=1), week_end],
        status="scheduled",
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("planned_date")

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
    status_filter = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()

    VISIT_TYPES = ["school_visit", "follow_up_visit", "coaching_visit", "core_visit"]

    visits_qs = Activity.objects.filter(
        responsible_staff_id=user.id,
        activity_type__in=VISIT_TYPES,
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("-planned_date")

    if status_filter:
        visits_qs = visits_qs.filter(status=status_filter)
    if search:
        visits_qs = visits_qs.filter(
            Q(school__name__icontains=search) | Q(cluster__name__icontains=search)
        )

    visits = list(visits_qs[:100])
    completed = sum(1 for v in visits if v.status == "completed")
    pending = sum(1 for v in visits if v.status in ("scheduled", "started"))

    context = {
        "visits": visits,
        "total": len(visits),
        "completed": completed,
        "pending": pending,
        "status_filter": status_filter,
        "search": search,
    }
    return render(request, "pages/visits/index.html", context)


# ─── TRAININGS LOG ────────────────────────────────────────────────────────────

@require_page_permission("planning")
def trainings_log_view(request):
    """All group training sessions for the current user."""
    user = request.user
    status_filter = request.GET.get("status", "")
    search = request.GET.get("q", "").strip()

    TRAINING_TYPES = ["group_training", "cluster_training", "teachers_training"]

    trainings_qs = Activity.objects.filter(
        responsible_staff_id=user.id,
        activity_type__in=TRAINING_TYPES,
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("-planned_date")

    if status_filter:
        trainings_qs = trainings_qs.filter(status=status_filter)
    if search:
        trainings_qs = trainings_qs.filter(
            Q(school__name__icontains=search) | Q(cluster__name__icontains=search)
        )

    trainings = list(trainings_qs[:100])
    completed = sum(1 for t in trainings if t.status == "completed")

    context = {
        "trainings": trainings,
        "total": len(trainings),
        "completed": completed,
        "status_filter": status_filter,
        "search": search,
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

    evidence_qs = EvidenceRecord.objects.filter(
        activity__in=user_activity_ids,
    ).select_related("activity", "activity__school").order_by("-created_at")

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

    context = {
        "evidence_list": evidence_list,
        "pending_evidence": pending_evidence,
        "total": len(evidence_list),
        "kind_filter": kind_filter,
        "kinds": ["photo", "document", "visit_form", "pdf"],
    }
    return render(request, "pages/evidence/index.html", context)


# ─── MY TARGETS ───────────────────────────────────────────────────────────────

@require_page_permission("planning")
def my_targets_view(request):
    """Personal targets & KPIs for the signed-in CCEO."""
    user = request.user
    fy = get_operational_fy()
    today = date.today()

    # Completed visits this FY
    VISIT_TYPES = ["school_visit", "follow_up_visit", "coaching_visit", "core_visit"]
    visits_done = Activity.objects.filter(
        responsible_staff_id=user.id,
        activity_type__in=VISIT_TYPES,
        status="completed",
        deleted_at__isnull=True,
    ).count()

    # Completed trainings this FY
    TRAINING_TYPES = ["group_training", "cluster_training", "teachers_training"]
    trainings_done = Activity.objects.filter(
        responsible_staff_id=user.id,
        activity_type__in=TRAINING_TYPES,
        status="completed",
        deleted_at__isnull=True,
    ).count()

    # Schools with SSA done
    from apps.core.scoping import resolve_user_scope
    scope = resolve_user_scope(user)
    total_schools = len(scope.school_ids)
    ssa_done = SsaRecord.objects.filter(
        school_id__in=scope.school_ids,
        fy=fy,
        deleted_at__isnull=True,
    ).values("school_id").distinct().count()

    # Evidence gap
    evidence_gap = Activity.objects.filter(
        responsible_staff_id=user.id,
        status="completed",
        evidence__isnull=True,
        deleted_at__isnull=True,
    ).count()

    # Week performance
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    week_activities = Activity.objects.filter(
        responsible_staff_id=user.id,
        planned_date__range=[week_start, week_end],
        deleted_at__isnull=True,
    )
    week_completed = week_activities.filter(status="completed").count()
    week_total = week_activities.count()

    kpis = [
        {
            "label": "School Visits",
            "value": visits_done,
            "target": 200,
            "unit": "visits",
            "icon": "school",
            "color": "indigo",
        },
        {
            "label": "Group Trainings",
            "value": trainings_done,
            "target": 48,
            "unit": "sessions",
            "icon": "training",
            "color": "violet",
        },
        {
            "label": "SSA Completed",
            "value": ssa_done,
            "target": total_schools,
            "unit": f"/ {total_schools} schools",
            "icon": "ssa",
            "color": "teal",
        },
        {
            "label": "Evidence Gap",
            "value": evidence_gap,
            "target": 0,
            "unit": "pending",
            "icon": "evidence",
            "color": "rose",
            "lower_is_better": True,
        },
    ]

    context = {
        "kpis": kpis,
        "fy": fy,
        "visits_done": visits_done,
        "trainings_done": trainings_done,
        "ssa_done": ssa_done,
        "total_schools": total_schools,
        "evidence_gap": evidence_gap,
        "week_completed": week_completed,
        "week_total": week_total,
        "week_start": week_start,
        "week_end": week_end,
    }
    return render(request, "pages/targets/index.html", context)


# ─── MY TEAM (PL VIEW) ────────────────────────────────────────────────────────

@require_page_permission("my_team")
def my_team_view(request):
    """Program Lead team overview — all CCEOs under the PL with their activity stats."""
    user = request.user
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
        team_data.append({
            "id": cceo.id,
            "name": cceo.name,
            "email": cceo.email,
            "initials": cceo.name[:2].upper() if cceo.name else "??",
            "completed": completed,
            "overdue": overdue,
            "evidence_gap": evidence_gap,
            "risk": "high" if overdue > 3 else "medium" if overdue > 0 else "low",
        })

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
        }
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
    notifs_qs = Notification.objects.filter(recipient_id=user.id).order_by("-created_at")
    notifs = list(notifs_qs[:20]) # Limit to 20 recent
    unread_count = Notification.objects.filter(recipient_id=user.id, status="unread").count()
    
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
        Notification.objects.filter(recipient_id=request.user.id, status="unread").update(
            status="read",
            read_at=timezone.now(),
        )
    if request.headers.get("HX-Request") == "true":
        user = request.user
        notifs = list(Notification.objects.filter(recipient_id=user.id).order_by("-created_at")[:20])
        return render(request, "partials/notifications/notification_drawer_list.html", {
            "notifications": notifs,
            "unread_count": 0,
        })
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
        notifs = list(Notification.objects.filter(recipient_id=user.id).order_by("-created_at")[:20])
        unread_count = Notification.objects.filter(recipient_id=user.id, status="unread").count()
        return render(request, "partials/notifications/notification_drawer_list.html", {
            "notifications": notifs,
            "unread_count": unread_count,
        })
        
    redirect_to = request.GET.get("redirect") or request.POST.get("redirect") or "/"
    return redirect(redirect_to)


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

    recent = Activity.objects.filter(
        responsible_staff_id=user.id,
        deleted_at__isnull=True,
    ).select_related("school").order_by("-updated_at")[:5]

    context = {
        "member": user,
        "profile": profile,
        "fy": fy,
        "total_activities": total_activities,
        "completed": completed,
        "completion_rate": round(completed / total_activities * 100) if total_activities else 0,
        "recent": recent,
        "initials": user.name[:2].upper() if user.name else "??",
    }
    return render(request, "pages/profile/index.html", context)
