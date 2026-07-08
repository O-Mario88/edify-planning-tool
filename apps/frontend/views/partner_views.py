"""
GROUP 3 — Partner Views
Partner directory, partner detail, partner portal pages
"""

from django.shortcuts import render, get_object_or_404
from apps.core.permissions import require_page_permission
from django.db.models import Q
from datetime import date

from apps.partners.models import Partner
from apps.activities.models import Activity
from apps.evidence.models import EvidenceRecord
from apps.schools.models import School
from apps.accounts.models import User
from apps.core.scoping import resolve_user_scope
from apps.my_plan.services import serialize_activity_row


def _partner_activities_base_qs(user):
    """Activities delivered by the caller's partner organization. Prefers
    assigned_partner_id (the real org-level link set by planning's
    assign-to-partner flow) and also covers responsible_staff_id for any
    activity recorded directly against this user."""
    scope = resolve_user_scope(user)
    if scope.partner_ids:
        return Activity.objects.filter(
            Q(assigned_partner_id__in=scope.partner_ids)
            | Q(responsible_staff_id=user.id),
            deleted_at__isnull=True,
        )
    return Activity.objects.filter(
        responsible_staff_id=user.id, deleted_at__isnull=True
    )


@require_page_permission("partners")
def partners_list_view(request):
    """Partner organisations directory."""
    search = request.GET.get("q", "").strip()
    partners_qs = Partner.objects.filter(deleted_at__isnull=True).order_by("name")
    if search:
        partners_qs = partners_qs.filter(
            Q(name__icontains=search) | Q(region_name__icontains=search)
        )

    partners = list(partners_qs)
    active_count = sum(1 for p in partners if p.active_status)
    kpi_strip_items = [
        {
            "label": "Partner Organisations",
            "value": str(len(partners)),
            "raw_value": len(partners),
            "helper": "in directory",
            "icon": "briefcase",
            "variant": "info",
        },
        {
            "label": "Active",
            "value": str(active_count),
            "raw_value": active_count,
            "helper": "currently engaged",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Inactive",
            "value": str(len(partners) - active_count),
            "raw_value": len(partners) - active_count,
            "helper": "not currently engaged",
            "icon": "warning",
            "variant": "warning",
        },
    ]
    context = {
        "partners": partners,
        "total": len(partners),
        "search": search,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/partners/index.html", context)


@require_page_permission("partner_detail")
def partner_detail_view(request, partner_id):
    """Partner detail — schools, activities, performance."""
    partner = get_object_or_404(Partner, id=partner_id, deleted_at__isnull=True)

    # Activities delivered by this partner organization — the real link is
    # Activity.assigned_partner_id (delivery_type="partner"), not a linked
    # user account (partner.user is often unset for org-level partners).
    activities_qs = Activity.objects.filter(
        assigned_partner_id=partner.id,
        deleted_at__isnull=True,
    )
    if partner.user_id:
        activities_qs = Activity.objects.filter(
            Q(assigned_partner_id=partner.id) | Q(responsible_staff_id=partner.user_id),
            deleted_at__isnull=True,
        )
    activities = list(
        activities_qs.select_related("school").order_by("-planned_date")[:30]
    )

    from apps.partners.models import PartnerAssignment
    from apps.schools.models import School
    from apps.ssa.services import get_ssa_progress_by_fy

    assigned_school_ids = PartnerAssignment.objects.filter(partner=partner).values_list(
        "school_id", flat=True
    )
    partner_schools = School.objects.filter(
        id__in=assigned_school_ids, deleted_at__isnull=True
    )
    partner_progress = get_ssa_progress_by_fy(partner_schools)

    completed_count = sum(1 for a in activities if a.status == "completed")
    pending_evidence_count = sum(
        1
        for a in activities
        if a.status == "completed" and a.evidence_status != "uploaded"
    )
    kpi_strip_items = [
        {
            "label": "Assigned Schools",
            "value": str(partner_schools.count()),
            "raw_value": partner_schools.count(),
            "helper": "active assignments",
            "icon": "school",
            "variant": "info",
        },
        {
            "label": "Total Activities",
            "value": str(len(activities)),
            "raw_value": len(activities),
            "helper": "most recent 30",
            "icon": "calendar",
            "variant": "blue",
        },
        {
            "label": "Completed",
            "value": str(completed_count),
            "raw_value": completed_count,
            "helper": "of shown activities",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Evidence Pending",
            "value": str(pending_evidence_count),
            "raw_value": pending_evidence_count,
            "helper": "completed, no upload",
            "icon": "warning",
            "variant": "warning",
        },
    ]

    context = {
        "partner": partner,
        "activities": activities,
        "completed": completed_count,
        "partner_progress": partner_progress,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/partners/detail.html", context)


def _partner_row_maps():
    """Small lookup maps serialize_activity_row needs for badges/labels."""
    return (
        {p.id: p.name for p in Partner.objects.all()},
        {u.id: u.name for u in User.objects.all()},
    )


@require_page_permission("partner_today")
def partner_today_view(request):
    """Partner dashboard — today's work, one primary action per activity."""
    user = request.user
    today = date.today()
    base_qs = _partner_activities_base_qs(user)
    today_activities_qs = (
        base_qs.filter(planned_date=today)
        .select_related("school", "school__district", "school__sub_county", "cluster")
        .order_by("activity_type")
    )

    upcoming_qs = (
        base_qs.filter(planned_date__gt=today, status="scheduled")
        .select_related("school", "school__district", "school__sub_county", "cluster")
        .order_by("planned_date")[:10]
    )

    partners_map, users_map = _partner_row_maps()
    today_rows = [
        serialize_activity_row(a, today, partners_map, users_map)
        for a in today_activities_qs
    ]
    upcoming_rows = [
        serialize_activity_row(a, today, partners_map, users_map) for a in upcoming_qs
    ]

    kpi_strip_items = [
        {
            "label": "Due Today",
            "value": str(len(today_rows)),
            "raw_value": len(today_rows),
            "helper": "activities scheduled",
            "icon": "calendar",
            "variant": "warning",
        },
        {
            "label": "Upcoming",
            "value": str(len(upcoming_rows)),
            "raw_value": len(upcoming_rows),
            "helper": "next scheduled",
            "icon": "clock",
            "variant": "info",
        },
    ]

    context = {
        "today_activities": today_rows,
        "upcoming": upcoming_rows,
        "today": today,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/partner/today.html", context)


@require_page_permission("partner_schools")
def partner_schools_view(request):
    """Partner's assigned schools."""
    user = request.user
    activities_qs = _partner_activities_base_qs(user)
    school_ids = activities_qs.values_list("school_id", flat=True).distinct()
    schools = (
        School.objects.filter(id__in=school_ids, deleted_at__isnull=True)
        .select_related("district")
        .order_by("name")
    )

    ready_count = schools.exclude(
        planning_readiness__in=["requires_cluster", "data_cleanup_required"]
    ).count()
    no_ssa_count = schools.exclude(current_fy_ssa_status="done").count()

    kpi_strip_items = [
        {
            "label": "Assigned Schools",
            "value": str(schools.count()),
            "raw_value": schools.count(),
            "helper": "with activity history",
            "icon": "school",
            "variant": "info",
        },
        {
            "label": "Ready for Support",
            "value": str(ready_count),
            "raw_value": ready_count,
            "helper": "cleared for planning",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Missing Current SSA",
            "value": str(no_ssa_count),
            "raw_value": no_ssa_count,
            "helper": "needs a baseline",
            "icon": "warning",
            "variant": "danger",
        },
    ]

    context = {
        "schools": schools,
        "total": schools.count(),
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/partner/schools.html", context)


@require_page_permission("partner_activities")
def partner_activities_view(request):
    """Partner activities log — one primary action per row."""
    user = request.user
    today = date.today()
    status_filter = request.GET.get("status", "")
    activities_qs = (
        _partner_activities_base_qs(user)
        .select_related("school", "school__district", "school__sub_county", "cluster")
        .order_by("-planned_date")
    )
    if status_filter:
        activities_qs = activities_qs.filter(status=status_filter)

    all_activities = list(activities_qs[:60])
    partners_map, users_map = _partner_row_maps()
    rows = [
        serialize_activity_row(a, today, partners_map, users_map)
        for a in all_activities
    ]

    completed_count = sum(1 for a in all_activities if a.status == "completed")
    scheduled_count = sum(1 for a in all_activities if a.status == "scheduled")

    kpi_strip_items = [
        {
            "label": "Shown Activities",
            "value": str(len(rows)),
            "raw_value": len(rows),
            "helper": "most recent 60",
            "icon": "calendar",
            "variant": "info",
        },
        {
            "label": "Scheduled",
            "value": str(scheduled_count),
            "raw_value": scheduled_count,
            "helper": "not yet started",
            "icon": "clock",
            "variant": "warning",
        },
        {
            "label": "Completed",
            "value": str(completed_count),
            "raw_value": completed_count,
            "helper": "of shown activities",
            "icon": "check",
            "variant": "success",
        },
    ]

    context = {
        "activities": rows,
        "total": len(rows),
        "status_filter": status_filter,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/partner/activities.html", context)


@require_page_permission("partner_evidence")
def partner_evidence_view(request):
    """Partner evidence upload list — pending uploads need one action each."""
    user = request.user
    base_qs = _partner_activities_base_qs(user)
    activity_ids = base_qs.values_list("id", flat=True)
    evidence = list(
        EvidenceRecord.objects.filter(activity_id__in=activity_ids)
        .select_related("activity", "activity__school")
        .order_by("-created_at")[:50]
    )

    pending = list(
        base_qs.filter(status="completed", evidence__isnull=True).select_related(
            "school"
        )[:20]
    )

    kpi_strip_items = [
        {
            "label": "Uploaded",
            "value": str(len(evidence)),
            "raw_value": len(evidence),
            "helper": "most recent 50",
            "icon": "document",
            "variant": "info",
        },
        {
            "label": "Pending Upload",
            "value": str(len(pending)),
            "raw_value": len(pending),
            "helper": "completed, no evidence",
            "icon": "warning",
            "variant": "danger" if pending else "success",
        },
    ]

    context = {
        "evidence": evidence,
        "pending": pending,
        "kpi_strip_items": kpi_strip_items,
    }
    return render(request, "pages/partner/evidence.html", context)


@require_page_permission("partner_my_plan")
def partner_my_plan_view(request):
    """Partner cockpit - scheduled activities for the partner organization."""
    from apps.my_plan.services import get_frontend_context

    context = get_frontend_context(request.user, request.GET)
    return render(request, "pages/partner/my_plan.html", context)
