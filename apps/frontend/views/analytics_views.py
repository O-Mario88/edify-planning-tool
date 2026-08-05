import csv
import datetime
import hashlib
import json

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from apps.core.permissions import require_export_permission, require_page_permission
from django.utils import timezone
from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.core.fy import get_operational_fy
from apps.geography.models import Region, District
from apps.clusters.models import Cluster
from apps.partners.models import Partner
from apps.accounts.models import StaffProfile
from apps.schools.models import School
from apps.activities.models import Activity
from apps.analytics.analytics_dashboard_service import AnalyticsDashboardService
from apps.core.cache_utils import stampede_safe_get_or_compute


def _analytics_filters(request):
    """Return the supported analytics filters from the current request."""
    return {
        "fy": request.GET.get("fy"),
        "quarter": request.GET.get("quarter"),
        "district": request.GET.get("district"),
        "cluster": request.GET.get("cluster"),
        "staff": request.GET.get("staff"),
        "partner": request.GET.get("partner"),
        "school_type": request.GET.get("school_type"),
        "activity_type": request.GET.get("activity_type"),
        "q": request.GET.get("q"),
    }


@require_page_permission("analytics")
def analytics_dashboard_view(request):
    """GET to render the primary Analytics Dashboard with filters."""
    # 1. Gather all filters from GET parameters
    filters = _analytics_filters(request)

    # 2. Call Service to gather all dashboard datasets
    filter_fingerprint = hashlib.sha256(
        json.dumps(filters, sort_keys=True, default=str).encode()
    ).hexdigest()[:20]
    analytics_key = (
        f"analytics-dashboard:v1:{request.user.id}:"
        f"{request.user.active_role}:{filter_fingerprint}"
    )
    data = stampede_safe_get_or_compute(
        analytics_key,
        lambda: AnalyticsDashboardService.get_analytics_data(request.user, filters),
        timeout=settings.ANALYTICS_DASHBOARD_CACHE_SECONDS,
    )
    from apps.analytics.models import (
        DEFAULT_ANALYTICS_CARDS,
        AnalyticsDashboardPreference,
    )
    from apps.analytics.report_delivery import CARD_CATEGORY

    preference = AnalyticsDashboardPreference.objects.filter(
        user_id=request.user.id
    ).first()
    visible_cards = preference.visible_cards if preference else DEFAULT_ANALYTICS_CARDS
    data["kpi_strip_items"] = [
        item
        for item in data.get("kpi_strip_items", [])
        if CARD_CATEGORY.get(item.get("label"), "reach") in visible_cards
    ]
    analytics_layout = preference.layout if preference else "grid"

    # 3. Retrieve options list for dropdown filters
    #
    # Derived from the schools this user can actually reach, so every option is
    # a place results can come from. Listing every district in the country put
    # more than a hundred dead ends in a control whose whole job is to narrow —
    # and picking one returned an empty page that looked identical to a broken
    # filter.
    from apps.core.scoping import resolve_user_scope, school_queryset

    _scope = resolve_user_scope(request.user)
    _scoped_schools = school_queryset(_scope).filter(deleted_at__isnull=True)

    regions = Region.objects.all().order_by("name")
    districts = (
        District.objects.filter(id__in=_scoped_schools.values("district_id"))
        .distinct()
        .order_by("name")
    )
    # Cluster carries its own district, so it scopes through the same set
    # rather than through School.cluster_id, which is a CharField.
    clusters = (
        Cluster.objects.filter(district_id__in=_scoped_schools.values("district_id"))
        .distinct()
        .order_by("name")
    )
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
        "analytics_layout": analytics_layout,
        # The service has always narrowed schools, activities and SSA by `q`;
        # there was simply no control anywhere on the page to type it into, so
        # the top bar showed the generic global form and a working backend
        # search sat unreachable. It filters the entity lists behind the
        # numbers — never the charts' rendered labels.
        "topbar_search": {
            "placeholder": "Search analytics records…",
            "label": "Search analytics by school, School ID, cluster or staff",
            "name": "q",
            "value": filters.get("q") or "",
            "hx_get": "/analytics",
            "hx_target": "#analytics-kpi-and-content-container",
            "hx_trigger": "keyup changed delay:300ms, search",
            "hx_include": "#analytics-filters-form",
        },
    }

    # If HTMX request, render only content cards to swap
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/analytics/kpi_cards.html", context)

    return render(request, "pages/analytics/index.html", context)


@require_page_permission("analytics")
@require_export_permission
def analytics_export_view(request):
    """Download the caller's current role-scoped analytics KPIs as CSV."""
    data = AnalyticsDashboardService.get_analytics_data(
        request.user, _analytics_filters(request)
    )
    generated = timezone.localtime().strftime("%Y-%m-%d %H:%M %Z")
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="edify-analytics-{timezone.localdate().isoformat()}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(["Metric", "Value", "Context", "Generated at"])
    for card in data.get("kpi_strip_items", []):
        writer.writerow(
            [
                card.get("label", ""),
                card.get("value", ""),
                card.get("helper", ""),
                generated,
            ]
        )
    return response


@require_page_permission("pl_analytics")
def pl_analytics_view(request):
    """Program Lead Analytics — the supervised-team decision cockpit.

    Full page on a normal GET; the analytics body partial on an HX-Request so
    the filter row swaps only `#pl-analytics-body` (charts re-init via Alpine).
    Everything is scoped to the PL's supervised team by PLAnalyticsService."""
    from apps.analytics.pl_analytics_service import PLAnalyticsService

    filters = {
        "district": request.GET.get("district"),
        "cluster": request.GET.get("cluster"),
        "cceo": request.GET.get("cceo"),
        "partner": request.GET.get("partner"),
        "school_type": request.GET.get("school_type"),
        "activity_type": request.GET.get("activity_type"),
        "quarter": request.GET.get("quarter"),
    }
    fy = (request.GET.get("fy") or "").strip() or None
    quarter = (request.GET.get("quarter") or "").strip() or None

    data = PLAnalyticsService.get_dashboard(
        request.user,
        fy=fy,
        quarter=quarter,
        filters=filters,
        include_regional_map=True,
    )
    context = {
        **data,
        "timestamp": timezone.now().strftime("%B %d, %Y %I:%M %p"),
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/analytics/pl/body.html", context)
    return render(request, "pages/analytics/pl_analytics.html", context)


@require_page_permission("pl_analytics")
@require_export_permission
def pl_analytics_export_view(request):
    """CSV export of the PL's at-risk school list — scoped to the supervised
    portfolio (never another PL's schools)."""
    import csv

    from django.http import HttpResponse

    from apps.analytics.pl_analytics_service import PLAnalyticsService

    fy = (request.GET.get("fy") or "").strip() or None
    quarter = (request.GET.get("quarter") or "").strip() or None
    filters = {
        "district": request.GET.get("district"),
        "cluster": request.GET.get("cluster"),
        "cceo": request.GET.get("cceo"),
        "school_type": request.GET.get("school_type"),
    }
    rows = PLAnalyticsService.export_rows(
        request.user, fy=fy, quarter=quarter, filters=filters
    )
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="pl_analytics_risk.csv"'
    w = csv.writer(resp)
    w.writerow(
        ["School", "District", "Issue", "Last Visit", "Last Training", "Next Action"]
    )
    for r in rows:
        w.writerow(
            [
                r["school"],
                r["district"],
                r["issue"],
                r["last_visit"],
                r["last_training"],
                r["next_action"],
            ]
        )
    return resp


@require_page_permission("pl_analytics")
def pl_analytics_drilldown_view(request):
    """Role-scoped drill-down drawer for the PL cockpit (district / cluster /
    CCEO / risk-list / KPI). Renders into the global #drawer-container."""
    from apps.analytics.pl_analytics_service import PLAnalyticsService

    drill = (request.GET.get("drill") or "").strip()
    fy = (request.GET.get("fy") or "").strip() or None
    quarter = (request.GET.get("quarter") or "").strip() or None
    filters = {
        "district": request.GET.get("district"),
        "cluster": request.GET.get("cluster"),
        "cceo": request.GET.get("cceo"),
        "school_type": request.GET.get("school_type"),
        "activity_type": request.GET.get("activity_type"),
    }
    payload = PLAnalyticsService.drilldown(
        request.user, drill, request.GET, fy=fy, quarter=quarter, filters=filters
    )
    context = {"drill": drill, "drawer_size": "lg", **payload}
    return render(request, "partials/analytics/pl/drilldown.html", context)


@require_page_permission("analytics")
def analytics_drilldown_view(request):
    """GET to render the detailed trace records drawer."""
    metric = request.GET.get("metric", "").strip()
    fy = request.GET.get("fy") or get_operational_fy()
    quarter = request.GET.get("quarter") or "Q2"

    from apps.core.scoping import resolve_user_scope

    def _owner_names(school_rows):
        """Resolve account-owner display names for a batch of schools.

        School.account_owner_id is a plain CharField holding a user id -- there
        is no `account_owner` relation, so `s.account_owner` raises
        AttributeError on the FIRST row rendered. A previous fix removed the
        equally-invalid select_related("account_owner__user") but left the
        attribute access in place, so this endpoint still 500'd for any metric
        that actually returned rows. It only looked fixed because the fixtures
        used to verify it returned none.

        One query for the whole page rather than one per row.
        """
        owner_ids = {s.account_owner_id for s in school_rows if s.account_owner_id}
        if not owner_ids:
            return {}
        from apps.accounts.models import User

        return dict(User.objects.filter(id__in=owner_ids).values_list("id", "name"))

    def _owner_label(school, owner_names):
        # Fall back to the denormalised raw name before giving up: an owner may
        # legitimately predate the user record (Salesforce import), and "-" for
        # a school that does have a named owner is a worse answer.
        return (
            owner_names.get(school.account_owner_id)
            or school.account_owner_name_raw
            or "-"
        )

    # Base filter criteria are constrained before any metric-specific query.
    # The dashboard service already scopes aggregates; drill-down records must
    # obey the same boundary so a URL cannot reveal another portfolio.
    activities = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    # account_owner_id is a plain CharField holding a user id, not a
    # ForeignKey, so select_related("account_owner__user") raises FieldError
    # and this endpoint returned HTTP 500 for every metric. Only `district` is
    # a real relation here.
    schools = School.objects.filter(deleted_at__isnull=True).select_related("district")
    scope = resolve_user_scope(request.user)
    if scope.can_view_summary_only:
        activities = activities.none()
        schools = schools.none()
    elif not scope.country_scope:
        schools = schools.filter(id__in=scope.school_ids)
        activities = activities.filter(school_id__in=scope.school_ids)
        if scope.partner_ids:
            activities = activities.filter(assigned_partner_id__in=scope.partner_ids)

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
                status__in=COMPLETED_WORK_STATUSES,
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

        batch = list(
            schools.filter(current_fy_ssa_status__in=["not_done", "scheduled"])[:100]
        )
        owner_names = _owner_names(batch)
        for s in batch:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": _owner_label(s, owner_names),
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

        sixty_days_ago = timezone.now() - datetime.timedelta(days=60)
        visited_schools = (
            Activity.objects.filter(
                deleted_at__isnull=True,
                activity_type__in=[
                    "school_visit",
                    "follow_up_visit",
                    "coaching_visit",
                    "core_visit",
                ],
                status__in=COMPLETED_WORK_STATUSES,
                scheduled_date__gte=sixty_days_ago,
            )
            .values_list("school_id", flat=True)
            .distinct()
        )

        batch = list(schools.exclude(id__in=visited_schools)[:100])
        owner_names = _owner_names(batch)
        for s in batch:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": _owner_label(s, owner_names),
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
                status__in=COMPLETED_WORK_STATUSES,
                quarter=quarter,
            )
            .values_list("school_id", flat=True)
            .distinct()
        )

        batch = list(schools.exclude(id__in=trained_schools)[:100])
        owner_names = _owner_names(batch)
        for s in batch:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": _owner_label(s, owner_names),
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
    """Send a permission-scoped analytics snapshot to Messages immediately."""
    from apps.analytics.forms import AnalyticsInboxSnapshotForm
    from apps.analytics.report_delivery import send_analytics_snapshot
    from apps.audit.services import log as audit_log

    if request.method == "POST":
        form = AnalyticsInboxSnapshotForm(request.POST)
        if form.is_valid():
            try:
                thread = send_analytics_snapshot(
                    user=request.user,
                    categories=form.cleaned_data["categories"],
                )
            except RuntimeError:
                form.add_error(
                    None,
                    "The snapshot could not be delivered. Nothing was sent; please try again.",
                )
            else:
                audit_log(
                    action="analytics_snapshot_sent",
                    subject_kind="MessageThread",
                    subject_id=str(thread.id),
                    actor_id=str(request.user.id),
                    actor_role=request.user.active_role,
                    reason="User sent an analytics snapshot to their private inbox",
                    payload={
                        "categories": form.cleaned_data["categories"],
                        "recipient_user_id": str(request.user.id),
                        "channel": "in_app",
                    },
                )
                response = render(
                    request,
                    "partials/schools/toast_success.html",
                    {"message": "Analytics snapshot sent to your inbox."},
                )
                response["HX-Trigger"] = "close-drawer"
                return response
    else:
        form = AnalyticsInboxSnapshotForm(
            initial={"categories": ["targets", "training", "reach", "ssa"]}
        )
    context = {
        "drawer_size": "sm",
        "form": form,
    }
    return render(request, "partials/analytics/schedule_report_drawer.html", context)


@require_page_permission("analytics")
def analytics_customize_dashboard_view(request):
    """Persist the caller's KPI visibility and density preferences."""
    from apps.analytics.forms import AnalyticsDashboardPreferenceForm
    from apps.analytics.models import (
        AnalyticsDashboardPreference,
        DEFAULT_ANALYTICS_CARDS,
    )
    from apps.audit.services import log as audit_log

    preference = AnalyticsDashboardPreference.objects.filter(
        user_id=request.user.id
    ).first()
    if request.method == "POST":
        form = AnalyticsDashboardPreferenceForm(request.POST, instance=preference)
        if form.is_valid():
            preference = form.save(commit=False)
            preference.user_id = request.user.id
            preference.save()
            audit_log(
                action="analytics_dashboard_preference_saved",
                subject_kind="AnalyticsDashboardPreference",
                subject_id=str(preference.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                reason="User updated analytics presentation preferences",
                payload={
                    "layout": preference.layout,
                    "visible_cards": preference.visible_cards,
                },
            )
            response = render(
                request,
                "partials/schools/toast_success.html",
                {"message": "Analytics dashboard preferences saved."},
            )
            response["HX-Trigger"] = "close-drawer"
            response["HX-Refresh"] = "true"
            return response
    else:
        form = AnalyticsDashboardPreferenceForm(
            instance=preference,
            initial={"visible_cards": DEFAULT_ANALYTICS_CARDS, "layout": "grid"},
        )
    context = {
        "drawer_size": "sm",
        "form": form,
    }
    return render(
        request, "partials/analytics/customize_dashboard_drawer.html", context
    )


@require_page_permission("system_health")
def system_health_view(request):
    from apps.system_health.services import report as system_health_report

    health = stampede_safe_get_or_compute(
        "system-health-dashboard:v1",
        system_health_report,
        timeout=settings.SYSTEM_HEALTH_DASHBOARD_CACHE_SECONDS,
    )
    # The template reads workflow counts as top-level keys (health.unclusteredSchools
    # etc.), but report() nests them under workflowIssues — flatten them in.
    context = {
        "health": {**health, **health["workflowIssues"]},
    }
    return render(request, "pages/system_health/index.html", context)


# ── Country Director Analytics — national leadership-intelligence cockpit ──────
def _cd_filters(request):
    return {
        "pl": request.GET.get("pl"),
        "cceo": request.GET.get("cceo"),
        "district": request.GET.get("district"),
        "cluster": request.GET.get("cluster"),
        "partner": request.GET.get("partner"),
        "activity_type": request.GET.get("activity_type"),
        "quarter": request.GET.get("quarter"),
        "month": request.GET.get("month"),
    }


@require_page_permission("cd_analytics")
def cd_analytics_view(request):
    """Country Director Analytics — the national leadership cockpit.

    Country-wide intelligence across every PL, CCEO, district, region, partner,
    cluster and school. Full page on a normal GET; the analytics body partial on
    an HX-Request so the filter row swaps only `#cd-analytics-body`. The CD sees
    everything but acts only through oversight workflows — CDAnalyticsService
    never emits field-execution actions."""
    from apps.analytics.cd_analytics_service import CDAnalyticsService

    fy = (request.GET.get("fy") or "").strip() or None
    quarter = (request.GET.get("quarter") or "").strip() or None
    month = (request.GET.get("month") or "").strip() or None
    data = CDAnalyticsService.get_dashboard(
        request.user,
        fy=fy,
        quarter=quarter,
        month=month,
        filters=_cd_filters(request),
        include_regional_map=True,
    )
    # Month-of-FY labels (FY starts in October).
    _fy_months = [
        "Oct",
        "Nov",
        "Dec",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
    ]
    month_options = [(str(i + 1), lbl) for i, lbl in enumerate(_fy_months)]
    context = {
        **data,
        "month_options": month_options,
        "month": (month or ""),
        # The heatmap ships rendered at district and swaps level on demand; the
        # tabs need their labels on the first paint too.
        "heatmap_levels": _heatmap_level_choices(),
        "timestamp": timezone.now().strftime("%B %d, %Y %I:%M %p"),
    }
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/analytics/cd/body.html", context)
    return render(request, "pages/analytics/cd_analytics.html", context)


@require_page_permission("cd_analytics")
def cd_ssa_heatmap_view(request):
    """One level of the SSA heatmap, fetched on demand by the card's tabs.

    Separate from the page so switching level costs one small partial rather
    than rebuilding the whole CD cockpit — and so the three levels nobody is
    looking at are never computed. The page ships with district rendered; the
    rest arrive when asked for.
    """
    from apps.analytics.cd_analytics_service import CDAnalyticsService, resolve_cd_scope

    level = (request.GET.get("level") or "district").strip()
    # `get_dashboard` normalises this before resolving scope; calling
    # resolve_cd_scope directly does not, and a None fy reaches a queryset as
    # `fy=None` — "Cannot use None as a query value", a 500 on a bare GET.
    # The route crawl caught it.
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    quarter = (request.GET.get("quarter") or "").strip() or None
    month = (request.GET.get("month") or "").strip() or None
    cd = resolve_cd_scope(fy, quarter=quarter, month=month)
    return render(
        request,
        "partials/analytics/cd/district_heatmap.html",
        {
            "district_heatmap": CDAnalyticsService.ssa_heatmap(cd, level),
            "heatmap_levels": _heatmap_level_choices(),
            "fy": fy,
            "quarter": quarter or "",
            "month": month or "",
        },
    )


def _heatmap_level_choices():
    """(value, label) for the SSA heatmap's level tabs, in geographic order.

    Ordered widest-first because that is how somebody reads down to a problem —
    sub-region to district to sub-county — with cluster last since it cuts
    across geography rather than nesting inside it. HEATMAP_LEVELS is declared
    in that order, so it is the order.

    Derived from HEATMAP_LEVELS rather than repeated here. This used to hold
    its own `order` list filtered by `if key in levels`, which meant a level
    present in one and absent from the other vanished in silence: renaming
    `region` to `sub_region` left `region` in the order (dropped, no longer a
    level) and `sub_region` out of it (dropped, not in the order), so the
    heatmap lost a tab while every level still worked when requested by URL.
    A list that must agree with another list eventually will not.
    """
    from apps.analytics.cd_analytics_service import CDAnalyticsService

    return [(key, spec[2]) for key, spec in CDAnalyticsService.HEATMAP_LEVELS.items()]


@require_page_permission("cd_analytics")
def cd_analytics_drilldown_view(request):
    """Oversight-only drill-down drawer for the CD cockpit (PL / CCEO / district /
    region / partner / cluster / risk / budget). Every payload is read/oversight —
    it never exposes field-execution actions."""
    from apps.analytics.cd_analytics_service import CDAnalyticsService

    drill = (request.GET.get("drill") or "").strip()
    fy = (request.GET.get("fy") or "").strip() or None
    quarter = (request.GET.get("quarter") or "").strip() or None
    month = (request.GET.get("month") or "").strip() or None
    payload = CDAnalyticsService.drilldown(
        request.user,
        drill,
        request.GET,
        fy=fy,
        quarter=quarter,
        month=month,
        filters=_cd_filters(request),
    )
    context = {"drill": drill, "drawer_size": "lg", **payload}
    return render(request, "partials/analytics/cd/drilldown.html", context)


@require_page_permission("cd_analytics")
@require_export_permission
def cd_analytics_export_view(request):
    """CSV export of the CD's country oversight roster (PL performance + risk).
    Read-only export; respects the CD role gate."""
    import csv

    from django.http import HttpResponse

    from apps.analytics.cd_analytics_service import CDAnalyticsService

    fy = (request.GET.get("fy") or "").strip() or None
    quarter = (request.GET.get("quarter") or "").strip() or None
    month = (request.GET.get("month") or "").strip() or None
    rows = CDAnalyticsService.export_rows(
        request.user, fy=fy, quarter=quarter, month=month, filters=_cd_filters(request)
    )
    resp = HttpResponse(content_type="text/csv")
    resp["Content-Disposition"] = 'attachment; filename="cd_analytics_pl_oversight.csv"'
    w = csv.writer(resp)
    w.writerow(
        [
            "PL",
            "CCEOs Supervised",
            "Target Achievement %",
            "School Visits %",
            "Cluster Meetings %",
            "Cluster Trainings %",
            "SSA Completed %",
            "MSCS %",
            "Schools at Risk",
            "Budget Utilization %",
            "Backlog",
            "Risk Status",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r["name"],
                r["cceos"],
                r["target_pct"],
                *[
                    area["pct"] if area["pct"] is not None else "Not set"
                    for area in r["areas"]
                ],
                r["schools_at_risk"],
                r["budget_util"],
                r["backlog"],
                r["risk"],
            ]
        )
    return resp


@require_POST
@require_page_permission("analytics")
def combine_map_boundaries_view(request):
    """Combine sub-county rows for the boundaries the map matched.

    The browser does the geometry -- matching GeoJSON polygons to metric rows,
    which is presentation work -- and posts the matching here once, when the
    layer is drawn. The arithmetic happens on the server, where it has one
    implementation and tests behind it.
    """
    import json

    from apps.analytics.subcounty_insight import combine_boundaries

    try:
        payload = json.loads(request.body.decode() or "{}")
    except ValueError:
        return JsonResponse({"detail": "Invalid payload."}, status=400)

    groups = payload.get("groups")
    if not isinstance(groups, dict):
        return JsonResponse({"detail": "`groups` must be an object."}, status=400)
    # A country has a few thousand sub-counties; anything beyond that is not a
    # map draw.
    if len(groups) > 5000:
        return JsonResponse({"detail": "Too many boundaries."}, status=400)

    cleaned = {
        str(feature_id): [str(key) for key in (keys or [])][:200]
        for feature_id, keys in list(groups.items())[:5000]
    }
    return JsonResponse({"combined": combine_boundaries(cleaned)})


@require_GET
@require_page_permission("analytics")
def map_subcounty_metrics_view(request):
    """Return fresh marker aggregates for one district map drill-down.

    Dashboard HTML is deliberately cached, but school geography is mutable.
    Keeping this small response uncached lets a saved sub-county/parish move a
    marker immediately without discarding the much larger analytics cache or
    refetching country-wide boundary geometry.
    """
    district_id = (request.GET.get("district_id") or "").strip()
    district = District.objects.filter(id=district_id).first()
    if district is None:
        return JsonResponse({"detail": "District not found."}, status=404)

    fy = (request.GET.get("fy") or get_operational_fy()).strip()
    if not fy.isdigit():
        return JsonResponse({"detail": "Fiscal year must be numeric."}, status=400)

    from apps.analytics.subcounty_insight import subcounty_insight

    payload = subcounty_insight(
        fy,
        schools=School.objects.filter(
            deleted_at__isnull=True,
            district_id=district.id,
        ),
    )
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response
