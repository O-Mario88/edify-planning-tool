from apps.core.htmx_errors import error_fragment, notice_fragment
from apps.core.redirects import local_redirect
from apps.core.activity_types import COMPLETED_WORK_STATUSES, VISIT_TYPES
from apps.ssa.plan_alignment import verdict_display
from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import (
    has_permission,
    require_any_page_permission,
    require_page_permission,
    RolePermissionService,
)
from apps.core.rbac import Permission
from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.core.paginator import Paginator
from django.db.models import Count, Q
from datetime import date
from apps.audit.models import AuditLog
from apps.audit.services import log as audit_log

from apps.my_plan.services import get_frontend_context as get_my_plan

# The single Reschedule door: an in-school Training and its School Visit
# move together (apps.activities.pairs).
from apps.activities.pairs import reschedule as reschedule_activity
from apps.activities.services import (
    STARTABLE_STATUSES,
    get_activity,
    start_completion,
    start_in_school_training_pair,
    complete as complete_activity,
    complete_in_school_training_pair,
    in_school_training_pair,
    complete_partner_ssa_support,
    submit_for_review,
    record_attendance,
    ia_confirm,
    sf_kind,
    is_partner_ssa_support_activity,
)
from apps.activities.salesforce import (
    ENTRY_SOURCE_MANAGING_STAFF,
    ENTRY_SOURCE_STAFF_SELF,
    DuplicateSalesforceId,
    reserve_salesforce_id,
)
from apps.evidence.services import (
    record_pages_upload,
    record_upload,
    evidence_records_for_activity,
    infer_kind_from_upload,
    resolve_evidence_kind,
)
from apps.core.enums import ActivityType, EvidenceKind, SsaIntervention
from apps.pl_review.services import (
    confirm as pl_confirm,
    return_activity as pl_return,
)
from apps.activities.models import Activity
from apps.frontend.views.hr_programme_views import _back, _drawer, _field


# One table for the whole platform (apps.core.interventions).
from apps.core.interventions import (
    INTERVENTION_ABBREVIATIONS as SSA_SCORE_ABBREVIATIONS,
)  # noqa: E402
from apps.schools.lifecycle_service import active_schools


def _forbid_staff_on_partner_activity(request, a, *, allow_confirmer=False):
    """Partner-owned activities are read-only for staff monitors.

    Returns an HttpResponseForbidden when the activity is partner-delivered
    and the requesting user has no partner scope covering the assigned
    partner (i.e. a staff/monitoring user). Returns None when the actor IS
    the assigned partner's user, or when the activity is staff-delivered —
    so partners keep full use of these endpoints via /partner/my-plan.

    `allow_confirmer` opens the one act staff DO hold on partner work: the
    monitoring staff member enters the Salesforce record, and that completes
    the activity (owner, 2026-09-12). The partner's own deliverable — the
    visit form or the attendance form, the counts, the money — stays the
    partner's, so every other door keeps the default.
    """
    if a.delivery_type != "partner":
        return None
    from apps.core.scoping import resolve_user_scope

    scope = resolve_user_scope(request.user)
    if a.assigned_partner_id and a.assigned_partner_id in (scope.partner_ids or []):
        return None
    if allow_confirmer and RolePermissionService.can_confirm_partner_activity(
        request.user, a
    ):
        return None
    return HttpResponseForbidden("Partner-owned activity — staff can only monitor.")


def _partner_ssa_completion_context(a: Activity) -> dict:
    from apps.evidence.models import EvidenceRecord

    return {
        "a": a,
        "score_fields": [
            {
                "code": code,
                "label": label,
                "abbreviation": SSA_SCORE_ABBREVIATIONS[code],
            }
            for code, label in SsaIntervention.choices
        ],
        "assessment_date": (
            a.actual_delivery_date or a.planned_date or timezone.localdate()
        ),
        "evidence_count": EvidenceRecord.objects.filter(
            activity_id=a.id, quarantined=False
        ).count(),
        "drawer_size": "md",
    }


def _readiness_list(request, context) -> dict | None:
    """The schools behind a figure of the planner's own Planned and remaining
    (owner, 2026-10-05: "All those numbers should be link to the actual
    tables where those schools are located"): ``?list=<key>`` names it."""
    key = (request.GET.get("list") or "").strip()
    if not key or not context.get("readiness"):
        return None
    from apps.planning.planning_monitor import GAP_LABELS, list_schools, own_monitor

    if key not in GAP_LABELS:
        return None
    officer = own_monitor(request.user, str(context.get("fy") or ""))
    if officer is None:
        return None
    for school in (*officer.schools, *officer.outreach_schools):
        school.officer_name = officer.name
    return {
        "key": key,
        "label": GAP_LABELS[key],
        "schools": list_schools([officer], key),
    }


@require_page_permission("my_plan")
def my_plan_view(request):
    """The planning dashboard main view."""
    query = {
        "fy": request.GET.get("fy"),
        "quarter": request.GET.get("quarter"),
        "month": request.GET.get("month"),
        "week": request.GET.get("week"),
        # What the filter form was rendered with, so the service can tell a
        # widened filter from an unchanged one. See get_frontend_context.
        "fy_prev": request.GET.get("fy_prev"),
        "quarter_prev": request.GET.get("quarter_prev"),
        "district": request.GET.get("district"),
        "staff": request.GET.get("staff"),
        "activity_type": request.GET.get("activity_type"),
        "status": request.GET.get("status"),
        # Passed through as given. Defaulting it to "fy" here made every
        # request an explicitly-periodised one, so the month select could
        # never move the page off the year it was showing.
        "period": request.GET.get("period"),
        "q": request.GET.get("q", "").strip(),
    }

    context = get_my_plan(request.user, query)
    context["plan_list"] = _readiness_list(request, context)
    context["topbar_search"] = {
        "placeholder": "Search my plan…",
        "label": "Search my plan by school, School ID, cluster, district or purpose",
        "name": "q",
        "value": query["q"],
        "hx_get": "/my-plan",
        "hx_target": "#my-plan-workspace",
        "hx_trigger": "keyup changed delay:250ms, search",
        "hx_include": "#filters-form",
    }

    # The person's own planned-and-remaining figures as data: the numbers the
    # table on the page shows, for whoever reads them without the page.
    if request.GET.get("format", "").strip().lower() == "readiness-json":
        from django.http import JsonResponse

        figures = context.get("readiness")
        return JsonResponse(
            {"fy": str(context.get("fy") or ""), "readiness": figures.as_dict()}
            if figures
            else {"fy": str(context.get("fy") or ""), "readiness": None}
        )

    # The currently filtered feed, as CSV or as a workbook. Owner, 2026-09-22:
    # "IA and PL and CD and Regional Programme Leads, and CCEO should be able
    # to export all of their plans into Excel." This is the personal plan every
    # one of them holds; the team and country plans export from their own
    # oversight pages. CSV stays, so existing links keep working.
    export = request.GET.get("export", "").strip().lower()
    if export in {"csv", "xlsx", "excel"}:
        # Owner, 2026-09-27: "All exported plan should have school ID." The
        # School ID is the school's business code; a cluster session a row
        # stands for as a whole has none. A cluster training is listed once
        # per invited school, so its rows carry each school's own ID.
        headers = [
            "Activity ID",
            "School ID",
            "Type",
            "School / Cluster",
            "District",
            "Planned Date",
            "Status",
            "Owner",
            "Budget (UGX)",
        ]
        # Every table the page shows, the Core School and Programme School
        # cards included — the export used to stop at the three general
        # tables, so a Core School's visits and trainings never reached it.
        feed = [
            *context.get("core_school_visits", []),
            *context.get("core_school_trainings", []),
            *context.get("school_visits", []),
            *context.get("cluster_trainings", []),
            *context.get("cluster_meetings", []),
            *(
                row
                for group in context.get("programme_school_work", [])
                for row in group["rows"]
            ),
            *context.get("programme_activities", []),
        ]
        rows = []
        seen = set()
        for a in feed:
            is_cluster_row = a["activity_type"].startswith("cluster") and not a.get(
                "is_cluster_invited"
            )
            school_code = "" if is_cluster_row else (a.get("school_id") or "")
            key = (a["id"], school_code)
            if key in seen:
                continue
            seen.add(key)
            sequence = a.get("visit_number") or a.get("training_number") or ""
            rows.append(
                [
                    a["id"],
                    school_code,
                    f"{a['activity_type_label']} ({sequence})"
                    if sequence
                    else a["activity_type_label"],
                    a["cluster_name"] if is_cluster_row else a["school_name"],
                    a["cluster_district"] if is_cluster_row else a["school_district"],
                    a["planned_date"] or "",
                    a["status_label"],
                    a.get("owner", ""),
                    a.get("budget_total", ""),
                ]
            )

        if export in {"xlsx", "excel"}:
            from apps.core.excel import workbook_response

            return workbook_response(
                "my_plan_export.xlsx",
                [
                    {
                        "title": "My Plan",
                        "headers": headers,
                        "rows": rows,
                        # Budget is a number, and a plan people add up.
                        "number_formats": {9: "#,##0"},
                    }
                ],
            )

        import csv

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="my_plan_export.csv"'
        writer = csv.writer(response)
        writer.writerow(headers)
        for row in rows:
            writer.writerow(row)
        return response

    # Partners get their own My Plan — the accepted implementation schedule
    # (§8): five sections, one Actions menu, the Send Invoice button and the
    # payment tracker. It is not another planning page.
    from apps.core.scoping import resolve_partner_ids

    if resolve_partner_ids(request.user):
        from apps.fund_requests.partner_invoices import partner_payment_tracker
        from apps.frontend.views.partner_views import partner_plan_context

        context = partner_plan_context(request.user)
        context["is_partner_viewer"] = True
        context["partner_invoice_tracker"] = partner_payment_tracker(request.user)
        # The trainings it facilitates, each with its fee and invoice (owner,
        # 2026-09-29; partner_oversight_service.partner_facilitations).
        from apps.planning.partner_oversight_service import partner_facilitations

        context["training_facilitations"] = partner_facilitations(request.user)
        # The clusters it is assigned to facilitate (owner, 2026-10-02).
        from apps.clusters.facilitation import facilitated_clusters

        context["facilitated_clusters"] = facilitated_clusters(request.user)
        return render(request, "pages/partner/my_plan.html", context)

    # Which of the reader's clusters have a group training and a cluster
    # meeting planned (owner, 2026-09-28), for the Cluster Planning Status card.
    from apps.clusters.planning_status import cluster_planning_status
    from apps.core.fy import get_operational_fy

    context["cluster_planning"] = cluster_planning_status(
        request.user, fy=context.get("fy") or get_operational_fy()
    )
    context["can_plan_clusters"] = RolePermissionService.can_view_page(
        request.user, "planning"
    ) and RolePermissionService.can_schedule_activity(request.user)
    # My Training Summary (owner, 2026-10-06): the reader's own training
    # ceilings and what they have scheduled under them, never another
    # officer's (apps.planning.training_ceilings.own_summary).
    from apps.planning.training_ceilings import own_summary, summary_totals

    context["my_training_summary"] = own_summary(
        request.user, str(context.get("fy") or get_operational_fy())
    )
    # The line over the card, in the Project Capacity shape (owner,
    # 2026-10-06): trainings, ceilings, schools scheduled, balance, excess.
    context["my_training_totals"] = summary_totals(context["my_training_summary"])

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/my_plan/workspace.html", context)
    return render(request, "pages/my_plan/index.html", context)


def _return_context(a) -> dict:
    """Why a returned activity came back, for the pages its officer fixes it on.

    Shown only while the activity is in a returned status: the note stays on
    the record as history after resubmission, and a fixed completion must not
    keep telling its officer it was returned.
    """
    from apps.activities import return_notes
    from apps.activities.services import RETURNED_STATUSES

    if a.status not in RETURNED_STATUSES:
        return {"return_note": "", "returned_by": ""}
    return {
        "return_note": return_notes.note_for(a) or "Correction required",
        "returned_by": return_notes.returned_by(a),
    }


def _edit_state(activity, user) -> str:
    from apps.activities.editing import edit_state

    return edit_state(activity, user)


def _sent_fund_weeks(activity) -> str:
    """The weeks whose fund request has been sent and not paid and carries
    this activity, as the Edit and Reschedule drawers name them: the request
    comes back to its owner when the plan under it changes (owner,
    2026-10-07; apps.fund_requests.plan_changes)."""
    from apps.core.clock import local_day
    from apps.fund_requests.plan_changes import will_take_back

    day = activity.planned_date or (
        local_day(activity.scheduled_date) if activity.scheduled_date else None
    )
    return " and ".join(
        f"{wfr.week_start_date:%-d %b} – {wfr.week_end_date:%-d %b}"
        for wfr in will_take_back(activity, days=(day,))
        # A week set to No Advance has nobody waiting on it: its owner is
        # told when it reopens, not warned beforehand.
        if wfr.status != "not_requested"
    )


def _can_reschedule(activity, user) -> bool:
    """Whether Reschedule is offered: never on work already carried out,
    which `services.reschedule` refuses (owner, 2026-10-02), and on a
    partner's work only to the partner, who dates it (owner, 2026-10-05;
    apps.partners.dating_policy). The plan's rows already say "The partner
    reschedules"."""
    from apps.activities.editing import is_executed
    from apps.partners.dating_policy import acts_for_partner, is_agency_booking

    if is_executed(activity):
        return False
    if activity.delivery_type == "partner" and not is_agency_booking(activity):
        return acts_for_partner(user)
    # And only to a reader the service would let move it: a Programme Lead
    # or the Country Director reading a team member's activity was shown the
    # button all the same (owner, 2026-10-08: "strictly read only").
    return _may_change(activity, user)


def _may_change(activity, user) -> bool:
    """Whether this reader may run the activity at all: complete it, edit it,
    move it or call it off. A supervisor reading a team member's work may
    not, and is offered none of them (`services._assert_may_execute`)."""
    from apps.activities.profile_activities import _may_run

    return _may_run(activity, user)


def _team_read_only(request, activity):
    """The answer to a reader who opens a change drawer on an activity they
    may read and not run, or None when the activity is theirs to change."""
    if _may_change(activity, request.user):
        return None
    from apps.core.scoping import TEAM_READ_ONLY_MESSAGE

    return notice_fragment(TEAM_READ_ONLY_MESSAGE)


def _can_cancel(activity, user) -> bool:
    """Whether Cancel is offered on the activity's own page (owner,
    2026-10-05): work still live, for a reader who passes the checks
    `services.cancel` makes. A supervisor reads it and is offered nothing."""
    from apps.activities.group_actions import may_tick
    from apps.activities.profile_activities import _may_run

    return may_tick(activity.status) and _may_run(activity, user)


def _budget_breakdown(user, activity, snapshot, staff_name) -> dict:
    from apps.budget.breakdown import activity_budget_breakdown
    from apps.core.scoping import resolve_partner_ids

    return activity_budget_breakdown(
        activity,
        snapshot=snapshot,
        staff_name="" if staff_name == "Unknown Staff" else staff_name,
        partner_view=bool(resolve_partner_ids(user)),
    )


@require_page_permission("my_plan")
def activity_detail_view(request, activity_id):
    a = get_object_or_404(
        # The drawer renders line.finance_status per cost line — honour its
        # prefetch contract or every line costs two extra queries.
        Activity.objects.prefetch_related(
            "schedule_cost_lines__advance_requests",
            "schedule_cost_lines__weekly_request_lines__weekly_fund_request",
        ),
        id=activity_id,
        deleted_at__isnull=True,
    )

    # Enforce record ownership/scope gating
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_record_access",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to access activity detail outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to view this activity."
        )

    evidence_list = evidence_records_for_activity(activity_id, request.user)

    # Determine status details
    today = date.today()
    from apps.my_plan.services import get_activity_status_label_and_class

    status_label, status_class = get_activity_status_label_and_class(a, today)

    # Populate staff name
    from apps.accounts.models import User

    staff_name = "Unknown Staff"
    if a.responsible_staff_id:
        try:
            staff_name = User.objects.get(
                Q(id=a.responsible_staff_id)
                | Q(staff_profile__id=a.responsible_staff_id)
            ).name
        except User.DoesNotExist:
            pass

    # Timeline read from the activity's own state — scheduled, then evidence,
    # then completion. Nothing here is a placeholder: each step is Completed
    # only when the record says so, and Pending otherwise.
    from apps.core.activity_types import COMPLETED_WORK_STATUSES
    from apps.my_plan.services import status_tone

    scheduled_at = a.scheduled_date or a.created_at
    has_evidence = bool(evidence_list)
    is_complete = a.status in COMPLETED_WORK_STATUSES
    timeline = [
        {
            "label": "Activity scheduled",
            "when": scheduled_at,
            "done": bool(a.scheduled_date or a.planned_date),
            "detail": "" if (a.scheduled_date or a.planned_date) else "Not scheduled",
        },
        {
            "label": "Evidence upload",
            "when": evidence_list[0].created_at if has_evidence else None,
            "done": has_evidence,
            "detail": f"{len(evidence_list)} file(s)" if has_evidence else "Pending",
        },
        {
            "label": "Activity completion",
            "when": a.updated_at if is_complete else None,
            "done": is_complete,
            "detail": status_label if is_complete else "Pending",
        },
    ]

    # Staff finance wording follows the governed state machine and contains
    # only the country operational layer. Regional benchmark and reserve
    # capacity never enter this context.
    from apps.budget.models import ActivityCostSnapshot, ActivityCostStatus

    cost_snapshot = (
        ActivityCostSnapshot.objects.filter(activity=a, is_current=True)
        .select_related("operational_rate_card")
        .first()
    )
    if cost_snapshot and cost_snapshot.cost_status in (
        ActivityCostStatus.ACCOUNTED,
        ActivityCostStatus.CLOSED,
    ):
        activity_cost = {
            "label": "Actual Accounted Spend",
            "amount": int(cost_snapshot.actual_accounted_spend),
            "note": "Recorded after approved accountability",
            "amount_disbursed": int(cost_snapshot.amount_disbursed),
        }
    elif cost_snapshot and cost_snapshot.approved_operating_limit is not None:
        activity_cost = {
            "label": "Approved Operating Limit",
            "amount": int(cost_snapshot.approved_operating_limit),
            "note": "Maximum authorized activity spend",
            "amount_disbursed": int(cost_snapshot.amount_disbursed),
        }
    else:
        from apps.budget.costing_service import planned_minimum_amounts

        minimum_amount = planned_minimum_amounts([a]).get(a.id)
        activity_cost = {
            "label": "Minimum Viable Cost",
            "amount": minimum_amount,
            "note": (
                "Staff planning estimate. Funding is calculated at country operational rates."
                if minimum_amount is not None
                else "Minimum viable cost not configured. Ask the Country Director to set the missing rates."
            ),
            "amount_disbursed": 0,
        }

    budget = _budget_breakdown(request.user, a, cost_snapshot, staff_name)
    if budget["captured_elsewhere"] and activity_cost["amount"] is None:
        # The UGX 0 half of an in-school Training / School Visit pair is
        # priced, at nothing, by design (owner, 2026-10-05: keep it at UGX 0
        # and say where the cost is): never "not configured".
        activity_cost = {
            **activity_cost,
            "amount": 0,
            "note": budget["captured_elsewhere"].strip("()").capitalize(),
        }

    context = {
        "act": a,
        # The monitoring staff member — and Impact Assessment — record the
        # partner's Salesforce entry here, and that completes the activity
        # (owner, 2026-09-12). SSA Support has its own drawer, which also
        # carries the scores and the enrolment.
        "may_confirm_partner_work": (
            a.status == "awaiting_ia_verification"
            and not is_partner_ssa_support_activity(a)
            and RolePermissionService.can_confirm_partner_activity(request.user, a)
        ),
        "evidence_list": evidence_list,
        "status_label": status_label,
        "status_class": status_class,
        "status_tone": status_tone(status_class),
        "responsible_staff_name": staff_name,
        "timeline": timeline,
        "activity_cost": activity_cost,
        # Every cost item, how it was worked out and who shares the day
        # (owner, 2026-10-05: "for the team to make sure it is the right
        # cost"). A partner reads what it is paid, not the staff day.
        "budget": budget,
        "can_complete_partner_ssa_support": (
            RolePermissionService.can_complete_partner_ssa_support(request.user, a)
            and a.status == "awaiting_ia_verification"
        ),
        "ssa_verdict": verdict_display(a),
        # Edit (owner, 2026-10-02): "open" while the work is still scheduled,
        # "locked" (greyed) once it has been carried out, "" when it is not
        # this reader's to edit. Reschedule follows the same line.
        "edit_state": _edit_state(a, request.user),
        "can_reschedule": _can_reschedule(a, request.user),
        "can_cancel": _can_cancel(a, request.user),
        # Complete is the officer's too. It was offered to every reader of
        # the page; a team member's activity is read, not run (owner,
        # 2026-10-08).
        "can_complete": _may_change(a, request.user),
        **_return_context(a),
        **_facilitator_context(request.user, a),
        **_training_profile_context(a),
    }
    # ── IA review · IA-P: OneTest results ──
    # A delivered OneTest visit carries "Record learning results"; the link a
    # completion, To-Do or returned-result notice follows (?learning_results=1)
    # opens the drawer as the page loads.
    from apps.impact.evidence_services import may_record_for_activity

    if may_record_for_activity(request.user, a):
        context["onetest_results_drawer"] = f"/my-plan/{a.id}/learning-results"
        context["onetest_results_autoload"] = request.GET.get("learning_results") == "1"
    # ── end IA-P ──

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/my_plan/activity_detail_drawer.html", context)
    return render(request, "pages/my_plan/detail.html", context)


@require_any_page_permission("my_plan", "ia_partner_evidence")
def partner_ssa_completion_drawer_view(request, activity_id):
    """Dedicated completion drawer for partner-delivered school SSA Support."""
    a = get_object_or_404(
        Activity.objects.select_related("school"),
        id=activity_id,
        deleted_at__isnull=True,
    )
    if not RolePermissionService.can_complete_partner_ssa_support(request.user, a):
        return HttpResponseForbidden(
            "Only Impact Assessment or the staff member monitoring this partner "
            "SSA Support activity may complete it."
        )
    if a.status != "awaiting_ia_verification":
        return notice_fragment(
            "The partner must submit the completed SSA evidence before scores "
            "and enrolment can be recorded."
        )
    return render(
        request,
        "partials/my_plan/partner_ssa_completion_drawer.html",
        _partner_ssa_completion_context(a),
    )


@require_any_page_permission("my_plan", "ia_partner_evidence")
def partner_ssa_completion_action(request, activity_id):
    """Save eight scores + pupil enrolment and complete the partner activity."""
    if request.method != "POST":
        return HttpResponseForbidden("POST required")
    a = get_object_or_404(
        Activity.objects.select_related("school"),
        id=activity_id,
        deleted_at__isnull=True,
    )
    if not RolePermissionService.can_complete_partner_ssa_support(request.user, a):
        return HttpResponseForbidden(
            "Only Impact Assessment or the staff member monitoring this partner "
            "SSA Support activity may complete it."
        )

    payload = {
        "scores": [
            {
                "intervention": code,
                "score": request.POST.get(f"score_{code}", ""),
            }
            for code, _label in SsaIntervention.choices
        ],
        "enrollment": request.POST.get("enrollment", ""),
        "salesforceId": request.POST.get("salesforce_id", ""),
        "verificationNote": request.POST.get("verification_note", ""),
    }
    try:
        result = complete_partner_ssa_support(a.id, payload, request.user)
    except Exception as exc:
        return error_fragment(exc, action="SSA Support completion error", status=400)

    audit_log(
        action="complete_partner_ssa_support",
        subject_kind="Activity",
        subject_id=str(a.id),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=True,
        payload={
            "ssa_record_id": result["ssaRecordId"],
            "enrollment": result["enrollment"],
            "score_count": len(payload["scores"]),
        },
    )
    response = HttpResponse("<script>window.location.reload();</script>")
    response["HX-Trigger"] = "close-drawer"
    return response


@require_page_permission("my_plan")
def complete_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_record_access",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to open activity completion drawer outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to access this activity drawer."
        )

    if is_partner_ssa_support_activity(a):
        return partner_ssa_completion_drawer_view(request, activity_id)

    pair = in_school_training_pair(activity_id, request.user)
    paired_school_visit = None
    if pair is not None:
        a, paired_school_visit = pair
        if not RolePermissionService.can_view_record(request.user, paired_school_visit):
            return HttpResponseForbidden(
                "Access Denied: You do not have permission to access the paired "
                "School Visit."
            )
    act = get_activity(a.id, request.user)

    def attach_school_feedback():
        feedback = getattr(a, "school_visit_feedback", None)
        act["feedbackFinding"] = feedback.finding if feedback else ""
        act["schoolImprovements"] = feedback.improvements if feedback else []
        act["schoolImprovementsText"] = (
            "\n".join(feedback.improvements) if feedback else ""
        )

    attach_school_feedback()

    # Auto-start completion if in scheduling status to unlock files/codes
    pair_needs_start = paired_school_visit is not None and (
        act.get("status") in STARTABLE_STATUSES
        or paired_school_visit.status in STARTABLE_STATUSES
    )
    if pair_needs_start or act.get("status") in STARTABLE_STATUSES:
        forbidden = _forbid_staff_on_partner_activity(request, a)
        if forbidden:
            return forbidden
        try:
            if paired_school_visit is not None:
                start_in_school_training_pair(a.id, request.user)
            else:
                start_completion(a.id, principal=request.user)
            act = get_activity(a.id, request.user)
            attach_school_feedback()
        except Exception as e:
            return error_fragment(e, action="Error starting completion", status=400)

    evidence_list = list(evidence_records_for_activity(a.id, request.user))
    if paired_school_visit is not None:
        evidence_list.extend(
            evidence_records_for_activity(paired_school_visit.id, request.user)
        )

    cluster_schools = []
    guest_rows = []
    if a.cluster:
        from apps.activities.models import ClusterActivityAttendance

        cluster_schools = (
            active_schools().filter(cluster_id=a.cluster_id).order_by("name")
        )
        # The register opens on who was invited when this was scheduled, so
        # the person who delivered confirms rather than reconstructs. Rows
        # already marked attended stay ticked on a second visit.
        rows = {
            r.school_id: r for r in ClusterActivityAttendance.objects.filter(activity=a)
        }
        cluster_schools = [
            {
                "id": s.id,
                "name": s.name,
                "school_id": s.school_id,
                # No row at all means this drawer predates the invitation
                # list; tick everyone, which is what it used to assume.
                "ticked": (
                    rows[s.id].attended or rows[s.id].invited
                    if s.id in rows
                    else not rows
                ),
            }
            for s in cluster_schools
        ]
        guest_rows = [
            {
                "id": r.school_id,
                "name": r.school.name,
                "school_id": r.school.school_id,
                "teachers": r.teachers,
                "leaders": r.leaders,
                "other": r.other,
            }
            for r in ClusterActivityAttendance.objects.filter(
                activity=a, is_guest=True
            ).select_related("school")
        ]

    needs_netsuite_id = False
    disbursed_amount = None
    wfr_line = a.schedule_cost_lines.first()
    if wfr_line:
        adv = wfr_line.advance_requests.first()
        if adv and adv.status == "disbursed" and not adv.accountability_netsuite_id:
            needs_netsuite_id = True
            disbursed_amount = adv.disbursed_amount or adv.amount

    context = {
        "act": act,
        "evidence_list": evidence_list,
        "cluster_schools": cluster_schools,
        "guest_rows": guest_rows,
        "can_add_school": has_permission(
            request.user, Permission.SCHOOL_CREATE_SINGLE.value
        ),
        "interventions": SsaIntervention.choices,
        "drawer_size": "md",
        "needs_netsuite_id": needs_netsuite_id,
        "disbursed_amount": disbursed_amount,
        "is_paired_in_school_training": paired_school_visit is not None,
        "requires_school_feedback": (
            paired_school_visit is not None or a.activity_type in VISIT_TYPES
        ),
        "paired_school_visit": (
            get_activity(paired_school_visit.id, request.user)
            if paired_school_visit is not None
            else None
        ),
        **_return_context(a),
    }
    # A follow-up visit is completed against the exact training it answered
    # (owner, 2026-09-21). The list is the school's completed sessions by
    # either route — in-school, Core, or a cluster session it attended — the
    # same options the scheduling drawer offers and the same ones the service
    # re-checks on submit.
    from apps.activities.services import is_training_follow_up_visit

    context["is_training_follow_up"] = is_training_follow_up_visit(a)
    if context["is_training_follow_up"]:
        from apps.activities.training_history import follow_up_options

        context["follow_up_options"] = follow_up_options(a.school, fy=a.fy)
        context["follow_up_selected_id"] = a.follow_up_of_activity_id or ""
    # The platform already knows what this activity type needs, so the form
    # says so and pre-selects the outstanding one rather than offering twelve
    # kinds and letting someone guess wrong.
    from apps.core.enums import EvidenceKind
    from apps.evidence.requirements import checklist as evidence_checklist
    from apps.evidence.requirements import required_kinds

    _checklist = evidence_checklist(a)
    if paired_school_visit is not None:
        _checklist = [
            *[{**item, "recordLabel": "Training"} for item in _checklist],
            *[
                {**item, "recordLabel": "School Visit"}
                for item in evidence_checklist(paired_school_visit)
            ],
        ]
    context["evidence_checklist"] = _checklist
    required = set(required_kinds(a.activity_type))
    if paired_school_visit is not None:
        required.update(required_kinds(paired_school_visit.activity_type))
    context["evidence_required_kinds"] = list(required)
    context["evidence_kind_choices"] = EvidenceKind.choices

    return render(request, "partials/my_plan/complete_drawer.html", context)


@require_page_permission("my_plan")
def accountability_action(request, activity_id):
    """Submit accountability for a disbursed activity (GET drawer / POST submit).

    The responsible user declares actual spend, returned amount, a variance
    explanation when the numbers don't reconcile, uploads receipts, and enters
    the NetSuite Code — proof the expense entered NetSuite. Submission lands in
    ACCOUNTABILITY_PENDING for the Accountant's review; it never self-clears
    (advance_service.approve_accountability is the Accountant's action)."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_record_access",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted the accountability drawer outside their scope.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to access this activity."
        )

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    disbursed = list(
        a.advance_requests.filter(status="disbursed").select_related("budget_line")
    )
    total_disbursed = sum(
        (adv.disbursed_amount or adv.amount or 0) for adv in disbursed
    )

    if request.method != "POST":
        act = get_activity(activity_id, request.user)
        return render(
            request,
            "partials/my_plan/accountability_drawer.html",
            {
                "act": act,
                "disbursed_advances": disbursed,
                "total_disbursed": total_disbursed,
                "drawer_size": "md",
            },
        )

    if not disbursed:
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">No disbursed advance is awaiting accountability on this activity.</div>',
            status=400,
        )

    netsuite_code = request.POST.get("netsuite_code", "").strip()
    variance_note = request.POST.get("variance_note", "").strip()
    try:
        # Owner, 2026-09-12: "for staff fund accountability, one just has to
        # enter the NetSuite ID and submit" — an empty spend means the whole
        # advance was spent; a return is declared only when there was one.
        raw_spent = (request.POST.get("amount_spent") or "").strip()
        amount_spent = int(raw_spent) if raw_spent else int(total_disbursed)
        amount_returned = int(request.POST.get("amount_returned") or 0)
    except ValueError:
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Amounts must be whole UGX numbers.</div>',
            status=400,
        )

    receipt = request.FILES.get("receipt_file")
    if receipt:
        try:
            record_upload(
                principal=request.user,
                activity_id=activity_id,
                kind=infer_kind_from_upload(receipt),
                file_obj=receipt,
            )
        except Exception as e:
            return error_fragment(e, action="Receipt upload error", status=400)

    # One declared total, allocated per advance proportionally to what each
    # advance actually disbursed (remainder to the last so sums reconcile).
    from apps.fund_requests import advance_service

    try:
        spent_left, returned_left = amount_spent, amount_returned
        for i, adv in enumerate(disbursed):
            share = adv.disbursed_amount or adv.amount or 0
            if i == len(disbursed) - 1 or not total_disbursed:
                adv_spent, adv_returned = spent_left, returned_left
            else:
                adv_spent = round(amount_spent * share / total_disbursed)
                adv_returned = round(amount_returned * share / total_disbursed)
            spent_left -= adv_spent
            returned_left -= adv_returned
            advance_service.submit_accountability(
                adv.id,
                {
                    "netsuiteId": netsuite_code,
                    "amountSpent": adv_spent,
                    "amountReturned": adv_returned,
                    "varianceNote": variance_note,
                },
                request.user,
            )
    except Exception as e:
        return error_fragment(e, status=400)

    audit_log(
        action="accountability_submitted",
        subject_kind="Activity",
        subject_id=str(a.id),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=True,
        payload={
            "netsuite_code": netsuite_code,
            "amount_spent": amount_spent,
            "amount_returned": amount_returned,
        },
    )
    response = HttpResponse("<script>window.location.reload();</script>")
    response["HX-Trigger"] = "close-drawer"
    return response


@require_page_permission("my_plan")
def confirm_reimbursement_receipt_action(request, activity_id):
    """The responsible employee confirms a disbursed reimbursement actually
    arrived — required before the reimbursement (and the accountability it
    settles) reaches its terminal financially-cleared state (mandate: no
    accountability closes without the employee's own receipt confirmation)."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to access this activity."
        )

    adv = (
        a.advance_requests.filter(status="reimbursement_disbursed")
        .order_by("-reimbursed_at")
        .first()
    )
    if request.method != "POST":
        return render(
            request,
            "partials/my_plan/confirm_reimbursement_receipt_drawer.html",
            {
                "act": get_activity(activity_id, request.user),
                "adv": adv,
                "drawer_size": "sm",
            },
        )

    if not adv:
        return HttpResponse(
            '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">No disbursed reimbursement is awaiting receipt confirmation on this activity.</div>',
            status=400,
        )

    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests import advance_service

    try:
        advance_service.confirm_reimbursement_receipt(
            adv.id,
            {"amount": request.POST.get("amount", adv.reimbursed_amount)},
            request.user,
        )
    except (BadRequest, Forbidden) as e:
        return error_fragment(e, status=400)

    audit_log(
        action="reimbursement_receipt_confirmed",
        subject_kind="Activity",
        subject_id=str(a.id),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=True,
        payload={"advance_id": adv.id, "amount": adv.reimbursed_amount},
    )
    response = HttpResponse("<script>window.location.reload();</script>")
    response["HX-Trigger"] = "close-drawer"
    return response


@require_page_permission("my_plan")
def reschedule_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_record_access",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to open activity reschedule drawer outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to access this activity drawer."
        )

    # A team member's activity is read, not moved (owner, 2026-10-08): the
    # service refuses, so the drawer says so instead of offering a form.
    read_only = _team_read_only(request, a)
    if read_only is not None:
        return read_only

    # Work already delivered keeps its day (owner, 2026-10-02): the service
    # refuses the move, so the drawer says so instead of offering a form.
    # Work that was started and never submitted still moves (2026-10-07).
    from apps.activities.editing import is_executed

    if is_executed(a):
        return notice_fragment(
            "This activity has already been carried out, so it can no longer "
            "be rescheduled. Only an activity that is still scheduled can be."
        )

    # Rescheduling deliberately reuses the shared schedule drawer in its safe
    # edit mode. The existing activity remains the subject of the POST, so a
    # date change cannot accidentally create a second planned activity.
    subject_name = (
        a.school.name
        if a.school_id
        else a.cluster.name
        if a.cluster_id
        else "this activity"
    )
    activity_label = dict(ActivityType.choices).get(
        a.activity_type, a.activity_type.replace("_", " ").title()
    )
    assigning_staff_name = None
    if a.delivery_type == "partner":
        staff_id = a.monitored_by_staff_id
        if not staff_id:
            from apps.partners.models import PartnerAssignment

            assignment = None
            if a.cluster_id:
                assignment = PartnerAssignment.objects.filter(
                    cluster=a.cluster, partner_id=a.assigned_partner_id
                ).first()
            if not assignment and a.school_id:
                assignment = PartnerAssignment.objects.filter(
                    school=a.school, partner_id=a.assigned_partner_id
                ).first()
            if assignment:
                staff_id = assignment.assigning_staff_id
        if staff_id:
            from apps.accounts.models import User

            staff_user = User.objects.filter(
                Q(id=staff_id) | Q(staff_profile__id=staff_id)
            ).first()
            if staff_user:
                assigning_staff_name = staff_user.name
    from apps.activities import pairs

    context = {
        "reschedule_mode": True,
        "reschedule_activity": a,
        # Said before the date is saved: the other half of an in-school
        # Training pair moves with it.
        "pair_joins": pairs.joins(a, action=pairs.RESCHEDULE),
        "reschedule_action_url": f"/my-plan/{a.id}/reschedule",
        "sent_fund_weeks": _sent_fund_weeks(a),
        "schedule_subject_name": subject_name,
        "recommended_activity_type": a.activity_type,
        "recommended_activity_label": activity_label,
        "assigning_staff_name": assigning_staff_name,
        "drawer_size": "md",
    }
    return render(request, "partials/planning/schedule_drawer.html", context)


@require_page_permission("my_plan")
def reschedule_activity_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to reschedule an activity outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to reschedule this activity."
        )

    if request.method == "POST":
        new_date_str = request.POST.get("scheduled_date", "").strip()
        reason = request.POST.get("reason", "").strip()

        payload = {
            "scheduledDate": new_date_str,
            "reason": reason,
        }
        if new_date_str:
            try:
                dt = date.fromisoformat(new_date_str)
                payload["plannedMonth"] = dt.month
                payload["plannedWeek"] = min(5, (dt.day - 1) // 7 + 1)
            except ValueError:
                pass

        from apps.activities import pairs

        joined = pairs.joins(a, action=pairs.RESCHEDULE)
        try:
            reschedule_activity(activity_id, payload, request.user)
            # Each record that moved has its own line in the audit trail.
            for moved in (a, joined):
                if moved is None:
                    continue
                audit_log(
                    action="reschedule_activity",
                    subject_kind="Activity",
                    subject_id=str(moved.id),
                    actor_id=str(request.user.id),
                    actor_role=request.user.active_role,
                    success=True,
                    payload={
                        "new_date": new_date_str,
                        "reason": reason,
                        **({"moved_with": str(a.id)} if moved is not a else {}),
                    },
                )
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            messages.success(request, "Activity rescheduled successfully.")
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                return error_fragment(e, status=400)
            messages.error(request, f"Error: {e}")

    return local_redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def complete_activity_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(
        request.user, a
    ) or not RolePermissionService.can_upload_evidence(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to complete/upload evidence for an activity without proper authorization.",
        )
        return HttpResponseForbidden(
            "Access Denied: You are not authorized to complete this activity."
        )

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    pair = in_school_training_pair(activity_id, request.user)
    paired_school_visit = None
    if pair is not None:
        a, paired_school_visit = pair
        if not RolePermissionService.can_upload_evidence(
            request.user, paired_school_visit
        ):
            return HttpResponseForbidden(
                "Access Denied: You are not authorized to complete the paired "
                "School Visit."
            )
    act = get_activity(a.id, request.user)

    if request.method == "POST":
        # Handle start completion if still in scheduled status
        pair_needs_start = paired_school_visit is not None and (
            paired_school_visit.status in STARTABLE_STATUSES
        )
        if pair_needs_start or act.get("status") in STARTABLE_STATUSES:
            try:
                if paired_school_visit is not None:
                    start_in_school_training_pair(a.id, request.user)
                else:
                    start_completion(a.id, principal=request.user)
            except Exception as e:
                if request.headers.get("HX-Request") == "true":
                    return error_fragment(
                        e, action="Error starting completion", status=400
                    )
                messages.error(request, f"Error starting completion: {e}")
                return local_redirect(f"/my-plan/{a.id}")

        # Each form may come as several pages — photographed or chosen
        # together — merged into one PDF (owner, 2026-09-26).
        uploads = []
        evidence_files = request.FILES.getlist("evidence_file")
        if evidence_files:
            uploads.append(
                (
                    a,
                    evidence_files,
                    request.POST.get("evidence_kind"),
                )
            )
        if paired_school_visit is not None:
            training_files = request.FILES.getlist("training_evidence_file")
            visit_files = request.FILES.getlist("visit_evidence_file")
            if training_files:
                uploads.append((a, training_files, EvidenceKind.ATTENDANCE_FORM))
            if visit_files:
                uploads.append(
                    (paired_school_visit, visit_files, EvidenceKind.VISIT_FORM)
                )
        for target_activity, uploaded_files, asserted_kind in uploads:
            uploaded_file = uploaded_files[0]
            try:
                record_pages_upload(
                    principal=request.user,
                    activity_id=target_activity.id,
                    # What the person selected, else what this activity still
                    # needs, else the file's shape. Inference alone can only say
                    # "pdf" or "photo", which no requirement asks for -- so
                    # completion was unreachable for every activity type that
                    # declares one.
                    kind=resolve_evidence_kind(
                        uploaded_file,
                        activity=target_activity,
                        asserted=asserted_kind,
                    ),
                    files=uploaded_files,
                )
            except Exception as e:
                if request.headers.get("HX-Request") == "true":
                    return error_fragment(e, action="Upload Error", status=400)
                messages.error(request, f"Upload error: {e}")
                return local_redirect(f"/my-plan/{a.id}")

        salesforce_id = request.POST.get("salesforce_id", "").strip()
        visit_salesforce_id = request.POST.get("visit_salesforce_id", "").strip()
        teachers = request.POST.get("teachers_attended", 0)
        leaders = request.POST.get("leaders_attended", 0)
        other = request.POST.get("other_participants", 0)
        attended_school_ids = request.POST.getlist("attended_school_ids")

        netsuite_id = request.POST.get("netsuite_id", "").strip()
        if netsuite_id:
            wfr_line = a.schedule_cost_lines.first()
            if wfr_line:
                adv = wfr_line.advance_requests.first()
                if adv and adv.status == "disbursed":
                    # The responsible user SUBMITS accountability — this is not
                    # the closure step. It lands in ACCOUNTABILITY_PENDING; only
                    # the Accountant's approve_accountability() can close it to
                    # ACCOUNTED (see apps.fund_requests.advance_service). Do not
                    # write status/accountability_netsuite_id directly here —
                    # that would let staff self-certify their own accountability.
                    from apps.fund_requests import advance_service

                    try:
                        advance_service.submit_accountability(
                            adv.id,
                            {
                                "netsuiteId": netsuite_id,
                                "amountSpent": request.POST.get("amount_spent", 0),
                                "amountReturned": request.POST.get(
                                    "amount_returned", 0
                                ),
                                "varianceNote": request.POST.get("variance_note", ""),
                            },
                            request.user,
                        )
                    except Exception as e:
                        if request.headers.get("HX-Request") == "true":
                            return error_fragment(e, status=400)
                        messages.error(request, f"Error: {e}")
                        return local_redirect(f"/my-plan/{activity_id}")

        # Handle SSA collection expectations
        if a.ssa_collection_expected:
            ssa_collected = request.POST.get("ssa_collected")
            if ssa_collected == "yes":
                interventions_map = {
                    code: f"score_{code}" for code, _label in SsaIntervention.choices
                }

                def _label(code: str) -> str:
                    return code.replace("_", " ").title()

                scores_list = []
                for enum_val, field_name in interventions_map.items():
                    val = request.POST.get(field_name, "").strip()
                    if not val:
                        return notice_fragment(f"Missing score for {_label(enum_val)}")
                    try:
                        f_val = float(val)
                    except ValueError:
                        return notice_fragment(
                            f"Score for {_label(enum_val)} must be numeric"
                        )
                    if f_val < 0 or f_val > 10:
                        return notice_fragment(
                            f"Score for {_label(enum_val)} must be between 0 and 10"
                        )
                    scores_list.append({"intervention": enum_val, "score": f_val})

                from apps.core.exceptions import BadRequest
                from apps.ssa.services import upload as upload_ssa
                from apps.ssa.services import visit_assessment_date

                # IA review (2026-09-13): dated by the visit, linked to it, and
                # pending until a different verifier confirms the scores. A
                # refusal (a duplicate date, an unverified prior-year record)
                # is shown in the drawer, not returned as an error envelope.
                try:
                    upload_ssa(
                        {
                            "schoolId": a.school.school_id,
                            "dateOfSsa": visit_assessment_date(a).isoformat(),
                            "scores": scores_list,
                            "collectorType": "partner"
                            if a.delivery_type == "partner"
                            else "staff",
                            "collectedByPartnerId": a.assigned_partner_id,
                            "sourceActivityId": a.id,
                        },
                        request.user,
                    )
                except BadRequest as exc:
                    return notice_fragment(str(getattr(exc, "detail", exc)))
                a.ssa_not_collected_reason = None
            else:
                reason = request.POST.get("ssa_not_collected_reason", "").strip()
                if not reason:
                    return HttpResponse(
                        '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Please select a reason why SSA was not collected.</div>',
                        status=400,
                    )
                a.ssa_not_collected_reason = reason
            a.save(update_fields=["ssa_not_collected_reason", "updated_at"])

        payload = {
            # The form already refused above unless this question was
            # answered; pass the answer on so `complete()` can hold the same
            # rule for every other door (SSA-01).
            "ssaCollected": request.POST.get("ssa_collected") == "yes",
            "salesforceId": salesforce_id,
            "trainingSalesforceId": salesforce_id,
            "visitSalesforceId": visit_salesforce_id,
            "teachersAttended": int(teachers) if teachers else 0,
            "leadersAttended": int(leaders) if leaders else 0,
            "otherParticipants": int(other) if other else 0,
            "attendedSchoolIds": attended_school_ids,
            # Which training this visit followed up. Required by complete()
            # for a follow-up visit and ignored for everything else.
            "followUpOfActivityId": request.POST.get(
                "follow_up_of_activity_id", ""
            ).strip(),
            # What the officer saw -- stored by complete(); absent keys leave
            # earlier entries alone, so only send what the form carried.
            **{
                key: request.POST.get(field, "").strip()
                for key, field in (
                    ("actualOutcome", "actual_outcome"),
                    ("actualObservations", "actual_observations"),
                    ("followUpNote", "follow_up_note"),
                )
                if field in request.POST
            },
            **(
                {
                    "feedbackFinding": request.POST.get("feedback_finding", "").strip(),
                    "schoolImprovements": request.POST.get(
                        "school_improvements", ""
                    ).splitlines(),
                }
                if "feedback_finding" in request.POST
                or "school_improvements" in request.POST
                else {}
            ),
        }

        try:
            if paired_school_visit is not None:
                complete_in_school_training_pair(a.id, payload, request.user)
            else:
                complete_activity(a.id, payload, request.user)
            audit_log(
                action=(
                    "complete_in_school_training_pair"
                    if paired_school_visit is not None
                    else "complete_activity"
                ),
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload={
                    **payload,
                    "paired_school_visit_id": (
                        paired_school_visit.id if paired_school_visit else None
                    ),
                },
            )
            # ── IA review · IA-P: OneTest results ──
            # A delivered OneTest diagnostic visit offers "Record learning
            # results" at once: the visit page reopens on the results drawer
            # (apps/frontend/views/ia_school_evidence_views.py), where each
            # class's results are recorded pending verification and linked to
            # this visit.
            import json

            onetest_next = ""
            if paired_school_visit is None:
                from apps.impact.evidence_services import (
                    is_onetest,
                    may_record_for_activity,
                )

                if is_onetest(a):
                    a.refresh_from_db(fields=["status", "deleted_at"])
                    if may_record_for_activity(request.user, a):
                        onetest_next = f"/my-plan/{a.id}?learning_results=1"
            # ── end IA-P ──
            if request.headers.get("HX-Request") == "true":
                if onetest_next:
                    response = HttpResponse(
                        f"<script>window.location.assign({json.dumps(onetest_next)});</script>"
                    )
                else:
                    response = HttpResponse(
                        "<script>window.location.reload();</script>"
                    )
                response["HX-Trigger"] = "close-drawer"
                return response
            messages.success(
                request,
                (
                    "Training and School Visit completion submitted successfully."
                    if paired_school_visit is not None
                    else "Activity completion submitted successfully."
                ),
            )
            if onetest_next:
                return local_redirect(onetest_next)
        except Exception as e:
            if request.headers.get("HX-Request") == "true":
                return error_fragment(e, action="Submission Error", status=400)
            messages.error(request, f"Submission error: {e}")

    return local_redirect(f"/my-plan/{a.id}")


# ── Completion Reviews (Programme Lead alignment, 2026-09-13) ────────────────
# The lead confirms the team's completed work before Impact Assessment verifies
# it. The page, its drawers and its two decisions share one gate
# (`pl_review_queue`) and one rule (`apps.pl_review.services`): the queue lists
# exactly what the decisions accept, so no row offers a button that refuses.
PL_REVIEW_QUEUE_URL = "/pl/review-queue"


def _review_refusal(request, activity_id: str, verb: str):
    """Audit and answer a decision on work this reviewer may not decide."""
    audit_log(
        action="unauthorized_mutation_attempt",
        subject_kind="Activity",
        subject_id=str(activity_id),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=False,
        reason=(
            f"Program Lead attempted to {verb} activity completion outside "
            "their supervision."
        ),
    )
    return HttpResponseForbidden(
        "Access Denied: You do not supervise the owner of this activity."
    )


@require_page_permission("pl_review_queue")
def pl_queue_view(request):
    """Completion Reviews: the team's completed work waiting on this lead.

    A register rather than a stack of cards: one row per completion with the
    officer, the work, where and when it happened, the intervention, who
    attended, the evidence, the Salesforce reference and how long it has
    waited — oldest first. Open shows the whole completion in a drawer,
    Approve sends it to Impact Assessment, Return sends it back with the
    reason the officer will read.
    """
    from apps.pl_review.services import review_register

    register = review_register(request.user, cceo=request.GET.get("cceo") or "")
    filters = []
    # A filter with one officer to choose narrows nothing, so it is not drawn.
    if len(register["cceo_options"]) > 1 or register["cceo"]:
        filters.append(
            {
                "name": "cceo",
                "label": "Officer",
                "value": register["cceo"],
                "blank": "Every officer",
                "options": register["cceo_options"],
            }
        )
    # ?open=<activity id> opens that completion's drawer on arrival, so a
    # To-Do or notification can land on the one completion it names. Only an
    # id in this reviewer's own rows is honoured.
    wanted = (request.GET.get("open") or "").strip()
    autoload = (
        f"{PL_REVIEW_QUEUE_URL}/{wanted}/drawer"
        if wanted and any(row["id"] == wanted for row in register["rows"])
        else ""
    )
    return render(
        request,
        "pages/my_plan/pl_queue.html",
        {
            "rows": register["rows"],
            "filters": filters,
            "queue_url": PL_REVIEW_QUEUE_URL,
            "autoload_drawer": autoload,
        },
    )


def _ssa_basis_facts(activity) -> list[dict]:
    """Whether the completion's plan followed the SSA, and the planner's
    reason when it did not (owner, 2026-09-14)."""
    from apps.ssa.plan_alignment import verdict_display

    verdict = verdict_display(activity)
    if verdict is None:
        return []
    facts = [
        {"label": "SSA basis", "value": f"{verdict['label']}. {verdict['reason']}"}
    ]
    if verdict["deviation_reason"]:
        facts.append(
            {
                "label": "Why it departs from the SSA",
                "value": verdict["deviation_reason"],
            }
        )
    return facts


def _review_facts(activity) -> list[dict]:
    """What the lead reads before deciding: the completion as submitted.

    Called only with an activity `reviewable_activity` returned, so the
    reviewer's authority over it is already settled; the evidence is read
    directly rather than through the evidence service's own reach check, which
    predates cluster work and would hide a cluster session's files.
    """
    from apps.core.interventions import INTERVENTION_LABELS
    from apps.evidence.models import EvidenceRecord
    from apps.pl_review.services import _attendance_label, _owning_staff_id, _people

    owner = _owning_staff_id(activity) or ""
    names, _profile_of = _people([owner])
    when = activity.actual_delivery_date or activity.planned_date
    evidence = list(
        EvidenceRecord.objects.filter(activity_id=activity.id, quarantined=False)
        .order_by("created_at")
        .values_list("original_name", "kind")[:20]
    )
    where = (
        activity.school.name
        if activity.school_id
        else (activity.cluster.name if activity.cluster_id else activity.venue)
    )
    return [
        {"label": "Officer", "value": names.get(owner, "") or "Unnamed officer"},
        {
            "label": "Activity",
            "value": activity.activity_name_snapshot
            or activity.get_activity_type_display(),
        },
        {"label": "School or cluster", "value": where},
        {"label": "Delivered", "value": f"{when:%-d %b %Y}" if when else ""},
        {
            "label": "Intervention",
            "value": INTERVENTION_LABELS.get(activity.focus_intervention or "", ""),
        },
        *_ssa_basis_facts(activity),
        {"label": "Attendance", "value": _attendance_label(activity)},
        {
            "label": "Evidence",
            "value": "\n".join(
                f"{name or 'Unnamed file'} ({kind.replace('_', ' ')})"
                for name, kind in evidence
            )
            or "No files uploaded",
        },
        {"label": "Salesforce ID", "value": activity.salesforce_activity_id or ""},
        {"label": "Purpose", "value": activity.activity_purpose_text or ""},
        {"label": "Outcome", "value": activity.actual_outcome or ""},
        {"label": "Observations", "value": activity.actual_observations or ""},
        {"label": "Follow-up", "value": activity.follow_up_note or ""},
    ]


@require_page_permission("pl_review_queue")
def pl_review_drawer(request, activity_id):
    """Open: the whole completion, read-only, with Approve at the foot.

    Read-only by construction — the one form is the review decision itself.
    The officer's own record carries reschedule and completion controls, so
    the lead reads the completion here rather than on the officer's page.
    """
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
    from apps.pl_review.services import reviewable_activity

    try:
        activity = reviewable_activity(activity_id, request.user)
    except (BadRequest, Forbidden, NotFoundError) as exc:
        return _drawer(
            request,
            title="Completion review",
            subtitle="Not waiting on you",
            empty=str(getattr(exc, "detail", exc)),
        )
    # The two decisions a reviewer holds, named the same on every surface
    # (owner, 2026-09-24): Verified, or Return with the reason. Partner
    # Monitoring's Trainings table calls the first Confirm Verification
    # (owner, 2026-09-26); the act is the same.
    decision = (
        "Confirm Verification"
        if request.GET.get("from") == "partner-trainings"
        else "Verified"
    )
    return _drawer(
        request,
        title="Completion review",
        subtitle=activity.activity_name_snapshot
        or activity.get_activity_type_display(),
        facts=_review_facts(activity),
        action=f"{PL_REVIEW_QUEUE_URL}/{activity.id}/confirm",
        submit=decision,
        secondary={
            "label": "Return",
            "hx_get": f"{PL_REVIEW_QUEUE_URL}/{activity.id}/return-drawer",
        },
        note=(
            f"{decision} confirms the completion against Salesforce and marks "
            "it complete. Return sends it back to the officer with your "
            "reason — for example, participants not entered in Salesforce."
        ),
    )


@require_page_permission("pl_review_queue")
def pl_return_drawer(request, activity_id):
    """Return: the reasons ticked and what the lead writes, at least one of
    them, read by the officer as written (owner, 2026-09-26: "add a field for
    reasons, especially if the Salesforce ID is entered but there are no
    participants in Salesforce")."""
    from apps.activities.return_notes import COMMON_REASONS
    from apps.core.exceptions import BadRequest, Forbidden, NotFoundError
    from apps.pl_review.services import reviewable_activity

    try:
        activity = reviewable_activity(activity_id, request.user)
    except (BadRequest, Forbidden, NotFoundError) as exc:
        return _drawer(
            request,
            title="Return completion",
            subtitle="Not waiting on you",
            empty=str(getattr(exc, "detail", exc)),
        )
    facts = [
        fact
        for fact in _review_facts(activity)
        if fact["label"] in ("Officer", "Activity", "School or cluster", "Delivered")
    ]
    return _drawer(
        request,
        title="Return completion",
        subtitle=activity.activity_name_snapshot
        or activity.get_activity_type_display(),
        facts=facts,
        action=f"{PL_REVIEW_QUEUE_URL}/{activity.id}/return",
        submit="Return to officer",
        fields=[
            _field(
                "reasons",
                "Why are you returning it?",
                type="checkboxes",
                options=[(reason, reason) for reason in COMMON_REASONS],
                help="Tick every reason that applies.",
            ),
            _field(
                "reason",
                "What should the officer fix?",
                type="textarea",
                rows=4,
                maxlength=400,
                placeholder=(
                    "Say exactly what to fix, e.g. The attendance form and "
                    "training ID are uploaded, but the participants are not "
                    "entered in Salesforce."
                ),
                help=(
                    "Tick a reason, write one, or both. The officer reads this "
                    "as written on their My Plan."
                ),
            ),
        ],
    )


@require_page_permission("pl_review_queue")
def pl_confirm_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_review_activity(request.user, a):
        return _review_refusal(request, a.id, "confirm")

    if request.method == "POST":
        try:
            pl_confirm(activity_id, request.user)
            audit_log(
                action="pl_approve_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
            )
            # pl_review.services.confirm verifies the work outright: the
            # completion is complete, not waiting on Impact Assessment.
            messages.success(request, "Completion verified and marked complete.")
        except Exception as e:
            messages.error(request, str(getattr(e, "detail", e)))

    return _back(request, PL_REVIEW_QUEUE_URL)


@require_page_permission("pl_review_queue")
def pl_return_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_review_activity(request.user, a):
        return _review_refusal(request, a.id, "return")

    if request.method == "POST":
        reasons = request.POST.getlist("reasons")
        written = request.POST.get("reason", "").strip()
        reason = "; ".join([*reasons, written] if written else reasons)
        try:
            pl_return(
                activity_id, {"reasons": reasons, "reason": written}, request.user
            )
            audit_log(
                action="pl_return_completion",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                payload={"reason": reason},
            )
            messages.success(request, "Activity returned to CCEO for corrections.")
        except Exception as e:
            # A missing reason is refused by the service in words the lead can
            # act on; the page says so rather than returning silently.
            messages.error(request, str(getattr(e, "detail", e)))

    return _back(request, PL_REVIEW_QUEUE_URL)


@require_page_permission("my_plan")
def start_activity_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    context = {
        "act": a,
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/start_drawer.html", context)


@require_page_permission("my_plan")
def start_activity_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        notes = request.POST.get("notes", "").strip()
        try:
            start_completion(activity_id, {"notes": notes}, request.user)
        except Exception as exc:
            return error_fragment(exc, action="Start Error", status=400)

        audit_log(
            action="start_activity",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="Activity execution started",
            payload={"notes": notes},
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return local_redirect(f"/my-plan/{activity_id}")


def _facilitator_context(user, activity) -> dict:
    """ "Facilitated by" on a training's details (owner, 2026-09-29): the
    label, and whether this viewer may change it (staff, a planned staff-run
    training); the service repeats every check."""
    from apps.activities.facilitation import (
        FACILITATOR_EDITABLE_STATUSES,
        facilitator_label,
        takes_facilitator,
    )
    from apps.core.scoping import resolve_partner_ids

    if not takes_facilitator(activity.activity_type):
        return {}
    return {
        "facilitated_by": facilitator_label(activity),
        "can_change_facilitator": (
            activity.delivery_type == "staff"
            and activity.status in FACILITATOR_EDITABLE_STATUSES
            and not resolve_partner_ids(user)
        ),
    }


@require_page_permission("my_plan")
def facilitator_drawer_view(request, activity_id):
    """Change who facilitates a planned training (owner, 2026-09-29: "allow
    the staff to edit the planned activities to add the trainer"). GET shows
    the drawer; POST saves through activities.services.set_facilitator, which
    holds every rule."""
    from apps.activities.facilitation import facilitator_label
    from apps.activities.services import set_facilitator

    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    if request.method == "POST":
        try:
            set_facilitator(
                activity_id,
                request.POST.get("facilitating_partner_id", ""),
                request.user,
            )
        except Exception as exc:
            return error_fragment(exc, action="Facilitator not changed", status=400)
        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response
        return local_redirect("/my-plan")

    from apps.activities.facilitation import session_noun

    context = {
        "act": a,
        "current_facilitator": facilitator_label(a),
        "session_noun": session_noun(a.activity_type),
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/facilitator_drawer.html", context)


def _edit_drawer_context(user, a) -> dict:
    """What the Edit drawer shows for one planned activity."""
    from apps.activities import editing
    from apps.activities.facilitation import session_noun, takes_facilitator
    from apps.core.clock import local_day
    from apps.core.enums import SsaIntervention

    context = {
        "act": a,
        "edit_day": a.planned_date or local_day(a.scheduled_date),
        "takes_facilitator": takes_facilitator(a.activity_type),
        "session_noun": session_noun(a.activity_type),
        "interventions": SsaIntervention.choices,
        "is_cluster_session": editing.is_cluster_session(a),
        "may_move_school": editing.may_move_school(a),
        "sent_fund_weeks": _sent_fund_weeks(a),
        "drawer_size": "md",
    }
    if context["is_cluster_session"]:
        from apps.activities.models import ClusterActivityAttendance
        from apps.clusters.services import active_schools

        invited = set(
            ClusterActivityAttendance.objects.filter(
                activity=a, invited=True
            ).values_list("school_id", flat=True)
        )
        context["member_schools"] = [
            {
                "id": school.id,
                "name": school.name,
                "school_id": school.school_id,
                "invited": school.id in invited,
            }
            for school in active_schools(a.cluster_id)
        ]
        context["schools_invited"] = len(invited)
    elif context["may_move_school"]:
        context["movable_schools"] = list(
            editing.movable_schools(a, user).values("id", "school_id", "name")
        )
    try:
        pair = in_school_training_pair(a.id, user)
    except Exception:  # noqa: BLE001 — a broken pair is the save's to refuse
        pair = None
    if pair is not None:
        training, visit = pair
        context["other_half"] = visit if a.id == training.id else training
    context.update(_edit_project_context(user, a))
    context.update(_edit_training_context(a))
    return context


def _training_profile_context(a) -> dict:
    """What a training's profile says it is (owner, 2026-10-06): the training
    it delivers, by the name it was scheduled under, and how it is delivered —
    Group Training or In-School Training. A training that names none yet says
    so, and its Edit drawer is where one is chosen."""
    from apps.planning import training_ceilings

    if not training_ceilings.is_training(a):
        return {}
    from apps.core.activity_types import CLUSTER_MEETING_TYPES

    name = ""
    if training_ceilings.course_id_of(a):
        course = a.training_course or a.catalogue_item
        if a.activity_type in CLUSTER_MEETING_TYPES:
            # A meeting keeps its own name; the training is named beside it.
            name = (a.recommendation_source or {}).get("trainingCourseName") or (
                course.display_name
            )
        else:
            name = a.activity_name_snapshot or course.display_name
    return {
        "training_profile": {
            "name": name,
            "delivery": training_ceilings.DELIVERY_LABELS.get(
                training_ceilings.delivery_of(a), ""
            ),
        }
    }


def _edit_training_context(a) -> dict:
    """What the Edit drawer says about a training (owner, 2026-10-06).

    Which training it delivers, as a list of every training to choose from —
    empty when the plan names none yet ("click edit … the training field is
    empty … get a dropdown of all the trainings and select the right one").
    The SSA intervention it was scheduled under is read-only wherever the
    Training Catalogue decides it, and follows the training chosen. For a
    group delivery, the officer's ceiling is carried with this session's own
    schools left out of what is already scheduled, so they are never counted
    twice.
    """
    import json

    from apps.activities.training_change import may_change_training, training_options
    from apps.activity_catalogue.training_intervention import (
        catalogue_sets_intervention,
    )
    from apps.planning import training_ceilings

    if not training_ceilings.is_training(a):
        return {}
    course_id = training_ceilings.course_id_of(a)
    course = a.training_course or (a.catalogue_item if course_id else None)
    delivery = training_ceilings.delivery_of(a)
    may_change = may_change_training(a)
    options = training_options(a) if may_change else []
    context = {
        "edit_training": {
            "id": course_id or "",
            "name": course.display_name if course else "",
            "delivery": training_ceilings.DELIVERY_LABELS.get(delivery, ""),
            "may_change": may_change,
            "options": options,
            "options_json": json.dumps(
                [
                    {
                        "id": option["id"],
                        "label": option["label"],
                        "ssaInterventionLabel": option["ssaInterventionLabel"],
                        "plannerChooses": option["plannerChooses"],
                    }
                    for option in options
                ]
            ),
            "intervention_locked": catalogue_sets_intervention(a),
        }
    }
    if delivery == training_ceilings.GROUP:
        context["edit_ceiling_json"] = json.dumps(
            training_ceilings.capacity(
                a.responsible_staff_id, course_id, a.fy, exclude_activity_id=a.id
            )
        )
    return context


def _edit_project_context(user, a) -> dict:
    """The Project field of the Edit drawer, and the interventions each
    project is linked to (owner, 2026-10-02: "if a user wants to change a
    project to another they should be able to select an intervention the new
    project is linked to ... from Christlike behaviour to General which is
    linked to Alumni").

    Project work lists its focus from its project's own links instead of all
    eight interventions. The focus the activity already carries stays on the
    list when its project no longer names it, so opening the drawer and
    saving a new date never rewrites it.
    """
    if not a.project_id:
        return {}
    import json

    from apps.activities import editing
    from apps.core.enums import SsaIntervention
    from apps.projects.models import GENERAL_INTERVENTION, Project

    current = Project.objects.filter(id=a.project_id).first()
    if current is None:
        return {}
    projects = editing.changeable_projects(a, user) or [current]
    in_project = (
        set(a.school.project_assignments.values_list("project_id", flat=True))
        if a.school_id
        else set()
    )
    links = {}
    for project in projects:
        options = [
            # General is "no SSA focus": the form posts it as a blank.
            {"code": "" if code == GENERAL_INTERVENTION else code, "label": label}
            for code, label in editing.project_interventions(project)
        ]
        if not any(option["code"] == "" for option in options):
            options.insert(0, {"code": "", "label": "None"})
        links[project.id] = options
    saved = a.focus_intervention or ""
    if saved and all(option["code"] != saved for option in links[current.id]):
        links[current.id].append(
            {"code": saved, "label": dict(SsaIntervention.choices).get(saved, saved)}
        )
    return {
        "edit_project": current,
        "edit_projects": [
            {
                "id": project.id,
                "name": project.name,
                "joins": project.id != current.id and project.id not in in_project,
            }
            for project in projects
        ],
        "may_change_project": len(projects) > 1,
        "project_links_json": json.dumps(links),
    }


@require_page_permission("my_plan")
def edit_activity_drawer_view(request, activity_id):
    """The Edit drawer for a planned activity (owner, 2026-10-02: "when one
    opens view activities, they should be able to click edit button which
    then allows them to edit the activities").

    Opens only for staff work that is still scheduled and that the reader
    may run; `apps.activities.editing.edit` repeats every check on save.
    """
    from apps.activities import editing

    a = get_object_or_404(
        Activity.objects.select_related("school", "cluster"),
        id=activity_id,
        deleted_at__isnull=True,
    )
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to edit this activity."
        )
    state = editing.edit_state(a, request.user)
    if state == "locked":
        return notice_fragment(editing.LOCKED_REASON)
    if state != "open":
        return notice_fragment(
            "This activity is not yours to edit, or it is no longer a "
            "scheduled plan."
        )
    return render(
        request,
        "partials/my_plan/edit_activity_drawer.html",
        _edit_drawer_context(request.user, a),
    )


@require_page_permission("my_plan")
def edit_activity_action(request, activity_id):
    """Save the Edit drawer through `apps.activities.editing.edit`."""
    from apps.activities import editing

    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to edit an activity outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to edit this activity."
        )
    if request.method != "POST":
        return local_redirect(f"/my-plan/{activity_id}")

    data = {"reason": request.POST.get("reason", "").strip()}
    for key, name in (
        ("scheduledDate", "scheduled_date"),
        ("endDate", "end_date"),
    ):
        value = request.POST.get(name, "").strip()
        if value:
            data[key] = value
    for key, name in (
        ("activityPurposeText", "activity_purpose_text"),
        ("expectedOutcome", "expected_outcome"),
        ("focusIntervention", "focus_intervention"),
        ("facilitatingPartnerId", "facilitating_partner_id"),
        ("schoolId", "school_id"),
        ("projectId", "project_id"),
        ("trainingCourseId", "training_course_id"),
    ):
        if name in request.POST:
            data[key] = request.POST.get(name, "").strip()
    # The checklist posts nothing when every box is unticked, so the form
    # says it was shown; an empty list is then a real answer, and refused.
    if request.POST.get("invited_schools_shown"):
        data["invitedSchoolIds"] = [
            s.strip() for s in request.POST.getlist("invited_school_ids") if s.strip()
        ]

    try:
        result = editing.edit(activity_id, data, request.user)
    except Exception as exc:
        audit_log(
            action="edit_activity",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason=str(exc),
        )
        return error_fragment(exc, action="Activity not saved", status=400)

    audit_log(
        action="edit_activity",
        subject_kind="Activity",
        subject_id=str(a.id),
        actor_id=str(request.user.id),
        actor_role=request.user.active_role,
        success=True,
        payload={
            "fields": sorted(key for key in data if key != "reason"),
            "reason": data["reason"],
            "result_activity_id": result.get("id"),
        },
    )
    if request.headers.get("HX-Request") == "true":
        response = HttpResponse("<script>window.location.reload();</script>")
        response["HX-Trigger"] = "close-drawer"
        return response
    return local_redirect(f"/my-plan/{result.get('id') or activity_id}")


@require_page_permission("my_plan")
def cancel_activity_drawer_view(request, activity_id):
    """CANCEL-01. The screen that calls work off.

    `apps.activities.services.cancel` has always existed and always worked —
    it withdraws the cost from every draft funding surface, reverses any
    milestone credit, deletes advances whose money has not moved, preserves
    those that have, and notifies the assigned partner. What it did not have
    was a way in. The only door was `POST /api/activities/<id>/cancel`,
    generated from the service by the `_action_view` factory, which no page,
    drawer or button in the platform posts to. So plans that changed could
    not be recorded as changed, and the three things staff do instead are all
    worse than cancelling: leave dead work in the plan for ever, complete a
    visit that never happened, or ask someone to edit the database.
    """
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")
    # A team member's activity is read, not called off (owner, 2026-10-08).
    read_only = _team_read_only(request, a)
    if read_only is not None:
        return read_only

    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES, AdvanceRequest

    # Cancelling funded work is allowed — `_assert_may_execute` already decides
    # who may cancel, and Journey 8 proves the disbursed advance survives it.
    # What the person needs to know before they confirm is that the money does
    # not go away with the activity: it still has to be accounted for and the
    # remainder returned. Told up front rather than discovered afterwards.
    # The other half of an in-school Training pair is cancelled with it, and
    # it is the visit that carries the pair's money.
    from apps.activities import pairs

    joined = pairs.joins(a, action=pairs.CANCEL)
    money_moved = AdvanceRequest.objects.filter(
        activity_id__in=[a.id, *([joined.id] if joined else [])],
        status__in=MONEY_MOVED_ADVANCE_STATUSES,
    ).exists()

    # A Partner's dated work: cancelling undoes the date, and the school waits
    # for the Partner again (partners.services.undo_assignment_scheduling).
    from apps.partners.dating_policy import partner_has_dated, partner_name_for
    from apps.partners.models import PartnerAssignment

    partner_keeps_school = (
        a.delivery_type == "partner"
        and partner_has_dated(a)
        and PartnerAssignment.objects.filter(
            scheduled_activity_id=a.id,
            status__in=PartnerAssignment.SCHEDULED_STATUSES,
        ).exists()
    )

    return render(
        request,
        "partials/my_plan/cancel_drawer.html",
        {
            "act": a,
            "money_moved": money_moved,
            "pair_joins": joined,
            "partner_keeps_school": partner_keeps_school,
            "partner_name": (
                partner_name_for(a.assigned_partner_id) if partner_keeps_school else ""
            ),
            "drawer_size": "sm",
        },
    )


@require_page_permission("my_plan")
def cancel_activity_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        audit_log(
            action="unauthorized_mutation_attempt",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=False,
            reason="User attempted to cancel an activity outside their scoped schools/ownership.",
        )
        return HttpResponseForbidden(
            "Access Denied: You do not have permission to cancel this activity."
        )

    if request.method == "POST":
        reason = request.POST.get("reason", "").strip()
        from apps.activities import pairs
        from apps.activities.pairs import cancel as cancel_activity

        joined = pairs.joins(a, action=pairs.CANCEL)
        try:
            cancel_activity(activity_id, {"reason": reason}, request.user)
        except Exception as exc:
            audit_log(
                action="cancel_activity",
                subject_kind="Activity",
                subject_id=str(a.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=False,
                reason=str(exc),
            )
            return error_fragment(exc, action="Cancellation Error", status=400)

        # Each record that was called off has its own line in the trail.
        for stopped in (a, joined):
            if stopped is None:
                continue
            audit_log(
                action="cancel_activity",
                subject_kind="Activity",
                subject_id=str(stopped.id),
                actor_id=str(request.user.id),
                actor_role=request.user.active_role,
                success=True,
                reason="Activity cancelled",
                payload={
                    "reason": reason,
                    **({"cancelled_with": str(a.id)} if stopped is not a else {}),
                },
            )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return local_redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def complete_activity_drawer_view(request, activity_id):
    return complete_drawer_view(request, activity_id)


@require_page_permission("my_plan")
def evidence_upload_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    evidence_list = evidence_records_for_activity(activity_id, request.user)
    context = {
        "act": a,
        "evidence_list": evidence_list,
        "drawer_size": "sm",
    }
    # The platform already knows what this activity type needs (the two-form
    # law: Visit Form or Training Attendance) — the drawer renders one slot
    # per required form instead of offering twelve kinds to guess from.
    from apps.core.scoping import resolve_partner_ids
    from apps.evidence.requirements import checklist as evidence_checklist

    context["evidence_checklist"] = evidence_checklist(a)
    # Partners are never asked for a Salesforce ID — IA records it for their
    # work at Confirm Salesforce Entry (§12).
    context["is_partner_viewer"] = bool(resolve_partner_ids(request.user))
    context["asks_salesforce_id"] = _asks_salesforce_id(request.user, a)

    # Look up Google Drive folder URL (from staff member or supervising Program Lead)
    google_drive_url = None
    staff_profile = getattr(request.user, "staff_profile", None)
    if staff_profile:
        if staff_profile.google_drive_folder_url:
            google_drive_url = staff_profile.google_drive_folder_url
        else:
            supervisor_link = staff_profile.supervisor_links.select_related(
                "supervisor"
            ).first()
            if supervisor_link and supervisor_link.supervisor.google_drive_folder_url:
                google_drive_url = supervisor_link.supervisor.google_drive_folder_url
    context["google_drive_folder_url"] = google_drive_url

    return render(request, "partials/my_plan/evidence_drawer.html", context)


#: The two governed forms: a staff upload of either carries its Salesforce ID.
GOVERNED_FORM_KINDS = ("visit_form", "attendance_form")


def _asks_salesforce_id(user, activity) -> bool:
    """Whether the upload drawer carries the Salesforce ID: on staff work,
    for staff. Partner work never (owner, 2026-09-26): the partner uploads,
    and staff complete it with the Salesforce ID drawer."""
    from apps.core.scoping import resolve_partner_ids

    return activity.delivery_type != "partner" and not resolve_partner_ids(user)


def _posted_evidence(request, activity) -> list[tuple[str, list]]:
    """[(kind, files)] posted by the upload drawer: each form's pages as
    `evidence_file_<kind>`, in form order; or one form as `evidence_file`
    with `evidence_kind` (older drawers, and requests the field outbox saved
    before this change)."""
    from apps.evidence.services import VALID_KINDS

    uploads = []
    prefix = "evidence_file_"
    for key in request.FILES:
        kind = key[len(prefix) :] if key.startswith(prefix) else ""
        files = request.FILES.getlist(key) if kind in VALID_KINDS else []
        if files:
            uploads.append((kind, files))
    legacy = request.FILES.getlist("evidence_file")
    if legacy:
        # What the person selected, else what this activity still needs, else
        # the file's shape. Inference alone can only say "pdf" or "photo",
        # which no requirement asks for.
        kind = resolve_evidence_kind(
            legacy[0], activity=activity, asserted=request.POST.get("evidence_kind")
        )
        uploads.append((kind, legacy))
    return uploads


@require_page_permission("my_plan")
def evidence_upload_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        # One Submit saves the drawer (owner, 2026-09-26): each form's pages
        # and, on staff work, the Salesforce ID — so the Evidence and
        # Salesforce ID columns fill in together. The ID is saved first: if
        # an upload then fails, submitting again does not upload twice.
        from apps.core.exceptions import BadRequest

        uploads = _posted_evidence(request, a)
        asks_sf = _asks_salesforce_id(request.user, a)
        sf_id = (request.POST.get("salesforce_id") or "").strip() if asks_sf else ""
        new_sf = bool(sf_id) and sf_id != (a.salesforce_activity_id or "")
        try:
            if not uploads and not sf_id:
                raise BadRequest(
                    "Add the form (take a photo or choose files)"
                    + (" or enter the Salesforce ID" if asks_sf else "")
                    + ", then Submit."
                )
            # A STAFF upload of a governed form carries its Salesforce entry —
            # required (owner, 2026-08-19). Partners are exempt: staff record
            # theirs in the Salesforce ID drawer, completing the work.
            if (
                asks_sf
                and not sf_id
                and not a.salesforce_activity_id
                and any(kind in GOVERNED_FORM_KINDS for kind, _ in uploads)
            ):
                raise BadRequest(
                    "Enter the Salesforce ID with your form upload — it "
                    "is required for staff-delivered work."
                )
            if new_sf:
                if a.ia_verification_status == "confirmed":
                    raise BadRequest(
                        "The Salesforce ID is locked after IA confirmation. Ask "
                        "IA to return the activity to make a correction."
                    )
                # reserve_salesforce_id is the single write path: format,
                # uniqueness and idempotency all hold here too.
                from apps.activities.services import sf_kind_for_activity

                kind = sf_kind_for_activity(a)
                if kind is not None:
                    reserve_salesforce_id(
                        activity=a,
                        raw_value=sf_id,
                        kind=kind,
                        principal=request.user,
                        entry_source=ENTRY_SOURCE_STAFF_SELF,
                    )
            for kind, files in uploads:
                # One file, or the pages of one form — photographed or chosen
                # together — merged into one PDF (owner, 2026-09-26;
                # apps.evidence.services.record_pages_upload).
                record_pages_upload(
                    principal=request.user,
                    activity_id=activity_id,
                    kind=kind,
                    files=files,
                )
                audit_log(
                    action="upload_evidence",
                    subject_kind="Activity",
                    subject_id=str(a.id),
                    actor_id=str(request.user.id),
                    actor_role=request.user.active_role,
                    success=True,
                    reason="Evidence file uploaded",
                )
        except DuplicateSalesforceId as e:
            return error_fragment(e, status=409)
        except Exception as e:
            return error_fragment(e, status=400)

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return local_redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def salesforce_id_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")
    # This drawer is for completing partner work (owner, 2026-09-26). Staff
    # enter the Salesforce ID for their own work in the upload drawer, with
    # the form, so a link here for staff work opens that drawer.
    if a.delivery_type != "partner":
        return evidence_upload_drawer_view(request, activity_id)

    context = {
        "act": a,
        "drawer_size": "sm",
        # Says what the button will do: on partner work awaiting verification,
        # recording the ID completes the activity (owner, 2026-09-12).
        "confirms_partner_work": (
            a.delivery_type == "partner"
            and a.status == "awaiting_ia_verification"
            and not is_partner_ssa_support_activity(a)
            and RolePermissionService.can_confirm_partner_activity(request.user, a)
        ),
    }
    return render(request, "partials/my_plan/salesforce_id_drawer.html", context)


@require_page_permission("my_plan")
def salesforce_id_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a, allow_confirmer=True)
    if forbidden:
        return forbidden

    if request.method == "POST":
        salesforce_id = request.POST.get("salesforce_id", "").strip()
        if not salesforce_id:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: SF ID cannot be blank.</div>',
                status=400,
            )

        if a.ia_verification_status == "confirmed":
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Salesforce ID is locked after IA confirmation. Ask IA to return the activity to make a correction.</div>',
                status=400,
            )

        # For partner work the Salesforce entry IS the completion: the partner
        # uploaded its form, and whoever records the entry — Impact Assessment
        # or the monitoring staff member — completes the activity with it
        # (owner, 2026-09-12). SSA Support is the exception, because its
        # completion also carries the eight scores and pupil enrolment, so it
        # keeps its own drawer and this door points there.
        if a.delivery_type == "partner" and a.status == "awaiting_ia_verification":
            if is_partner_ssa_support_activity(a):
                return HttpResponse(
                    '<div class="p-3 bg-amber-50 text-amber-800 rounded-surface '
                    'text-[12px] font-bold">This is SSA Support — complete it from '
                    "the Complete drawer, which records the scores and the "
                    "enrolment with the Salesforce ID.</div>",
                    status=400,
                )
            try:
                ia_confirm(
                    a.id,
                    {
                        "salesforceId": salesforce_id,
                        "verificationNote": request.POST.get(
                            "verification_note", ""
                        ).strip(),
                    },
                    request.user,
                )
            except Exception as e:
                return error_fragment(e, status=400)
            if request.headers.get("HX-Request") == "true":
                response = HttpResponse("<script>window.location.reload();</script>")
                response["HX-Trigger"] = "close-drawer"
                return response
            return local_redirect(f"/my-plan/{activity_id}")

        kind = sf_kind(a.activity_type)
        entry_source = (
            ENTRY_SOURCE_MANAGING_STAFF
            if a.delivery_type == "partner"
            else ENTRY_SOURCE_STAFF_SELF
        )
        try:
            reserve_salesforce_id(
                activity=a,
                raw_value=salesforce_id,
                kind=kind,
                principal=request.user,
                entry_source=entry_source,
            )
        except DuplicateSalesforceId as e:
            return error_fragment(e, status=409)
        except Exception as e:
            return error_fragment(e, status=400)

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return local_redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def submit_for_review_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    # Build Checklist
    has_evidence = a.evidence_status in {"uploaded", "accepted"}
    has_sf_id = bool(a.salesforce_activity_id)

    ssa_required = a.activity_type in [
        "baseline_ssa_visit",
        "school_visit_ssa_collection",
        "partner_ssa_collection",
        "cluster_training_ssa_collection",
    ]
    has_ssa = False
    if ssa_required:
        if a.school and a.school.current_fy_ssa_status == "done":
            has_ssa = True

    has_participants = True
    if a.activity_type in [
        "training",
        "in_school_training",
        "cluster_training",
        "cluster_meeting",
        "core_training",
    ]:
        has_participants = (a.teachers_attended or 0) + (a.leaders_attended or 0) > 0

    all_ready = (
        has_evidence
        and has_sf_id
        and (not ssa_required or has_ssa)
        and has_participants
    )

    context = {
        "act": a,
        "has_evidence": has_evidence,
        "has_sf_id": has_sf_id,
        "ssa_required": ssa_required,
        "has_ssa": has_ssa,
        "has_participants": has_participants,
        "all_ready": all_ready,
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/submit_drawer.html", context)


@require_page_permission("my_plan")
def submit_for_review_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        try:
            submit_for_review(activity_id, request.user)
        except Exception as exc:
            return error_fragment(exc, action="Submission Error", status=400)

        audit_log(
            action="submit_for_review",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="Activity submitted for PL/IA review",
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return local_redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def activity_timeline_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    logs = AuditLog.objects.filter(
        subject_kind="Activity", subject_id=str(a.id)
    ).order_by("-created_at")
    context = {
        "act": a,
        "logs": logs,
        "drawer_size": "md",
    }
    return render(request, "partials/my_plan/timeline_drawer.html", context)


@require_page_permission("my_plan")
def evidence_packet_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    evidence_list = evidence_records_for_activity(activity_id, request.user)
    logs = AuditLog.objects.filter(
        subject_kind="Activity", subject_id=str(a.id)
    ).order_by("-created_at")

    context = {
        "act": a,
        "evidence_list": evidence_list,
        "logs": logs,
    }
    return render(request, "pages/my_plan/evidence_packet.html", context)


@require_page_permission("my_plan")
def attendance_upload_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    cluster_schools = []
    if a.cluster:
        cluster_schools = (
            active_schools().filter(cluster_id=a.cluster_id).order_by("name")
        )

    context = {
        "act": a,
        "drawer_size": "sm",
        "cluster_schools": cluster_schools,
    }
    return render(request, "partials/my_plan/attendance_drawer.html", context)


@require_page_permission("my_plan")
def attendance_upload_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    forbidden = _forbid_staff_on_partner_activity(request, a)
    if forbidden:
        return forbidden

    if request.method == "POST":
        teachers = request.POST.get("teachers_attended", 0)
        leaders = request.POST.get("leaders_attended", 0)
        attendance_file = request.FILES.get("attendance_file")
        notes = request.POST.get("notes", "").strip()
        attended_schools = request.POST.getlist("attended_schools")

        try:
            record_attendance(
                activity_id,
                {
                    "teachersAttended": teachers,
                    "leadersAttended": leaders,
                    "attendedSchoolIds": attended_schools,
                },
                request.user,
            )
        except Exception as exc:
            return error_fragment(exc, action="Attendance Error", status=400)

        # A school from outside the cluster that turned up. Recorded against
        # the canonical school, so the training lands on its profile and earns
        # the same follow-up a member would.
        guest_school_id = (request.POST.get("guest_school_id") or "").strip()
        if guest_school_id:
            from apps.activities.cluster_attendance import add_guest_school
            from apps.core.exceptions import BadRequest
            from apps.schools.models import School

            def _count(key):
                raw = (request.POST.get(key) or "").strip()
                return int(raw) if raw.isdigit() else None

            guest = School.objects.filter(
                school_id=guest_school_id, deleted_at__isnull=True
            ).first()
            if guest is None:
                return error_fragment(
                    BadRequest(
                        f"No school in the directory has the ID "
                        f"'{guest_school_id}'. Add the school first — it needs "
                        f"its Salesforce ID before work can be recorded "
                        f"against it."
                    ),
                    action="Attendance Error",
                    status=400,
                )
            try:
                add_guest_school(
                    a,
                    guest.id,
                    teachers=_count("guest_teachers"),
                    leaders=_count("guest_leaders"),
                    other=_count("guest_other"),
                    actor_id=str(request.user.id),
                )
            except Exception as exc:
                return error_fragment(exc, action="Attendance Error", status=400)

        if attendance_file:
            # The governed Training Attendance form is PDF-only; a photographed
            # sheet is welcome but is recorded as a supplementary PHOTO — it
            # does not satisfy the form requirement, the PDF does. Several
            # pages together are merged into one PDF (owner, 2026-09-26), and
            # that PDF is the form.
            attendance_files = request.FILES.getlist("attendance_file")
            is_pdf = len(attendance_files) > 1 or (
                attendance_file.name or ""
            ).lower().endswith(".pdf")
            record_pages_upload(
                principal=request.user,
                activity_id=activity_id,
                kind="attendance_form" if is_pdf else "photo",
                files=attendance_files or [attendance_file],
            )

        audit_log(
            action="upload_attendance",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="Attendance file and headcount uploaded",
            payload={"teachers": teachers, "leaders": leaders, "notes": notes},
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return local_redirect(f"/my-plan/{activity_id}")


@require_page_permission("my_plan")
def ssa_evidence_upload_drawer_view(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    context = {
        "act": a,
        "interventions": SsaIntervention.choices,
        "drawer_size": "sm",
    }
    return render(request, "partials/my_plan/ssa_upload_drawer.html", context)


@require_page_permission("my_plan")
def ssa_evidence_upload_action(request, activity_id):
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    if not RolePermissionService.can_view_record(request.user, a):
        return HttpResponseForbidden("Access Denied.")

    if request.method == "POST":
        ssa_file = request.FILES.get("ssa_file")
        notes = request.POST.get("notes", "").strip()

        # Parse scores if provided — derived from the canonical enum so the
        # field names always match the SsaScore.intervention choices.
        score_fields = [f"score_{code}" for code, _label in SsaIntervention.choices]
        scores_list = []
        has_scores = False

        for sf in score_fields:
            val = request.POST.get(sf, "").strip()
            if val:
                has_scores = True
                try:
                    scores_list.append(
                        {"intervention": sf.replace("score_", ""), "score": float(val)}
                    )
                except ValueError:
                    return HttpResponse(
                        '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: Score must be numeric</div>',
                        status=400,
                    )

        if has_scores:
            if len(scores_list) < 8:
                return HttpResponse(
                    '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: All 8 scores must be provided if manual entry is selected.</div>',
                    status=400,
                )

            from apps.core.exceptions import BadRequest
            from apps.ssa.services import upload as upload_ssa
            from apps.ssa.services import visit_assessment_date

            # Dated by the visit and linked to it; pending until a different
            # verifier confirms (IA review, 2026-09-13). A refusal is shown in
            # the drawer rather than escaping as an error envelope.
            try:
                upload_ssa(
                    {
                        "schoolId": a.school.school_id,
                        "dateOfSsa": visit_assessment_date(a).isoformat(),
                        "scores": scores_list,
                        "collectorType": "partner"
                        if a.delivery_type == "partner"
                        else "staff",
                        "collectedByPartnerId": a.assigned_partner_id,
                        "sourceActivityId": a.id,
                    },
                    request.user,
                )
            except BadRequest as exc:
                return notice_fragment(str(getattr(exc, "detail", exc)))

        if ssa_file:
            record_upload(
                principal=request.user,
                activity_id=activity_id,
                kind="assessment_form",
                file_obj=ssa_file,
            )

        audit_log(
            action="upload_ssa",
            subject_kind="Activity",
            subject_id=str(a.id),
            actor_id=str(request.user.id),
            actor_role=request.user.active_role,
            success=True,
            reason="SSA scores or form uploaded",
            payload={"notes": notes},
        )

        if request.headers.get("HX-Request") == "true":
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response

    return local_redirect(f"/my-plan/{activity_id}")


@require_page_permission("evidence_center")
def evidence_center_view(request):
    """Scoped, URL-addressable Evidence Center.

    The page previously loaded every Activity into Python and passed raw model
    objects into a table that expected dictionaries, producing blank actions.
    Filtering, counts and pagination now stay in SQL and every rendered action
    is an explicit, non-empty route.
    """
    from apps.accounts.models import StaffProfile
    from apps.core.scoping import resolve_user_scope
    from apps.partners.models import Partner

    from apps.core.activity_types import NOT_IN_PLAN_ACTIVITY_STATUSES

    scope = resolve_user_scope(request.user)
    # No evidence is owed for work that was called off, so it is on none of
    # these lists and in none of their counts (owner, 2026-10-08).
    activities = Activity.objects.filter(deleted_at__isnull=True).exclude(
        status__in=NOT_IN_PLAN_ACTIVITY_STATUSES
    )
    if scope.can_view_summary_only:
        activities = activities.none()
    elif not scope.country_scope:
        if scope.partner_ids:
            activities = activities.filter(assigned_partner_id__in=scope.partner_ids)
        elif scope.school_ids:
            staff_ids = [
                *scope.staff_ids,
                *scope.supervised_staff_ids,
                request.user.user_id,
            ]
            activities = activities.filter(
                Q(school_id__in=scope.school_ids)
                | Q(responsible_staff_id__in=[value for value in staff_ids if value])
            )
        else:
            staff_ids = [*scope.staff_ids, request.user.user_id]
            activities = activities.filter(
                responsible_staff_id__in=[value for value in staff_ids if value]
            )

    submitted_statuses = (
        "submitted_to_pl",
        "awaiting_ia_verification",
        "ia_verified",
        "accountant_confirmed",
    )
    returned_statuses = ("returned", "returned_by_pl", "returned_by_ia")
    tab_filters = {
        "pending": Q(status__in=COMPLETED_WORK_STATUSES, evidence_status="none"),
        "sf_missing": Q(evidence_status="uploaded")
        & (Q(salesforce_activity_id__isnull=True) | Q(salesforce_activity_id="")),
        "submitted": Q(status__in=submitted_statuses),
        "returned": Q(status__in=returned_statuses),
        "ia_pending": Q(
            status="awaiting_ia_verification", ia_verification_status="pending"
        ),
        "verified": Q(ia_verification_status="confirmed"),
        "partner_ev": Q(delivery_type="partner"),
    }
    tab_labels = {
        "pending": "Evidence Pending",
        "sf_missing": "SF ID Missing",
        "submitted": "Submitted",
        "returned": "Returned",
        "ia_pending": "IA Pending",
        "verified": "Verified",
        "partner_ev": "Partner Work",
    }
    active_tab = request.GET.get("tab", "pending")
    if active_tab not in tab_filters:
        active_tab = "pending"
    search_query = request.GET.get("q", "").strip()[:100]

    aggregate_fields = {
        f"{key}_count": Count("id", filter=condition)
        for key, condition in tab_filters.items()
    }
    count_values = activities.aggregate(**aggregate_fields)
    tabs = [
        {
            "key": key,
            "label": tab_labels[key],
            "count": count_values[f"{key}_count"],
        }
        for key in tab_filters
    ]

    filtered = activities.filter(tab_filters[active_tab])
    if search_query:
        filtered = filtered.filter(
            Q(school__name__icontains=search_query)
            | Q(school__school_id__icontains=search_query)
            | Q(cluster__name__icontains=search_query)
            | Q(salesforce_activity_id__icontains=search_query)
            | Q(activity_type__icontains=search_query)
        )
    page_obj = Paginator(
        filtered.select_related(
            "school",
            "school__district",
            "cluster",
            "cluster__district",
        ).order_by("-updated_at", "-id"),
        50,
    ).get_page(request.GET.get("page"))

    owner_ids = {
        value
        for activity in page_obj.object_list
        for value in (activity.responsible_staff_id, activity.assigned_partner_id)
        if value
    }
    owners = {
        profile.id: profile.user.name
        for profile in StaffProfile.objects.filter(id__in=owner_ids).select_related(
            "user"
        )
    }
    owners.update(
        {
            partner.id: partner.name
            for partner in Partner.objects.filter(id__in=owner_ids)
        }
    )

    rows = []
    for activity in page_obj.object_list:
        if active_tab == "pending":
            action = {
                "label": "Upload evidence",
                "url": f"/activities/{activity.id}/evidence",
                "drawer": True,
            }
        elif active_tab == "sf_missing":
            # Staff enter their own work's ID in the upload drawer; the
            # Salesforce ID drawer is for completing partner work.
            action = {
                "label": "Enter SF ID",
                "url": (
                    f"/activities/{activity.id}/salesforce-id"
                    if activity.delivery_type == "partner"
                    else f"/activities/{activity.id}/evidence"
                ),
                "drawer": True,
            }
        elif active_tab == "verified":
            action = {
                "label": "View evidence packet",
                "url": f"/activities/{activity.id}/evidence/detail",
                "drawer": False,
            }
        else:
            action = {
                "label": "View details",
                "url": f"/my-plan/{activity.id}",
                "drawer": False,
            }
        location = activity.school or activity.cluster
        district = ""
        if activity.school and activity.school.district:
            district = activity.school.district.name
        elif activity.cluster and activity.cluster.district:
            district = activity.cluster.district.name
        rows.append(
            {
                "id": activity.id,
                "activity_type": activity.get_activity_type_display(),
                "location": getattr(location, "name", "No location assigned"),
                "location_id": getattr(activity.school, "school_id", ""),
                "district": district,
                "owner": owners.get(
                    activity.assigned_partner_id
                    if activity.delivery_type == "partner"
                    else activity.responsible_staff_id,
                    "Unassigned",
                ),
                "delivery": activity.get_delivery_type_display(),
                "evidence": activity.get_evidence_status_display(),
                "verification": activity.get_ia_verification_status_display(),
                "status": activity.get_status_display(),
                "salesforce_id": activity.salesforce_activity_id,
                "updated_at": activity.updated_at,
                "action": action,
            }
        )

    context = {
        "active_tab": active_tab,
        "tabs": tabs,
        "rows": rows,
        "page_obj": page_obj,
        "search_query": search_query,
        # The query above has always been read and applied; the page simply
        # never rendered a control to produce it, so the top bar showed the
        # generic global form and this search was unreachable. Carries the tab
        # so a query narrows the tab in view rather than resetting to pending.
        "topbar_search": {
            "placeholder": "Search evidence…",
            "label": "Search evidence by school, School ID, cluster or Salesforce ID",
            "name": "q",
            "value": search_query,
            "hx_get": "/evidence/",
            "hx_target": "#evidence-workspace",
            "hx_trigger": "keyup changed delay:250ms, search",
            "hidden": [{"name": "tab", "value": active_tab}],
        },
    }
    template = (
        "partials/evidence/workspace.html"
        if request.headers.get("HX-Request") == "true"
        else "pages/evidence/index.html"
    )
    return render(request, template, context)


@require_page_permission("evidence_center")
def returned_evidence_view(request):
    """Keep saved links working through the scoped, paginated evidence workspace."""
    return redirect("/evidence/?tab=returned")


@require_page_permission("disbursements")
def accounts_activity_evidence_view(request, activity_id):
    """Read-only view of activity evidence for Accountants. Gated by the
    finance page permission — the previous "my_plan" gate excluded the
    Accountant role this page exists for. Object-level finance scoping
    (Accountant reaches only money-movement activities) is enforced inside
    evidence_records_for_activity."""
    a = get_object_or_404(Activity, id=activity_id, deleted_at__isnull=True)
    evidence_list = evidence_records_for_activity(activity_id, request.user)

    context = {
        "act": a,
        "evidence_list": evidence_list,
    }
    return render(request, "pages/accounts/activity_evidence.html", context)


@require_page_permission("my_plan")
def request_budget_amendment_action(request, activity_id):
    """POST: staff requests a date change for a finance-locked activity —
    the sanctioned Budget Amendment path the cost-snapshot lock points to."""
    from apps.budget.amendment_service import request_amendment

    if request.method == "POST":
        try:
            amendment = request_amendment(
                activity_id,
                {
                    "newDate": request.POST.get("new_date", "").strip(),
                    "reason": request.POST.get("reason", "").strip(),
                },
                request.user,
            )
            messages.success(
                request,
                f"Budget amendment submitted for review (move to {amendment.new_date}). "
                "The accountant will apply it without touching the locked cost snapshot.",
            )
        except Exception as exc:
            messages.error(request, f"Amendment request failed: {exc}")
    return redirect("/my-plan")


@require_page_permission("my_plan")
def day_package_view(request):
    """The offline day package (roadmap Phase 3): one JSON document carrying
    the caller's field day — route-grouped activities, school locations,
    evidence checklists, participant plans — for the client to cache before
    travel. Own work only; scope comes from the same resolver as My Plan."""

    from django.http import JsonResponse

    from apps.my_plan.day_package import build_day_package

    raw_date = (request.GET.get("date") or "").strip()
    try:
        target = date.fromisoformat(raw_date) if raw_date else None
    except ValueError:
        return JsonResponse({"error": "date must be YYYY-MM-DD"}, status=400)
    return JsonResponse(build_day_package(request.user, day=target))
