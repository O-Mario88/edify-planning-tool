"""
GROUP 3 — Partner Views
Partner directory, partner detail, partner portal pages
"""

from apps.core.activity_types import COMPLETED_WORK_STATUSES
import csv
from collections import defaultdict

from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse
from urllib.parse import urlencode
from apps.core.permissions import (
    RolePermissionService,
    require_export_permission,
    require_page_permission,
)
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_partner_ids
from django.db.models import Q
from datetime import date
from django.utils import timezone

from apps.core.fy import fy_options, get_fy_date_range, get_operational_fy
from apps.core.metrics import MetricValue, render_kpi_item
from apps.clusters.models import Cluster
from apps.geography.models import Region
from apps.partners.models import Partner, PartnerAssignment
from apps.partners.purposes import visit_purpose_label
from apps.activities.models import Activity
from apps.evidence.models import EvidenceRecord
from apps.schools.models import School

#: Work a partner must not act on: stopped by staff, or already refused.
#: Named once so every partner-facing list excludes the same set —
#: "cancelled" alone would leave deferred and rejected work on somebody's day.
STOPPED_ACTIVITY_STATUSES = ("cancelled", "deferred", "rejected")

# Row-level scoping: a Partner-role login (no StaffProfile, no country/region
# scope) must only ever see their OWN partner org — matching what the REST
# endpoint already intends (PartnerListOnboardView/PartnerUpdateView require
# PARTNER_VIEW/PARTNER_MANAGE, permissions Partner roles don't hold at all).
# The browser routes are ALL_ROLES for every staff role, so the restriction
# has to be applied here rather than at the page-permission layer.
PARTNER_ROLES = (EdifyRole.PARTNER_ADMIN.value, EdifyRole.PARTNER_FIELD_OFFICER.value)


@require_page_permission("partners")
@require_export_permission
def partners_list_view(request):
    """Partner Activities workspace for partner organisations.

    Staff are redirected to Partner Oversight, which is now the single staff
    view of partner work. The two pages answered the same question — which
    schools are with which partner, who has scheduled, what it costs — from
    two sidebar entries, and a supervisor had no way to tell which one to
    trust. Oversight won because it also carries the withdrawal decisions and
    the per-item risks.

    The redirect is deliberately conditional rather than a route-level one.
    `/partners` is ALL_ROLES and Partner Oversight is not, so redirecting
    everybody would bounce three populations into a page that then refuses
    them: the external partner organisations, for whom this is the only
    directory they have, and HR, the RVP and the Project Coordinator, who hold
    `partners` but not `partner_oversight`.

    It asks `can_view_page` rather than listing roles, so the redirect and the
    destination's own gate can never disagree — a hardcoded list here would
    drift the first time either page's audience changed.
    """
    if RolePermissionService.can_view_page(request.user, "partner_oversight"):
        # Carry the filters both pages read under the same names, so a saved
        # link survives the merge — dropping them would silently reset somebody
        # to the current period and look like the data had changed.
        #
        # Named individually rather than forwarded wholesale. Passing the whole
        # query string put request data into a redirect target, which CodeQL
        # flagged: the fixed `/partner-oversight/?` prefix meant it could not
        # actually leave the site, but "cannot escape today" is a property of
        # the prefix rather than of the code, and the next edit owns it. An
        # allowlist cannot be argued with — and the directory's other params
        # (`q`, `status`, `region`) mean nothing on the destination anyway.
        carried = {
            key: value
            for key, value in ((k, request.GET.get(k)) for k in ("fy", "partner"))
            if value
        }
        target = reverse("frontend:partner_oversight")
        query = urlencode(carried)
        return redirect(f"{target}?{query}" if query else target)
    return _partner_workspace(request)


def _partner_workspace(request):
    """The partner-facing workspace body.

    The former directory only named organisations. This view joins the
    assignment queue with scheduled partner work so a partner organisation can
    see what is assigned, scheduled, due, and funded without leaving the page.
    """
    search = request.GET.get("q", "").strip()
    selected_fy = request.GET.get("fy", get_operational_fy())
    if selected_fy not in fy_options():
        selected_fy = get_operational_fy()
    selected_region = request.GET.get("region", "").strip()
    selected_partner = request.GET.get("partner", "").strip()
    selected_status = request.GET.get("status", "").strip()

    partners_qs = Partner.objects.filter(deleted_at__isnull=True).order_by("name")
    if request.user.active_role in PARTNER_ROLES:
        partners_qs = partners_qs.filter(id__in=resolve_partner_ids(request.user))
    if search:
        # Partner Monitor is used to answer "who is working in this school" at
        # least as often as "where is this partner". Name and region alone
        # could not answer the first, so the school a partner is assigned to
        # now reaches the partner, resolved through the assignment table so a
        # partner with fifty schools still returns one row.
        partners_qs = partners_qs.filter(
            Q(name__icontains=search)
            | Q(region_name__icontains=search)
            | Q(
                id__in=PartnerAssignment.objects.filter(
                    Q(school__name__icontains=search)
                    | Q(school__school_id__icontains=search)
                    | Q(school__district__name__icontains=search)
                ).values("partner_id")
            )
        )
    if selected_partner:
        partners_qs = partners_qs.filter(id=selected_partner)

    partners = list(partners_qs)
    partner_ids = [partner.id for partner in partners]
    start, end = get_fy_date_range(selected_fy)
    start_date, end_date = start.date(), end.date()

    activities_qs = (
        Activity.objects.filter(
            assigned_partner_id__in=partner_ids,
            deleted_at__isnull=True,
            fy=selected_fy,
        )
        .select_related("school__district", "cluster")
        .order_by("planned_date", "scheduled_date", "created_at")
    )
    assignments_qs = (
        PartnerAssignment.objects.filter(partner_id__in=partner_ids)
        .select_related("partner", "school__district", "cluster")
        .order_by("scheduled_date", "created_at")
    )
    if selected_region:
        activities_qs = activities_qs.filter(school__region_id=selected_region)
        assignments_qs = assignments_qs.filter(school__region_id=selected_region)

    if selected_status == "scheduled":
        activities_qs = activities_qs.filter(scheduled_date__isnull=False)
        assignments_qs = assignments_qs.filter(scheduled_date__isnull=False)
    elif selected_status == "yet_to_schedule":
        activities_qs = activities_qs.filter(scheduled_date__isnull=True)
        assignments_qs = assignments_qs.filter(scheduled_date__isnull=True)
    elif selected_status == "overdue":
        today = date.today()
        activities_qs = activities_qs.filter(scheduled_date__lt=today).exclude(
            status__in=COMPLETED_WORK_STATUSES
        )
        assignments_qs = assignments_qs.filter(scheduled_date__lt=today)

    # A date-less handoff remains visible in the queue because it still needs
    # a partner to set a delivery date. Dated handoffs must lie in the chosen
    # fiscal year unless an associated Activity already supplies the FY.
    assignments = list(
        assignments_qs.filter(
            Q(scheduled_date__isnull=True)
            | Q(scheduled_date__gte=start_date, scheduled_date__lt=end_date)
        )
    )
    activities = list(activities_qs)
    cluster_ids = (
        {activity.cluster_id for activity in activities if activity.cluster_id}
        | {assignment.cluster_id for assignment in assignments if assignment.cluster_id}
        | {
            assignment.school.cluster_id
            for assignment in assignments
            if assignment.school and assignment.school.cluster_id
        }
        | {
            activity.school.cluster_id
            for activity in activities
            if activity.school and activity.school.cluster_id
        }
    )
    clusters_by_id = {
        cluster.id: cluster
        for cluster in Cluster.objects.filter(id__in=cluster_ids).only("id", "name")
    }
    today = timezone.localdate()

    activities_by_partner: dict[str, list[Activity]] = defaultdict(list)
    activity_keys: set[tuple[str, str, str, date | None]] = set()
    for activity in activities:
        activities_by_partner[activity.assigned_partner_id].append(activity)
        activity_keys.add(
            (
                activity.assigned_partner_id,
                activity.school_id or activity.cluster_id or "",
                activity.activity_type,
                activity.planned_date,
            )
        )

    assignments_by_partner: dict[str, list[PartnerAssignment]] = defaultdict(list)
    for assignment in assignments:
        assignments_by_partner[assignment.partner_id].append(assignment)

    complete_statuses = {
        "completed",
        "closed",
        "ia_verified",
        "payment_approved",
    }
    partner_cards = []
    all_rows = []
    for partner in partners:
        partner_rows = []
        partner_activities = activities_by_partner[partner.id]
        for activity in partner_activities:
            target = activity.school or activity.cluster
            scheduled_for = activity.planned_date or (
                timezone.localdate(activity.scheduled_date)
                if activity.scheduled_date
                else None
            )
            is_overdue = bool(
                scheduled_for
                and scheduled_for < today
                and activity.status not in complete_statuses
            )
            status_label = (
                "Completed"
                if activity.status in complete_statuses
                else "Overdue"
                if is_overdue
                else "Scheduled"
                if scheduled_for
                else "Awaiting schedule"
            )
            status_tone = (
                "success"
                if status_label == "Completed"
                else "danger"
                if status_label == "Overdue"
                else "info"
                if status_label == "Scheduled"
                else "warning"
            )
            row = {
                "school_name": target.name if target else "Unassigned target",
                "district_cluster": _partner_location_label(activity, clusters_by_id),
                "purpose": visit_purpose_label(
                    activity.purpose_type,
                    activity.get_activity_type_display(),
                ),
                "focus": activity.get_focus_intervention_display() or "General support",
                "date": scheduled_for,
                "status_label": status_label,
                "status_tone": status_tone,
                "cost": activity.est_cost_cents,
                "cost_pending": activity.cost_missing,
                "detail_url": _my_plan_activity_url(activity),
                "is_pending": False,
                "is_overdue": is_overdue,
            }
            partner_rows.append(row)

        for assignment in assignments_by_partner[partner.id]:
            assignment_type = assignment.expected_activity_type or "school_visit"
            target_id = assignment.school_id or assignment.cluster_id or ""
            assignment_key = (
                partner.id,
                target_id,
                assignment_type,
                assignment.scheduled_date,
            )
            if assignment.scheduled_date and assignment_key in activity_keys:
                continue
            target = assignment.school or assignment.cluster
            is_overdue = bool(
                assignment.scheduled_date and assignment.scheduled_date < today
            )
            status_label = "Overdue" if is_overdue else "Yet to schedule"
            row = {
                "school_name": target.name if target else "Unassigned target",
                "district_cluster": _partner_assignment_location_label(
                    assignment, clusters_by_id
                ),
                "purpose": visit_purpose_label(
                    assignment.purpose_of_visit,
                    assignment.expected_activity_type.replace("_", " ").title()
                    if assignment.expected_activity_type
                    else "Partner support",
                ),
                "focus": assignment.get_focus_intervention_display()
                if assignment.focus_intervention
                else "General support",
                "date": assignment.scheduled_date,
                "status_label": status_label,
                "status_tone": "danger" if is_overdue else "warning",
                "cost": 0,
                "cost_pending": True,
                "detail_url": f"/partners/{partner.id}",
                "is_pending": True,
                "is_overdue": is_overdue,
            }
            partner_rows.append(row)

        if search:
            query = search.casefold()
            partner_rows = [
                row
                for row in partner_rows
                if query in row["school_name"].casefold()
                or query in row["purpose"].casefold()
                or query in row["focus"].casefold()
            ]
            if not partner_rows and query not in partner.name.casefold():
                continue
        if selected_status:
            partner_rows = [
                row
                for row in partner_rows
                if row["status_label"].casefold().replace(" ", "_") == selected_status
            ]
            if not partner_rows:
                continue

        partner_rows.sort(
            key=lambda row: (row["date"] is None, row["date"] or date.max)
        )
        scheduled_count = sum(not row["is_pending"] for row in partner_rows)
        pending_count = sum(row["is_pending"] for row in partner_rows)
        assigned_school_count = len(
            {
                assignment.school_id
                for assignment in assignments_by_partner[partner.id]
                if assignment.school_id
            }
            | {
                activity.school_id
                for activity in partner_activities
                if activity.school_id
            }
        )
        focus_values = [
            row["focus"] for row in partner_rows if row["focus"] != "General support"
        ]
        focus = (
            max(set(focus_values), key=focus_values.count)
            if focus_values
            else "General support"
        )
        partner_cards.append(
            {
                "partner": partner,
                "rows": partner_rows,
                "assigned_school_count": assigned_school_count,
                "scheduled_count": scheduled_count,
                "pending_count": pending_count,
                "focus": focus,
            }
        )
        all_rows.extend([{**row, "partner": partner} for row in partner_rows])

    scheduled_rows = [row for row in all_rows if not row["is_pending"]]
    pending_rows = [row for row in all_rows if row["is_pending"]]
    overdue_rows = [row for row in all_rows if row["is_overdue"]]
    total_cost = sum(row["cost"] for row in scheduled_rows)
    total_rows = len(scheduled_rows) + len(pending_rows)
    scheduled_pct = round((len(scheduled_rows) / total_rows) * 100) if total_rows else 0
    pending_pct = round((len(pending_rows) / total_rows) * 100) if total_rows else 0
    overdue_pct = round((len(overdue_rows) / total_rows) * 100) if total_rows else 0
    assigned_school_count = len(
        {assignment.school_id for assignment in assignments if assignment.school_id}
        | {activity.school_id for activity in activities if activity.school_id}
    )

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="partner-activities-fy-{selected_fy}.csv"'
        )
        writer = csv.writer(response)
        writer.writerow(
            [
                "Partner",
                "School / target",
                "District / cluster",
                "Purpose of Visit",
                "Intervention focus",
                "Scheduled date",
                "Status",
                "Cost (UGX)",
            ]
        )
        for row in all_rows:
            writer.writerow(
                [
                    row["partner"].name,
                    row["school_name"],
                    row["district_cluster"],
                    row["purpose"],
                    row["focus"],
                    row["date"] or "",
                    row["status_label"],
                    row["cost"],
                ]
            )
        return response

    context = {
        "partners": partners,
        "total": len(partners),
        "search": search,
        "partner_cards": partner_cards,
        "selected_fy": selected_fy,
        "selected_region": selected_region,
        "selected_partner": selected_partner,
        "selected_status": selected_status,
        "fy_options": fy_options(),
        "regions": Region.objects.order_by("name"),
        "kpis": {
            "partners": len(partner_cards),
            "assigned_schools": assigned_school_count,
            "scheduled": len(scheduled_rows),
            "pending": len(pending_rows),
            "cost": total_cost,
            "overdue": len(overdue_rows),
        },
        "status_breakdown": {
            "scheduled": len(scheduled_rows),
            "pending": len(pending_rows),
            "overdue": len(overdue_rows),
            "scheduled_pct": scheduled_pct,
            "pending_pct": pending_pct,
            "overdue_pct": overdue_pct,
        },
        "partner_kpi_items": [
            render_kpi_item(
                "partner_total_partners",
                MetricValue.measured(len(partner_cards)),
                helper="In this view",
            ),
            render_kpi_item(
                "partner_assigned_schools",
                MetricValue.measured(assigned_school_count),
                helper="Across all partners",
                tone="info",
            ),
            render_kpi_item(
                "partner_scheduled_activities",
                MetricValue.measured(len(scheduled_rows)),
                helper=f"{scheduled_pct}% of work",
                tone="success",
            ),
            render_kpi_item(
                "partner_activities_yet_to_schedule",
                MetricValue.measured(len(pending_rows)),
                helper=f"{pending_pct}% need a date",
                tone="warning",
            ),
            render_kpi_item(
                "partner_scheduled_activity_cost",
                MetricValue.measured(total_cost),
                helper="Scheduled work",
            ),
            render_kpi_item(
                "partner_high_risk_delays",
                MetricValue.measured(len(overdue_rows)),
                helper="Needs attention" if overdue_rows else "No late work",
                tone="danger" if overdue_rows else "success",
            ),
        ],
        "pending_reminders": pending_rows[:5],
        "upcoming_activities": sorted(
            [row for row in scheduled_rows if row["date"] and row["date"] >= today],
            key=lambda row: row["date"],
        )[:5],
    }
    # One persistent search: the top bar, attached to the page filter form.
    context["topbar_search"] = {
        "placeholder": "Search schools or support…",
        "name": "search",
        "value": request.GET.get("search", ""),
        "attach_to": "partner-activity-filters",
        "autosubmit": True,
    }
    return render(request, "pages/partners/index.html", context)


@require_page_permission("partners")
def create_partner_view(request):
    """Legacy partner-onboarding drawer; management now lives under Users."""
    from apps.core.enums import SsaIntervention
    from apps.partners.services import onboard as onboard_partner_service
    from django.contrib import messages
    from django.shortcuts import redirect

    allowed_roles = {
        "CountryDirector",
        "Admin",
        "CD",
        "ADMIN",
    }
    user_role = getattr(request.user, "active_role", None)
    if user_role not in allowed_roles and not request.user.is_superuser:
        if request.headers.get("HX-Request"):
            return HttpResponseForbidden(
                "Only a Country Director or Admin can onboard new partners."
            )
        messages.error(
            request,
            "Only a Country Director or Admin can onboard new partners.",
        )
        return redirect("frontend:partners_list")

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        region_name = request.POST.get("region_name", "").strip()
        contact_person = request.POST.get("contact_person", "").strip()
        email = request.POST.get("email", "").strip()
        phone = request.POST.get("phone", "").strip()
        ssa_intervention = request.POST.get("ssa_intervention", "").strip()
        notes = request.POST.get("notes", "").strip()

        if not name:
            messages.error(request, "Partner name is required.")
            return redirect("frontend:admin_users")

        payload = {
            "name": name,
            "regionName": region_name,
            "contactPerson": contact_person,
            "email": email,
            "phone": phone,
            "ssaIntervention": ssa_intervention,
            "notes": notes,
        }

        try:
            onboard_partner_service(payload, request.user)
            messages.success(
                request, f"Partner organisation '{name}' onboarded successfully."
            )
        except Exception as exc:
            messages.error(request, str(getattr(exc, "detail", exc)))

        return redirect("frontend:admin_users")

    context = {
        "regions": Region.objects.order_by("name"),
        "interventions": SsaIntervention.choices,
    }
    return render(request, "partials/partners/create_partner_drawer.html", context)


def _partner_location_label(
    activity: Activity, clusters_by_id: dict[str, Cluster]
) -> str:
    if activity.school:
        district = activity.school.district.name if activity.school.district else "—"
        cluster = activity.cluster or clusters_by_id.get(activity.school.cluster_id)
        cluster_name = cluster.name if cluster else "Unclustered"
        return f"{district} / {cluster_name}"
    return activity.cluster.name if activity.cluster else "—"


def _partner_assignment_location_label(
    assignment: PartnerAssignment, clusters_by_id: dict[str, Cluster]
) -> str:
    if assignment.school:
        district = (
            assignment.school.district.name if assignment.school.district else "—"
        )
        cluster = assignment.cluster or clusters_by_id.get(assignment.school.cluster_id)
        cluster_name = cluster.name if cluster else "Unclustered"
        return f"{district} / {cluster_name}"
    return assignment.cluster.name if assignment.cluster else "—"


def _my_plan_activity_url(activity: Activity) -> str:
    """Link to the week that contains a partner-delivered activity."""
    if not activity.planned_date:
        return "/my-plan"
    planned = activity.planned_date
    return (
        f"/my-plan?fy={activity.fy}&month={planned.month}"
        f"&week={min(5, (planned.day - 1) // 7 + 1)}&period=week"
    )


@require_page_permission("partner_detail")
def partner_detail_view(request, partner_id):
    """Partner detail — schools, activities, performance."""
    if request.user.active_role in PARTNER_ROLES and str(
        partner_id
    ) not in resolve_partner_ids(request.user):
        return HttpResponseForbidden("You may only view your own partner organization.")
    partner = get_object_or_404(Partner, id=partner_id, deleted_at__isnull=True)

    # Activities delivered by this partner (assigned_partner_id is the
    # partner-activity link used across planning/IA views).
    activities = list(
        Activity.objects.filter(
            assigned_partner_id=partner.id,
            deleted_at__isnull=True,
        )
        .select_related("school")
        .order_by("-planned_date")[:30]
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

    context = {
        "partner": partner,
        "activities": activities,
        "completed": sum(1 for a in activities if a.status in COMPLETED_WORK_STATUSES),
        "partner_progress": partner_progress,
    }
    return render(request, "pages/partners/detail.html", context)


@require_page_permission("partner_today")
def partner_today_view(request):
    """Retired 2026-08-20: the partner's home is Assigned Activities; their
    plan lives on My Plan. Old bookmarks land safely."""
    from django.shortcuts import redirect as _redirect

    return _redirect("/partner/assigned-schools")


@require_page_permission("partner_schools")
def partner_schools_view(request):
    """Partner's assigned schools."""
    user = request.user
    partner_ids = resolve_partner_ids(user)
    school_ids = (
        Activity.objects.filter(
            assigned_partner_id__in=partner_ids,
            deleted_at__isnull=True,
        )
        .values_list("school_id", flat=True)
        .distinct()
    )
    schools = School.objects.filter(
        id__in=school_ids, deleted_at__isnull=True
    ).order_by("name")

    context = {"schools": schools, "total": schools.count()}
    return render(request, "pages/partner/schools.html", context)


@require_page_permission("partner_activities")
def partner_activities_view(request):
    """Partner activities log."""
    user = request.user
    status_filter = request.GET.get("status", "")
    partner_ids = resolve_partner_ids(user)
    activities = (
        Activity.objects.filter(
            assigned_partner_id__in=partner_ids,
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("-planned_date")
    )
    if status_filter:
        activities = activities.filter(status=status_filter)
    activities = list(activities[:60])
    assignments = list(
        PartnerAssignment.objects.filter(
            partner_id__in=partner_ids,
            status__in=["assigned", "pending_scheduling"],
        )
        .select_related(
            "school",
            "cluster",
            "catalogue_item",
            "source_ssa",
        )
        .prefetch_related("allowed_catalogue_items")
        .order_by("scheduled_date", "created_at")[:60]
    )
    context = {
        "activities": activities,
        "assignments": assignments,
        "total": len(activities),
        "status_filter": status_filter,
    }
    return render(request, "pages/partner/activities.html", context)


@require_page_permission("partner_activities")
def partner_schedule_assignment_drawer(request, assignment_id):
    partner_ids = resolve_partner_ids(request.user)
    assignment = get_object_or_404(
        PartnerAssignment.objects.select_related(
            "school", "cluster", "catalogue_item", "source_ssa"
        ).prefetch_related("allowed_catalogue_items"),
        id=assignment_id,
        partner_id__in=partner_ids,
        status__in=["assigned", "pending_scheduling"],
    )
    _ensure_assignment_item(assignment)
    return render(
        request,
        "partials/partners/schedule_assignment_drawer.html",
        {
            "assignment": assignment,
            "approved_item": assignment.catalogue_item,
            "drawer_size": "md",
        },
    )


@require_page_permission("partner_activities")
def partner_schedule_assignment_action(request, assignment_id):
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    partner_ids = resolve_partner_ids(request.user)
    assignment = get_object_or_404(
        PartnerAssignment,
        id=assignment_id,
        partner_id__in=partner_ids,
        status__in=["assigned", "pending_scheduling"],
    )
    try:
        from apps.partners.services import schedule_activity

        schedule_activity(
            assignment.id,
            {
                "scheduledDate": request.POST.get("scheduled_date"),
                "expectedParticipants": request.POST.get("expected_participants")
                or None,
                "catalogueItemId": request.POST.get("catalogue_item_id"),
                "requireCatalogue": True,
            },
            request.user,
        )
        # Scheduled work lives on My Plan (§6) — land the partner there.
        response = HttpResponse('<script>window.location.href="/my-plan";</script>')
        response["HX-Trigger"] = "close-drawer"
        return response
    except Exception as exc:
        from apps.core.htmx_errors import error_fragment

        return error_fragment(exc, status=400)


@require_page_permission("partner_activities")
def partner_return_assignment_drawer(request, assignment_id):
    """The Return form. Scoped and state-checked here as well as in the service.

    The status filter is not decoration: without it the drawer would open for
    an already-scheduled assignment and offer an action the service will
    refuse, which reads to the partner as a broken button rather than a rule.
    """
    from apps.partners.models import PartnerAssignment, PartnerReturnReason
    from apps.partners.services import (
        RETURN_REASON_MAX_LENGTH,
        RETURN_REASON_MIN_LENGTH,
    )

    partner_ids = resolve_partner_ids(request.user)
    assignment = get_object_or_404(
        PartnerAssignment.objects.select_related("school", "cluster", "catalogue_item"),
        id=assignment_id,
        partner_id__in=partner_ids,
        status__in=PartnerAssignment.UNSCHEDULED_STATUSES,
    )
    return render(
        request,
        "partials/partners/return_assignment_drawer.html",
        {
            "assignment": assignment,
            "reason_categories": PartnerReturnReason.choices,
            "reason_min": RETURN_REASON_MIN_LENGTH,
            "reason_max": RETURN_REASON_MAX_LENGTH,
            "drawer_size": "md",
        },
    )


@require_page_permission("partner_activities")
def partner_return_assignment_action(request, assignment_id):
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    try:
        from apps.partners.services import return_assignment

        return_assignment(
            assignment_id,
            {
                "reason_category": request.POST.get("reason_category"),
                "reason": request.POST.get("reason"),
            },
            request.user,
        )
        # A returned assignment leaves the intake — show the updated list.
        response = HttpResponse(
            '<script>window.location.href="/partner/assigned-schools";</script>'
        )
        response["HX-Trigger"] = "close-drawer"
        return response
    except Exception as exc:
        from apps.core.htmx_errors import error_fragment

        return error_fragment(
            exc, action="Could not return this assignment", status=400
        )


@require_page_permission("partner_evidence")
def partner_evidence_view(request):
    """Partner evidence upload list."""
    user = request.user
    partner_ids = resolve_partner_ids(user)
    activity_ids = Activity.objects.filter(
        assigned_partner_id__in=partner_ids,
        deleted_at__isnull=True,
    ).values_list("id", flat=True)
    evidence = (
        EvidenceRecord.objects.filter(activity_id__in=activity_ids)
        .select_related("activity", "activity__school")
        .order_by("-created_at")[:50]
    )

    pending = Activity.objects.filter(
        assigned_partner_id__in=partner_ids,
        status__in=COMPLETED_WORK_STATUSES,
        evidence__isnull=True,
        deleted_at__isnull=True,
    ).select_related("school")[:10]

    context = {"evidence": evidence, "pending": pending}
    return render(request, "pages/partner/evidence.html", context)


@require_page_permission("partner_my_plan")
def partner_my_plan_view(request):
    """Redirect legacy partner plan view to unified my-plan view."""
    from django.shortcuts import redirect

    return redirect("/my-plan")


@require_page_permission("partner_my_plan")
def partner_invoice_drawer(request):
    """The partner's PERIOD invoice drawer. One invoice sums all their
    planned activity costs for the chosen week/month/quarter, grouped by
    category; the entered amount must equal the fetched period total."""
    from datetime import date as _date

    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests.partner_invoices import invoice_basis

    kind = (request.GET.get("period_kind") or "month").strip()
    instalment = (request.GET.get("instalment") or "advance").strip()
    anchor_raw = (request.GET.get("anchor") or "").strip()
    try:
        anchor = _date.fromisoformat(anchor_raw[:10]) if anchor_raw else _date.today()
    except ValueError:
        anchor = _date.today()
    try:
        basis = invoice_basis(request.user, kind, anchor, instalment)
        basis_error = None
    except (BadRequest, Forbidden) as exc:
        basis, basis_error = None, str(exc)
    return render(
        request,
        "partials/partner/invoice_drawer.html",
        {
            "basis": basis,
            "basis_error": basis_error,
            "kind": kind,
            "instalment": instalment,
            "anchor": anchor.isoformat(),
        },
    )


@require_page_permission("partner_my_plan")
def partner_invoice_submit(request):
    """POST multipart — create the period invoice and route it to the PL."""
    from datetime import date as _date

    from django.http import HttpResponse

    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests.partner_invoices import submit_invoice

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    try:
        anchor = _date.fromisoformat((request.POST.get("anchor") or "")[:10])
        result = submit_invoice(
            request.user,
            (request.POST.get("period_kind") or "month").strip(),
            anchor,
            (request.POST.get("instalment") or "advance").strip(),
            request.POST.get("entered_total"),
            request.FILES.get("invoice_file"),
        )
    except (BadRequest, Forbidden, ValueError) as exc:
        return HttpResponse(
            f'<div class="p-3 rounded-surface bg-rose-50 text-rose-700 '
            f'text-[12px] font-bold" role="alert">{exc}</div>',
            status=400,
        )
    label = "50% advance" if result["invoiceType"] == "advance" else "clearance"
    response = HttpResponse(
        '<div class="p-3 rounded-surface bg-emerald-50 text-emerald-800 '
        f'text-[13px] font-bold" role="status">Invoice for {result["label"]} '
        f"submitted — the {label} of UGX {result['payable']:,} is with your "
        "Program Lead for confirmation.</div>"
        "<script>window.setTimeout(function () {"
        'window.location.href = "/my-plan";'
        "}, 1100);</script>"
    )
    response["HX-Trigger"] = "close-drawer"
    return response


@require_page_permission("partner_assignments")
def partner_assignments_view(request):
    """Assigned Activities — the partner's home. Everything assigned to
    their organisation: what still needs scheduling (with the schedule
    drawer), and what is already scheduled (which lives on in My Plan)."""
    partner_ids = resolve_partner_ids(request.user)
    assignments = list(
        PartnerAssignment.objects.filter(partner_id__in=partner_ids)
        .select_related("school", "cluster", "catalogue_item")
        .order_by("-created_at")[:200]
    )
    pending = [a for a in assignments if a.status in ("assigned", "pending_scheduling")]
    scheduled = [a for a in assignments if a.status == "partner_scheduled"]
    return render(
        request,
        "pages/partner/assignments.html",
        {
            "pending": pending,
            "scheduled": scheduled,
            "mobile_primary_action": {
                "label": "Schedule assigned work" if pending else "Open My Plan",
                "url": "/partner/assignments" if pending else "/partner/my-plan",
            },
        },
    )


# ── §2 classification: scope, not venue, decides the category ────────────────
_CLUSTER_SCOPE_TYPES = {
    "cluster_training",
    "cluster_meeting",
    "cluster_meeting_ssa_review",
    "cluster_training_ssa_collection",
    "training",
}


def _ensure_assignment_item(assignment):
    """The approved Catalogue Activity is the ASSIGNER's decision — the
    partner never chooses one. Rows written before the pin became mandatory
    self-heal from their recorded purpose (one active standard-support item
    per workflow kind, by DB constraint)."""
    if assignment.catalogue_item_id:
        return assignment
    from apps.activity_catalogue.services import resolve_assignment_item

    resolved = resolve_assignment_item(
        purpose_of_visit=assignment.purpose_of_visit or None,
        expected_activity_type=assignment.expected_activity_type or None,
    )
    if resolved is not None:
        assignment.catalogue_item = resolved
        assignment.catalogue_snapshot = resolved.snapshot()
        assignment.save(
            update_fields=["catalogue_item", "catalogue_snapshot", "updated_at"]
        )
    return assignment


def _assignment_is_school_scoped(assignment) -> bool:
    """One specific school = a School Visit, whatever the intervention.
    Cluster/group scope = an Assigned Activity, wherever it is held."""
    if assignment.cluster_id:
        return False
    if (assignment.expected_activity_type or "") in _CLUSTER_SCOPE_TYPES:
        return False
    return bool(assignment.school_id)


def _assigned_intake(request, *, school_scoped: bool):
    partner_ids = resolve_partner_ids(request.user)
    assignments = [
        a
        for a in PartnerAssignment.objects.filter(
            partner_id__in=partner_ids,
            status__in=["assigned", "pending_scheduling", "returned"],
        )
        .select_related("school", "school__district", "cluster", "catalogue_item")
        .order_by("-created_at")[:300]
        if _assignment_is_school_scoped(a) is school_scoped
    ]
    from apps.accounts.models import User as _User

    names = dict(
        _User.objects.filter(
            id__in={a.assigning_staff_id for a in assignments if a.assigning_staff_id}
        ).values_list("id", "name")
    )
    from apps.accounts.models import StaffProfile as _SP

    sp_names = dict(
        _SP.objects.filter(
            id__in={a.assigning_staff_id for a in assignments if a.assigning_staff_id}
        ).values_list("id", "user__name")
    )
    for a in assignments:
        a.assigned_by_name = (
            names.get(a.assigning_staff_id) or sp_names.get(a.assigning_staff_id) or "—"
        )
        # §2.3 — the partner sees the simple category; the governed subtype
        # stays authoritative underneath for evidence/costing/Salesforce.
        a.facing_category = "School Visit" if school_scoped else "Cluster Activity"
        _ensure_assignment_item(a)
        a.subtype_label = (
            a.catalogue_item.display_name
            if a.catalogue_item_id
            else (a.expected_activity_type or "").replace("_", " ").title()
        )
        # Coded purpose first ("SSA Support", never the ssa_support token);
        # the staff member's free-text reason only when nothing coded exists.
        a.purpose_label = (
            visit_purpose_label(a.purpose_of_visit, "") or a.purpose or "—"
        )
    return assignments


@require_page_permission("partner_schools")
def partner_assigned_schools_view(request):
    """§3 Assigned Schools — school-based work awaiting the partner's
    Schedule-or-Return decision. One click opens the assignment detail."""
    return render(
        request,
        "pages/partner/assigned_list.html",
        {
            "rows": _assigned_intake(request, school_scoped=True),
            "page_title": "Assigned Schools",
            "page_blurb": (
                "Schools Edify has assigned to your organisation. Open one to "
                "review the brief, then Schedule it or Return it."
            ),
            "school_scoped": True,
        },
    )


@require_page_permission("partner_assignments")
def partner_assigned_activities_view(request):
    """§4 Assigned Activities — cluster/group work awaiting the decision."""
    return render(
        request,
        "pages/partner/assigned_list.html",
        {
            "rows": _assigned_intake(request, school_scoped=False),
            "page_title": "Assigned Activities",
            "page_blurb": (
                "Trainings, cluster meetings and other group work assigned to "
                "your organisation."
            ),
            "school_scoped": False,
        },
    )


@require_page_permission("partner_assignments")
def partner_assignment_detail_view(request, assignment_id):
    """§5 the assignment-acceptance surface: read-only brief with exactly two
    decisions — Schedule (primary) and Return (secondary)."""
    partner_ids = resolve_partner_ids(request.user)
    assignment = get_object_or_404(
        PartnerAssignment.objects.select_related(
            "school", "school__district", "cluster", "catalogue_item", "source_ssa"
        ),
        id=assignment_id,
        partner_id__in=partner_ids,
    )
    school_scoped = _assignment_is_school_scoped(assignment)
    assignment.facing_category = "School Visit" if school_scoped else "Cluster Activity"
    _ensure_assignment_item(assignment)
    assignment.subtype_label = (
        assignment.catalogue_item.display_name
        if assignment.catalogue_item_id
        else (assignment.expected_activity_type or "").replace("_", " ").title()
    )
    assignment.purpose_label = (
        visit_purpose_label(assignment.purpose_of_visit, "")
        or assignment.purpose
        or "—"
    )
    can_decide = assignment.status in ("assigned", "pending_scheduling")
    return render(
        request,
        "pages/partner/assignment_detail.html",
        {
            "a": assignment,
            "can_decide": can_decide,
            "back_url": "/partner/assigned-schools"
            if school_scoped
            else "/partner/assigned-activities",
        },
    )


@require_page_permission("partner_activities")
def partner_completed_payments_view(request):
    """§14 Completed & Payments — where every submitted school or activity
    stands: IA review, Salesforce, and payment, in partner-facing language."""
    partner_ids = resolve_partner_ids(request.user)
    tab = "activities" if request.GET.get("tab") == "activities" else "schools"
    activities = list(
        Activity.objects.filter(
            assigned_partner_id__in=partner_ids,
            deleted_at__isnull=True,
            status__in=[
                "completed",
                "submitted_to_ia",
                "awaiting_ia_verification",
                "returned",
                "returned_by_ia",
                "ia_verified",
                "accountant_confirmed",
                "closed",
            ],
        )
        .select_related("school", "cluster")
        .order_by("-scheduled_date")[:200]
    )
    from apps.fund_requests.finance_models import PartnerInvoiceItem, PartnerPayment

    payments: dict[str, list] = {}
    for payment in PartnerPayment.objects.filter(
        activity_id__in=[a.id for a in activities]
    ):
        payments.setdefault(payment.activity_id, []).append(payment)

    # §13.3 the in-flight invoice dimension: an activity sitting on a live
    # period invoice is "processing" (with the PL) or "awaiting the
    # accountant" (confirmed) — distinct from eligible-but-uninvoiced.
    invoice_stage: dict[str, str] = {}
    for item in PartnerInvoiceItem.objects.filter(
        activity_id__in=[a.id for a in activities],
        invoice__status__in=("submitted_to_pl", "confirmed_by_pl"),
    ).select_related("invoice"):
        stage = (
            "awaiting_accountant"
            if item.invoice.status == "confirmed_by_pl"
            else "processing"
        )
        # Awaiting-accountant outranks processing if both somehow exist.
        if invoice_stage.get(item.activity_id) != "awaiting_accountant":
            invoice_stage[item.activity_id] = stage

    rows = []
    for a in activities:
        school_scoped = bool(a.school_id) and a.activity_type not in (
            _CLUSTER_SCOPE_TYPES
        )
        if (tab == "schools") is not school_scoped:
            continue
        paid_rows = payments.get(a.id, [])
        paid_total = sum(p.amount_paid for p in paid_rows)
        cleared = any(p.payment_type == "clearance" for p in paid_rows)
        # §14.4 partner-facing language, three dimensions honest underneath.
        if a.status in ("awaiting_ia_verification", "submitted_to_ia", "completed"):
            ia_label, ia_tone = "Under IA Review", "info"
        elif a.status in ("returned", "returned_by_ia"):
            ia_label, ia_tone = "Returned for Correction", "danger"
        else:
            ia_label, ia_tone = "Verified", "success"
        sf_label = "Confirmed" if a.salesforce_activity_id else "Pending"
        stage = invoice_stage.get(a.id)
        if cleared:
            pay_label, pay_tone = "Paid", "success"
        elif stage == "awaiting_accountant":
            pay_label, pay_tone = "Awaiting Accountant", "warning"
        elif stage == "processing":
            pay_label, pay_tone = "Payment Processing", "info"
        elif paid_rows:
            pay_label, pay_tone = "Advance Paid — Balance Pending", "info"
        elif ia_label == "Verified":
            pay_label, pay_tone = "Awaiting Payment", "warning"
        else:
            pay_label, pay_tone = "Not Yet Eligible", "neutral"
        last_payment = paid_rows[-1] if paid_rows else None
        rows.append(
            {
                "activity": a,
                "ia_label": ia_label,
                "ia_tone": ia_tone,
                "sf_label": sf_label,
                "pay_label": pay_label,
                "pay_tone": pay_tone,
                "paid_total": paid_total,
                "payment_date": last_payment.payment_date if last_payment else None,
                "payment_reference": (
                    last_payment.payment_reference if last_payment else ""
                ),
            }
        )
    return render(
        request,
        "pages/partner/completed_payments.html",
        {"rows": rows, "tab": tab},
    )


# ── §9 The partner activity workroom ─────────────────────────────────────────
# One page per activity: Start → actuals + evidence → Submit Evidence to IA.
# The page adapts to the activity's state instead of scattering the flow
# across drawers, and it is the target of every partner To-Do link.

_WORKROOM_STARTABLE = (
    "scheduled",
    "partner_scheduled",
    "assigned_to_partner",
    "rescheduled",
)
_WORKROOM_OPEN = (
    "completion_started",
    "in_progress",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
    "returned",
    "returned_by_pl",
    "returned_by_ia",
)
_WORKROOM_SUBMITTED = ("awaiting_ia_verification",)
_WORKROOM_DONE = ("ia_verified", "accountant_confirmed", "completed", "closed")


def _own_partner_activity(request, activity_id):
    partner_ids = resolve_partner_ids(request.user)
    return get_object_or_404(
        Activity.objects.select_related("school", "school__district", "cluster"),
        id=activity_id,
        assigned_partner_id__in=partner_ids,
        delivery_type="partner",
        deleted_at__isnull=True,
    )


@require_page_permission("partner_evidence")
def partner_activity_workroom_view(request, activity_id):
    from apps.evidence.requirements import checklist, evidence_optional
    from apps.activities.services import sf_kind_for_activity

    a = _own_partner_activity(request, activity_id)
    assignment = (
        PartnerAssignment.objects.select_related("source_ssa", "catalogue_item")
        .filter(scheduled_activity_id=a.id)
        .first()
    )
    evidence = list(
        EvidenceRecord.objects.filter(activity_id=a.id, quarantined=False).order_by(
            "-created_at"
        )
    )
    state = (
        "startable"
        if a.status in _WORKROOM_STARTABLE
        else "submitted"
        if a.status in _WORKROOM_SUBMITTED
        else "done"
        if a.status in _WORKROOM_DONE
        else "returned"
        if a.status in ("returned", "returned_by_pl", "returned_by_ia")
        else "open"
    )
    member_schools = []
    if a.cluster_id:
        member_schools = list(
            School.objects.filter(
                cluster_id=a.cluster_id, deleted_at__isnull=True
            ).order_by("name")
        )
    context = {
        "a": a,
        "assignment": assignment,
        "partner_org": Partner.objects.filter(id=a.assigned_partner_id).first(),
        "evidence": evidence,
        "evidence_checklist": checklist(a),
        "evidence_is_optional": evidence_optional(a),
        "state": state,
        "is_training_kind": sf_kind_for_activity(a) == "training",
        "member_schools": member_schools,
        "attended_ids": set(a.attended_school_ids or []),
        "back_url": "/my-plan",
    }
    return render(request, "pages/partner/activity_workroom.html", context)


@require_page_permission("partner_evidence")
def partner_activity_start_action(request, activity_id):
    """§9 Start Activity: in progress + start moment recorded, then straight
    to the evidence workroom. Starting never completes anything."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    a = _own_partner_activity(request, activity_id)
    try:
        from apps.activities.services import start_completion

        start_completion(a.id, principal=request.user)
    except Exception as exc:
        from apps.core.htmx_errors import error_fragment

        return error_fragment(exc, status=400)
    from apps.audit.services import log as audit_log

    audit_log(
        action="partner_start_activity",
        subject_kind="Activity",
        subject_id=str(a.id),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=True,
        reason=f"Started from {request.META.get('HTTP_USER_AGENT', 'unknown device')[:120]}",
    )
    return redirect(f"/partner/activities/{a.id}/evidence")


@require_page_permission("partner_evidence")
def partner_activity_submit_action(request, activity_id):
    """§9.4 Submit Evidence to IA — the one authoritative gate (`complete`),
    with actuals and no Salesforce ID (IA enters that at confirmation)."""
    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    a = _own_partner_activity(request, activity_id)
    try:
        from apps.activities.services import complete

        def _num(name):
            raw = (request.POST.get(name) or "").strip()
            return int(raw) if raw.isdigit() else None

        complete(
            a.id,
            {
                "actualDeliveryDate": request.POST.get("actual_delivery_date") or None,
                "teachersAttended": _num("teachers_attended"),
                "leadersAttended": _num("leaders_attended"),
                "otherParticipants": _num("other_participants"),
                "attendedSchoolIds": request.POST.getlist("attended_school_ids")
                or None,
                "actualOutcome": request.POST.get("actual_outcome") or "",
                "actualObservations": request.POST.get("actual_observations") or "",
                "followUpNote": request.POST.get("follow_up_note") or "",
            },
            request.user,
        )
    except Exception as exc:
        from apps.core.htmx_errors import error_fragment

        return error_fragment(exc, status=400)
    response = HttpResponse(
        '<script>try{localStorage.removeItem("partner-evidence-draft-"+%s)}catch(e){};window.location.href="/partner/completed";</script>'
        % repr(str(a.id))
    )
    response["HX-Trigger"] = "close-drawer"
    return response


# ── §8 The partner's My Plan: accepted implementation schedule ───────────────
# Five sections, one Actions menu per row. Submitted work leaves this page
# (it lives on Completed & Payments); stopped work never appears.

_PLAN_SCHEDULED = (
    "partner_scheduled",
    "scheduled",
    "rescheduled",
    "assigned_to_partner",
)
_PLAN_IN_PROGRESS = (
    "completion_started",
    "in_progress",
    "evidence_uploaded",
    "evidence_accepted",
    "salesforce_id_required",
)
_PLAN_RETURNED = ("returned", "returned_by_pl", "returned_by_ia")


def partner_plan_context(user):
    """The §8.1 sections. Every row carries what the table shows and the one
    Actions menu the far column renders."""
    from datetime import timedelta
    from apps.evidence.requirements import required_kinds_for_activity

    today = timezone.localdate()
    week_end = today + timedelta(days=6 - today.weekday())
    partner_ids = resolve_partner_ids(user)
    acts = list(
        Activity.objects.filter(
            assigned_partner_id__in=partner_ids,
            delivery_type="partner",
            deleted_at__isnull=True,
            status__in=_PLAN_SCHEDULED + _PLAN_IN_PROGRESS + _PLAN_RETURNED,
        )
        .select_related("school", "school__district", "cluster")
        .order_by("planned_date", "created_at")[:200]
    )
    present = defaultdict(set)
    for activity_id, kind in EvidenceRecord.objects.filter(
        activity_id__in=[a.id for a in acts], quarantined=False
    ).values_list("activity_id", "kind"):
        present[activity_id].add(kind)

    sections = {
        "needs_attention": [],
        "in_progress": [],
        "due_today": [],
        "this_week": [],
        "later": [],
    }
    for a in acts:
        needed = required_kinds_for_activity(a)
        have = present[a.id]
        if needed:
            met = sum(1 for k in needed if k in have)
            evidence_summary = f"{met}/{len(needed)} evidence items"
        else:
            evidence_summary = f"{len(have)} file(s)" if have else "No evidence yet"

        if a.status in _PLAN_RETURNED:
            bucket, actions = "needs_attention", ["correct"]
        elif a.status in _PLAN_IN_PROGRESS:
            bucket, actions = "in_progress", ["continue", "reschedule"]
        elif a.planned_date == today:
            bucket, actions = "due_today", ["start", "reschedule"]
        elif a.planned_date and a.planned_date < today:
            # Scheduled but the date passed unstarted — that IS attention.
            bucket, actions = "needs_attention", ["start", "reschedule"]
        elif a.planned_date and a.planned_date <= week_end:
            bucket, actions = "this_week", ["start", "reschedule"]
        else:
            bucket, actions = "later", ["start", "reschedule"]

        sections[bucket].append(
            {
                "a": a,
                "where": (
                    a.school.name
                    if a.school_id
                    else (a.cluster.name if a.cluster_id else "Field work")
                ),
                "location": (
                    a.school.district.name
                    if a.school_id and a.school.district_id
                    else ""
                ),
                "evidence_summary": evidence_summary,
                "return_reason": a.pl_review_note if a.status in _PLAN_RETURNED else "",
                "actions": actions,
            }
        )
    section_list = [
        (
            "Needs Attention",
            "Returned evidence and overdue work — fix these first.",
            sections["needs_attention"],
            "danger",
        ),
        (
            "In Progress",
            "Started — finish the evidence and submit to IA.",
            sections["in_progress"],
            "info",
        ),
        ("Due Today", "On today's schedule.", sections["due_today"], "warning"),
        ("Planned This Week", "Coming up this week.", sections["this_week"], "neutral"),
        ("Planned Later", "Scheduled beyond this week.", sections["later"], "neutral"),
    ]
    return {
        "plan_sections": section_list,
        "plan_total": len(acts),
    }
