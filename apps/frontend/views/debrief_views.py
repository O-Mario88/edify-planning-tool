"""Field Debrief views (§1-§21) — the dashboard (mockup), submission form,
detail page, and the action dispatcher shared by clarification/recommendation/
leadership-action/peer-solution flows."""

from __future__ import annotations

from django.contrib import messages
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
)
from django.shortcuts import redirect, render
from django.utils.html import escape

from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
from apps.core.permissions import require_page_permission

from apps.debriefs.action_service import DebriefActionRoutingService
from apps.debriefs.dashboard_service import FieldDebriefDashboardService
from apps.debriefs.field_debrief_service import FieldDebriefService
from apps.debriefs.insight_service import InsightReviewService
from apps.debriefs.peer_solution_service import PeerSolutionService


@require_page_permission("debriefs_list")
def field_debrief_dashboard_view(request):
    params = {
        "fy": request.GET.get("fy"),
        "tab": request.GET.get("tab") or "all",
        "page": request.GET.get("page"),
        "district_id": request.GET.get("district_id"),
        "staff_id": request.GET.get("staff_id"),
        "partner_id": request.GET.get("partner_id"),
        "risk_level": request.GET.get("risk_level"),
        "status": request.GET.get("status"),
        "q": request.GET.get("q"),
        "range_days": request.GET.get("range_days"),
    }
    try:
        context = FieldDebriefDashboardService.get_dashboard(request.user, params)
    except ValueError:
        return HttpResponseBadRequest("Invalid filter value.")
    if (
        request.headers.get("HX-Request") == "true"
        and request.GET.get("partial") == "table"
    ):
        return render(request, "partials/debriefs/dashboard_table.html", context)
    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/debriefs/dashboard_body.html", context)
    # One persistent search: the top bar.
    context["topbar_search"] = {
        "placeholder": "Search debrief titles or summaries…",
        "name": "q",
        "value": request.GET.get("q", ""),
        "hx_get": "/debriefs",
        "hx_target": "#debrief-dashboard-body",
        "hx_trigger": "keyup changed delay:300ms, search",
        "hx_include": "#debrief-filters",
    }
    return render(request, "pages/debriefs/dashboard.html", context)


@require_page_permission("debrief_detail")
def field_debrief_detail_view(request, debrief_id):
    """`get_one` returns 404 (not 403) for a debrief that exists but is out
    of the viewer's scope — this avoids confirming to an unauthorized
    viewer that a given debrief ID exists at all."""
    try:
        debrief = FieldDebriefService.get_one(request.user, debrief_id)
    except NotFoundError as exc:
        raise Http404(str(exc)) from exc
    context = {
        "debrief": debrief,
        "activity_links": list(debrief.activity_links.select_related("activity")),
        "challenges": list(debrief.challenges.all()),
        "commitments": list(debrief.commitments.all()),
        "support_requests": list(debrief.support_requests.all()),
        "actions": list(debrief.actions.all()),
        "peer_solutions": list(debrief.peer_solutions.all()),
        "recipients": list(debrief.recipients.all()),
        "can_manage": getattr(request.user, "active_role", "")
        in (
            "Program Lead",
            "CountryDirector",
            "HumanResources",
            "ImpactAssessment",
            "RegionalVicePresident",
            "Admin",
        ),
        "is_own": debrief.submitted_by_user_id == request.user.user_id,
    }
    return render(request, "pages/debriefs/detail.html", context)


@require_page_permission("debriefs_list")
def field_debrief_submit_view(request):
    """The simplified Daily Debrief (5 questions, work auto-fetched from My
    Plan). GET renders the day's form (or its submitted read-only state);
    POST handles `intent=autosave` (HTMX draft save, returns a saved chip)
    and `intent=submit` (final submission → routed to PL/CD/HR)."""
    from django.utils import timezone as _tz

    from apps.debriefs.field_debrief_service import DailyDebriefFlowService

    today = _tz.localdate()

    if request.method == "GET":
        state = DailyDebriefFlowService.get_state(request.user, today)
        return render(
            request,
            "pages/debriefs/submit.html",
            {
                "today": today,
                "can_submit": FieldDebriefService.can_submit(request.user),
                **state,
            },
        )

    if not FieldDebriefService.can_submit(request.user):
        return HttpResponseForbidden("Your role cannot submit a Daily Debrief.")

    data = _parse_daily(request)
    intent = request.POST.get("intent") or "submit"

    if intent == "autosave":
        try:
            DailyDebriefFlowService.save_draft(request.user, data, today)
        except (BadRequest, Forbidden) as exc:
            return render(
                request,
                "partials/debriefs/autosave_chip.html",
                {"error": str(exc)},
                status=400,
            )
        return render(
            request,
            "partials/debriefs/autosave_chip.html",
            {"saved_at": _tz.localtime()},
        )

    try:
        DailyDebriefFlowService.submit(request.user, data, today)
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
        state = DailyDebriefFlowService.get_state(request.user, today)
        return render(
            request,
            "pages/debriefs/submit.html",
            {
                "today": today,
                "can_submit": True,
                "error": str(exc),
                **state,
            },
            status=400,
        )
    messages.success(
        request,
        "Debrief submitted successfully. Your Program Lead, Country Director "
        "and HR can now review it.",
    )
    return redirect("/debriefs/submit")


def _parse_daily(request) -> dict:
    p = request.POST
    return {
        "activity_ids": p.getlist("activity_ids"),
        "what_went_well": p.get("what_went_well"),
        "what_did_not_go_well": p.get("what_did_not_go_well"),
        "challenges_faced": p.get("challenges_faced"),
        "recommendations": p.get("recommendations"),
        "other_work_description": p.get("other_work_description"),
    }


def _parse_submission(request) -> dict:
    p = request.POST
    return {
        "title": p.get("title"),
        "kind": p.get("kind"),
        "summary": p.get("summary"),
        "what_happened": p.get("what_happened"),
        "what_went_well": p.get("what_went_well"),
        "what_did_not_go_well": p.get("what_did_not_go_well"),
        "support_needed": p.get("support_needed"),
        "recommendations": p.get("recommendations"),
        "next_action": p.get("next_action"),
        "activity_ids": p.getlist("activity_ids"),
        "school_ids": p.getlist("school_ids"),
        "partner_id": p.get("partner_id"),
        "completion_status": p.get("completion_status"),
        "incomplete_reason": p.get("incomplete_reason"),
        "actual_start_time": p.get("actual_start_time") or None,
        "actual_end_time": p.get("actual_end_time") or None,
        "participants_summary": p.get("participants_summary"),
        "what_was_done": p.get("what_was_done"),
        "intended_purpose": p.get("intended_purpose"),
        "purpose_achieved": p.get("purpose_achieved") == "true"
        if p.get("purpose_achieved")
        else None,
        "what_observed": p.get("what_observed"),
        "what_improved": p.get("what_improved"),
        "what_remains_weak": p.get("what_remains_weak"),
        "what_surprised": p.get("what_surprised"),
        "support_needed_next": p.get("support_needed_next"),
        "intervention_tags": p.getlist("intervention_tags"),
        "expected_participants": _int(p.get("expected_participants")),
        "actual_participants": _int(p.get("actual_participants")),
        "school_leaders_present": _int(p.get("school_leaders_present")),
        "teachers_present": _int(p.get("teachers_present")),
        "other_participants_present": _int(p.get("other_participants_present")),
        "engagement_level": p.get("engagement_level"),
        "attendance_concerns": p.get("attendance_concerns"),
        "planned_route": p.get("planned_route"),
        "actual_route": p.get("actual_route"),
        "schools_planned_count": _int(p.get("schools_planned_count")),
        "schools_reached_count": _int(p.get("schools_reached_count")),
        "travel_start_time": p.get("travel_start_time") or None,
        "travel_end_time": p.get("travel_end_time") or None,
        "estimated_travel_minutes": _int(p.get("estimated_travel_minutes")),
        "actual_travel_minutes": _int(p.get("actual_travel_minutes")),
        "route_quality": p.get("route_quality"),
        "transport_issue": p.get("transport_issue"),
        "immediate_result": p.get("immediate_result"),
        "follow_up_date": p.get("follow_up_date") or None,
        "follow_up_owner_id": p.get("follow_up_owner_id"),
        "recommended_next_activity_type": p.get("recommended_next_activity_type"),
        "recommended_intervention": p.get("recommended_intervention"),
        "key_success": p.get("key_success"),
        "key_lesson_learned": p.get("key_lesson_learned"),
        "practice_worth_repeating": p.get("practice_worth_repeating"),
        "innovation_observed": p.get("innovation_observed"),
        "potential_mscs_flag": p.get("potential_mscs_flag") == "on",
        "potential_mscs_title": p.get("potential_mscs_title"),
        "potential_mscs_narrative": p.get("potential_mscs_narrative"),
        "potential_champion_flag": p.get("potential_champion_flag") == "on",
        "potential_champion_note": p.get("potential_champion_note"),
        "potential_partner_success_flag": p.get("potential_partner_success_flag")
        == "on",
        "risk_level": p.get("risk_level"),
        "is_restricted_incident": p.get("is_restricted_incident") == "on",
        "restricted_incident_category": p.get("restricted_incident_category"),
        "challenges": _parse_indexed(p, "challenges"),
        "commitments": _parse_indexed(p, "commitments"),
        "support_requests": _parse_indexed(p, "support_requests"),
    }


def _int(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_indexed(p, prefix: str) -> list[dict]:
    """Parses repeated `{prefix}[N][field]` form fields into a list of dicts."""
    import re

    rows: dict[str, dict] = {}
    pattern = re.compile(rf"^{prefix}\[(\d+)\]\[(\w+)\]$")
    for key in p.keys():
        m = pattern.match(key)
        if not m:
            continue
        idx, field = m.groups()
        rows.setdefault(idx, {})[field] = p.get(key)
    return [rows[idx] for idx in sorted(rows, key=int)]


@require_page_permission("debriefs_list")
def field_debrief_action_view(request):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required.")
    action = request.POST.get("action")
    debrief_id = request.POST.get("debrief_id")
    try:
        if action == "request_clarification":
            FieldDebriefService.request_clarification(
                request.user, debrief_id, request.POST.get("note", "")
            )
            messages.success(request, "Clarification requested.")
        elif action == "update_after_clarification":
            FieldDebriefService.update_after_clarification(
                request.user,
                debrief_id,
                {
                    "summary": request.POST.get("summary"),
                    "what_happened": request.POST.get("what_happened"),
                    "next_action": request.POST.get("next_action"),
                },
            )
            messages.success(request, "Debrief updated.")
        elif action == "accept_recommendation":
            activity = FieldDebriefService.accept_recommendation(
                request.user, debrief_id
            )
            messages.success(
                request,
                f"Recommendation accepted — Activity {activity.id} created in My Plan.",
            )
        elif action == "reject_recommendation":
            FieldDebriefService.reject_recommendation(request.user, debrief_id)
            messages.info(request, "Recommendation rejected.")
        elif action == "create_leadership_action":
            DebriefActionRoutingService.create(
                request.user,
                debrief_id,
                issue=request.POST.get("issue", ""),
                action=request.POST.get("action_text", ""),
                owner_user_id=request.POST.get("owner_user_id", ""),
                priority=request.POST.get("priority", "medium"),
                due_date=request.POST.get("due_date") or None,
            )
            messages.success(request, "Leadership action created.")
        elif action == "update_action_status":
            DebriefActionRoutingService.update_status(
                request.user,
                request.POST.get("action_id"),
                status=request.POST.get("status"),
                note=request.POST.get("note", ""),
            )
            messages.success(request, "Action updated.")
        elif action == "propose_peer_solution":
            PeerSolutionService.propose(
                request.user,
                debrief_id,
                suggestion=request.POST.get("suggestion", ""),
                related_experience=request.POST.get("related_experience", ""),
            )
            messages.success(request, "Peer solution proposed.")
        elif action == "endorse_peer_solution":
            PeerSolutionService.endorse(request.user, request.POST.get("solution_id"))
            messages.success(request, "Endorsed.")
        elif action == "pl_classify_peer_solution":
            PeerSolutionService.pl_classify(
                request.user,
                request.POST.get("solution_id"),
                classification=request.POST.get("classification"),
            )
            messages.success(request, "Peer solution classified.")
        elif action == "resolve_commitment":
            FieldDebriefService.resolve_commitment(
                request.user, request.POST.get("commitment_id")
            )
            messages.success(request, "Commitment marked resolved.")
        elif action == "resolve_support_request":
            FieldDebriefService.resolve_support_request(
                request.user, request.POST.get("support_request_id")
            )
            messages.success(request, "Support request marked resolved.")
        elif action == "acknowledge_insight":
            InsightReviewService.acknowledge(
                request.user, request.POST.get("insight_id")
            )
            messages.success(request, "Insight acknowledged.")
        elif action == "dismiss_insight":
            InsightReviewService.dismiss(request.user, request.POST.get("insight_id"))
            messages.success(request, "Insight dismissed.")
        else:
            return HttpResponseBadRequest("Unknown action.")
    except NotFoundError as exc:
        # The referenced id doesn't exist at all — redirecting back to its
        # own (non-existent) detail page would just trade the raw JSON
        # envelope for a blank 404, silently swallowing the flash message.
        # Send the user to the dashboard instead, where they'll see it.
        messages.error(request, str(exc))
        return redirect(request.POST.get("redirect_to") or "/debriefs")
    except (BadRequest, Forbidden) as exc:
        messages.error(request, str(exc))
    redirect_to = request.POST.get("redirect_to") or (
        f"/debriefs/{debrief_id}" if debrief_id else "/debriefs"
    )
    return redirect(redirect_to)


@require_page_permission("debriefs_list")
def field_debrief_activity_options_view(request):
    """HTMX: <option> tags of the current user's own recent activities, for
    the submission form's multi-select (grouping several activities, or one
    debrief per activity — user's choice)."""
    from apps.accounts.models import StaffProfile
    from apps.activities.models import Activity
    from apps.core.fy import get_operational_fy

    sp = StaffProfile.objects.filter(user_id=request.user.user_id).first()
    fy = request.GET.get("fy") or get_operational_fy()
    qs = Activity.objects.filter(fy=fy)
    if sp:
        qs = qs.filter(responsible_staff_id__in=[sp.id, request.user.user_id])
    else:
        qs = qs.filter(responsible_staff_id=request.user.user_id)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(school__name__icontains=q)
    qs = qs.select_related("school").order_by("-scheduled_date")[:50]

    options = "".join(
        f'<option value="{escape(a.id)}">{escape(a.get_activity_type_display())} — '
        f'{escape(a.school.name) if a.school else "No school"} '
        f'({a.scheduled_date.strftime("%d %b") if a.scheduled_date else "unscheduled"})</option>'
        for a in qs
    )
    return HttpResponse(
        options or '<option value="">No recent activities found</option>'
    )
