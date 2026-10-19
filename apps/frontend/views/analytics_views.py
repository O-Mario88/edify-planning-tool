import datetime
import json

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST
from apps.core.permissions import (
    require_export_permission,
    require_page_permission,
)
from django.utils import timezone
from apps.core.activity_types import COMPLETED_WORK_STATUSES
from apps.core.fy import get_operational_fy
from apps.geography.models import District
from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.analytics.analytics_dashboard_service import (
    ACHIEVED_STATUSES,
    AnalyticsDashboardService,
)
from apps.core.cache_utils import stampede_safe_get_or_compute
from apps.schools.lifecycle_service import active_schools


#: The filters Analytics understands; anything else a request carries is ignored.
ANALYTICS_FILTER_KEYS = (
    "fy",
    "quarter",
    "month",
    "region",
    "pl",
    "cceo",
    "sub_region",
    "district",
    "sub_county",
    "cluster",
    "staff",
    "partner",
    "school_type",
    "activity_type",
    "q",
)


def _analytics_filters(request, source=None):
    """Return the supported analytics filters from the current request (or
    from `source`, a submitted form's data)."""
    data = request.GET if source is None else source
    return {key: data.get(key) for key in ANALYTICS_FILTER_KEYS}


@require_page_permission("analytics")
@require_export_permission
def analytics_export_view(request):
    """Download the caller's current role-scoped analytics KPIs, as an Excel
    workbook (owner, 2026-09-27); ``?format=csv`` still answers as CSV."""
    from apps.core.excel import table_download

    data = AnalyticsDashboardService.get_analytics_data(
        request.user, _analytics_filters(request)
    )
    generated = timezone.localtime().strftime("%Y-%m-%d %H:%M %Z")
    rows = [
        [
            card.get("label", ""),
            card.get("value", ""),
            card.get("helper", ""),
            generated,
        ]
        for card in data.get("kpi_strip_items", [])
    ]
    return table_download(
        request,
        f"edify-analytics-{timezone.localdate().isoformat()}",
        [
            {
                "title": "Analytics",
                "headers": ["Metric", "Value", "Context", "Generated at"],
                "rows": rows,
            }
        ],
    )


@require_page_permission("pl_analytics")
@require_export_permission
def pl_analytics_export_view(request):
    """CSV export of the PL's at-risk school list — scoped to the supervised
    portfolio (never another PL's schools)."""

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
    from apps.core.excel import safe_csv_writer

    w = safe_csv_writer(resp)
    # Every export that lists schools carries the School ID (owner,
    # 2026-10-19), the business code beside the name.
    w.writerow(
        [
            "School ID",
            "School Name",
            "District",
            "Issue",
            "Last Visit",
            "Last Training",
            "Next Action",
        ]
    )
    for r in rows:
        w.writerow(
            [
                r["school_id"],
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
    # The cockpit's filters, as the tile that opened this drawer was computed
    # under them (the service appends them to every drill-down link).
    filters = {
        "district": request.GET.get("district"),
        "cluster": request.GET.get("cluster"),
        "cceo": request.GET.get("cceo"),
        "partner": request.GET.get("partner"),
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
    schools = active_schools().select_related("district")
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
                    # The school the row names, where it names one, so its
                    # name opens the profile (owner, 2026-10-08).
                    "school_ref": a.school.school_id if a.school else "",
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
            # The tile's own rule (AnalyticsDashboardService), so the list
            # is the schools the number counted.
            activities.filter(
                quarter=quarter,
                status__in=ACHIEVED_STATUSES,
                school_id__isnull=False,
            )
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

    # The snapshot is the report on screen (controls audit F-06, 2026-09-14):
    # the drawer opens with the page's filters and posts them back, and the
    # delivery reads the same canonical filters the CSV export reads. The
    # service still applies the reader's own permission scope.
    source = request.POST if request.method == "POST" else request.GET
    filters = {
        key: value
        for key, value in _analytics_filters(request, source).items()
        if value
    }
    if request.method == "POST":
        form = AnalyticsInboxSnapshotForm(request.POST)
        if form.is_valid():
            try:
                thread = send_analytics_snapshot(
                    user=request.user,
                    categories=form.cleaned_data["categories"],
                    filters=filters,
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
                        "filters": filters,
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
        "filters": filters,
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
from apps.analytics.cd_export_service import dataset_label  # noqa: E402


def _cd_filters(request):
    return {
        "pl": request.GET.get("pl"),
        "cceo": request.GET.get("cceo"),
        # The Region select has been on this filter row all along and the
        # service has always supported it (cd_analytics_service scopes schools
        # by region_id), but it was never put in the dict — so choosing a
        # region did nothing at all (2026-09-06).
        "region": request.GET.get("region"),
        "district": request.GET.get("district"),
        "cluster": request.GET.get("cluster"),
        "partner": request.GET.get("partner"),
        "activity_type": request.GET.get("activity_type"),
        "quarter": request.GET.get("quarter"),
        "month": request.GET.get("month"),
    }


@require_page_permission("cd_analytics")
def cd_ssa_heatmap_view(request):
    """One level of the SSA heatmap, fetched on demand by the card's tabs.

    Separate from the page so switching level costs one small partial rather
    than rebuilding the whole CD cockpit — and so the three levels nobody is
    looking at are never computed. The page ships with district rendered; the
    rest arrive when asked for.
    """
    from apps.analytics.cd_analytics_service import (
        CDAnalyticsService,
        country_for,
        resolve_cd_scope,
    )

    level = (request.GET.get("level") or "district").strip()
    # `get_dashboard` normalises this before resolving scope; calling
    # resolve_cd_scope directly does not, and a None fy reaches a queryset as
    # `fy=None` — "Cannot use None as a query value", a 500 on a bare GET.
    # The route crawl caught it.
    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    quarter = (request.GET.get("quarter") or "").strip() or None
    month = (request.GET.get("month") or "").strip() or None
    cd = resolve_cd_scope(
        fy, quarter=quarter, month=month, country=country_for(request.user)
    )
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

    # Widest first, following the real hierarchy:
    # Region -> Sub-Region -> District -> Sub-County. Cluster is last
    # because it cuts across geography rather than nesting inside it.
    order = ["region", "sub_region", "district", "sub_county", "cluster"]
    levels = CDAnalyticsService.HEATMAP_LEVELS
    return [(key, levels[key][2]) for key in order if key in levels]


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
    """The CD's country export, for the cockpit's current period.

    One Export button, one Excel workbook (owner, 2026-09-27: "export buttons
    dont have to be two buttons. It should be export in excel not csv"): a
    sheet per dataset. ``?set=delivery|risk|finance|core|impact`` narrows it
    to one dataset, and ``?format=csv`` answers that dataset as CSV for links
    that already ask for it. The FY, quarter, month and filters are the ones
    the page is showing. Read-only; respects the CD role gate and the export
    permission."""
    from apps.analytics.cd_export_service import (
        DATASETS,
        country_export,
        normalise_dataset,
    )
    from apps.core.excel import table_download

    fy = (request.GET.get("fy") or "").strip() or None
    quarter = (request.GET.get("quarter") or "").strip() or None
    month = (request.GET.get("month") or "").strip() or None
    wanted = (request.GET.get("set") or "").strip()
    csv_asked = (request.GET.get("format") or "").strip().lower() == "csv"
    datasets = [normalise_dataset(wanted)] if wanted or csv_asked else list(DATASETS)
    sheets, slugs = [], []
    for dataset in datasets:
        slug, header, rows = country_export(
            request.user,
            dataset,
            fy=fy,
            quarter=quarter,
            month=month,
            filters=_cd_filters(request),
        )
        slugs.append(slug)
        sheets.append(
            {"title": dataset_label(dataset), "headers": header, "rows": rows}
        )
    stem = slugs[0] if len(slugs) == 1 else "country"
    return table_download(request, f"cd-{stem}-{fy or get_operational_fy()}", sheets)


@require_POST
@require_page_permission("analytics")
def combine_map_boundaries_view(request):
    """Combine sub-county rows for the boundaries the map matched.

    The browser does the geometry -- matching GeoJSON polygons to metric rows,
    which is presentation work -- and posts the matching here once, when the
    layer is drawn. The arithmetic happens on the server, where it has one
    implementation and tests behind it.
    """

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
        schools=active_schools().filter(district_id=district.id),
    )
    response = JsonResponse(payload)
    response["Cache-Control"] = "private, no-store"
    return response
