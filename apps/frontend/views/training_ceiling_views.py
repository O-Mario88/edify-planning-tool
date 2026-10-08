"""Training ceilings and the training summary (owner, 2026-10-06).

A Programme Lead sets, for each officer they supervise, how many schools that
officer may schedule for a training in a fiscal year; officers see their own
ceiling and what they have scheduled under it; and every figure opens the
schools it counts. Every number, every permission and every refusal comes from
``apps.planning.training_ceilings`` — these views only ask it.

The ceiling drawer follows Project Capacity's (the page header's capacity
button opens it), and the summary sits where each role reads plans: the
Training Summary tab of Planning Oversight for a Programme Lead (their
officers) and for the Country Director, Impact Assessment and Admin (every
officer), and My Plan for the officer (their own table).

Admin and Impact Assessment set the Country Ceiling of a training from the
same tab (owner, 2026-10-06: "The admin IA will set the Country Ceiling and
Leads will set each staff ceiling"); the Country Director reads.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.fy import fy_options, get_operational_fy
from apps.core.permissions import (
    RolePermissionService,
    require_any_page_permission,
    require_page_permission,
)
from apps.core.rbac import EdifyRole

SUMMARY_URL = "/team-planning-oversight/?view=trainings"


def _fy_from(raw) -> str:
    """The fiscal year of the day a drawer has chosen; this year when none."""
    text = str(raw or "").strip()[:10]
    if text:
        try:
            return str(get_operational_fy(date.fromisoformat(text)))
        except ValueError:
            pass
    return str(get_operational_fy())


def _own_staff_id(user) -> str | None:
    return getattr(user, "staff_profile_id", None) or getattr(user, "user_id", None)


def _session_owner(request) -> str | None:
    """Whose cluster session the drawer is planning: the name a Programme
    Lead or Admin chose, anyone else's own — the rule the save applies."""
    chosen = (request.GET.get("staff") or "").strip()
    if chosen and getattr(request.user, "active_role", "") in (
        EdifyRole.COUNTRY_PROGRAM_LEAD.value,
        EdifyRole.ADMIN.value,
    ):
        return chosen
    return _own_staff_id(request.user)


@require_any_page_permission("planning", "my_plan", "core_schools", "clusters")
@require_http_methods(["GET"])
def training_capacity_view(request):
    """What a scheduling drawer shows under its Training field: the ceiling of
    the officer the plan belongs to, and what is already scheduled under it.

    A read for the browser's benefit. The save counts again, behind a lock
    (``training_ceilings.reserve``), so nothing here is trusted on the way
    back in.
    """
    from apps.activities.models import Activity
    from apps.planning import training_ceilings

    training_id = (request.GET.get("training") or "").strip()
    activity_id = (request.GET.get("activity") or "").strip()
    school_key = (request.GET.get("school") or "").strip()
    # The one school a drawer is scheduling for, where the drawer files the
    # work under its own reader: only asked so the answer can say whether
    # that school is already counted and so takes no new place.
    for_school = (request.GET.get("for_school") or "").strip()
    named_school_id = None
    exclude = None
    if activity_id:
        # The Edit drawer: the plan's own officer, training and year, with
        # its own schools left out of what is "already scheduled".
        activity = (
            Activity.objects.select_related("catalogue_item")
            .filter(id=activity_id, deleted_at__isnull=True)
            .first()
        )
        if activity is None or not RolePermissionService.can_view_record(
            request.user, activity
        ):
            return JsonResponse({"managed": False}, status=404)
        staff_id = activity.responsible_staff_id
        # The training the drawer has chosen for it, else the one it names.
        training_id = training_id or training_ceilings.course_id_of(activity) or ""
        if not training_ceilings.is_training(activity):
            training_id = ""
        fy = (
            _fy_from(request.GET.get("date"))
            if request.GET.get("date")
            else str(activity.fy)
        )
        exclude = activity.id
    elif school_key:
        # An in-school training belongs to whoever the school drawer files
        # the visit under, resolved the way its save resolves it.
        from apps.core.permissions import get_visit_target_school_or_404
        from apps.frontend.views.planning_views import visit_owner_for

        school = get_visit_target_school_or_404(
            request.user, Q(id=school_key) | Q(school_id=school_key)
        )
        staff_id, _name = visit_owner_for(school, request.user)
        fy = _fy_from(request.GET.get("date"))
        named_school_id = school.id
    else:
        staff_id = _session_owner(request)
        fy = _fy_from(request.GET.get("date"))
        if for_school:
            from apps.schools.models import School

            named_school_id = (
                School.objects.filter(Q(id=for_school) | Q(school_id=for_school))
                .values_list("id", flat=True)
                .first()
            )
    return JsonResponse(
        training_ceilings.capacity(
            staff_id,
            training_id,
            fy,
            exclude_activity_id=exclude,
            school_id=named_school_id,
        )
    )


# ── The Programme Lead sets a ceiling ───────────────────────────────────────
def _refresh(message: str, *, to: str) -> HttpResponse:
    """Close the drawer and redraw the page with the saved state."""
    from django.utils.html import escape

    response = HttpResponse(
        f'<p class="pill pill-success" role="status">{escape(message)}</p>'
    )
    response["HX-Trigger"] = "close-drawer"
    response["HX-Redirect"] = to
    return response


def _drawer(request, context, status=200):
    return render(
        request,
        "partials/trainings/ceiling_drawer.html",
        {"drawer_size": "md", **context},
        status=status,
    )


def _plural(count: int) -> str:
    return f"{count} school{'' if count == 1 else 's'}"


@require_page_permission("team_planning_oversight")
@require_http_methods(["GET", "POST"])
def training_ceiling_set_view(request):
    """``+ Set Training Ceiling``: one officer, one training, one year."""
    from apps.planning import training_ceilings

    staff_options = training_ceilings.ceiling_staff_options(request.user)
    source = request.POST if request.method == "POST" else request.GET
    values = {
        "staff_id": (source.get("staff_id") or source.get("staff") or "").strip(),
        "training_id": (
            source.get("training_id") or source.get("training") or ""
        ).strip(),
        "fy": (source.get("fy") or "").strip() or str(get_operational_fy()),
        "ceiling": (source.get("ceiling") or "").strip(),
    }
    context = {
        "mode": "create",
        "staff_options": staff_options,
        "trainings": training_ceilings.training_options(),
        "fy_options": fy_options(),
        "values": values,
        "may_set": bool(staff_options),
    }
    if values["staff_id"] and values["training_id"]:
        context["current"] = training_ceilings.capacity(
            values["staff_id"], values["training_id"], values["fy"]
        )
        # A ceiling already set is changed by saving over it, and can be
        # removed from here.
        from apps.planning.models import TrainingCeiling

        existing = TrainingCeiling.objects.filter(
            staff_id=values["staff_id"],
            training_id=values["training_id"],
            fy=values["fy"],
        ).first()
        if existing and training_ceilings.may_set_ceiling(
            request.user, existing.staff_id
        ):
            context["existing"] = existing
            if not values["ceiling"] and request.method == "GET":
                values["ceiling"] = str(existing.ceiling)
    if request.method == "POST":
        try:
            row = training_ceilings.set_ceiling(
                request.user,
                staff_id=values["staff_id"],
                training_id=values["training_id"],
                fy=values["fy"],
                ceiling=values["ceiling"],
            )
        except (BadRequest, Forbidden, NotFoundError) as exc:
            context["validation_error"] = str(getattr(exc, "detail", exc))
            return _drawer(request, context)
        return _refresh(
            f"{row.staff.user.name} may schedule {_plural(row.ceiling)} for "
            f"{row.training.display_name} in FY {row.fy}.",
            to=f"{SUMMARY_URL}&{urlencode({'fy': row.fy})}",
        )
    return _drawer(request, context)


def _ceiling_row(user, ceiling_id):
    from apps.planning import training_ceilings
    from apps.planning.models import TrainingCeiling

    row = (
        TrainingCeiling.objects.select_related("staff__user", "training")
        .filter(id=ceiling_id)
        .first()
    )
    if row is None or not training_ceilings.may_set_ceiling(user, row.staff_id):
        return None
    return row


@require_page_permission("team_planning_oversight")
@require_http_methods(["GET", "POST"])
def training_ceiling_edit_view(request, ceiling_id):
    """Change one ceiling."""
    from apps.planning import training_ceilings

    row = _ceiling_row(request.user, ceiling_id)
    if row is None:
        return _drawer(request, {"mode": "missing"}, status=404)
    context = {
        "mode": "edit",
        "row": row,
        "current": training_ceilings.capacity(row.staff_id, row.training_id, row.fy),
        "values": {
            "ceiling": (request.POST.get("ceiling") or str(row.ceiling)).strip()
        },
        "may_set": True,
    }
    if request.method == "POST":
        try:
            row = training_ceilings.set_ceiling(
                request.user,
                staff_id=row.staff_id,
                training_id=row.training_id,
                fy=row.fy,
                ceiling=context["values"]["ceiling"],
            )
        except (BadRequest, Forbidden, NotFoundError) as exc:
            context["validation_error"] = str(getattr(exc, "detail", exc))
            return _drawer(request, context)
        return _refresh(
            f"{row.staff.user.name}'s ceiling for {row.training.display_name} "
            f"is {_plural(row.ceiling)}.",
            to=f"{SUMMARY_URL}&{urlencode({'fy': row.fy})}",
        )
    return _drawer(request, context)


@require_page_permission("team_planning_oversight")
@require_http_methods(["GET", "POST"])
def training_ceiling_remove_view(request, ceiling_id):
    """Remove one ceiling, after the drawer has said what that means."""
    from apps.planning import training_ceilings

    row = _ceiling_row(request.user, ceiling_id)
    if row is None:
        return _drawer(request, {"mode": "missing"}, status=404)
    context = {
        "mode": "remove",
        "row": row,
        "current": training_ceilings.capacity(row.staff_id, row.training_id, row.fy),
        "may_set": True,
    }
    if request.method == "POST":
        try:
            detail = training_ceilings.remove_ceiling(request.user, row.id)
        except (BadRequest, Forbidden, NotFoundError) as exc:
            context["validation_error"] = str(getattr(exc, "detail", exc))
            return _drawer(request, context)
        return _refresh(
            f"{detail['staffName']} has no ceiling for {detail['training']} "
            f"in FY {detail['fy']}.",
            to=f"{SUMMARY_URL}&{urlencode({'fy': detail['fy']})}",
        )
    return _drawer(request, context)


# ── Admin and Impact Assessment set the Country Ceiling ─────────────────────
def _country_drawer(request, context, status=200):
    return render(
        request,
        "partials/trainings/country_ceiling_drawer.html",
        {"drawer_size": "md", **context},
        status=status,
    )


@require_page_permission("team_planning_oversight")
@require_http_methods(["GET", "POST"])
def training_country_ceiling_set_view(request):
    """``+ Set Country Ceiling``: one training, one year, for the country.

    Owner, 2026-10-06: "The admin IA will set the Country Ceiling and Leads
    will set each staff ceiling." Anyone else who reaches this is told so.
    """
    from apps.planning import training_ceilings
    from apps.planning.models import TrainingCountryCeiling

    may_set = training_ceilings.may_set_country_ceiling(request.user)
    country = training_ceilings.country_of(request.user)
    source = request.POST if request.method == "POST" else request.GET
    values = {
        "training_id": (
            source.get("training_id") or source.get("training") or ""
        ).strip(),
        "fy": (source.get("fy") or "").strip() or str(get_operational_fy()),
        "ceiling": (source.get("ceiling") or "").strip(),
    }
    context = {
        "mode": "create",
        "trainings": training_ceilings.training_options() if may_set else [],
        "fy_options": fy_options(),
        "values": values,
        "may_set": may_set,
        "country": country,
    }
    if may_set and values["training_id"]:
        context["current"] = training_ceilings.country_capacity(
            values["training_id"], values["fy"], country
        )
        existing = TrainingCountryCeiling.objects.filter(
            training_id=values["training_id"], fy=values["fy"], country=country
        ).first()
        if existing:
            context["existing"] = existing
            if not values["ceiling"] and request.method == "GET":
                values["ceiling"] = str(existing.ceiling)
    if request.method == "POST":
        try:
            row = training_ceilings.set_country_ceiling(
                request.user,
                training_id=values["training_id"],
                fy=values["fy"],
                ceiling=values["ceiling"],
                country=country,
            )
        except Forbidden as exc:
            context["validation_error"] = str(getattr(exc, "detail", exc))
            return _country_drawer(request, context, status=403)
        except (BadRequest, NotFoundError) as exc:
            context["validation_error"] = str(getattr(exc, "detail", exc))
            return _country_drawer(request, context)
        return _refresh(
            f"The Country Ceiling for {row.training.display_name} in FY {row.fy} "
            f"is {_plural(row.ceiling)}.",
            to=f"{SUMMARY_URL}&{urlencode({'fy': row.fy})}",
        )
    return _country_drawer(request, context)


def _country_ceiling_row(user, ceiling_id):
    from apps.planning import training_ceilings
    from apps.planning.models import TrainingCountryCeiling

    if not training_ceilings.may_set_country_ceiling(user):
        return None
    return (
        TrainingCountryCeiling.objects.select_related("training")
        .filter(id=ceiling_id, country=training_ceilings.country_of(user))
        .first()
    )


@require_page_permission("team_planning_oversight")
@require_http_methods(["GET", "POST"])
def training_country_ceiling_edit_view(request, ceiling_id):
    """Change the Country Ceiling of one training."""
    from apps.planning import training_ceilings

    row = _country_ceiling_row(request.user, ceiling_id)
    if row is None:
        return _country_drawer(request, {"mode": "missing"}, status=404)
    context = {
        "mode": "edit",
        "row": row,
        "current": training_ceilings.country_capacity(
            row.training_id, row.fy, row.country
        ),
        "values": {
            "ceiling": (request.POST.get("ceiling") or str(row.ceiling)).strip()
        },
        "may_set": True,
        "country": row.country,
    }
    if request.method == "POST":
        try:
            row = training_ceilings.set_country_ceiling(
                request.user,
                training_id=row.training_id,
                fy=row.fy,
                ceiling=context["values"]["ceiling"],
                country=row.country,
            )
        except (BadRequest, Forbidden, NotFoundError) as exc:
            context["validation_error"] = str(getattr(exc, "detail", exc))
            return _country_drawer(request, context)
        return _refresh(
            f"The Country Ceiling for {row.training.display_name} in FY {row.fy} "
            f"is {_plural(row.ceiling)}.",
            to=f"{SUMMARY_URL}&{urlencode({'fy': row.fy})}",
        )
    return _country_drawer(request, context)


@require_page_permission("team_planning_oversight")
@require_http_methods(["GET", "POST"])
def training_country_ceiling_remove_view(request, ceiling_id):
    """Remove the Country Ceiling of one training, after saying what it means."""
    from apps.planning import training_ceilings

    row = _country_ceiling_row(request.user, ceiling_id)
    if row is None:
        return _country_drawer(request, {"mode": "missing"}, status=404)
    context = {
        "mode": "remove",
        "row": row,
        "current": training_ceilings.country_capacity(
            row.training_id, row.fy, row.country
        ),
        "may_set": True,
        "country": row.country,
    }
    if request.method == "POST":
        try:
            detail = training_ceilings.remove_country_ceiling(request.user, row.id)
        except (BadRequest, Forbidden, NotFoundError) as exc:
            context["validation_error"] = str(getattr(exc, "detail", exc))
            return _country_drawer(request, context)
        return _refresh(
            f"{detail['training']} has no Country Ceiling in FY {detail['fy']}.",
            to=f"{SUMMARY_URL}&{urlencode({'fy': detail['fy']})}",
        )
    return _country_drawer(request, context)


# ── The schools behind a figure ─────────────────────────────────────────────
@require_any_page_permission("my_plan", "team_planning_oversight")
@require_http_methods(["GET"])
def training_summary_schools_drawer(request):
    """The schools one summary figure counts, read-only.

    An officer opens their own; a Programme Lead, a supervised officer's. A
    link edited to name anybody else is refused with the reason.
    """
    from apps.planning import training_ceilings

    template = "partials/trainings/summary_schools_drawer.html"
    try:
        result = training_ceilings.schools_behind(
            request.user,
            staff_id=(request.GET.get("staff") or "").strip(),
            training_id=(request.GET.get("training") or "").strip(),
            fy=(request.GET.get("fy") or "").strip() or str(get_operational_fy()),
            delivery=(request.GET.get("delivery") or "").strip(),
        )
    except (BadRequest, Forbidden, NotFoundError) as exc:
        return render(
            request,
            template,
            {"refusal": str(getattr(exc, "detail", exc)), "drawer_size": "xl"},
            status=403 if isinstance(exc, Forbidden) else 404,
        )
    return render(request, template, {**result, "drawer_size": "xl"})
