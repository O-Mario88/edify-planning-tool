import csv
from datetime import timedelta
from django.db.models import Avg
from django.http import HttpResponse
from django.shortcuts import render
from apps.core.permissions import require_page_permission
from django.utils import timezone
from apps.core.fy import get_operational_fy, get_quarter_for_date, fy_options
from apps.core.scoping import resolve_user_scope
from apps.geography.models import Region, District
from apps.clusters.models import Cluster
from apps.partners.models import Partner
from apps.accounts.models import StaffProfile, Report
from apps.schools.models import School
from apps.activities.models import Activity
from apps.ssa.models import SsaRecord
from apps.analytics.analytics_dashboard_service import AnalyticsDashboardService

# KPI strip items carry a stable `code` (set by AnalyticsDashboardService) so
# the Customize Dashboard drawer can persist per-user visibility choices in
# the session without needing a new model/migration.
KPI_TOGGLE_GROUPS = [
    ("target_achievement", "Overall Target Achievement"),
    ("teachers_trained", "Teachers & Leaders Trained"),
    ("students_impacted", "Students & Schools Impacted"),
    ("districts_covered", "Districts & Clusters Covered"),
    ("activities_completed", "Activities Completed"),
    ("ssa_average", "SSA Average Performance"),
]
# leaders_trained/schools_impacted/clusters_covered ride along with their
# paired toggle so one checkbox controls both related KPI tiles.
KPI_TOGGLE_PAIRS = {
    "teachers_trained": ["teachers_trained", "leaders_trained"],
    "students_impacted": ["students_impacted", "schools_impacted"],
    "districts_covered": ["districts_covered", "clusters_covered"],
}


def _role_scope_text(scope) -> str:
    if scope.country_scope:
        return "Showing all schools, activities and SSA records nationwide."
    if scope.can_view_summary_only:
        return "Showing a regional summary for your assigned region(s) only."
    if scope.own_school_ids or scope.team_school_ids:
        return "Showing your own and supervised team's assigned schools only."
    if scope.partner_ids:
        return "Showing activities assigned to your partner organization only."
    return "Showing data scoped to your account — no assignments found yet."


def _build_filter_fields(
    filters, regions, districts, clusters, staff_profiles, partners
):
    def opts(pairs, selected):
        return [
            {"value": v, "label": lbl, "selected": (str(v) == str(selected))}
            for v, lbl in pairs
        ]

    selected = filters
    fy_pairs = [(fy, f"FY {fy}") for fy in fy_options()]
    quarter_pairs = [
        ("Q1", "Q1 (Oct-Dec)"),
        ("Q2", "Q2 (Jan-Mar)"),
        ("Q3", "Q3 (Apr-Jun)"),
        ("Q4", "Q4 (Jul-Sep)"),
    ]
    school_type_pairs = [
        ("All", "All"),
        ("core", "Core"),
        ("champion", "Champion"),
        ("client", "Client"),
    ]
    activity_type_pairs = [
        ("All", "All"),
        ("school_visit", "School Visit"),
        ("cluster_training", "Cluster Training"),
        ("cluster_meeting", "Cluster Meeting"),
        ("ssa_activity", "SSA Support"),
    ]

    return [
        {
            "name": "fy",
            "label": "Fiscal Year",
            "options": opts(fy_pairs, selected["selected_fy"]),
        },
        {
            "name": "quarter",
            "label": "Quarter",
            "options": opts(quarter_pairs, selected["selected_quarter"]),
        },
        {
            "name": "region",
            "label": "Region",
            "options": [
                {
                    "value": "",
                    "label": "All",
                    "selected": not selected["selected_region"],
                }
            ]
            + opts([(r.id, r.name) for r in regions], selected["selected_region"]),
        },
        {
            "name": "district",
            "label": "District",
            "options": [
                {
                    "value": "",
                    "label": "All",
                    "selected": not selected["selected_district"],
                }
            ]
            + opts([(d.id, d.name) for d in districts], selected["selected_district"]),
        },
        {
            "name": "cluster",
            "label": "Cluster",
            "options": [
                {
                    "value": "",
                    "label": "All",
                    "selected": not selected["selected_cluster"],
                }
            ]
            + opts([(c.id, c.name) for c in clusters], selected["selected_cluster"]),
        },
        {
            "name": "staff",
            "label": "Staff",
            "options": [
                {
                    "value": "",
                    "label": "All",
                    "selected": not selected["selected_staff"],
                }
            ]
            + opts(
                [(s.id, s.user.name) for s in staff_profiles],
                selected["selected_staff"],
            ),
        },
        {
            "name": "partner",
            "label": "Partner",
            "options": [
                {
                    "value": "",
                    "label": "All",
                    "selected": not selected["selected_partner"],
                }
            ]
            + opts([(p.id, p.name) for p in partners], selected["selected_partner"]),
        },
        {
            "name": "school_type",
            "label": "School Type",
            "options": opts(
                school_type_pairs, selected["selected_school_type"] or "All"
            ),
        },
        {
            "name": "activity_type",
            "label": "Activity Type",
            "options": opts(
                activity_type_pairs, selected["selected_activity_type"] or "All"
            ),
        },
    ]


def _export_csv(data):
    fy = data["filters"]["selected_fy"]
    quarter = data["filters"]["selected_quarter"]
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="edify-analytics-FY{fy}-{quarter}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow(["Edify Analytics Snapshot", f"FY {fy}", quarter])
    writer.writerow([])
    writer.writerow(["Metric", "Value", "Helper / trend"])
    for item in data["kpi_strip_items"]:
        trend_val = item["trend"]["value"] if item.get("trend") else ""
        writer.writerow(
            [item["label"], item["value"], item.get("helper", ""), trend_val]
        )
    writer.writerow([])
    writer.writerow(["Target Achievement by District", "Achieved", "Planned", "%"])
    for d in data["target_by_district"]:
        writer.writerow([d["name"], d["achieved"], d["planned"], d["pct"]])
    writer.writerow([])
    writer.writerow(
        [
            "Cluster",
            "Avg SSA",
            "Trainings",
            "Visits",
            "Best Intervention",
            "Weakest Intervention",
        ]
    )
    for c in data["cluster_performance"]:
        writer.writerow(
            [
                c["name"],
                c["ssa_avg"],
                c["trainings"],
                c["visits"],
                c["best_intervention"],
                c["worst_intervention"],
            ]
        )
    return response


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

    if request.GET.get("export") == "csv":
        return _export_csv(data)

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

    # 4. Apply the signed-in user's saved KPI visibility preference (session-
    # backed — set from the Customize Dashboard drawer).
    hidden_kpis = set(request.session.get("analytics_hidden_kpis", []))
    visible_kpi_items = [
        item for item in data["kpi_strip_items"] if item.get("code") not in hidden_kpis
    ]

    scope = resolve_user_scope(request.user)

    # 5. Render context
    context = {
        **data,
        "kpi_strip_items": visible_kpi_items,
        "regions": regions,
        "districts": districts,
        "clusters": clusters,
        "staff_profiles": staff_profiles,
        "partners": partners,
        "filter_fields": _build_filter_fields(
            data["filters"], regions, districts, clusters, staff_profiles, partners
        ),
        "role_scope_text": _role_scope_text(scope),
        # Action settings
        "use_dark_sidebar": False,
        "timestamp": timezone.now().strftime("%B %d, %Y %I:%M %p"),
    }

    # If HTMX request, render only content cards to swap
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/analytics/kpi_cards.html", context)

    return render(request, "pages/analytics/index.html", context)


def _owner_name_map(schools_qs) -> dict:
    """`School.account_owner_id` is a plain CharField (not a real FK — the
    model has no `.account_owner` relation), so it must be resolved through
    StaffProfile explicitly. Returns {account_owner_id: staff name}."""
    owner_ids = [
        oid
        for oid in schools_qs.values_list("account_owner_id", flat=True).distinct()
        if oid
    ]
    if not owner_ids:
        return {}
    return {
        sp.id: sp.user.name
        for sp in StaffProfile.objects.filter(id__in=owner_ids).select_related("user")
    }


def _status_tone(status_code: str) -> str:
    """Map a real status/enum value to a badge tone — driven by the actual
    stored code, not a fragile substring match on the display label."""
    if status_code in (
        "ia_verified",
        "accountant_confirmed",
        "closed",
        "verified",
        "confirmed",
        "completed",
    ):
        return "success"
    if status_code in ("started", "in_progress"):
        return "info"
    if status_code in ("not_done", "scheduled", "pending"):
        return "warning"
    return "neutral"


@require_page_permission("analytics")
def analytics_drilldown_view(request):
    """GET to render the detailed trace records drawer."""
    metric = request.GET.get("metric", "").strip()
    cluster_id = request.GET.get("id", "").strip()
    fy = request.GET.get("fy") or get_operational_fy()
    quarter = request.GET.get("quarter") or get_quarter_for_date()

    # Base filter criteria — scoped to the caller's role visibility so a
    # CCEO/Program Lead drilling into a risk card only ever sees their own
    # assigned schools, matching the scoping the dashboard itself applies.
    scope = resolve_user_scope(request.user)
    activities = Activity.objects.filter(deleted_at__isnull=True, fy=fy)
    schools = School.objects.filter(deleted_at__isnull=True)
    if not scope.country_scope:
        if scope.school_ids:
            schools = schools.filter(id__in=scope.school_ids)
            activities = activities.filter(school_id__in=scope.school_ids)
        elif scope.region_ids:
            schools = schools.filter(region_id__in=scope.region_ids)
            activities = activities.filter(school__region_id__in=scope.region_ids)
        else:
            schools = schools.none()
            activities = activities.none()

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
        # a.responsible_staff_id stores the User id (not StaffProfile id) —
        # key the lookup map by user_id to actually resolve names.
        staff_ids = [a.responsible_staff_id for a in acts if a.responsible_staff_id]
        staff_map = {
            sp.user_id: sp.user.name
            for sp in StaffProfile.objects.filter(user_id__in=staff_ids).select_related(
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
                    "col4_tone": _status_tone(a.status),
                    "col5": a.salesforce_activity_id or "Not Entered",
                }
            )

    elif metric == "cluster":
        cluster = Cluster.objects.filter(id=cluster_id).first()
        title = (
            f"Cluster Performance — {cluster.name}"
            if cluster
            else "Cluster Performance"
        )
        description = (
            f"Activities logged against this cluster's schools for {quarter} FY {fy}."
        )
        headers = [
            "Activity Type",
            "School",
            "Responsible Owner",
            "Status",
            "Planned Date",
        ]
        if cluster:
            acts = list(
                activities.filter(
                    school__cluster_id=cluster.id, quarter=quarter
                ).select_related("school")[:100]
            )
            staff_ids = [a.responsible_staff_id for a in acts if a.responsible_staff_id]
            staff_map = {
                sp.user_id: sp.user.name
                for sp in StaffProfile.objects.filter(
                    user_id__in=staff_ids
                ).select_related("user")
            }
            for a in acts:
                rows.append(
                    {
                        "col1": a.activity_type.replace("_", " ").title(),
                        "col2": a.school.name if a.school else "-",
                        "col3": staff_map.get(a.responsible_staff_id, "Partner/Staff"),
                        "col4": a.status.replace("_", " ").title(),
                        "col4_tone": _status_tone(a.status),
                        "col5": a.planned_date.strftime("%d %b %Y")
                        if a.planned_date
                        else "-",
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
                    "col4_tone": "neutral",
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
            "SSA Status",
            "Account Owner",
        ]

        no_ssa_schools = list(
            schools.filter(current_fy_ssa_status__in=["not_done", "scheduled"])[:100]
        )
        owner_map = _owner_name_map(schools)
        for s in no_ssa_schools:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": s.get_current_fy_ssa_status_display(),
                    "col4_tone": _status_tone(s.current_fy_ssa_status),
                    "col5": owner_map.get(s.account_owner_id, "-"),
                }
            )

    elif metric == "not_visited":
        title = "Schools not visited"
        description = "Schools without a completed staff visit in the last 60+ days."
        headers = [
            "School ID",
            "School Name",
            "District",
            "SSA Status",
            "Account Owner",
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

        not_visited_schools = list(schools.exclude(id__in=visited_schools)[:100])
        owner_map = _owner_name_map(schools)
        for s in not_visited_schools:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": s.get_current_fy_ssa_status_display(),
                    "col4_tone": _status_tone(s.current_fy_ssa_status),
                    "col5": owner_map.get(s.account_owner_id, "-"),
                }
            )

    elif metric == "not_trained":
        title = "Schools not trained"
        description = "Schools that have not participated in any training workshops in this quarter."
        headers = [
            "School ID",
            "School Name",
            "District",
            "SSA Status",
            "Account Owner",
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

        not_trained_schools = list(schools.exclude(id__in=trained_schools)[:100])
        owner_map = _owner_name_map(schools)
        for s in not_trained_schools:
            rows.append(
                {
                    "col1": s.school_id,
                    "col2": s.name,
                    "col3": s.district.name if s.district else "-",
                    "col4": s.get_current_fy_ssa_status_display(),
                    "col4_tone": _status_tone(s.current_fy_ssa_status),
                    "col5": owner_map.get(s.account_owner_id, "-"),
                }
            )

    elif metric == "high_risk_districts":
        title = "High-risk districts"
        description = f"Districts under 60% target achievement in {quarter} FY {fy}."
        headers = ["District", "Planned", "Achieved", "Achievement %"]
        all_districts = District.objects.all().order_by("name")
        if not scope.country_scope and scope.district_ids:
            all_districts = all_districts.filter(id__in=scope.district_ids)
        for dist in all_districts:
            planned_d = activities.filter(
                school__district=dist, quarter=quarter
            ).count()
            achieved_d = activities.filter(
                school__district=dist,
                quarter=quarter,
                status__in=["ia_verified", "closed", "accountant_confirmed"],
            ).count()
            pct_d = round((achieved_d / planned_d * 100)) if planned_d > 0 else 0
            if planned_d > 0 and pct_d < 60:
                rows.append(
                    {
                        "col1": dist.name,
                        "col2": str(planned_d),
                        "col3": str(achieved_d),
                        "col4": f"{pct_d}%",
                        "col4_tone": "warning" if pct_d >= 40 else "danger",
                    }
                )

    elif metric == "clusters_attention":
        title = "Clusters needing attention"
        description = "Clusters with confirmed SSA average below 4.0."
        headers = ["Cluster", "District", "Avg SSA", "Status"]
        clusters_list = Cluster.objects.all().order_by("name")
        if not scope.country_scope and scope.cluster_ids:
            clusters_list = clusters_list.filter(id__in=scope.cluster_ids)
        elif not scope.country_scope and scope.region_ids:
            clusters_list = clusters_list.filter(region_id__in=scope.region_ids)
        elif not scope.country_scope:
            clusters_list = clusters_list.none()
        for cl in clusters_list.select_related("district"):
            cl_ssa = SsaRecord.objects.filter(
                school__cluster_id=cl.id, fy=fy, verification_status="confirmed"
            ).aggregate(a=Avg("average_score"))["a"]
            if cl_ssa is not None and cl_ssa < 4.0:
                rows.append(
                    {
                        "col1": cl.name,
                        "col2": cl.district.name if cl.district else "-",
                        "col3": f"{cl_ssa:.2f}",
                        "col4": "Below target",
                        "col4_tone": "danger",
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
    """GET renders the Save Report drawer form. POST persists a real Report
    snapshot record (apps.accounts.models.Report) and returns a confirmation
    with a working CSV download link.

    There is no email/cron infrastructure in this codebase, so this
    deliberately does not promise recurring scheduled delivery — it saves an
    audit-trail record of the current filtered view and lets the user export
    it immediately, which is the one thing it can honestly deliver.
    """
    fy = request.GET.get("fy") or request.POST.get("fy") or get_operational_fy()
    quarter = (
        request.GET.get("quarter")
        or request.POST.get("quarter")
        or get_quarter_for_date()
    )

    if request.method == "POST":
        categories = request.POST.getlist("categories")
        query_params = {
            "fy": request.POST.get("fy") or fy,
            "quarter": request.POST.get("quarter") or quarter,
            "region": request.POST.get("region", ""),
            "district": request.POST.get("district", ""),
            "cluster": request.POST.get("cluster", ""),
        }
        is_filtered = any(
            [query_params["region"], query_params["district"], query_params["cluster"]]
        )
        report = Report.objects.create(
            title=f"Analytics snapshot — FY{query_params['fy']} {query_params['quarter']}",
            type="analytics_snapshot",
            fy=query_params["fy"],
            scope="filtered" if is_filtered else "country",
            created_by_user_id=request.user.id,
            summary_json={
                "quarter": query_params["quarter"],
                "categories": categories,
                "filters": query_params,
                "requested_at": timezone.now().isoformat(),
            },
        )
        download_qs = "&".join(f"{k}={v}" for k, v in query_params.items() if v)
        context = {
            "drawer_size": "sm",
            "saved": True,
            "report_id": report.id,
            "download_url": f"/analytics?export=csv&{download_qs}",
        }
        return render(
            request, "partials/analytics/schedule_report_drawer.html", context
        )

    context = {
        "drawer_size": "sm",
        "saved": False,
        "fy": fy,
        "quarter": quarter,
    }
    return render(request, "partials/analytics/schedule_report_drawer.html", context)


@require_page_permission("analytics")
def analytics_customize_dashboard_view(request):
    """GET renders the Customize Dashboard drawer pre-filled from the
    session. POST saves which KPI Strip tiles the user wants hidden — backed
    by the session (no extra model/migration needed) — then reloads the
    dashboard so the KPI Strip immediately reflects the choice, matching the
    existing app-wide `window.location.reload()` + `HX-Trigger: close-drawer`
    convention used by other drawer forms.
    """
    if request.method == "POST":
        checked = set(request.POST.getlist("kpi_toggle"))
        hidden = []
        for code, _label in KPI_TOGGLE_GROUPS:
            if code not in checked:
                hidden.extend(KPI_TOGGLE_PAIRS.get(code, [code]))
        request.session["analytics_hidden_kpis"] = hidden
        response = HttpResponse("<script>window.location.reload();</script>")
        response["HX-Trigger"] = "close-drawer"
        return response

    hidden = set(request.session.get("analytics_hidden_kpis", []))
    toggles = [
        {"code": code, "label": label, "checked": code not in hidden}
        for code, label in KPI_TOGGLE_GROUPS
    ]
    context = {
        "drawer_size": "sm",
        "toggles": toggles,
    }
    return render(
        request, "partials/analytics/customize_dashboard_drawer.html", context
    )


@require_page_permission("system_health")
def system_health_view(request):
    from apps.system_health.services import report as system_health_report

    health = system_health_report()

    ssa_done = health["ssaDone"]
    schools_total = health["schoolsTotal"]
    ssa_rate = round(ssa_done / schools_total * 100) if schools_total else 0
    clustered_rate = (
        round(health["clustered"] / schools_total * 100) if schools_total else 0
    )
    planning_rate = (
        round(health["planningReady"] / schools_total * 100) if schools_total else 0
    )

    kpi_strip_items = [
        {
            "label": "Total Schools",
            "value": str(schools_total),
            "raw_value": schools_total,
            "helper": f"FY{health['fy']}",
            "icon": "school",
            "variant": "info",
        },
        {
            "label": "SSA Done",
            "value": f"{ssa_rate}%",
            "raw_value": ssa_rate,
            "helper": f"{ssa_done} of {schools_total} schools",
            "icon": "check",
            "variant": "success" if ssa_rate >= 70 else "warning",
        },
        {
            "label": "Clustered",
            "value": f"{clustered_rate}%",
            "raw_value": clustered_rate,
            "helper": f"{health['clustered']} of {schools_total} schools",
            "icon": "target",
            "variant": "success" if clustered_rate >= 70 else "warning",
        },
        {
            "label": "Planning Ready",
            "value": f"{planning_rate}%",
            "raw_value": planning_rate,
            "helper": f"{health['planningReady']} of {schools_total} schools",
            "icon": "calendar",
            "variant": "success" if planning_rate >= 70 else "warning",
        },
        {
            "label": "Data Leakage Scan",
            "value": "Clean" if health["mockDataLeakage"]["clean"] else "Flagged",
            "raw_value": 1 if health["mockDataLeakage"]["clean"] else 0,
            "helper": f"{len(health['mockDataLeakage']['violations'])} violation(s)",
            "icon": "shield",
            "variant": "success" if health["mockDataLeakage"]["clean"] else "danger",
        },
        {
            "label": "RBAC Gating Scan",
            "value": "Clean" if health["permissionAudit"]["clean"] else "Flagged",
            "raw_value": 1 if health["permissionAudit"]["clean"] else 0,
            "helper": f"{health['permissionAudit']['unguardedCount']} unguarded route(s)",
            "icon": "shield",
            "variant": "success" if health["permissionAudit"]["clean"] else "danger",
        },
    ]

    by_type = health["bySchoolType"]
    school_type_has_data = schools_total > 0
    school_type_chart_options = {
        "chart": {"type": "donut", "fontFamily": "inherit"},
        "labels": ["Client", "Core", "Champion"],
        "series": [by_type["client"], by_type["core"], by_type["champion"]],
        "colors": ["#3b82f6", "#10b981", "#f59e0b"],
        "legend": {"show": True, "position": "bottom", "fontSize": "11px"},
        "dataLabels": {"enabled": False},
        "stroke": {"width": 2, "colors": ["#ffffff"]},
        "plotOptions": {
            "pie": {
                "donut": {
                    "size": "72%",
                    "labels": {
                        "show": True,
                        "total": {
                            "show": True,
                            "label": "Schools",
                            "color": "#1e293b",
                        },
                    },
                }
            }
        },
    }

    workflow = health["workflowIssues"]
    workflow_checks = [
        ("Schools without cluster", workflow["unclusteredSchools"]),
        (
            "Scheduled missing budget lines",
            workflow["scheduledActivitiesMissingCostLines"],
        ),
        ("Stuck in Planning", workflow["stuckInPlanning"]),
        ("Partner work missing from My Plan", workflow["partnerScheduledMissing"]),
        ("Completed missing evidence", workflow["completedActivitiesWithoutEvidence"]),
        (
            "Completed missing Salesforce ID",
            workflow["completedActivitiesWithoutActivityCode"],
        ),
        ("IA verification skipped", workflow["iaSkipped"]),
        ("Accounts cleared before IA", workflow["accountsClearanceBeforeIa"]),
        ("Closed missing NetSuite ID", workflow["netsuiteIdMissing"]),
        ("Closed missing from analytics", workflow["closedMissingAnalytics"]),
    ]
    workflow_has_data = any(count for _label, count in workflow_checks)
    workflow_chart_options = {
        "chart": {
            "type": "bar",
            "height": 320,
            "toolbar": {"show": False},
            "fontFamily": "inherit",
        },
        "series": [{"name": "Open items", "data": [c for _l, c in workflow_checks]}],
        "xaxis": {"categories": [label for label, _c in workflow_checks]},
        "plotOptions": {
            "bar": {"borderRadius": 4, "horizontal": True, "barHeight": "55%"}
        },
        "colors": ["#f43f5e" if c > 0 else "#10b981" for _l, c in workflow_checks],
        "legend": {"show": False},
        "grid": {"borderColor": "#f1f5f9"},
        "dataLabels": {"enabled": True},
        "tooltip": {"theme": "light"},
    }

    context = {
        "health": health,
        "kpi_strip_items": kpi_strip_items,
        "school_type_chart_options": school_type_chart_options,
        "school_type_has_data": school_type_has_data,
        "workflow_chart_options": workflow_chart_options,
        "workflow_has_data": workflow_has_data,
    }
    return render(request, "pages/system_health/index.html", context)
