from datetime import timedelta
from django.shortcuts import render
from apps.core.permissions import require_page_permission
from django.utils import timezone
from apps.core.fy import get_operational_fy
from apps.geography.models import Region, District
from apps.clusters.models import Cluster
from apps.partners.models import Partner
from apps.accounts.models import StaffProfile
from apps.schools.models import School
from apps.activities.models import Activity
from apps.ssa.models import SsaRecord
from apps.analytics.analytics_dashboard_service import AnalyticsDashboardService


@require_page_permission("analytics")
def analytics_dashboard_view(request):
    """GET to render the primary Analytics Dashboard with filters."""
    # 1. Gather all filters from GET parameters
    filters = {
        "fy": request.GET.get("fy"),
        "quarter": request.GET.get("quarter"),
        "region": request.GET.get("region"),
        "district": request.GET.get("district"),
        "cluster": request.GET.get("cluster"),
        "staff": request.GET.get("staff"),
        "partner": request.GET.get("partner"),
        "school_type": request.GET.get("school_type"),
        "activity_type": request.GET.get("activity_type"),
        "q": request.GET.get("q"),
    }

    # 2. Call Service to gather all dashboard datasets
    data = AnalyticsDashboardService.get_analytics_data(request.user, filters)

    # 3. Retrieve options list for dropdown filters
    regions = Region.objects.all().order_by("name")
    districts = District.objects.all().order_by("name")
    clusters = Cluster.objects.all().order_by("name")
    staff_profiles = (
        StaffProfile.objects.filter(deleted_at__isnull=True)
        .select_related("user")
        .order_by("user__name")
    )
    partners = Partner.objects.filter(deleted_at__isnull=True).order_by("name")

    # 4. Render context
    context = {
        **data,
        "regions": regions,
        "districts": districts,
        "clusters": clusters,
        "staff_profiles": staff_profiles,
        "partners": partners,
        # Action settings
        "use_dark_sidebar": False,
        "timestamp": timezone.now().strftime("%B %d, %Y %I:%M %p"),
    }

    # If HTMX request, render only content cards to swap
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/analytics/kpi_cards.html", context)

    return render(request, "pages/analytics/index.html", context)


@require_page_permission("analytics")
def analytics_drilldown_view(request):
    """GET to render the detailed trace records drawer."""
    metric = request.GET.get("metric", "").strip()
    fy = request.GET.get("fy") or get_operational_fy()
    quarter = request.GET.get("quarter") or "Q2"

    # Base filter criteria
    activities = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    schools = School.objects.filter(deleted_at__isnull=True)
    SsaRecord.objects.filter(deleted_at__isnull=True, fy=fy)

    title = "Drilldown Details"
    description = "Traceable source records for the selected metric."
    headers = ["Entity", "Details", "Date", "Status"]
    rows = []

    # Query specific data traces
    if (
        metric == "teachers_trained"
        or metric == "leaders_trained"
        or metric == "activities_completed"
    ):
        title = "Trained Participants / Activities completed"
        description = f"Completed and verified activities for {quarter} FY {fy}."
        headers = [
            "Activity Type",
            "Target Location/School",
            "Responsible Owner",
            "Verification Status",
            "SF Activity ID",
        ]

        acts = list(
            activities.filter(
                quarter=quarter,
                status__in=["completed", "ia_verified", "accountant_confirmed"],
            ).select_related("school", "cluster")[:100]
        )
        staff_ids = [a.responsible_staff_id for a in acts if a.responsible_staff_id]
        staff_map = {
            sp.id: sp.user.name
            for sp in StaffProfile.objects.filter(id__in=staff_ids).select_related(
                "user"
            )
        }

        for a in acts:
            target = (
                a.school.name if a.school else (a.cluster.name if a.cluster else "-")
            )
            rows.append(
                {
                    "col1": a.activity_type.replace("_", " ").title(),
                    "col2": target,
                    "col3": staff_map.get(a.responsible_staff_id, "Partner/Staff"),
                    "col4": a.status.replace("_", " ").title(),
                    "col5": a.salesforce_activity_id or "Not Entered",
                }
            )

    elif metric == "schools_impacted":
        title = "Schools Reached"
        description = (
            f"Distinct school sites with completed program activities in {quarter}."
        )
        headers = ["School ID", "School Name", "District", "Type", "Enrollment"]

        school_ids = (
            activities.filter(quarter=quarter, status__in=["completed", "ia_verified"])
            .values_list("school_id", flat=True)
            .distinct()
        )
        for s in schools.filter(id__in=school_ids)[:100]:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": s.school_type.upper(),
                    "col5": f"{s.enrollment:,}",
                }
            )

    elif metric == "no_ssa":
        title = "Schools without SSA"
        description = (
            "Active schools lacking current-FY Self-School Assessment reports."
        )
        headers = [
            "School ID",
            "School Name",
            "District",
            "Account Owner",
            "SSA Status",
        ]

        for s in schools.filter(current_fy_ssa_status__in=["not_done", "scheduled"])[
            :100
        ]:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": s.account_owner.user.name if s.account_owner else "-",
                    "col5": s.get_current_fy_ssa_status_display(),
                }
            )

    elif metric == "not_visited":
        title = "Schools not visited"
        description = "Schools without a completed staff visit in the last 60+ days."
        headers = [
            "School ID",
            "School Name",
            "District",
            "Account Owner",
            "SSA Status",
        ]

        sixty_days_ago = timezone.now() - timedelta(days=60)
        visited_schools = (
            Activity.objects.filter(
                deleted_at__isnull=True,
                activity_type__in=[
                    "school_visit",
                    "follow_up_visit",
                    "coaching_visit",
                    "core_visit",
                ],
                status__in=["completed", "ia_verified", "accountant_confirmed"],
                scheduled_date__gte=sixty_days_ago,
            )
            .values_list("school_id", flat=True)
            .distinct()
        )

        for s in schools.exclude(id__in=visited_schools)[:100]:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": s.account_owner.user.name if s.account_owner else "-",
                    "col5": s.get_current_fy_ssa_status_display(),
                }
            )

    elif metric == "not_trained":
        title = "Schools not trained"
        description = "Schools that have not participated in any training workshops in this quarter."
        headers = [
            "School ID",
            "School Name",
            "District",
            "Account Owner",
            "SSA Status",
        ]

        trained_schools = (
            Activity.objects.filter(
                deleted_at__isnull=True,
                activity_type__in=[
                    "training",
                    "school_improvement_training",
                    "cluster_training",
                    "core_training",
                ],
                status__in=["completed", "ia_verified", "accountant_confirmed"],
                quarter=quarter,
            )
            .values_list("school_id", flat=True)
            .distinct()
        )

        for s in schools.exclude(id__in=trained_schools)[:100]:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": s.account_owner.user.name if s.account_owner else "-",
                    "col5": s.get_current_fy_ssa_status_display(),
                }
            )

    else:
        # Fallback trace listing
        title = f"{metric.replace('_', ' ').title()} Records"
        headers = ["Name / Identifier", "Details", "Month", "Verification Code"]
        for s in schools[:20]:
            rows.append(
                {
                    "col1": s.name,
                    "col2": s.school_type.title(),
                    "col3": quarter,
                    "col4": s.school_id,
                }
            )

    context = {
        "title": title,
        "description": description,
        "headers": headers,
        "rows": rows,
        "drawer_size": "lg",
    }
    return render(request, "partials/analytics/drilldown_drawer.html", context)


@require_page_permission("analytics")
def analytics_schedule_report_view(request):
    """GET to render the Schedule Report configurations drawer."""
    context = {
        "drawer_size": "sm",
    }
    return render(request, "partials/analytics/schedule_report_drawer.html", context)


@require_page_permission("analytics")
def analytics_customize_dashboard_view(request):
    """GET to render the Customize Dashboard configurations drawer."""
    context = {
        "drawer_size": "sm",
    }
    return render(
        request, "partials/analytics/customize_dashboard_drawer.html", context
    )


@require_page_permission("system_health")
def system_health_view(request):
    from apps.system_health.services import report as system_health_report

    health = system_health_report()
    context = {
        "health": health,
    }
    return render(request, "pages/system_health/index.html", context)
