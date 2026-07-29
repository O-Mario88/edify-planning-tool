"""Admin platform-operations pages and the platform-wide support intake."""

from __future__ import annotations

from datetime import date
from urllib.parse import quote, urlencode

from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.admin_ops.detection import report_client_defect
from apps.admin_ops.models import (
    AdminOperationsWorkItem,
    IncidentStatus,
    MaintenanceTemplate,
    Severity,
    SupportTicket,
    SystemIncident,
    TicketStatus,
    WorkItemStatus,
)
from apps.admin_ops.services import (
    AdminMyPlanService,
    AdminPlanningService,
    AdminWorkItemService,
    SupportTicketService,
    SystemIncidentService,
)
from apps.admin_ops.team_plans import AdminTeamPlansService
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.permissions import require_page_permission


def _admin_only(request):
    """Admin-only guard for the platform-operations workspaces.

    Layered under `require_page_permission`, which handles the anonymous case
    by redirecting to login. This adds the role check, so a signed-in
    non-Admin is refused rather than silently shown an empty workspace.
    """
    if getattr(request.user, "active_role", None) != "Admin":
        return HttpResponseForbidden("Platform operations are Admin-only.")
    return None


# ── Team Plans (read-only) ───────────────────────────────────────────────────


@require_page_permission("admin_team_plans")
def team_plans_view(request):
    denied = _admin_only(request)
    if denied:
        return denied
    query = {
        k: request.GET.get(k, "")
        for k in (
            "fy",
            "month",
            "week",
            "activity_type",
            "status",
            "district",
            "project",
            "partner",
            "user",
            "team",
            "role",
            "overdue",
        )
    }
    context = AdminTeamPlansService.get(request.user, query)
    context["options"] = AdminTeamPlansService.filter_options(context["fy"])
    context["group_by"] = request.GET.get("group_by", "user")
    return render(request, "pages/admin_ops/team_plans.html", context)


# ── Admin Planning (unscheduled backlog) ─────────────────────────────────────


@require_page_permission("admin_planning")
def admin_planning_view(request):
    denied = _admin_only(request)
    if denied:
        return denied
    context = AdminPlanningService.context(request.user)
    context["severities"] = Severity.choices
    return render(request, "pages/admin_ops/planning.html", context)


@require_POST
@require_page_permission("admin_planning")
def schedule_work_item_view(request, item_id):
    denied = _admin_only(request)
    if denied:
        return denied
    raw = (request.POST.get("scheduled_date") or "").strip()
    try:
        when = date.fromisoformat(raw)
    except ValueError:
        messages.error(request, "Choose a valid date to schedule this work.")
        return redirect("/admin-ops/planning")
    try:
        item = AdminWorkItemService.schedule(item_id, request.user, when)
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
        return redirect("/admin-ops/planning")
    messages.success(
        request, f"{item.reference} scheduled for {when:%d %b} — now in Admin My Plan."
    )
    return redirect("/admin-ops/my-plan")


# ── Admin My Plan (scheduled platform work) ──────────────────────────────────


@require_page_permission("admin_my_plan")
def admin_my_plan_view(request):
    denied = _admin_only(request)
    if denied:
        return denied
    context = AdminMyPlanService.context(request.user)
    return render(request, "pages/admin_ops/my_plan.html", context)


@require_POST
@require_page_permission("admin_my_plan")
def start_work_item_view(request, item_id):
    denied = _admin_only(request)
    if denied:
        return denied
    try:
        AdminWorkItemService.start(item_id, request.user)
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/admin-ops/my-plan")


@require_POST
@require_page_permission("admin_my_plan")
def complete_work_item_view(request, item_id):
    denied = _admin_only(request)
    if denied:
        return denied
    note = (request.POST.get("verification_note") or "").strip()
    try:
        AdminWorkItemService.complete(item_id, request.user, note)
        messages.success(request, "Work verified and closed.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/admin-ops/my-plan")


# ── Support tickets ──────────────────────────────────────────────────────────


@require_page_permission("admin_support_queue")
def support_queue_view(request):
    denied = _admin_only(request)
    if denied:
        return denied
    status = request.GET.get("status", "")
    tickets = SupportTicket.objects.all()
    if status:
        tickets = tickets.filter(status=status)
    return render(
        request,
        "pages/admin_ops/support_queue.html",
        {
            "tickets": list(tickets[:200]),
            "status": status,
            "statuses": TicketStatus.choices,
            "counts": {
                "untriaged": SupportTicket.objects.filter(
                    status=TicketStatus.SUBMITTED
                ).count(),
                "open": SupportTicket.objects.exclude(
                    status__in=[
                        TicketStatus.CLOSED,
                        TicketStatus.RESOLVED,
                        TicketStatus.INVALID,
                        TicketStatus.CANCELLED,
                        TicketStatus.DUPLICATE,
                    ]
                ).count(),
            },
        },
    )


@require_POST
@require_page_permission("admin_support_queue")
def triage_ticket_view(request, ticket_id):
    denied = _admin_only(request)
    if denied:
        return denied
    severity = request.POST.get("severity") or Severity.MEDIUM
    raw = (request.POST.get("scheduled_date") or "").strip()
    when = None
    if raw:
        try:
            when = date.fromisoformat(raw)
        except ValueError:
            when = None
    try:
        item = SupportTicketService.triage(
            ticket_id, request.user, severity=severity, schedule_for=when
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
        return redirect("/admin-ops/support")
    destination = "/admin-ops/my-plan" if item.scheduled_date else "/admin-ops/planning"
    messages.success(request, f"{item.reference} created from the ticket.")
    return redirect(destination)


@require_POST
@require_page_permission("admin_support_queue")
def resolve_ticket_view(request, ticket_id):
    denied = _admin_only(request)
    if denied:
        return denied
    note = (request.POST.get("resolution") or "").strip()
    try:
        SupportTicketService.transition(
            ticket_id, TicketStatus.RESOLVED, request.user, note
        )
        messages.success(request, "Ticket resolved — the reporter has been notified.")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect("/admin-ops/support")


# ── Support intake — every role, every page ──────────────────────────────────


@require_page_permission("report_problem")
def report_problem_view(request):
    """The canonical "Report a Problem" surface, open to every signed-in role."""
    if request.method == "GET":
        return render(
            request,
            "pages/admin_ops/report_problem.html",
            {
                "route": request.GET.get("route", ""),
                "categories": SupportTicket._meta.get_field("category").choices,
                "urgencies": Severity.choices,
                "my_tickets": list(
                    SupportTicket.objects.filter(
                        reporter_id=getattr(request.user, "id", "")
                    )[:20]
                ),
            },
        )

    context = {
        "route": (request.POST.get("route") or "")[:255],
        "page_title": (request.POST.get("page_title") or "")[:255],
        "object_type": (request.POST.get("object_type") or "")[:64],
        "object_id": (request.POST.get("object_id") or "")[:64],
        "browser": request.META.get("HTTP_USER_AGENT", "")[:255],
        "request_id": getattr(request, "correlation_id", "") or "",
    }
    try:
        ticket = SupportTicketService.create(request.user, request.POST.dict(), context)
    except BadRequest as exc:
        messages.error(request, str(exc))
        return redirect("/support")
    messages.success(
        request,
        f"Thank you — {ticket.reference} is with the platform team. "
        "You can follow its status here.",
    )
    return redirect("/support")


@require_POST
@require_page_permission("report_problem")
def client_defect_view(request):
    """Browser-side defect beacon: dead buttons, JS errors, failed HTMX swaps."""
    import json

    try:
        payload = json.loads(request.body.decode() or "{}")
    except ValueError:
        return JsonResponse({"detail": "Invalid payload."}, status=400)
    incident = report_client_defect(
        kind=(payload.get("kind") or "")[:32],
        route=(payload.get("route") or "")[:255],
        component=(payload.get("component") or "")[:128],
        detail=payload.get("detail") or {},
        request_id=getattr(request, "correlation_id", "") or "",
    )
    if incident is None:
        return JsonResponse({"detail": "Unrecognised defect kind."}, status=400)
    return JsonResponse({"incident": incident.reference}, status=201)


# ── Incidents ────────────────────────────────────────────────────────────────


@require_page_permission("admin_incidents")
def incidents_view(request):
    denied = _admin_only(request)
    if denied:
        return denied
    status = request.GET.get("status", "")
    incidents = SystemIncident.objects.all()
    if status:
        incidents = incidents.filter(status=status)
    return render(
        request,
        "pages/admin_ops/incidents.html",
        {
            "incidents": list(incidents[:200]),
            "status": status,
            "statuses": IncidentStatus.choices,
        },
    )


@require_page_permission("admin_incidents")
def incident_detail_view(request, incident_id):
    denied = _admin_only(request)
    if denied:
        return denied
    incident = get_object_or_404(SystemIncident, id=incident_id)
    from apps.audit.models import AuditLog

    return render(
        request,
        "pages/admin_ops/incident_detail.html",
        {
            "incident": incident,
            "work_items": list(incident.work_items.all()),
            "audit": list(
                AuditLog.objects.filter(subject_id=incident.id).order_by("-created_at")[
                    :50
                ]
            ),
        },
    )


def _incident_url(incident_id) -> str:
    """This incident's own page, with the id encoded into the path segment.

    The URLconf declares ``<str:incident_id>``, and Django's ``str`` converter
    already excludes "/", so interpolating the raw id could not escape the
    /admin-ops/ prefix today. Encode it anyway: a Location header should be
    provably inert at the line that builds it, not by way of a converter
    declared in another file that a later route change could loosen to
    ``<path:…>`` without anyone rereading these redirects.
    """
    return f"/admin-ops/incidents/{quote(str(incident_id), safe='')}"


@require_POST
@require_page_permission("admin_incidents")
def acknowledge_incident_view(request, incident_id):
    denied = _admin_only(request)
    if denied:
        return denied
    try:
        SystemIncidentService.acknowledge(incident_id, request.user)
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect(_incident_url(incident_id))


@require_POST
@require_page_permission("admin_incidents")
def resolve_incident_view(request, incident_id):
    denied = _admin_only(request)
    if denied:
        return denied
    try:
        SystemIncidentService.resolve(
            incident_id, request.user, (request.POST.get("note") or "").strip()
        )
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    return redirect(_incident_url(incident_id))


# ── Maintenance calendar ─────────────────────────────────────────────────────


@require_page_permission("admin_maintenance")
def maintenance_view(request):
    denied = _admin_only(request)
    if denied:
        return denied
    return render(
        request,
        "pages/admin_ops/maintenance.html",
        {
            "templates": list(MaintenanceTemplate.objects.all()),
            "generated": list(
                AdminOperationsWorkItem.objects.filter(
                    category__in=["preventive_maintenance", "corrective_maintenance"]
                ).exclude(status=WorkItemStatus.DONE)[:50]
            ),
        },
    )


# ── Data Repair Center (§26) ─────────────────────────────────────────────────


@require_page_permission("data_repair")
def data_repair_view(request):
    denied = _admin_only(request)
    if denied:
        return denied
    from apps.admin_ops.repair import DataRepairService

    key = request.GET.get("repair", "")
    preview = None
    if key:
        try:
            preview = DataRepairService.dry_run(request.user, key)
        except BadRequest as exc:
            messages.error(request, str(exc))
    return render(
        request,
        "pages/admin_ops/data_repair.html",
        {
            "catalogue": DataRepairService.catalogue(request.user),
            "preview": preview,
        },
    )


@require_POST
@require_page_permission("data_repair")
def apply_repair_view(request, key):
    denied = _admin_only(request)
    if denied:
        return denied
    from apps.admin_ops.repair import DataRepairService

    reason = (request.POST.get("reason") or "").strip()
    try:
        result = DataRepairService.apply(request.user, key, reason)
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
        return redirect(f"/data-repair?{urlencode({'repair': key})}")
    if result.get("referred"):
        messages.success(
            request,
            f"{result['affected']} record(s) referred — {result['work_item']} is in "
            "Admin My Plan.",
        )
    elif result.get("verified"):
        messages.success(
            request,
            f"Repaired {result['changed']} record(s); verification found none left.",
        )
    else:
        messages.warning(
            request,
            f"Repaired {result['changed']} record(s), but {result['remaining']} "
            "still match — investigate before re-running.",
        )
    return redirect("/data-repair")
