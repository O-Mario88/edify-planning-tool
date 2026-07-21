"""
GROUP 3 — Partner Views
Partner directory, partner detail, partner portal pages
"""

from apps.core.activity_types import COMPLETED_WORK_STATUSES
import csv
from collections import defaultdict

from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import render, get_object_or_404
from apps.core.permissions import require_export_permission, require_page_permission
from apps.core.rbac import EdifyRole
from apps.core.scoping import resolve_partner_ids
from django.db.models import Q
from datetime import date
from django.utils import timezone

from apps.core.fy import fy_options, get_fy_date_range, get_operational_fy
from apps.clusters.models import Cluster
from apps.geography.models import Region
from apps.partners.models import Partner, PartnerAssignment
from apps.partners.purposes import visit_purpose_label
from apps.activities.models import Activity
from apps.evidence.models import EvidenceRecord
from apps.schools.models import School

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
    """Partner Activities workspace for staff and partner organisations.

    The former directory only named organisations.  This view joins the
    assignment queue with scheduled partner work so staff can see what is
    assigned, scheduled, due, and funded without leaving the page.
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
        partners_qs = partners_qs.filter(
            Q(name__icontains=search) | Q(region_name__icontains=search)
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
            "assigned_schools": len(
                {
                    assignment.school_id
                    for assignment in assignments
                    if assignment.school_id
                }
                | {activity.school_id for activity in activities if activity.school_id}
            ),
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
        "pending_reminders": pending_rows[:5],
        "upcoming_activities": sorted(
            [row for row in scheduled_rows if row["date"] and row["date"] >= today],
            key=lambda row: row["date"],
        )[:5],
    }
    return render(request, "pages/partners/index.html", context)


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
    """Partner dashboard — today's work."""
    user = request.user
    today = date.today()
    # Partner-role logins have no StaffProfile, so responsible_staff_id (a
    # StaffProfile id) never matches user.id — scope by the partner-activity
    # link instead (same resolver used everywhere else a partner identity is
    # checked, e.g. apps/debriefs/field_debrief_service.py).
    partner_ids = resolve_partner_ids(user)
    today_activities = (
        Activity.objects.filter(
            assigned_partner_id__in=partner_ids,
            planned_date=today,
            deleted_at__isnull=True,
        )
        .select_related("school", "cluster")
        .order_by("activity_type")
    )

    upcoming = (
        Activity.objects.filter(
            assigned_partner_id__in=partner_ids,
            planned_date__gt=today,
            status="scheduled",
            deleted_at__isnull=True,
        )
        .select_related("school")
        .order_by("planned_date")[:5]
    )

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
