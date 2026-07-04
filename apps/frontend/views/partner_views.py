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


@require_page_permission("partners")
def partners_list_view(request):
    """Partner organisations directory."""
    search = request.GET.get("q", "").strip()
    partners_qs = Partner.objects.filter(deleted_at__isnull=True).order_by("name")
    if search:
        partners_qs = partners_qs.filter(Q(name__icontains=search) | Q(region_name__icontains=search))

    partners = list(partners_qs)
    context = {
        "partners": partners,
        "total": len(partners),
        "search": search,
    }
    return render(request, "pages/partners/index.html", context)


@require_page_permission("partner_detail")
def partner_detail_view(request, partner_id):
    """Partner detail — schools, activities, performance."""
    partner = get_object_or_404(Partner, id=partner_id, deleted_at__isnull=True)

    # Get partner user if linked
    partner_user = partner.primary_contact
    activities = []
    if partner_user:
        activities = Activity.objects.filter(
            responsible_staff_id=partner_user.id,
            deleted_at__isnull=True,
        ).select_related("school").order_by("-planned_date")[:30]

    from apps.partners.models import PartnerAssignment
    from apps.schools.models import School
    from apps.ssa.services import get_ssa_progress_by_fy
    assigned_school_ids = PartnerAssignment.objects.filter(partner=partner).values_list("school_id", flat=True)
    partner_schools = School.objects.filter(id__in=assigned_school_ids, deleted_at__isnull=True)
    partner_progress = get_ssa_progress_by_fy(partner_schools)

    context = {
        "partner": partner,
        "activities": activities,
        "completed": sum(1 for a in activities if a.status == "completed"),
        "partner_progress": partner_progress,
    }
    return render(request, "pages/partners/detail.html", context)


@require_page_permission("partner_today")
def partner_today_view(request):
    """Partner dashboard — today's work."""
    user = request.user
    today = date.today()
    today_activities = Activity.objects.filter(
        responsible_staff_id=user.id,
        planned_date=today,
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("activity_type")

    upcoming = Activity.objects.filter(
        responsible_staff_id=user.id,
        planned_date__gt=today,
        status="scheduled",
        deleted_at__isnull=True,
    ).select_related("school").order_by("planned_date")[:5]

    context = {
        "today_activities": today_activities,
        "upcoming": upcoming,
        "today": today,
    }
    return render(request, "pages/partner/today.html", context)


@require_page_permission("partner_schools")
def partner_schools_view(request):
    """Partner's assigned schools."""
    user = request.user
    school_ids = Activity.objects.filter(
        responsible_staff_id=user.id,
        deleted_at__isnull=True,
    ).values_list("school_id", flat=True).distinct()
    schools = School.objects.filter(id__in=school_ids, deleted_at__isnull=True).order_by("name")

    context = {"schools": schools, "total": schools.count()}
    return render(request, "pages/partner/schools.html", context)


@require_page_permission("partner_activities")
def partner_activities_view(request):
    """Partner activities log."""
    user = request.user
    status_filter = request.GET.get("status", "")
    activities = Activity.objects.filter(
        responsible_staff_id=user.id,
        deleted_at__isnull=True,
    ).select_related("school", "cluster").order_by("-planned_date")
    if status_filter:
        activities = activities.filter(status=status_filter)
    activities = list(activities[:60])
    context = {
        "activities": activities,
        "total": len(activities),
        "status_filter": status_filter,
    }
    return render(request, "pages/partner/activities.html", context)


@require_page_permission("partner_evidence")
def partner_evidence_view(request):
    """Partner evidence upload list."""
    user = request.user
    activity_ids = Activity.objects.filter(
        responsible_staff_id=user.id,
        deleted_at__isnull=True,
    ).values_list("id", flat=True)
    evidence = EvidenceRecord.objects.filter(activity_id__in=activity_ids).select_related(
        "activity", "activity__school"
    ).order_by("-created_at")[:50]

    pending = Activity.objects.filter(
        responsible_staff_id=user.id,
        status="completed",
        evidence__isnull=True,
        deleted_at__isnull=True,
    ).select_related("school")[:10]

    context = {"evidence": evidence, "pending": pending}
    return render(request, "pages/partner/evidence.html", context)


@require_page_permission("partner_my_plan")
def partner_my_plan_view(request):
    """Partner cockpit - scheduled activities for the partner organization."""
    from apps.my_plan.services import get_frontend_context
    context = get_frontend_context(request.user, request.GET)
    return render(request, "pages/partner/my_plan.html", context)
