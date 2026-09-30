"""Staff Activity Log pages (owner, 2026-09-29) — replaces Who's Online.

* ``/staff-activity`` — the log: a Programme Lead's team, or the country
  grouped by Programme Lead for the Country Director (and the Admin, read
  only). The summary strip, side panel and table answer the same filters.
* ``/staff-activity/people/<id>`` — one person's detail, fetched only when
  their row is opened.
* ``/staff-activity/follow-ups…`` — the manager follow-up workflow. A
  follow-up is readable by everyone party to it, so its own page is guarded
  by the follow-up rather than by the log's page permission: an officer
  opens the follow-up their Lead sent them without being able to read the
  log.
* ``/staff-activity/beat`` — the browser's activity heartbeat.
"""

from __future__ import annotations

from datetime import date

from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.permissions import require_page_permission

PAGE_URL = "/staff-activity"


def _filters(request) -> dict:
    get = request.GET
    return {
        "period": get.get("period") or None,
        "on": get.get("on") or None,
        "role": (get.get("role") or "").strip() or None,
        "program_lead": (get.get("pl") or "").strip() or None,
        "status": (get.get("status") or "").strip() or None,
        "q": (get.get("q") or "").strip()[:80] or None,
    }


def _query(request, **overrides) -> str:
    query = request.GET.copy()
    for key in ("page", "staff_page"):
        query.pop(key, None)
    for key, value in overrides.items():
        if value in (None, ""):
            query.pop(key, None)
        else:
            query[key] = value
    return query.urlencode()


@require_page_permission("staff_activity")
@require_GET
def staff_activity_view(request):
    """The log. A Programme Lead reads their team's on their dashboard's This
    Week (owner, 2026-09-29; apps.frontend.views.dashboard_embed): the
    dashboard section's requests get the workspace with its own heading and
    actions, and the page opened on its own sends the Lead there."""
    from apps.core.metrics.payload import render_precomputed_metric_for_source
    from apps.frontend.views import dashboard_embed
    from apps.staff_activity.follow_ups import open_count_for
    from apps.staff_activity.services import activity_log

    if dashboard_embed.reads_on_dashboard(request):
        return dashboard_embed.to_dashboard(request, dashboard_embed.STAFF_ACTIVITY)
    embedded = dashboard_embed.is_embedded(request)
    try:
        log = activity_log(request.user, **_filters(request))
    except PermissionError:
        # A role granted the page some other way still reads nobody's log.
        return HttpResponseForbidden(
            "The Staff Activity Log is for Programme Leads and the Country Director."
        )
    context = {
        "log": log,
        "kpi_items": _kpi_items(log, render_precomputed_metric_for_source),
        "query": _query(request),
        "period_links": [
            {
                "key": key,
                "label": {"fy": "FY"}.get(key, label),
                "href": f"{PAGE_URL}?{_query(request, period=key)}",
                "active": key == log["period"]["key"],
            }
            for key, label in log["period_options"]
        ],
        "follow_up_count": open_count_for(request.user),
        # One search, the top bar's, bound to the filter form (§ search
        # consolidation): typing narrows the table like any other filter.
        "topbar_search": {
            "placeholder": "Search staff…",
            "name": "q",
            "value": request.GET.get("q", ""),
            "attach_to": "sal-choice-form",
            "input_id": "sal-search",
            "autosubmit": True,
        },
        "has_filters": any(
            _filters(request)[k] for k in ("role", "program_lead", "status", "q")
        )
        or not log["period"]["is_default"],
        "embedded": embedded,
    }
    if embedded:
        return dashboard_embed.fragment(
            render(request, "partials/staff_activity/_workspace.html", context)
        )
    if (
        request.headers.get("HX-Request") == "true"
        and request.headers.get("HX-Target") == "staff-activity-workspace"
    ):
        return render(request, "partials/staff_activity/_workspace.html", context)
    return render(request, "pages/staff_activity/index.html", context)


METRIC_SOURCE = "apps.frontend.views.staff_activity_views:_kpi_items"


def _kpi_items(log: dict, render_metric) -> list[dict]:
    """The compact summary strip (§7.2), through the reconciled registry
    (apps/core/metrics/staff_activity_metrics.py holds the definitions)."""
    k = log["kpis"]
    share = (
        f"{k['active_share']}% of expected"
        if k["active_share"] is not None
        else "nobody expected"
    )

    def item(label, value, helper, tone="info"):
        return render_metric(METRIC_SOURCE, label, value, helper=helper, tone=tone)

    return [
        item(
            "Staff Expected",
            k["staff_expected"],
            f"of {k['staff_total']} with an expected working day",
        ),
        item("Staff Active", k["staff_active"], share, "success"),
        item(
            "No Login",
            k["no_login"],
            "expected, but did not sign in",
            "danger" if k["no_login"] else "success",
        ),
        item(
            "Total Active Time",
            k["total_active_label"],
            "deduplicated across tabs and devices",
        ),
        item("Median Active Time", k["median_active_label"], "per active staff member"),
        item(
            "Meaningful Actions",
            k["meaningful_actions"],
            f"{k['schools']} schools acted on",
            "success",
        ),
        item(
            "Open Follow-ups",
            k["open_follow_ups"],
            f"{k['suggested']} more suggested" if k["suggested"] else "none suggested",
            "warning" if k["open_follow_ups"] or k["suggested"] else "success",
        ),
    ]


@require_page_permission("staff_activity")
@require_GET
def staff_activity_person_view(request, person_id: str):
    from apps.staff_activity.services import person_detail

    try:
        detail = person_detail(
            request.user,
            person_id,
            period=request.GET.get("period") or None,
            on=request.GET.get("on") or None,
        )
    except PermissionError:
        return HttpResponseForbidden("This person is not in your scope.")
    from apps.staff_activity.services import viewer_scope

    return render(
        request,
        "partials/staff_activity/_person_detail.html",
        {
            "detail": detail,
            "person": detail["person"],
            # Nobody follows up with themselves (the Lead's own row).
            "can_follow_up": viewer_scope(request.user)["can_follow_up"]
            and not detail["person"]["is_self"],
            "query": _query(request),
        },
    )


@require_page_permission("staff_activity")
@require_GET
def staff_activity_export_view(request):
    from apps.core.excel import table_download
    from apps.staff_activity.services import activity_log

    try:
        log = activity_log(request.user, **_filters(request))
    except PermissionError:
        # A role granted the page some other way still reads nobody's log.
        return HttpResponseForbidden(
            "The Staff Activity Log is for Programme Leads and the Country Director."
        )
    headers = [
        "Staff",
        "Role",
        "Supervisor",
        "Program Lead",
        "Region",
        "Logins",
        "First active",
        "Last active",
        "Overall active time (minutes)",
        "Last page",
        "Last meaningful action",
        "Meaningful actions",
        "Failed actions",
        "Schools acted on",
        "Status",
        "Usage status",
        "Open follow-ups",
    ]
    rows = [
        [
            p["name"],
            p["title"],
            p["supervisor"],
            (p["program_lead"] or {}).get("name", ""),
            p["region"],
            p["logins"],
            p["first_active_label"],
            p["last_active_label"],
            round(p["active_seconds"] / 60),
            p["last_page"],
            p["last_action"],
            p["actions"],
            p["failed"],
            p["schools"],
            p["status_label"],
            p["usage_label"],
            len(p["open_follow_ups"]),
        ]
        for p in log["people"]
    ]
    return table_download(
        request,
        f"staff-activity-{log['period']['start']:%Y%m%d}-{log['period']['end']:%Y%m%d}",
        [{"title": "Staff activity", "headers": headers, "rows": rows}],
    )


# ── Follow-ups ───────────────────────────────────────────────────────────────
@require_page_permission("staff_activity")
@require_GET
def follow_up_new_view(request, person_id: str):
    """The Follow Up drawer for one person (§9.2)."""
    from apps.staff_activity.follow_ups import default_due_date, recipient_for
    from apps.staff_activity.models import FollowUpPriority, FollowUpTrigger
    from apps.staff_activity.services import person_detail, viewer_scope

    scope = viewer_scope(request.user)
    if not scope or not scope["can_follow_up"]:
        return HttpResponseForbidden(
            "Follow-ups are sent by a Programme Lead or the Country Director."
        )
    if person_id == scope.get("self_id"):
        return HttpResponseForbidden("A follow-up is about someone else.")
    try:
        detail = person_detail(
            request.user,
            person_id,
            period=request.GET.get("period") or None,
            on=request.GET.get("on") or None,
        )
    except PermissionError:
        return HttpResponseForbidden("This person is not in your scope.")
    from apps.accounts.models import User

    subject = User.objects.get(pk=person_id)
    assignee, route = recipient_for(request.user, subject)
    person = detail["person"]
    suggested = person["suggestions"][0]["trigger"] if person["suggestions"] else ""
    return render(
        request,
        "partials/staff_activity/_follow_up_new_drawer.html",
        {
            "person": person,
            "detail": detail,
            "assignee": assignee,
            "via_manager": route == "director_to_manager",
            "triggers": FollowUpTrigger.choices,
            "priorities": FollowUpPriority.choices,
            "suggested": suggested,
            "due": default_due_date(),
            "today": timezone.localdate(),
            "query": _query(request),
        },
    )


@require_page_permission("staff_activity")
@require_POST
def follow_up_create_view(request, person_id: str):
    from apps.staff_activity.follow_ups import FollowUpError, create_follow_up
    from apps.staff_activity.services import person_detail

    try:
        detail = person_detail(
            request.user,
            person_id,
            period=request.POST.get("period") or None,
            on=request.POST.get("on") or None,
        )
    except PermissionError:
        return HttpResponseForbidden("This person is not in your scope.")
    person = detail["person"]
    try:
        due = date.fromisoformat((request.POST.get("due_date") or "").strip())
    except ValueError:
        due = None
    try:
        create_follow_up(
            request.user,
            person_id,
            trigger=request.POST.get("trigger") or "",
            note=request.POST.get("note") or "",
            priority=request.POST.get("priority") or "",
            due_date=due,
            period=detail["period"],
            snapshot={
                "period": detail["period"]["label"],
                "logins": person["logins"],
                "active": person["active_label"],
                "actions": person["actions"],
                "schools": person["schools"],
                "failed": person["failed"],
                "usage": person["usage_label"],
            },
        )
    except FollowUpError as error:
        return _form_error(str(error))
    response = HttpResponse(status=204)
    response["HX-Trigger"] = "close-drawer"
    response["HX-Refresh"] = "true"
    return response


def _form_error(message: str) -> HttpResponse:
    from django.utils.html import escape

    return HttpResponse(
        f'<p class="staff-activity-error" role="alert">{escape(message)}</p>',
        status=200,
    )


@require_page_permission("staff_activity")
@require_GET
def follow_up_queue_view(request):
    """The Follow-up Queue (header button): sent to me, sent by me."""
    from apps.staff_activity.follow_ups import queue_for

    return render(
        request,
        "partials/staff_activity/_follow_up_queue_drawer.html",
        {"queue": queue_for(request.user)},
    )


@require_page_permission("dashboard")
@require_GET
def follow_up_detail_view(request, follow_up_id: str):
    """One follow-up, for every party to it — the staff member it was sent
    to, the manager, the Country Director. A drawer from the log; a page from
    a notification or the To-Do list."""
    from apps.staff_activity.follow_ups import (
        actions_for,
        can_view,
        sweep_auto_resolutions,
    )
    from apps.staff_activity.models import StaffUsageFollowUp

    follow_up = get_object_or_404(
        StaffUsageFollowUp.objects.select_related(
            "subject", "assignee", "created_by", "resolved_by"
        ),
        pk=follow_up_id,
    )
    if not can_view(follow_up, request.user):
        return HttpResponseForbidden("This follow-up is not yours to open.")
    sweep_auto_resolutions([follow_up])
    context = {
        "follow_up": follow_up,
        "actions": actions_for(follow_up, request.user),
        "is_subject": follow_up.subject_id == request.user.id,
    }
    if request.headers.get("HX-Request") == "true":
        return render(
            request, "partials/staff_activity/_follow_up_drawer.html", context
        )
    return render(request, "pages/staff_activity/follow_up.html", context)


@require_page_permission("dashboard")
@require_POST
def follow_up_transition_view(request, follow_up_id: str, action: str):
    from apps.staff_activity.follow_ups import FollowUpError, can_view, transition
    from apps.staff_activity.models import StaffUsageFollowUp

    follow_up = get_object_or_404(StaffUsageFollowUp, pk=follow_up_id)
    if not can_view(follow_up, request.user):
        return HttpResponseForbidden("This follow-up is not yours to change.")
    try:
        transition(follow_up, request.user, action, request.POST.get("note") or "")
    except FollowUpError as error:
        if request.headers.get("HX-Request") == "true":
            return _form_error(str(error))
        from django.contrib import messages
        from django.shortcuts import redirect

        messages.error(request, str(error))
        return redirect(
            reverse("frontend:staff_activity_follow_up", args=[follow_up.pk])
        )
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse(status=204)
        response["HX-Refresh"] = "true"
        return response
    from django.shortcuts import redirect

    return redirect(reverse("frontend:staff_activity_follow_up", args=[follow_up.pk]))


# ── The heartbeat ────────────────────────────────────────────────────────────
@require_page_permission("dashboard")
@require_POST
def staff_activity_beat_view(request):
    """A beat from a page that is visible, focused and was used within the
    idle threshold (static/js/staff-activity-beat.js). It carries no time —
    the server's clock decides how much of the gap since the last beat was
    active — only the page it was sent from, so a person reading or filling a
    long form keeps counting without making requests of their own."""
    from apps.accounts.presence import is_untracked_path, touch_presence
    from apps.accounts.presence_labels import page_path

    page = page_path((request.POST.get("page") or "").strip())[:255]
    if not page.startswith("/") or is_untracked_path(page):
        return HttpResponse(status=204)
    user = request.user
    # Still on the page of the last beat: keep what they were doing there
    # (the drawer they opened is still open).
    action = (
        (user.last_seen_action or "") if page == (user.last_seen_path or "") else ""
    )
    touch_presence(user, request, footprint=(page, action))
    # SlidingSessionMiddleware would touch again for this POST.
    request._edify_presence_touched = True
    return JsonResponse({"ok": True})
