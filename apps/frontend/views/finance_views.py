"""
GROUP 2 — Finance & Budget Views
Disbursements, Budget Overview, Cost Catalogue, Fund Requests list
"""

from django.shortcuts import render, redirect, get_object_or_404
from apps.core.permissions import render_access_denied, require_page_permission
from django.contrib import messages
from django.utils import timezone
from django.http import HttpResponse

from apps.fund_requests.models import (
    WeeklyFundRequest,
    AdvanceRequest,
    AdvanceRequestStatus,
)
from apps.budget.allocation_service import VISIT_TYPES
from apps.budget.models import CostCatalogue, CostSetting
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.fy import get_operational_fy
from apps.fund_requests.weekly_service import disburse as disburse_weekly
from apps.fund_requests.advance_service import reimburse as process_reimburse
from apps.fund_requests.pl_approval_service import _ugx


@require_page_permission("fund_requests")
def fund_requests_list_view(request):
    """All fund requests list — redirect to weekly."""
    return redirect("/fund-requests/weekly")


def _disb_filters(request):
    return {
        k: request.GET.get(k)
        for k in ("fy", "month", "status", "q", "item")
        if request.GET.get(k)
    }


@require_page_permission("disbursements")
def disbursements_view(request):
    """Fund Disbursement Dashboard — the Accountant's finance execution center.
    Receives only approved, valid, scheduled, costed fund requests; the
    accountant disburses, holds, returns, and tracks reconciliation."""
    from apps.fund_requests.disbursement_dashboard_service import (
        get_disbursement_dashboard,
    )

    ctx = get_disbursement_dashboard(request.user, _disb_filters(request))
    ctx["status_filter"] = request.GET.get("status", "")
    ctx["q"] = request.GET.get("q", "")
    if request.headers.get("HX-Target") == "disb-root":
        return render(request, "partials/disbursements/root.html", ctx)
    return render(request, "pages/disbursements/index.html", ctx)


@require_page_permission("disbursements")
def disbursement_detail_view(request):
    """Center panel only — a light HTMX swap so clicking a queue item instantly
    switches the funding breakdown."""
    from apps.fund_requests.disbursement_dashboard_service import (
        get_disbursement_dashboard,
    )

    ctx = get_disbursement_dashboard(request.user, _disb_filters(request))
    return render(request, "partials/disbursements/detail.html", ctx)


@require_page_permission("disbursements")
def disbursement_drawer_view(request):
    """Disburse / Hold / Return drawers for monthly fund plans."""
    from apps.fund_requests.disbursement_dashboard_service import (
        get_disbursement_dashboard,
    )

    dtype = request.GET.get("type")
    template = {
        "disburse": "partials/disbursements/disburse_drawer.html",
        "hold": "partials/disbursements/hold_drawer.html",
        "return": "partials/disbursements/return_drawer.html",
    }.get(dtype)
    if not template:
        return HttpResponse("Unknown drawer", status=400)
    ctx = get_disbursement_dashboard(request.user, _disb_filters(request))
    return render(request, template, ctx)


@require_page_permission("disbursements")
def disbursement_action_view(request):
    """Disburse / Hold / Release / Return a monthly fund plan, then re-render
    the dashboard root."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests import disbursement_dashboard_service as svc

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    action = request.POST.get("action")
    fr_id = request.POST.get("fund_request_id")
    data = {
        "amount": request.POST.get("amount"),
        "method": request.POST.get("method"),
        "reference": request.POST.get("reference"),
        "reason": request.POST.get("reason"),
        "comment": request.POST.get("comment"),
    }
    error = ok = None
    try:
        if action == "disburse":
            fr = svc.disburse(request.user, fr_id, data)
            ok = f"Funds disbursed for {fr.period_key} — the requester has been asked to confirm receipt."
        elif action == "hold":
            fr = svc.hold(request.user, fr_id, data)
            ok = f"{fr.period_key} placed on hold."
        elif action == "release":
            fr = svc.release(request.user, fr_id)
            ok = f"{fr.period_key} released back to the disbursement queue."
        elif action == "return":
            fr = svc.return_item(request.user, fr_id, data)
            ok = f"{fr.period_key} returned for correction."
        else:
            error = "Unknown action."
    except (BadRequest, Forbidden) as e:
        error = str(e)

    ctx = svc.get_disbursement_dashboard(
        request.user,
        {
            "fy": request.POST.get("fy"),
            "month": request.POST.get("month"),
            "item": request.POST.get("item"),
        },
    )
    ctx["status_filter"] = ""
    ctx["action_error"] = error
    ctx["action_ok"] = ok
    resp = render(request, "partials/disbursements/root.html", ctx)
    resp["HX-Trigger"] = "close-drawer"
    return resp


@require_page_permission("fund_requests")
def fund_receipt_confirm_action(request):
    """The requester confirms disbursed funds arrived (auto-closes their
    Confirm-Receipt To-Do)."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.fund_requests.disbursement_dashboard_service import confirm_receipt

    if request.method == "POST":
        try:
            fr = confirm_receipt(request.user, request.POST.get("fund_request_id"))
            messages.success(request, f"Receipt confirmed for {fr.period_key}.")
        except (BadRequest, Forbidden) as e:
            messages.error(request, str(e))
    return redirect(request.POST.get("next") or "/fund-requests/weekly")


@require_page_permission("disbursements")
def finance_action_drawer_view(request):
    """GET to render the floating drawer for various finance actions."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    action = request.GET.get("action")
    request_id = request.GET.get("request_id")
    activity_id = request.GET.get("activity_id")
    advance_id = request.GET.get("advance_id")

    item = None
    if request_id:
        # Load WeeklyFundRequest
        wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
        from apps.fund_requests.weekly_service import _serialize_request

        item = _serialize_request(wfr, include_lines=True)
        # Format field names to match template expectations
        item["accountedAmount"] = wfr.accounted_amount
        item["returnedAmount"] = wfr.returned_amount
        item["accountabilityNetsuiteId"] = wfr.accountability_netsuite_id
        if action == "confirm_accountability":
            # Accountability lives on the child advances — the responsible
            # user submitted spend/returned/variance + NetSuite Code there.
            pending = list(
                AdvanceRequest.objects.filter(
                    budget_line__weekly_request_lines__weekly_fund_request=wfr,
                    status="accountability_pending",
                ).select_related("budget_line")
            )
            item["pendingAdvances"] = [
                {
                    "label": a.budget_line.label,
                    "netsuiteId": a.accountability_netsuite_id,
                    "accounted": a.accounted_amount or 0,
                    "returned": a.returned_amount or 0,
                    "disbursed": a.disbursed_amount or a.amount or 0,
                    "varianceNote": a.last_note,
                }
                for a in pending
            ]
            item["accountedAmount"] = sum(a.accounted_amount or 0 for a in pending)
            item["returnedAmount"] = sum(a.returned_amount or 0 for a in pending)
            item["disbursedTotal"] = sum(
                (a.disbursed_amount or a.amount or 0) for a in pending
            )
            item["accountabilityNetsuiteId"] = ", ".join(
                sorted(
                    {
                        a.accountability_netsuite_id
                        for a in pending
                        if a.accountability_netsuite_id
                    }
                )
            )
            item["varianceNote"] = next(
                (a.last_note for a in pending if a.last_note), None
            )
    elif activity_id:
        # Load Activity
        act = get_object_or_404(Activity, id=activity_id)
        from apps.activities.services import _serialize

        item = _serialize(act)
    elif advance_id:
        # Load AdvanceRequest
        adv = get_object_or_404(AdvanceRequest, id=advance_id)
        from apps.fund_requests.advance_service import _serialize as serialize_adv

        item = serialize_adv(adv)

    context = {
        "action": action,
        "item": item,
        "drawer_size": "md",
    }
    return render(request, "partials/finance/finance_action_drawer.html", context)


@require_page_permission("disbursements")
def disburse_advance_action(request):
    """POST to disburse weekly advance."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        request_id = request.POST.get("request_id")
        amount = request.POST.get("amount")
        method = request.POST.get("method", "mobile_money")
        reference = request.POST.get("reference", "").strip()

        payload = {
            "method": method,
            "reference": reference,
        }

        try:
            if amount:
                payload["amount"] = int(amount)
            disburse_weekly(request_id, payload, request.user)
            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
                status=400,
            )


@require_page_permission("disbursements")
def clear_partner_payment_action(request):
    """POST to clear partner payment."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        activity_id = request.POST.get("activity_id")
        netsuite_id = request.POST.get("netsuite_id", "").strip()
        amount = request.POST.get("amount")
        reference = request.POST.get("reference", "").strip()

        activity = get_object_or_404(Activity, id=activity_id)

        try:
            # Route through the canonical service rather than re-implementing
            # the payout inline. The hand-rolled version enforced only the
            # blocked-reason check and a non-empty NetSuite ID — it had no
            # cross-channel guard (so an activity whose staff advance had
            # already released money could ALSO be partner-paid for the same
            # cost lines), no idempotency check (a replayed POST re-stamped the
            # activity and re-wrote the NetSuite record), wrote no
            # PartnerPayment ledger row, and wrote no FinanceAuditLog entry —
            # which meant its payouts were invisible to the very guard that
            # protects the other channel.
            from apps.fund_requests.finance_services import PartnerPaymentService

            partner_name = ""
            if activity.assigned_partner_id:
                from apps.partners.models import Partner

                partner_name = (
                    Partner.objects.filter(id=activity.assigned_partner_id)
                    .values_list("name", flat=True)
                    .first()
                    or ""
                )

            try:
                paid_amount = int(amount or 0)
            except (TypeError, ValueError):
                paid_amount = 0

            PartnerPaymentService.pay_partner(
                activity=activity,
                partner_name=partner_name,
                amount=paid_amount,
                method=request.POST.get("method", "") or "bank_transfer",
                reference=reference,
                user_id=request.user.user_id,
                netsuite_id=netsuite_id,
            )

            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
                status=400,
            )


@require_page_permission("disbursements")
def process_reimbursement_action(request):
    """POST to disburse self-funded reimbursement."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        advance_id = request.POST.get("advance_id")
        netsuite_id = request.POST.get("netsuite_id", "").strip()
        amount = request.POST.get("amount")
        reference = request.POST.get("reference", "").strip()

        payload = {
            "method": "bank_transfer",
            "reference": reference,
            "netsuiteId": netsuite_id,
        }
        try:
            if amount:
                payload["amount"] = int(amount)
            adv = get_object_or_404(AdvanceRequest, id=advance_id)
            adv.accountability_netsuite_id = netsuite_id
            adv.save(update_fields=["accountability_netsuite_id"])

            process_reimburse(advance_id, payload, request.user)

            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
                status=400,
            )


@require_page_permission("disbursements")
def confirm_accountability_action(request):
    """POST — Accountant clears SUBMITTED accountability on a weekly request.

    The NetSuite Code and amounts were entered by the responsible user at
    submission (advance_service.submit_accountability); the Accountant only
    reviews. Each advance clears through approve_accountability, which
    enforces the hard gates: NetSuite Code present + IA verification done.
    The weekly request itself closes to "accounted" only when every one of
    its linked advances is accounted."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        request_id = request.POST.get("request_id")

        try:
            from django.db import transaction

            from apps.fund_requests import advance_service

            with transaction.atomic():
                wfr = get_object_or_404(WeeklyFundRequest, id=request_id)
                advances = [
                    adv
                    for line in wfr.lines.select_related("activity_budget_line")
                    for adv in [line.activity_budget_line.advance_requests.first()]
                    if adv
                ]
                pending = [
                    a
                    for a in advances
                    if a.status == AdvanceRequestStatus.ACCOUNTABILITY_PENDING
                ]
                if not pending:
                    return HttpResponse(
                        '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">No submitted accountability awaits review on this request.</div>',
                        status=400,
                    )
                for adv in pending:
                    # An under-spend's returned amount is accountant-verified
                    # as part of this single "Confirm Accountability
                    # Clearance" click (mandate §11) — a genuine, separately
                    # audited verify_return() call, not a silent trust of the
                    # employee's self-declared figure.
                    if adv.returned_amount:
                        advance_service.verify_return(
                            adv.id, {"reference": ""}, request.user
                        )
                    advance_service.approve_accountability(adv.id, request.user)

                # Close the weekly request once the whole set has reached a
                # terminal cleared state — ACCOUNTED (exact-spend/verified
                # return) or REIMBURSED (an over-spent advance's
                # reimbursement was disbursed and receipt-confirmed).
                # REIMBURSEMENT_SUBMITTED/_DISBURSED are legitimate
                # in-progress states that must NOT close the request yet.
                for adv in advances:
                    adv.refresh_from_db()
                if all(
                    a.status
                    in (
                        AdvanceRequestStatus.ACCOUNTED,
                        AdvanceRequestStatus.REIMBURSED,
                    )
                    for a in advances
                ):
                    codes = sorted(
                        {
                            a.accountability_netsuite_id
                            for a in advances
                            if a.accountability_netsuite_id
                        }
                    )
                    wfr.status = "accounted"
                    wfr.accountability_netsuite_id = ", ".join(codes)[:128] or None
                    wfr.accountability_submitted_at = (
                        wfr.accountability_submitted_at
                        or min(
                            (
                                a.accountability_submitted_at
                                for a in advances
                                if a.accountability_submitted_at
                            ),
                            default=timezone.now(),
                        )
                    )
                    wfr.accountability_reviewed_at = timezone.now()
                    wfr.accounted_amount = sum(
                        a.accounted_amount or 0 for a in advances
                    )
                    wfr.returned_amount = sum(a.returned_amount or 0 for a in advances)
                    wfr.save(
                        update_fields=[
                            "status",
                            "accountability_netsuite_id",
                            "accountability_submitted_at",
                            "accountability_reviewed_at",
                            "accounted_amount",
                            "returned_amount",
                            "updated_at",
                        ]
                    )

            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
                status=400,
            )


@require_page_permission("disbursements")
def finance_return_action(request):
    """POST to return a confirmed-for-advance weekly fund request for
    correction — the Accountant's alternative to disbursing it."""
    if request.user.active_role != "Accountant":
        return HttpResponse("Unauthorized", status=403)

    if request.method == "POST":
        request_id = request.POST.get("request_id")
        reason = request.POST.get("reason", "").strip()
        if not reason:
            return HttpResponse(
                '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">A return reason is required.</div>',
                status=400,
            )

        try:
            from django.db import transaction

            with transaction.atomic():
                wfr = (
                    WeeklyFundRequest.objects.select_for_update()
                    .filter(id=request_id)
                    .first()
                )
                if not wfr:
                    return HttpResponse(
                        '<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Weekly fund request not found.</div>',
                        status=400,
                    )
                # Same precondition disburse() requires — only a plan the
                # Accountant hasn't yet acted on can still be returned. This
                # also blocks the request from being un-disbursed/un-accounted
                # by a stale tab or double-click on this action.
                if wfr.status != "confirmed_for_advance":
                    return HttpResponse(
                        f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Only a confirmed request can be returned by the accountant — this one is already {wfr.get_status_display()}.</div>',
                        status=400,
                    )

                wfr.status = "returned_by_accountant"
                wfr.confirmed_at = None
                wfr.save(update_fields=["status", "confirmed_at", "updated_at"])

                # Only advances still awaiting disbursement move with it — an
                # advance that's already disbursed/accounted on a sibling line
                # must never be silently reopened.
                for line in wfr.lines.select_related("activity_budget_line"):
                    adv = line.activity_budget_line.advance_requests.filter(
                        status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
                    ).first()
                    if adv:
                        adv.status = AdvanceRequestStatus.RETURNED
                        adv.last_note = reason
                        adv.save(update_fields=["status", "last_note", "updated_at"])

                from apps.audit.services import log as audit_log

                audit_log(
                    action="weekly_fund_request.return_by_accountant",
                    subject_kind="WeeklyFundRequest",
                    subject_id=str(wfr.id),
                    actor_id=str(request.user.id),
                    actor_role=request.user.active_role,
                    success=True,
                    payload={"reason": reason, "total_amount": wfr.total_amount},
                )

            response = HttpResponse("<script>window.location.reload();</script>")
            response["HX-Trigger"] = "close-drawer"
            return response
        except Exception as e:
            return HttpResponse(
                f'<div class="p-3 bg-rose-50 text-rose-700 rounded-surface text-[12px] font-bold">Error: {str(e)}</div>',
                status=400,
            )


@require_page_permission("consolidated_fund_allocation")
def budget_overview_view(request):
    """Budget overview — CD/Accountant view."""
    from apps.budget.services import fy_budget, monthly_budget

    fy = get_operational_fy()

    fy_data = fy_budget({"fy": fy})

    monthly_data = []
    for m in range(1, 13):
        m_data = monthly_budget({"fy": fy, "month": m})
        if m_data["plannedBudget"] > 0 or m_data["requestedBudget"] > 0:
            # Add helper display name for the month-of-fy (1=October, 2=November, ...)
            months_names = {
                1: "October",
                2: "November",
                3: "December",
                4: "January",
                5: "February",
                6: "March",
                7: "April",
                8: "May",
                9: "June",
                10: "July",
                11: "August",
                12: "September",
            }
            m_data["display_name"] = months_names.get(m, f"Month {m}")
            monthly_data.append(m_data)

    pending_approvals = WeeklyFundRequest.objects.filter(
        status__in=["submitted_to_pl", "submitted_to_cd"]
    ).count()

    context = {
        "monthly_data": monthly_data,
        "fy_data": fy_data,
        "pending_approvals": pending_approvals,
        "fy": fy,
    }
    return render(request, "pages/budget/index.html", context)


@require_page_permission("cost_settings")
def cost_settings_view(request):
    """CD Cost Catalogue management."""
    from apps.budget.costing import LEGACY_CLUSTER_ACTIVITY_COST_KEYS

    fy = get_operational_fy()

    catalogues = CostCatalogue.objects.filter(fy=fy).order_by("-version")
    active_catalogue = catalogues.filter(is_active=True).first()

    cost_items = []
    if active_catalogue:
        cost_items = list(
            CostSetting.objects.filter(catalogue=active_catalogue)
            .exclude(key__in=LEGACY_CLUSTER_ACTIVITY_COST_KEYS)
            .order_by("label")
        )

    context = {
        "catalogues": catalogues,
        "active_catalogue": active_catalogue,
        "cost_items": cost_items,
        "fy": fy,
        "can_initialize": request.user.active_role in ("CountryDirector", "Admin"),
    }
    return render(request, "pages/cost_settings/index.html", context)


@require_page_permission("consolidated_fund_allocation")
def fund_allocation_view(request):
    import csv
    from django.http import HttpResponse
    from apps.geography.models import Region, District
    from apps.budget.allocation_service import MonthlyFundAllocationService

    # 1. Parse filter inputs & parameters
    month_name = request.GET.get("month", "April").strip()
    fy = request.GET.get("fy", "2026").strip()
    region_id = request.GET.get("region", "").strip()
    district_id = request.GET.get("district", "").strip()
    search_q = request.GET.get("q", "").strip()
    export_mode = request.GET.get("export_mode", "full").strip()

    try:
        page = int(request.GET.get("page", 1))
    except ValueError:
        page = 1

    try:
        per_page = int(request.GET.get("per_page", 10))
    except ValueError:
        per_page = 10

    MONTH_MAP = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    month_num = MONTH_MAP.get(month_name.lower(), 4)

    # 2. Get Allocation Data & Calculations
    data = MonthlyFundAllocationService.get_monthly_allocation(
        month_num=month_num,
        fy=fy,
        region_id=region_id or None,
        district_id=district_id or None,
        search_q=search_q or None,
        page=page,
        per_page=per_page,
        principal=request.user,
    )

    # Check if CSV export is requested
    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="consolidated_fund_allocation_{month_name}_{fy}.csv"'
        )
        writer = csv.writer(response)

        if export_mode == "admin_only":
            writer.writerow(
                [
                    "Line Item Description",
                    "Cost Category",
                    "Quantity",
                    "Unit Cost (UGX)",
                    "Total Cost (UGX)",
                    "Status",
                ]
            )
            for line in data["admin_budget_data"]["lines"]:
                writer.writerow(
                    [
                        line["description"],
                        line["cost_category"],
                        line["quantity"],
                        line["unit_cost"],
                        line["total_cost"],
                        line["status"],
                    ]
                )
        else:
            writer.writerow(
                [
                    "Staff",
                    "Staff Visits Count",
                    "Staff Visits Cost",
                    "Staff Visits Total",
                    "Partner Visits Count",
                    "Partner Visits Cost",
                    "Partner Visits Total",
                    "SSA Count",
                    "SSA Cost",
                    "SSA Total",
                    "Cluster Training Count",
                    "Cluster Training Cost",
                    "Cluster Training Total",
                    "Partner In-School Training Count",
                    "Partner In-School Training Cost",
                    "Partner In-School Training Total",
                    "Admin Budget Planned",
                    "Admin Budget Allocated",
                    "Admin Budget Total",
                    "Total Monthly Allocation",
                ]
            )
            rows_to_export = data["rows_all"]
            if export_mode == "field_only":
                rows_to_export = [
                    r for r in rows_to_export if r["user_id"] != "cd_admin_budget"
                ]

            for r in rows_to_export:
                admin_p = (
                    r.get("admin_budget", {}).get("planned", 0)
                    if "admin_budget" in r
                    else 0
                )
                admin_a = (
                    r.get("admin_budget", {}).get("allocated", 0)
                    if "admin_budget" in r
                    else 0
                )
                admin_t = (
                    r.get("admin_budget", {}).get("total", 0)
                    if "admin_budget" in r
                    else 0
                )

                writer.writerow(
                    [
                        r["name"],
                        r["staff_visits"]["count"],
                        r["staff_visits"]["unit_cost"],
                        r["staff_visits"]["total"],
                        r["partner_visits"]["count"],
                        r["partner_visits"]["unit_cost"],
                        r["partner_visits"]["total"],
                        r["ssa"]["count"],
                        r["ssa"]["unit_cost"],
                        r["ssa"]["total"],
                        r["cluster_training"]["count"],
                        r["cluster_training"]["unit_cost"],
                        r["cluster_training"]["total"],
                        r["partner_in_school_training"]["count"],
                        r["partner_in_school_training"]["unit_cost"],
                        r["partner_in_school_training"]["total"],
                        admin_p,
                        admin_a,
                        admin_t,
                        r["total_allocation"],
                    ]
                )
        return response

    insights = MonthlyFundAllocationService.calculate_insights(
        rows_all=data["rows_all"],
        grand_totals=data["grand_totals"],
        total_staff_count=data["total_staff_count"],
    )

    # Format UGX compact helper
    def format_ugx_compact(val):
        if not val:
            return "UGX 0"
        if val >= 1_000_000_000:
            return f"UGX {val / 1_000_000_000:.1f}B"
        if val >= 1_000_000:
            return f"UGX {val / 1_000_000:.1f}M"
        if val >= 1_000:
            return f"UGX {val / 1_000:.0f}K"
        return f"UGX {val}"

    grand_totals = data["grand_totals"]
    total_staff_count = data["total_staff_count"]
    total_activities_count = data["total_activities_count"]

    kpi_strip_items = [
        {
            "label": "Total Allocation",
            "value": format_ugx_compact(grand_totals.get("total_allocation", 0)),
            "raw_value": int(grand_totals.get("total_allocation", 0)),
            "helper": f"Across {total_staff_count} staff",
            "icon": "finance",
            "variant": "finance",
        },
        {
            "label": "Staff Included",
            "value": str(total_staff_count),
            "raw_value": total_staff_count,
            "helper": "Active staff",
            "icon": "users",
            "variant": "primary",
        },
        {
            "label": "Planned Activities",
            "value": str(total_activities_count),
            "raw_value": total_activities_count,
            "helper": "Across categories",
            "icon": "chart",
            "variant": "info",
        },
        {
            "label": "Staff Visits Cost",
            "value": format_ugx_compact(
                grand_totals.get("staff_visits", {}).get("total", 0)
            ),
            "raw_value": int(grand_totals.get("staff_visits", {}).get("total", 0)),
            "helper": f"{grand_totals.get('staff_visits', {}).get('count', 0)} visits",
            "icon": "school",
            "variant": "blue",
        },
        {
            "label": "Partner Visits Cost",
            "value": format_ugx_compact(
                grand_totals.get("partner_visits", {}).get("total", 0)
            ),
            "raw_value": int(grand_totals.get("partner_visits", {}).get("total", 0)),
            "helper": f"{grand_totals.get('partner_visits', {}).get('count', 0)} visits",
            "icon": "users",
            "variant": "purple",
        },
        {
            "label": "SSA Cost",
            "value": format_ugx_compact(grand_totals.get("ssa", {}).get("total", 0)),
            "raw_value": int(grand_totals.get("ssa", {}).get("total", 0)),
            "helper": f"{grand_totals.get('ssa', {}).get('count', 0)} visits",
            "icon": "report",
            "variant": "warning",
        },
        {
            "label": "Cluster Training Cost",
            "value": format_ugx_compact(
                grand_totals.get("cluster_training", {}).get("total", 0)
            ),
            "raw_value": int(grand_totals.get("cluster_training", {}).get("total", 0)),
            "helper": f"{grand_totals.get('cluster_training', {}).get('count', 0)} schools",
            "icon": "target",
            "variant": "success",
        },
        {
            "label": "Admin Budget",
            "value": format_ugx_compact(
                grand_totals.get("admin_budget", {}).get("total", 0)
            ),
            "raw_value": int(grand_totals.get("admin_budget", {}).get("total", 0)),
            "helper": "CD Plan",
            "icon": "currency",
            "variant": "neutral",
        },
    ]

    # Pagination info
    total_pages = (data["total_staff_count"] + per_page - 1) // per_page
    from apps.core.pagination import make_pagination_window

    pages_list = make_pagination_window(page, total_pages)
    showing_start = (page - 1) * per_page + 1 if data["total_staff_count"] > 0 else 0
    showing_end = min(page * per_page, data["total_staff_count"])

    # 3. Filter Options Lists
    regions = Region.objects.all().order_by("name")
    districts = District.objects.all().order_by("name")

    # 4. Render context
    context = {
        "rows": data["rows"],
        "grand_totals": data["grand_totals"],
        "kpi_strip_items": kpi_strip_items,
        "total_staff_count": data["total_staff_count"],
        "total_activities_count": data["total_activities_count"],
        "insights": insights,
        "admin_budget_data": data["admin_budget_data"],
        # Pagination
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
        "pages_list": pages_list,
        "showing_start": showing_start,
        "showing_end": showing_end,
        # Filters dropdown options
        "regions": regions,
        "districts": districts,
        # Selected states
        "selected_month": month_name,
        "selected_fy": fy,
        "selected_region": region_id,
        "selected_district": district_id,
        "search_q": search_q,
        # Dark sidebar indicator
        "use_dark_sidebar": True,
        "timestamp": timezone.now().strftime("%B %d, %Y %I:%M %p"),
        # The table partial only emits its hx-swap-oob blocks on HTMX
        # refreshes — on full page loads they would render as duplicates.
        "is_htmx": request.headers.get("HX-Request") == "true",
    }

    if request.headers.get("HX-Request") == "true":
        return render(request, "partials/finance/fund_allocation_table.html", context)

    return render(request, "pages/finance/fund_allocation.html", context)


@require_page_permission("consolidated_fund_allocation")
def admin_budget_drilldown_view(request):
    """GET to render the admin budget breakdown floating drawer."""
    from apps.budget.admin_budget_service import AdminBudgetAllocationService

    month_name = request.GET.get("month", "April").strip()
    fy = request.GET.get("fy", "2026").strip()

    MONTH_MAP = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    month_num = MONTH_MAP.get(month_name.lower(), 4)

    admin_data = AdminBudgetAllocationService.get_admin_budget_allocation(month_num, fy)

    context = {
        "admin_data": admin_data,
        "selected_month": month_name,
        "selected_fy": fy,
        "drawer_size": "lg",
    }
    return render(request, "partials/finance/admin_budget_drilldown.html", context)


@require_page_permission("consolidated_fund_allocation")
def allocation_drilldown_view(request):
    """GET to render detailed activities list for a specific staff's cell."""
    staff_id = request.GET.get("staff_id", "").strip()
    category = request.GET.get("category", "").strip()
    month_name = request.GET.get("month", "April").strip()
    fy = request.GET.get("fy", "2026").strip()

    MONTH_MAP = {
        "january": 1,
        "february": 2,
        "march": 3,
        "april": 4,
        "may": 5,
        "june": 6,
        "july": 7,
        "august": 8,
        "september": 9,
        "october": 10,
        "november": 11,
        "december": 12,
    }
    month_num = MONTH_MAP.get(month_name.lower(), 4)

    from apps.accounts.models import StaffProfile, User
    from apps.budget.allocation_service import MonthlyFundAllocationService

    staff_user = get_object_or_404(User, id=staff_id)
    # The roster above is scoped; this drilldown was not, so an out-of-scope
    # `?staff_id=` returned a named individual's itemised monthly spend.
    if not MonthlyFundAllocationService._scope_staff(
        request.user, StaffProfile.objects.filter(user_id=staff_user.id)
    ).exists():
        return render_access_denied(
            request, "You do not have access to this staff member's allocation."
        )

    # Query cost lines for this staff in the month & FY
    cost_lines = ActivityScheduleCostLine.objects.filter(
        fiscal_year=fy, month=month_num, responsible_user=staff_id
    ).select_related("activity", "activity__school", "activity__cluster")

    # Filter by category classification
    filtered_lines = []
    for line in cost_lines:
        act = line.activity
        act_type = act.activity_type
        delivery = act.delivery_type

        # Classification
        if act_type == "ssa_activity":
            cat = "ssa"
        elif act_type in [
            "cluster_training",
            "training",
            "school_improvement_training",
            "core_training",
            "cluster_meeting",
        ]:
            cat = "cluster_training"
        elif act_type == "partner_activity" or (
            act_type in ["training", "school_improvement_training", "core_training"]
            and delivery == "partner"
        ):
            cat = "partner_in_school_training"
        elif act_type in VISIT_TYPES and delivery == "partner":
            cat = "partner_visits"
        else:
            cat = "staff_visits"

        if cat == category:
            filtered_lines.append(line)

    context = {
        "staff_user": staff_user,
        "category_label": category.replace("_", " ").title(),
        "lines": filtered_lines,
        "selected_month": month_name,
        "selected_fy": fy,
        "drawer_size": "lg",
    }
    return render(request, "partials/finance/allocation_drilldown_drawer.html", context)


@require_page_permission("consolidated_fund_allocation")
def export_drawer_view(request):
    """GET to render the CSV export settings floating drawer."""
    month_name = request.GET.get("month", "April").strip()
    fy = request.GET.get("fy", "2026").strip()

    context = {
        "selected_month": month_name,
        "selected_fy": fy,
        "drawer_size": "sm",
    }
    return render(request, "partials/finance/export_drawer.html", context)


@require_page_permission("cost_settings")
def cost_setting_row_view(request, key):
    from django.shortcuts import get_object_or_404
    from django.http import HttpResponse
    from apps.budget.models import CostSetting
    from apps.budget import services as budget_services

    if request.user.active_role not in ("CountryDirector", "Admin"):
        return HttpResponse("Forbidden", status=403)

    setting = get_object_or_404(CostSetting, key=key)
    mode = request.GET.get("mode", "view")

    if request.method == "POST":
        new_cost_str = request.POST.get("unit_cost", "").strip()
        reason = request.POST.get("reason", "").strip() or "Updated via CD Dashboard"
        try:
            new_cost = int(new_cost_str.replace(",", ""))
            budget_services.upsert_cost_setting(
                {
                    "key": setting.key,
                    "label": setting.label,
                    "unitCost": new_cost,
                    "reason": reason,
                    "fy": setting.fy,
                },
                request.user,
            )
            setting = CostSetting.objects.get(key=key)
            mode = "view"
        except ValueError:
            return HttpResponse("Invalid cost value", status=400)

    context = {
        "c": setting,
        "mode": mode,
    }
    return render(request, "partials/cost_settings/cost_setting_row.html", context)


@require_page_permission("cost_settings")
def initialize_default_catalogue_view(request):
    from django.shortcuts import redirect
    from django.http import HttpResponse
    from apps.budget.models import CostCatalogue, CostSetting
    from apps.core.fy import get_operational_fy

    if request.user.active_role not in ("CountryDirector", "Admin"):
        return HttpResponse("Forbidden", status=403)

    fy = get_operational_fy()
    active = CostCatalogue.objects.filter(fy=fy, is_active=True).first()
    if not active:
        active = CostCatalogue.objects.create(
            country="Uganda",
            fy=fy,
            version=1,
            is_active=True,
            label=f"Uganda FY{fy} Country Cost Catalogue",
        )
    default_settings = [
        ("accommodation", "Accommodation per night", 40000, "per night"),
        ("breakfast", "Breakfast", 8000, "per head"),
        (
            "cluster_meeting_participant_meal_cost_per_head",
            "Participant snacks",
            10000,
            "per participant",
        ),
        ("dinner", "Dinner", 12000, "per head"),
        ("lunch", "Lunch", 12000, "per head"),
        (
            "group_training_participant_meal_cost_per_head",
            "Participant meals",
            5000,
            "per participant",
        ),
        ("group_training_facilitation_fee", "Facilitation fee", 50000, "per session"),
        ("group_training_venue_cost", "Venue fee", 30000, "per session"),
        (
            "partner_training_lump_sum",
            "Partner training/facilitation rate",
            16000,
            "per item",
        ),
        ("partner_visit_lump_sum", "Partner visit rate", 40000, "per item"),
        (
            "staff_visit_transport_primary",
            "Staff visit transport (primary district)",
            50000,
            "per item",
        ),
        (
            "staff_visit_transport_secondary",
            "Staff visit transport (secondary district)",
            25000,
            "per item",
        ),
        # Core / SSA / Special Project categories — each key is consumed by
        # apps.budget.costing.cost_for_activity's dedicated branch; without it
        # the engine falls through to the generic visit/training/partner rate.
        ("core_school_visit", "Core school visit cost", 50000, "per visit"),
        ("core_school_training", "Core school training cost", 250000, "per session"),
        ("ssa_visit_rate", "Baseline SSA visit cost", 50000, "per visit"),
        (
            "project_partner_lump_sum",
            "Special project partner activity rate",
            40000,
            "per item",
        ),
        # Daily Visit Batch rates: a staff member's daily transport/lunch(/
        # accommodation/dinner) cost pool, shared and split across every
        # school scheduled for that same day (not costed per school alone).
        (
            "primary_transport_per_day",
            "Primary district daily transport pool",
            50000,
            "per day",
        ),
        (
            "primary_lunch_per_day",
            "Primary district daily lunch pool",
            12000,
            "per day",
        ),
        (
            "secondary_transport_per_day",
            "Secondary district daily transport pool",
            80000,
            "per day",
        ),
        (
            "secondary_lunch_per_day",
            "Secondary district daily lunch pool",
            12000,
            "per day",
        ),
        (
            "secondary_accommodation_per_night",
            "Secondary district accommodation per night",
            40000,
            "per night",
        ),
        (
            "secondary_overnight_dinner_per_day",
            "Secondary district overnight dinner",
            12000,
            "per day",
        ),
        (
            "secondary_breakfast_per_day",
            "Secondary district breakfast (optional)",
            8000,
            "per day",
        ),
        (
            "secondary_incidentals_per_day",
            "Secondary district incidentals (optional)",
            5000,
            "per day",
        ),
    ]
    for key, label, cost, unit in default_settings:
        CostSetting.objects.get_or_create(
            key=key,
            defaults={
                "label": label,
                "unit_cost": cost,
                "fy": fy,
                "catalogue": active,
                "version": 1,
            },
        )
    CostSetting.objects.filter(catalogue__isnull=True).update(catalogue=active)

    return redirect("/dashboard")


def _country_budget_filters(request):
    return {k: request.GET.get(k) for k in ("fy", "month", "q") if request.GET.get(k)}


@require_page_permission("country_budget")
def country_budget_view(request):
    """Country Monthly Budget — the CD's monthly finance control page.
    Consolidates only plan-backed, scheduled, costed activity budgets for the
    month plus the CD Admin Budget from the CD Monthly Admin Plan."""
    from apps.monthly_work_plan.country_budget_service import (
        get_country_monthly_budget,
    )

    ctx = get_country_monthly_budget(request.user, _country_budget_filters(request))
    if request.headers.get("HX-Target") == "country-budget-root":
        return render(request, "partials/finance/country_budget/root.html", ctx)
    return render(request, "pages/finance/country_budget.html", ctx)


@require_page_permission("country_budget")
def country_budget_plan_sources_view(request):
    """The 'View Plan Sources' drawer — activities + cost lines behind the
    selected month's budget."""
    from apps.monthly_work_plan.country_budget_service import get_plan_sources

    ctx = get_plan_sources(request.user, _country_budget_filters(request))
    return render(
        request, "partials/finance/country_budget/plan_sources_drawer.html", ctx
    )


@require_page_permission("country_budget")
def country_budget_return_drawer_view(request):
    """The RVP return-for-correction drawer."""
    from apps.core.fy import get_operational_fy
    from apps.monthly_work_plan.country_budget_service import RETURN_REASONS
    from apps.fund_requests.pl_approval_service import MONTHS

    fy = request.GET.get("fy") or get_operational_fy()
    month = int(request.GET.get("month") or timezone.now().month)
    return render(
        request,
        "partials/finance/country_budget/return_drawer.html",
        {
            "budget_id": request.GET.get("budget_id", ""),
            "fy": fy,
            "month": month,
            "month_label": MONTHS[month] if 1 <= month <= 12 else str(month),
            "return_reasons": RETURN_REASONS,
        },
    )


@require_page_permission("country_budget")
def country_budget_action_view(request):
    """Send to RVP / Approve / Return — mutate then re-render the root."""
    from apps.core.exceptions import BadRequest, Forbidden
    from apps.monthly_work_plan import country_budget_service as svc

    if request.method != "POST":
        return HttpResponse("Method not allowed", status=405)
    action = request.POST.get("action")
    budget_id = request.POST.get("budget_id")
    error = ok = None
    try:
        if action == "send_to_rvp":
            b = svc.send_to_rvp(request.user, budget_id)
            ok = f"{b.month_key} Country Monthly Budget sent to the RVP for approval."
        elif action == "approve":
            b = svc.approve(request.user, budget_id)
            ok = f"{b.month_key} Country Monthly Budget approved."
        elif action == "return":
            b = svc.return_budget(
                request.user,
                budget_id,
                {
                    "reason": request.POST.get("reason"),
                    "comment": request.POST.get("comment"),
                },
            )
            ok = f"{b.month_key} Country Monthly Budget returned for correction."
        elif action == "approve_pl_request":
            svc.approve_pl_monthly_request(request.user, request.POST.get("request_id"))
            ok = "Program Lead request approved and added to the country budget."
        elif action == "return_pl_request":
            svc.return_pl_monthly_request(
                request.user,
                request.POST.get("request_id"),
                request.POST.get("note"),
            )
            ok = "Program Lead request returned for changes."
        elif action == "add_admin_line":
            from apps.monthly_work_plan import services as monthly_plan_service

            monthly_plan_service.add_admin_line(
                budget_id,
                {
                    "description": request.POST.get("description"),
                    "costCategory": request.POST.get("cost_category"),
                    "quantity": request.POST.get("quantity"),
                    "unitCost": request.POST.get("unit_cost"),
                    "justification": request.POST.get("justification"),
                },
                request.user,
            )
            ok = "Admin budget item added to the country budget."
        elif action == "send_to_accountant":
            from apps.monthly_work_plan import services as monthly_plan_service

            monthly_plan_service.mark_sent_to_accountant(budget_id, request.user)
            ok = "Country budget handed to the Accountant for disbursement."
        elif action == "mark_disbursed":
            # The envelope previously stopped at approved_by_rvp forever — the
            # disbursed/closed statuses existed but nothing ever wrote them.
            from apps.monthly_work_plan import reconciliation_service as recon

            result = recon.mark_disbursed(budget_id, request.user)
            ok = (
                "Country budget marked disbursed — "
                f"{_ugx(result['reconciliation']['disbursedTotal'])} "
                "recorded against the approved envelope."
            )
        elif action == "close_month":
            from apps.monthly_work_plan import reconciliation_service as recon

            result = recon.close_month(budget_id, request.user)
            rec = result["reconciliation"]
            verb = "under" if rec["variance"] >= 0 else "over"
            ok = (
                f"{rec['monthKey']} closed — accounted "
                f"{_ugx(rec['accountedTotal'])} against an approved "
                f"{_ugx(rec['approvedTotal'])} "
                f"({_ugx(abs(rec['variance']))} {verb})."
            )
        else:
            error = "Unknown action."
    except (BadRequest, Forbidden) as e:
        error = str(e)

    ctx = svc.get_country_monthly_budget(
        request.user,
        {"fy": request.POST.get("fy"), "month": request.POST.get("month")},
    )
    ctx["action_error"] = error
    ctx["action_ok"] = ok
    resp = render(request, "partials/finance/country_budget/root.html", ctx)
    resp["HX-Trigger"] = "close-drawer"
    return resp
