"""Extra Assigned Work pages (§18) — assign, execute, review, track."""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.htmx_errors import error_fragment
from apps.core.permissions import require_page_permission
from apps.hr import extra_work
from apps.hr.models import ExtraAssignment


def _reload():
    response = HttpResponse("<script>window.location.reload();</script>")
    response["HX-Trigger"] = "close-drawer"
    return response


@require_page_permission("extra_work")
def extra_work_page(request):
    from apps.core.fy import fy_options, get_operational_fy

    fy = (request.GET.get("fy") or "").strip() or get_operational_fy()
    uid = str(request.user.id)
    role = getattr(request.user, "active_role", "")
    today = timezone.localdate()

    mine = list(
        ExtraAssignment.objects.filter(assignee_id=uid, fy=fy).order_by("due_date")[
            :100
        ]
    )
    assigned_by_me = list(
        ExtraAssignment.objects.filter(assigner_id=uid, fy=fy).order_by("due_date")[
            :100
        ]
    )
    to_review = list(
        ExtraAssignment.objects.filter(
            reviewer_id=uid, status="submitted", fy=fy
        ).order_by("submitted_at")[:50]
    )
    # A supervising PL monitors CD assignments on their team (read-only).
    monitoring = list(
        ExtraAssignment.objects.filter(supervising_pl_id=uid, fy=fy)
        .exclude(assigner_id=uid)
        .order_by("due_date")[:50]
    )
    for row in mine + assigned_by_me + to_review + monitoring:
        row.is_overdue = (
            row.status in ExtraAssignment.OPEN_STATUSES and row.due_date < today
        )

    return render(
        request,
        "pages/hr/extra_work.html",
        {
            "fy": fy,
            "fy_options": fy_options(),
            "mine": mine,
            "assigned_by_me": assigned_by_me,
            "to_review": to_review,
            "monitoring": monitoring,
            "can_assign": role in extra_work.ASSIGNER_ROLES,
            "summary": extra_work.performance_summary(uid, fy),
            "use_dark_sidebar": True,
        },
    )


@require_page_permission("extra_work")
def extra_work_assign_drawer(request):
    role = getattr(request.user, "active_role", "")
    if role not in extra_work.ASSIGNER_ROLES:
        return error_fragment(
            Forbidden("Only the CD or a Program Lead assigns extra work."),
            status=403,
        )
    User = get_user_model()
    if role == "CountryDirector":
        assignees = User.objects.filter(
            active_role__in=("Program Lead", "CCEO"), is_active=True
        ).order_by("name")
    else:
        from apps.accounts.models import StaffSupervisorAssignment

        supervised_ids = StaffSupervisorAssignment.objects.filter(
            supervisor_id=getattr(request.user, "staff_profile_id", None)
        ).values_list("supervisee__user_id", flat=True)
        assignees = User.objects.filter(
            id__in=list(supervised_ids), is_active=True
        ).order_by("name")
    from apps.hr.models import PriorityMilestone

    milestones = PriorityMilestone.objects.filter(
        priority__level="country", priority__country_id="Uganda"
    ).order_by("priority__sequence", "source_order")
    return render(
        request,
        "partials/hr/extra_work_assign_drawer.html",
        {
            "assignees": assignees.exclude(id=request.user.id)[:200],
            "milestones": milestones[:120],
            "categories": ExtraAssignment.CATEGORIES,
            "drawer_size": "md",
        },
    )


@require_page_permission("extra_work")
def extra_work_assign_action(request):
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        extra_work.create_assignment(
            request.user,
            {
                "assignee_id": request.POST.get("assignee_id"),
                "title": request.POST.get("title"),
                "instruction": request.POST.get("instruction"),
                "reason": request.POST.get("reason"),
                "category": request.POST.get("category"),
                "linked_milestone_id": request.POST.get("linked_milestone_id"),
                "due_date": request.POST.get("due_date") or None,
                "expected_output": request.POST.get("expected_output"),
                "evidence_required": request.POST.get("evidence_required") == "on",
                "complexity": request.POST.get("complexity"),
                "urgency": request.POST.get("urgency"),
            },
        )
    except (BadRequest, Forbidden) as exc:
        return error_fragment(exc, status=400)
    return _reload()


@require_page_permission("extra_work")
def extra_work_submit_drawer(request, assignment_id):
    a = ExtraAssignment.objects.filter(
        id=assignment_id, assignee_id=str(request.user.id)
    ).first()
    if a is None:
        return error_fragment(BadRequest("Assignment not found."), status=404)
    return render(
        request,
        "partials/hr/extra_work_submit_drawer.html",
        {"a": a, "drawer_size": "md"},
    )


@require_page_permission("extra_work")
def extra_work_action(request, assignment_id, action):
    if request.method != "POST":
        return HttpResponse(status=405)
    try:
        if action == "acknowledge":
            extra_work.acknowledge(request.user, assignment_id)
        elif action == "start":
            extra_work.start(request.user, assignment_id)
        elif action == "submit":
            extra_work.submit(
                request.user,
                assignment_id,
                {
                    "outcome": request.POST.get("outcome"),
                    "evidence_note": request.POST.get("evidence_note"),
                    "evidence_uri": request.POST.get("evidence_uri"),
                },
            )
        elif action == "return":
            extra_work.return_work(
                request.user, assignment_id, request.POST.get("reason", "")
            )
        elif action == "verify":
            extra_work.verify(request.user, assignment_id, request.POST.get("note", ""))
        elif action == "cancel":
            extra_work.cancel(
                request.user, assignment_id, request.POST.get("reason", "")
            )
        else:
            return HttpResponse("Unknown action", status=400)
    except (BadRequest, Forbidden) as exc:
        return error_fragment(exc, status=400)
    return _reload()
