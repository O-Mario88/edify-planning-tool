"""Project Capacity — the Project Coordinator's school allocations.

Brief, 2026-09-29: the coordinator sets how many schools each staff member
may add to each project, and sees at a glance, project by project, who holds
how many, how many are left and where the work stands. The page follows Cost
Settings: one primary button in the header opens a drawer, a compact filter,
and each record edited in its own drawer.

Every number here comes from ``apps.projects.capacity``; the views only ask
it. Withdrawing a school lives here too because it returns a place to an
allocation: the staff member who added the school and the project's
coordinator reach it from Project Monitoring's row menu.
"""

from __future__ import annotations

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render

from apps.core.exceptions import BadRequest, ConflictError, Forbidden, NotFoundError
from apps.core.permissions import require_page_permission


def _directed_projects(user):
    """The live projects this principal may set allocations on."""
    from apps.projects.authority import projects_directed_by
    from apps.projects.models import LIVE_PROJECT_STATUSES, Project
    from apps.projects.scoping import scoped_projects

    live = [status.value for status in LIVE_PROJECT_STATUSES]
    projects = list(
        scoped_projects(user, base=Project.objects.filter(deleted_at__isnull=True))
        .filter(status__in=live)
        .order_by("name")
    )
    directed = projects_directed_by(user, [p.id for p in projects])
    return [p for p in projects if p.id in directed]


def _refresh(message: str, *, to: str) -> HttpResponse:
    """Close the drawer and redraw the page with the saved state."""
    from django.utils.html import escape

    response = HttpResponse(
        f'<p class="pill pill-success" role="status">{escape(message)}</p>'
    )
    response["HX-Trigger"] = "close-drawer"
    response["HX-Redirect"] = to
    return response


@require_page_permission("project_capacity")
def project_capacity_view(request):
    from apps.projects import capacity

    projects = _directed_projects(request.user)
    selected = (request.GET.get("project") or "").strip()
    shown = [p for p in projects if p.id == selected] if selected else projects
    by_project = capacity.allocations_by_project([p.id for p in shown])
    sections = []
    for project in shown:
        allocations = by_project.get(project.id, [])
        sections.append(
            {
                "project": project,
                "allocations": allocations,
                "summary": capacity.project_summary(project, allocations),
                "blocked": not project.accepts_new_work,
            }
        )
    return render(
        request,
        "pages/projects/capacity.html",
        {
            "project_options": projects,
            "selected_project": selected,
            "sections": sections,
        },
    )


def _drawer(request, context, status=200):
    return render(
        request, "partials/projects/capacity_drawer.html", context, status=status
    )


@require_page_permission("project_capacity")
def project_capacity_set_view(request):
    """``+ Set Staff Capacity``: a new allocation for one staff member."""
    from apps.projects import capacity

    projects = _directed_projects(request.user)
    project_id = (
        request.POST.get("project_id") or request.GET.get("project") or ""
    ).strip()
    project = next((p for p in projects if p.id == project_id), None)
    staff_options = list(capacity.eligible_staff(project)) if project else []
    taken = (
        set(project.staff_capacities.values_list("staff_id", flat=True))
        if project
        else set()
    )
    context = {
        "mode": "create",
        "projects": projects,
        "project": project,
        "staff_options": staff_options,
        "taken_staff": taken,
        "values": {
            "staff_id": (request.POST.get("staff_id") or "").strip(),
            "max_schools": (request.POST.get("max_schools") or "").strip(),
        },
        "drawer_size": "md",
    }
    if request.method == "POST" and request.POST.get("save"):
        try:
            allocation = capacity.set_capacity(
                project_id,
                context["values"]["staff_id"],
                context["values"]["max_schools"],
                request.user,
                create=True,
            )
        except (BadRequest, Forbidden, NotFoundError) as exc:
            context["validation_error"] = str(exc)
            return _drawer(request, context, status=200)
        return _refresh(
            f"{allocation.staff_name} may add {allocation.maximum} schools to "
            f"{allocation.project_name}.",
            to=f"/projects/capacity?project={allocation.project_id}",
        )
    return _drawer(request, context)


@require_page_permission("project_capacity")
def project_capacity_edit_view(request, capacity_id):
    """Change one allocation's maximum."""
    from apps.projects import capacity
    from apps.projects.models import ProjectStaffCapacity

    row = (
        ProjectStaffCapacity.objects.select_related("project", "staff__user")
        .filter(id=capacity_id, project__deleted_at__isnull=True)
        .first()
    )
    projects = {p.id: p for p in _directed_projects(request.user)}
    if row is None or row.project_id not in projects:
        return _drawer(
            request,
            {"mode": "missing", "drawer_size": "md"},
            status=404,
        )
    allocation = capacity.allocation_for(row.project_id, row.staff_id)
    context = {
        "mode": "edit",
        "row": row,
        "project": row.project,
        "allocation": allocation,
        "values": {
            "max_schools": (
                request.POST.get("max_schools") or str(row.max_schools)
            ).strip()
        },
        "drawer_size": "md",
    }
    if request.method == "POST":
        try:
            allocation = capacity.set_capacity(
                row.project_id,
                row.staff_id,
                context["values"]["max_schools"],
                request.user,
                create=False,
            )
        except (BadRequest, Forbidden, NotFoundError) as exc:
            context["validation_error"] = str(exc)
            return _drawer(request, context)
        return _refresh(
            f"{allocation.staff_name}'s allocation on {allocation.project_name} "
            f"is {allocation.maximum} schools.",
            to=f"/projects/capacity?project={allocation.project_id}",
        )
    return _drawer(request, context)


# ── Withdraw a school from a project ────────────────────────────────────────
def _withdrawable_enrolment(user, enrolment_id):
    """The enrolment, when this user may withdraw it; else None."""
    from apps.projects.capacity import may_withdraw
    from apps.projects.models import ProjectSchoolAssignment

    enrolment = (
        ProjectSchoolAssignment.objects.select_related(
            "project", "school", "school__district", "assigned_staff__user"
        )
        .filter(id=enrolment_id or "", project__deleted_at__isnull=True)
        .first()
    )
    if enrolment is None or not may_withdraw(user, enrolment):
        return None
    return enrolment


@require_page_permission("project_monitoring")
def project_withdraw_school_view(request):
    """Withdraw School: the confirmation drawer and its submission.

    The service (``projects.services.remove_school``) decides again whether
    the school may leave and who may take it out; this drawer only shows what
    it will decide, so the button is never live for a refusal.
    """
    from apps.projects import capacity
    from apps.projects.services import remove_school

    enrolment_id = (
        request.POST.get("enrolment") or request.GET.get("enrolment") or ""
    ).strip()
    enrolment = _withdrawable_enrolment(request.user, enrolment_id)
    if enrolment is None:
        return render(
            request,
            "partials/projects/withdraw_school_drawer.html",
            {"enrolment": None, "drawer_size": "md"},
            status=404,
        )
    context = {
        "enrolment": enrolment,
        # Not "block": inside {% block %} Django binds that name to the
        # template's BlockNode.
        "leave_block": capacity.withdrawal_block(
            enrolment.project_id, enrolment.school_id
        ),
        "reasons": capacity.WITHDRAWAL_REASONS,
        "values": {
            "reason_code": (request.POST.get("reason_code") or "").strip(),
            "reason_other": (request.POST.get("reason_other") or "").strip(),
        },
        "drawer_size": "md",
    }
    if request.method == "POST":
        try:
            remove_school(
                enrolment.project_id,
                enrolment.school_id,
                request.user,
                reason=context["values"]["reason_other"],
                reason_code=context["values"]["reason_code"],
            )
        except (BadRequest, ConflictError, Forbidden, NotFoundError) as exc:
            context["validation_error"] = str(exc)
            context["leave_block"] = capacity.withdrawal_block(
                enrolment.project_id, enrolment.school_id
            )
            return render(
                request, "partials/projects/withdraw_school_drawer.html", context
            )
        message = f"{enrolment.school.name} withdrawn from {enrolment.project.name}."
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse(status=204)
            response["HX-Trigger"] = "close-drawer"
            response["HX-Refresh"] = "true"
            messages.success(request, message)
            return response
        messages.success(request, message)
        return redirect("/projects/monitoring")
    return render(request, "partials/projects/withdraw_school_drawer.html", context)


# ── Withdraw many schools from a project (owner, 2026-09-29) ────────────────
def mark_withdrawable(user, project, rows) -> bool:
    """Set ``can_withdraw`` (and ``withdraw_block``, why not) on each
    portfolio row for this reader; True when any row can be ticked.

    The same two questions the single Withdraw asks: may this reader take the
    enrolment out (``capacity.may_withdraw``), and has its work not begun
    (``capacity.withdrawal_blocks``). The service asks both again."""
    from apps.projects import capacity
    from apps.projects.models import ProjectSchoolAssignment

    if not rows:
        return False
    enrolments = {
        e.id: e
        for e in ProjectSchoolAssignment.objects.filter(
            id__in=[r["assignment_id"] for r in rows]
        )
    }
    blocks = capacity.withdrawal_blocks((project.id, r["school_id"]) for r in rows)
    any_withdrawable = False
    for row in rows:
        enrolment = enrolments.get(row["assignment_id"])
        block = blocks.get((str(project.id), str(row["school_id"])))
        allowed = enrolment is not None and capacity.may_withdraw(user, enrolment)
        row["can_withdraw"] = bool(allowed and block is None)
        row["withdraw_block"] = block.title if (allowed and block) else ""
        # Why the box is greyed: a state or ownership lock says so (owner's
        # rule, 2026-09-27: such locks stay visible, greyed, with a reason).
        row["withdraw_reason"] = (
            ""
            if row["can_withdraw"]
            else row["withdraw_block"]
            or "Only the officer who added it, or the Project Coordinator, "
            "can withdraw it"
        )
        any_withdrawable = any_withdrawable or row["can_withdraw"]
    return any_withdrawable


@require_page_permission("projects")
def project_bulk_withdraw_view(request, project_id):
    """Withdraw the schools ticked on a project's Participating Schools.

    GET lists each ticked school with whether it will leave (and why not);
    POST withdraws each through ``projects.services.remove_schools`` with the
    one reason given, and reports every school."""
    from apps.projects import capacity
    from apps.projects.models import Project
    from apps.projects.portfolio import portfolio_rows
    from apps.projects.services import remove_schools

    project = Project.objects.filter(id=project_id, deleted_at__isnull=True).first()
    if project is None:
        return render(
            request,
            "partials/projects/bulk_withdraw_drawer.html",
            {"error": "Project not found.", "drawer_size": "md"},
            status=404,
        )
    source = request.POST if request.method == "POST" else request.GET
    ticked = [i.strip() for i in source.getlist("school_ids") if i.strip()]
    rows = [r for r in portfolio_rows(project) if r["school_id"] in set(ticked)]
    mark_withdrawable(request.user, project, rows)
    values = {
        "reason_code": (request.POST.get("reason_code") or "").strip(),
        "reason_other": (request.POST.get("reason_other") or "").strip(),
    }
    context = {
        "project": project,
        "rows": rows,
        "withdrawable": [r for r in rows if r["can_withdraw"]],
        "reasons": capacity.WITHDRAWAL_REASONS,
        "values": values,
        "drawer_size": "md",
    }
    if request.method == "POST":
        try:
            outcomes = remove_schools(
                project.id,
                [r["school_id"] for r in context["withdrawable"]],
                request.user,
                reason=values["reason_other"],
                reason_code=values["reason_code"],
            )
        except BadRequest as exc:
            context["validation_error"] = str(exc)
            return render(
                request, "partials/projects/bulk_withdraw_drawer.html", context
            )
        done = sum(1 for o in outcomes if o["ok"])
        message = (
            f"{done} school{'s' if done != 1 else ''} withdrawn from {project.name}."
        )
        left = [o for o in outcomes if not o["ok"]]
        if left:
            message += " Not withdrawn: " + "; ".join(
                f"{o['school'] or 'a school'} ({o['message']})" for o in left
            )
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse(status=204)
            response["HX-Trigger"] = "close-drawer"
            response["HX-Refresh"] = "true"
            (messages.success if done else messages.error)(request, message)
            return response
        (messages.success if done else messages.error)(request, message)
        return redirect(f"/projects/{project.id}")
    return render(request, "partials/projects/bulk_withdraw_drawer.html", context)
