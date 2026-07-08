from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from django.db import models
from django.utils import timezone

from apps.core.permissions import require_page_permission
from apps.activities.models import Activity
from apps.fund_requests.models import (
    ReimbursementClaim,
    AccountabilityRecord,
    FinanceReturn,
    VarianceReview,
    FinanceAuditLog,
    WeeklyFundRequest,
)
from apps.fund_requests.finance_services import (
    FinanceBlockedReasonService,
    AdvanceDisbursementService,
    PartnerPaymentService,
    ReimbursementService,
    NetSuiteExpenseService,
)


VISIT_TYPES = [
    "school_visit",
    "follow_up_visit",
    "coaching_visit",
    "in_school_support",
    "core_visit",
]


def _ugx_compact(val):
    """Format an integer UGX amount compactly (e.g. UGX 2.4B / 186.4M / 65K)."""
    if not val:
        return "UGX 0"
    if val >= 1_000_000_000:
        return f"UGX {val / 1_000_000_000:.1f}B"
    if val >= 1_000_000:
        return f"UGX {val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"UGX {val / 1_000:.0f}K"
    return f"UGX {val:,}"


def _activity_cost(activity):
    """The real, honest cost of an activity: the sum of its persisted budget
    lines (schedule_cost_lines), falling back to the auto-costed estimate.
    Mirrors the accessor used by apps.budget.services (board/monthly_budget)."""
    total = sum(line.amount for line in activity.schedule_cost_lines.all())
    return total or activity.est_cost_cents or 0


@require_page_permission("disbursements")
def accountant_dashboard_view(request):
    """Main Accountant Dashboard / Finance Command Center."""
    import json
    from apps.core.fy import get_operational_fy
    from apps.fund_requests.models import WeeklyFundRequest
    from apps.accounts.models import User, StaffProfile

    fy = get_operational_fy()

    # 1. Real database queries for KPIs (WeeklyFundRequest lifecycle:
    # pending_responsible_confirmation -> confirmed_for_advance -> disbursed/paid/closed,
    # plus self_funded / not_requested / cancelled side paths).
    CONFIRMED_ONWARD = [
        "confirmed_for_advance",
        "disbursed",
        "paid",
        "closed",
        "cleared",
        "self_funded",
        "self_funded_pending_reimbursement",
    ]
    total_approved_db = (
        WeeklyFundRequest.objects.filter(fy=fy, status__in=CONFIRMED_ONWARD).aggregate(
            Sum("total_amount")
        )["total_amount__sum"]
        or 0
    )

    total_disbursed_db = (
        WeeklyFundRequest.objects.filter(fy=fy).aggregate(Sum("disbursed_amount"))[
            "disbursed_amount__sum"
        ]
        or 0
    )

    # Let's query all WeeklyFundRequests
    from apps.geography.models import District

    wfrs_db = list(WeeklyFundRequest.objects.all().order_by("-week_start_date"))
    user_ids = [w.responsible_user for w in wfrs_db]
    users_by_id = {u.id: u for u in User.objects.filter(id__in=user_ids)}
    profiles_by_id = {
        p.user_id: p for p in StaffProfile.objects.filter(user_id__in=user_ids)
    }
    region_by_district_id = {
        d.id: (d.region.name if d.region_id else "—")
        for d in District.objects.select_related("region")
    }

    def _region_for(profile_obj):
        """StaffProfile has no 'portfolio' field — resolve the staff member's
        real geographic Region via their primary_district_id instead."""
        if not profile_obj or not profile_obj.primary_district_id:
            return "—"
        return region_by_district_id.get(profile_obj.primary_district_id, "—")

    queue_items = []

    # Map real DB requests to queue items
    for w in wfrs_db:
        user_obj = users_by_id.get(w.responsible_user)
        profile_obj = profiles_by_id.get(w.responsible_user)
        user_name = user_obj.name if user_obj else "System User"
        role_name = w.responsible_role or "CCEO"

        # Serialize lines
        lines_list = []
        for line in w.lines.all():
            lines_list.append(
                {
                    "category": line.description or line.line_item_type,
                    "quantity": line.quantity,
                    "unit_cost": line.unit_cost,
                    "total": line.total_cost,
                }
            )

        status_display = w.status.replace("_", " ").title()
        status_class = "bg-amber-50 text-amber-700 border-amber-250"
        if w.status == "disbursed":
            status_class = "bg-blue-50 text-blue-700 border-blue-250"
        elif w.status == "accounted":
            status_class = "bg-emerald-50 text-emerald-700 border-emerald-250"
        elif w.status == "returned_by_accountant":
            status_class = "bg-rose-50 text-rose-700 border-rose-250"

        queue_items.append(
            {
                "id": w.id,
                "user_name": user_name,
                "role": role_name,
                "region": _region_for(profile_obj),
                "requested": w.total_amount,
                "approved": w.total_amount,
                "disbursed": w.disbursed_amount or 0,
                "balance": w.total_amount - (w.disbursed_amount or 0),
                "status": status_display,
                "status_class": status_class,
                "week_start": w.week_start_date.strftime("%d %b %Y"),
                "week_end": w.week_end_date.strftime("%d %b %Y"),
                "lines": lines_list,
                "pl_approved": True,
                "cd_approved": w.status
                in ["approved_by_cd", "sent_to_accountant", "disbursed", "accounted"],
                "rvp_approved": w.status in ["disbursed", "accounted"],
                "finance_completed": w.status in ["disbursed", "accounted"],
                "disbursed_completed": w.status in ["disbursed", "accounted"],
            }
        )

    # KPIs are computed from the live fund-request tables only — no mock rows.
    fy_qs = WeeklyFundRequest.objects.filter(fy=fy)
    in_approval_statuses = ["pending_responsible_confirmation"]
    pending_disb_qs = fy_qs.filter(status="confirmed_for_advance")
    awaiting_qs = fy_qs.filter(status__in=in_approval_statuses)
    disbursed_qs = fy_qs.filter(status__in=["disbursed", "paid", "closed", "cleared"])
    accounted_count = fy_qs.filter(accounted_amount__isnull=False).count()
    disbursed_count = disbursed_qs.count()

    pending_disb_amount = sum(
        (w.total_amount or 0) - (w.disbursed_amount or 0) for w in pending_disb_qs
    )
    awaiting_amount = (
        awaiting_qs.aggregate(Sum("total_amount"))["total_amount__sum"] or 0
    )
    recon_rate = (
        round(accounted_count / disbursed_count * 100) if disbursed_count else 0
    )
    budget_util = (
        round(total_disbursed_db / total_approved_db * 100) if total_approved_db else 0
    )

    all_funds = queue_items
    all_funds_json = json.dumps(all_funds)

    # ── Right-rail + bottom-row live rollups ─────────────────────────────
    month_start = (
        timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).date()
    )
    month_qs = fy_qs.filter(week_start_date__gte=month_start)

    def _sum(qs, field="total_amount"):
        return qs.aggregate(v=Sum(field))["v"] or 0

    month_overview = {
        "waiting": _ugx_compact(
            _sum(month_qs.filter(status="pending_responsible_confirmation"))
        ),
        "pending_disb": _ugx_compact(
            sum(
                (w.total_amount or 0) - (w.disbursed_amount or 0)
                for w in month_qs.filter(status="confirmed_for_advance")
            )
        ),
        "disbursed": _ugx_compact(_sum(month_qs, "disbursed_amount")),
        "accounted": _ugx_compact(
            _sum(month_qs.filter(accounted_amount__isnull=False), "accounted_amount")
        ),
    }

    # Disbursement status donut over the FY's requests (share of request count)
    n_all = fy_qs.count()
    n_waiting = fy_qs.filter(status="pending_responsible_confirmation").count()
    n_confirmed = pending_disb_qs.count()
    n_disbursed = disbursed_qs.count()
    n_other = max(0, n_all - n_waiting - n_confirmed - n_disbursed)

    def _share(n):
        return round(n / n_all * 100) if n_all else 0

    disb_donut = {
        "total": _ugx_compact(_sum(fy_qs)),
        "confirmed": _share(n_confirmed),
        "waiting": _share(n_waiting),
        "disbursed": _share(n_disbursed),
        "other": _share(n_other),
        "waiting_offset": -_share(n_confirmed),
        "disbursed_offset": -(_share(n_confirmed) + _share(n_waiting)),
        "other_offset": -(
            _share(n_confirmed) + _share(n_waiting) + _share(n_disbursed)
        ),
    }

    recent_disbursements = []
    for w in fy_qs.filter(
        status__in=["disbursed", "paid", "closed", "cleared"]
    ).order_by("-updated_at")[:4]:
        u = users_by_id.get(w.responsible_user)
        p = profiles_by_id.get(w.responsible_user)
        recent_disbursements.append(
            {
                "name": u.name if u else "—",
                "initials": (u.name[:2].upper() if u and u.name else "—"),
                "region": _region_for(p),
                "when": w.updated_at.strftime("%d %b, %I:%M %p")
                if w.updated_at
                else "—",
                "amount": _ugx_compact(w.disbursed_amount or w.total_amount),
                "status": w.status.replace("_", " ").title(),
            }
        )

    awaiting_accountability_qs = fy_qs.filter(
        status__in=["disbursed", "paid"], accounted_amount__isnull=True
    )
    recon = {
        "awaiting_receipts": awaiting_accountability_qs.count(),
        "partially_accounted": fy_qs.filter(accounted_amount__isnull=False)
        .exclude(accounted_amount=models.F("disbursed_amount"))
        .count(),
        "closed": fy_qs.filter(status__in=["closed", "cleared"]).count(),
        "pending_confirmation": n_waiting,
    }
    recon_rows = []
    now_ts = timezone.now()
    for w in awaiting_accountability_qs.order_by("updated_at")[:3]:
        u = users_by_id.get(w.responsible_user)
        p = profiles_by_id.get(w.responsible_user)
        days = max(0, (now_ts - w.updated_at).days) if w.updated_at else 0
        recon_rows.append(
            {
                "who": f"{u.name if u else '—'} • {_region_for(p)}",
                "amount": f"{(w.disbursed_amount or w.total_amount):,}",
                "days": days,
            }
        )

    cash = {
        "confirmed": _ugx_compact(total_approved_db),
        "committed": _ugx_compact(pending_disb_amount),
        "pending": _ugx_compact(awaiting_amount),
        "disbursed": _ugx_compact(total_disbursed_db),
        "util": budget_util,
    }

    # ApexCharts donut config — request counts by disbursement-lifecycle stage.
    disb_donut_options = {
        "chart": {"type": "donut", "fontFamily": "inherit"},
        "labels": ["Confirmed", "Awaiting Confirmation", "Disbursed", "Other"],
        "series": [n_confirmed, n_waiting, n_disbursed, n_other],
        "colors": ["#10b981", "#f59e0b", "#3b82f6", "#f43f5e"],
        "legend": {"show": False},
        "dataLabels": {"enabled": False},
        "stroke": {"width": 2, "colors": ["#ffffff"]},
        "plotOptions": {
            "pie": {
                "donut": {
                    "size": "72%",
                    "labels": {
                        "show": True,
                        "total": {"show": True, "label": "Total", "color": "#1e293b"},
                    },
                }
            }
        },
    }

    kpi_strip_items = [
        {
            "label": "Approved This FY",
            "value": _ugx_compact(total_approved_db),
            "helper": f"{fy_qs.filter(status__in=CONFIRMED_ONWARD).count()} requests",
            "icon": "check",
            "variant": "success",
        },
        {
            "label": "Pending Disbursement",
            "value": _ugx_compact(pending_disb_amount),
            "helper": f"{pending_disb_qs.count()} requests awaiting",
            "icon": "clock",
            "variant": "warning",
        },
        {
            "label": "Disbursed This FY",
            "value": _ugx_compact(total_disbursed_db),
            "helper": f"{disbursed_count} disbursements",
            "icon": "currency",
            "variant": "blue",
        },
        {
            "label": "Awaiting Approvals",
            "value": _ugx_compact(awaiting_amount),
            "helper": f"{awaiting_qs.count()} requests in chain",
            "icon": "report",
            "variant": "purple",
        },
        {
            "label": "Reconciliation Rate",
            "value": f"{recon_rate}%",
            "helper": "accounted of disbursed",
            "icon": "shield",
            "variant": "neutral",
        },
        {
            "label": "Budget Utilization",
            "value": f"{budget_util}%",
            "helper": f"{_ugx_compact(total_disbursed_db)} used",
            "icon": "target",
            "variant": "finance",
        },
    ]

    context = {
        "month_overview": month_overview,
        "disb_donut": disb_donut,
        "disb_donut_options": disb_donut_options,
        "disb_donut_has_data": n_all > 0,
        "recent_disbursements": recent_disbursements,
        "recon": recon,
        "recon_rows": recon_rows,
        "cash": cash,
        "kpi_strip_items": kpi_strip_items,
        "kpis": {
            "total_approved": _ugx_compact(total_approved_db),
            "total_disbursed": _ugx_compact(total_disbursed_db),
            "pending_disb": _ugx_compact(pending_disb_amount),
            "pending_disb_count": pending_disb_qs.count(),
            "awaiting_approval": _ugx_compact(awaiting_amount),
            "awaiting_count": awaiting_qs.count(),
            "disbursed_count": disbursed_count,
            "approved_count": fy_qs.filter(status__in=CONFIRMED_ONWARD).count(),
            "recon_rate": f"{recon_rate}%",
            "budget_util": f"{budget_util}%",
            "budget_util_pct": budget_util,
            "disbursed_raw": _ugx_compact(total_disbursed_db),
        },
        "all_funds": all_funds,
        "all_funds_json": all_funds_json,
        "fy": fy,
    }
    return render(request, "pages/accounts/dashboard.html", context)


@require_page_permission("disbursements")
def ready_for_advance_view(request):
    """Ready for Advance Disbursement Page."""
    advances = list(
        Activity.objects.filter(
            deleted_at__isnull=True, payment_status="pending", delivery_type="staff"
        )
        .select_related("school", "cluster")
        .prefetch_related("schedule_cost_lines")
    )
    for a in advances:
        a.approved_amount = _activity_cost(a)

    total_ready = sum(a.approved_amount for a in advances)

    context = {
        "advances": advances,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque", "Cash"],
        "kpi_strip_items": [
            {
                "label": "Ready for Disbursement",
                "value": str(len(advances)),
                "helper": "Advance requests",
                "icon": "clock",
                "variant": "warning",
            },
            {
                "label": "Total Approved Value",
                "value": _ugx_compact(total_ready),
                "helper": "Sum of budget lines",
                "icon": "currency",
                "variant": "finance",
            },
        ],
        "today": timezone.now().date().isoformat(),
    }
    return render(request, "pages/accounts/ready_for_advance.html", context)


@require_page_permission("disbursements")
def mark_disbursed_action(request, activity_id):
    """POST to record a disbursement in the advance drawer."""
    activity = get_object_or_404(Activity, id=activity_id)

    if request.method == "POST":
        method = request.POST.get("payment_method")
        reference = request.POST.get("payment_reference", "").strip()
        notes = request.POST.get("notes", "").strip()

        try:
            amount = int(request.POST.get("amount_disbursed", 0))
            AdvanceDisbursementService.disburse_advance(
                activity, amount, method, reference, request.user.user_id, notes
            )
            messages.success(
                request,
                f"Advance of {amount} UGX disbursed for Activity #{activity.id[:8]} successfully.",
            )
        except Exception as e:
            messages.error(request, f"Disbursement failed: {e}")

    return redirect("/accounts/advances/")


@require_page_permission("disbursements")
def partner_payments_view(request):
    """Partner Payment Queue."""
    from apps.partners.models import Partner

    payments = list(
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="partner",
            status="ia_verified",
            payment_status__in=["pending", "ia_confirmed"],
        )
        .select_related("school", "cluster")
        .prefetch_related("schedule_cost_lines")
    )
    partner_ids = [a.assigned_partner_id for a in payments if a.assigned_partner_id]
    partners_by_id = {p.id: p for p in Partner.objects.filter(id__in=partner_ids)}
    for a in payments:
        a.payment_amount = _activity_cost(a)
        partner = partners_by_id.get(a.assigned_partner_id)
        a.partner_name = (
            partner.name if partner else (a.assigned_partner_id or "Unassigned")
        )

    context = {
        "payments": payments,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque"],
        "kpi_strip_items": [
            {
                "label": "Verified & Awaiting Payment",
                "value": str(len(payments)),
                "helper": "Partner activities",
                "icon": "users",
                "variant": "success",
            },
            {
                "label": "Total Payable",
                "value": _ugx_compact(sum(a.payment_amount for a in payments)),
                "helper": "Sum of budget lines",
                "icon": "currency",
                "variant": "finance",
            },
        ],
    }
    return render(request, "pages/accounts/partner_payments.html", context)


@require_page_permission("disbursements")
def pay_partner_action(request, activity_id):
    """POST to pay partner."""
    activity = get_object_or_404(Activity, id=activity_id)

    if request.method == "POST":
        partner_name = request.POST.get("partner_name", "").strip()
        method = request.POST.get("payment_method")
        reference = request.POST.get("payment_reference", "").strip()
        notes = request.POST.get("notes", "").strip()

        try:
            amount = int(request.POST.get("amount_paid", 0))
            PartnerPaymentService.pay_partner(
                activity,
                partner_name,
                amount,
                method,
                reference,
                request.user.user_id,
                notes,
            )
            messages.success(
                request, f"Partner payment of {amount} UGX processed successfully."
            )
        except Exception as e:
            messages.error(request, f"Partner payment failed: {e}")

    return redirect("/accounts/partner-payments/")


@require_page_permission("disbursements")
def reimbursements_view(request):
    """Reimbursement Queue."""
    claims = ReimbursementClaim.objects.filter(status="pending").select_related(
        "activity", "activity__school"
    )
    total_claimed = claims.aggregate(v=Sum("reimbursement_amount"))["v"] or 0

    context = {
        "claims": claims,
        "methods": ["Mobile Money", "Bank Transfer"],
        "kpi_strip_items": [
            {
                "label": "Pending Claims",
                "value": str(claims.count()),
                "helper": "Awaiting payout",
                "icon": "clock",
                "variant": "warning",
            },
            {
                "label": "Total Claimed",
                "value": _ugx_compact(total_claimed),
                "helper": "Reimbursement amount",
                "icon": "currency",
                "variant": "finance",
            },
        ],
    }
    return render(request, "pages/accounts/reimbursements.html", context)


@require_page_permission("disbursements")
def pay_reimbursement_action(request, claim_id):
    """POST to disburse reimbursement claim."""
    claim = get_object_or_404(ReimbursementClaim, id=claim_id)

    if request.method == "POST":
        method = request.POST.get("payment_method")
        reference = request.POST.get("payment_reference", "").strip()

        try:
            ReimbursementService.disburse_reimbursement(
                claim, method, reference, request.user.user_id
            )
            messages.success(
                request,
                f"Reimbursement of {claim.reimbursement_amount} UGX paid successfully.",
            )
        except Exception as e:
            messages.error(request, f"Reimbursement payout failed: {e}")

    return redirect("/accounts/reimbursements/")


@require_page_permission("disbursements")
def accountability_view(request):
    """Accountability Pending Page."""
    records = (
        AccountabilityRecord.objects.all()
        .select_related("activity", "activity__school")
        .order_by("-submitted_at")
    )
    pending_count = records.filter(status="pending").count()
    cleared_count = records.filter(status="cleared").count()

    context = {
        "records": records,
        "today": timezone.now().date().isoformat(),
        "kpi_strip_items": [
            {
                "label": "Registry Records",
                "value": str(records.count()),
                "helper": "All accountability entries",
                "icon": "document",
                "variant": "neutral",
            },
            {
                "label": "Pending Clearance",
                "value": str(pending_count),
                "helper": "Need NetSuite ID",
                "icon": "clock",
                "variant": "warning",
            },
            {
                "label": "Cleared",
                "value": str(cleared_count),
                "helper": "Fully reconciled",
                "icon": "check",
                "variant": "success",
            },
        ],
    }
    return render(request, "pages/accounts/accountability.html", context)


@require_page_permission("disbursements")
def netsuite_id_action(request, activity_id):
    """POST to record NetSuite Expense ID."""
    activity = get_object_or_404(Activity, id=activity_id)

    if request.method == "POST":
        netsuite_id = request.POST.get("netsuite_expense_id", "").strip()
        expense_date = request.POST.get("expense_date")
        notes = request.POST.get("notes", "").strip()

        try:
            amount = int(request.POST.get("amount_entered", 0))
            NetSuiteExpenseService.enter_netsuite_id(
                activity, netsuite_id, amount, expense_date, request.user.user_id, notes
            )
            messages.success(
                request,
                f"NetSuite ID {netsuite_id} entered for Activity #{activity.id[:8]} successfully.",
            )
        except Exception as e:
            messages.error(request, f"NetSuite ID entry failed: {e}")

    return redirect("/accounts/accountability/")


@require_page_permission("disbursements")
def blocked_view(request):
    """Finance Blocked Page."""
    activities = (
        Activity.objects.filter(deleted_at__isnull=True)
        .prefetch_related("schedule_cost_lines")
        .select_related("school")
    )

    # Fetch all active evidence activity IDs in one query
    from apps.evidence.models import EvidenceRecord

    activity_ids = [a.id for a in activities]
    evidence_activity_ids = set(
        EvidenceRecord.objects.filter(
            activity_id__in=activity_ids, quarantined=False
        ).values_list("activity_id", flat=True)
    )

    blocked_list = []
    for a in activities:
        # Check prefetch cache for budget lines
        has_budget = len(a.schedule_cost_lines.all()) > 0
        has_ev = a.id in evidence_activity_ids

        reasons = FinanceBlockedReasonService.get_blocked_reasons(
            a, has_evidence=has_ev, has_budget_lines=has_budget
        )
        if reasons:
            blocked_list.append(
                {"activity": a, "reasons": reasons, "reasons_label": ", ".join(reasons)}
            )

    context = {
        "blocked": blocked_list,
        "kpi_strip_items": [
            {
                "label": "Blocked Items",
                "value": str(len(blocked_list)),
                "helper": "Cannot clear until resolved",
                "icon": "warning",
                "variant": "danger",
            },
        ],
    }
    return render(request, "pages/accounts/blocked.html", context)


@require_page_permission("disbursements")
def variance_review_view(request):
    """Variance Review Page."""
    reviews = VarianceReview.objects.filter(status="pending").select_related(
        "activity", "activity__school"
    )
    total_variance = reviews.aggregate(v=Sum("variance"))["v"] or 0

    context = {
        "reviews": reviews,
        "kpi_strip_items": [
            {
                "label": "Pending Reviews",
                "value": str(reviews.count()),
                "helper": "Actual spend vs. disbursed",
                "icon": "warning",
                "variant": "warning",
            },
            {
                "label": "Total Variance",
                "value": _ugx_compact(abs(total_variance)),
                "helper": "Absolute sum",
                "icon": "currency",
                "variant": "danger" if total_variance > 0 else "finance",
            },
        ],
    }
    return render(request, "pages/accounts/variance_review.html", context)


@require_page_permission("disbursements")
def returned_view(request):
    """Returned Finance Items Page."""
    returns = FinanceReturn.objects.filter(status="pending").select_related(
        "activity", "activity__school"
    )

    context = {
        "returns": returns,
        "kpi_strip_items": [
            {
                "label": "Awaiting Correction",
                "value": str(returns.count()),
                "helper": "Returned for fixes",
                "icon": "warning",
                "variant": "danger",
            },
        ],
    }
    return render(request, "pages/accounts/returned.html", context)


@require_page_permission("disbursements")
def cleared_view(request):
    """Cleared / Closed Finance Ledger."""
    closed_activities = list(
        Activity.objects.filter(deleted_at__isnull=True, status="closed")
        .select_related("school", "cluster")
        .prefetch_related(
            "schedule_cost_lines",
            "disbursements",
            "accountability_records",
            "netsuite_expenses",
        )
        .order_by("-updated_at")
    )
    for act in closed_activities:
        act.approved_amount = _activity_cost(act)
        disb = act.disbursements.all()
        act.disbursed_amount = sum(d.amount_disbursed for d in disb)
        rec = act.accountability_records.first()
        act.spend_amount = rec.actual_spend if rec else act.disbursed_amount
        act.variance_amount = rec.variance if rec else 0
        ns = act.netsuite_expenses.first()
        act.netsuite_id = ns.netsuite_expense_id if ns else None

    context = {
        "closed": closed_activities,
        "kpi_strip_items": [
            {
                "label": "Closed Activities",
                "value": str(len(closed_activities)),
                "helper": "Fully cleared",
                "icon": "check",
                "variant": "success",
            },
            {
                "label": "Total Disbursed",
                "value": _ugx_compact(
                    sum(a.disbursed_amount for a in closed_activities)
                ),
                "helper": "Across closed activities",
                "icon": "currency",
                "variant": "finance",
            },
        ],
    }
    return render(request, "pages/accounts/cleared.html", context)


@require_page_permission("disbursements")
def activity_finance_detail_view(request, activity_id):
    """One complete finance view for a single activity."""
    a = get_object_or_404(Activity, id=activity_id)
    costs = a.schedule_cost_lines.all()
    disbursements = a.disbursements.all()
    partner_payments = a.partner_payments.all()
    reimbursements = a.reimbursement_claims.all()
    accountability = a.accountability_records.all()
    netsuite = a.netsuite_expenses.all()
    audit_logs = a.finance_audit_logs.all().order_by("-timestamp")
    blocked_reasons = FinanceBlockedReasonService.get_blocked_reasons(a)

    latest_accountability = accountability.order_by("-submitted_at").first()

    context = {
        "act": a,
        "costs": costs,
        "disbursements": disbursements,
        "partner_payments": partner_payments,
        "reimbursements": reimbursements,
        "accountability": accountability,
        "netsuite": netsuite,
        "audit_logs": audit_logs,
        "blocked_reasons": blocked_reasons,
        "methods": ["Mobile Money", "Bank Transfer", "Cheque", "Cash"],
        "today": timezone.now().date().isoformat(),
        "suggested_amount": latest_accountability.actual_spend
        if latest_accountability
        else "",
    }
    return render(request, "pages/accounts/activity_finance_detail.html", context)


@require_page_permission("disbursements")
def batch_payments_view(request):
    """Batch Payments Page."""
    advances = list(
        Activity.objects.filter(
            deleted_at__isnull=True, payment_status="pending", delivery_type="staff"
        ).prefetch_related("schedule_cost_lines")
    )
    partners = list(
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="partner",
            status="ia_verified",
            payment_status__in=["pending", "ia_confirmed"],
        ).prefetch_related("schedule_cost_lines")
    )
    reimbursements = ReimbursementClaim.objects.filter(status="pending")

    for a in advances:
        a.approved_amount = _activity_cost(a)
    for a in partners:
        a.approved_amount = _activity_cost(a)

    advances_total = sum(a.approved_amount for a in advances)
    partners_total = sum(a.approved_amount for a in partners)
    reimbursements_total = sum(c.reimbursement_amount for c in reimbursements)

    context = {
        "advances": advances,
        "partners": partners,
        "reimbursements": reimbursements,
        "advances_total": advances_total,
        "partners_total": partners_total,
        "reimbursements_total": reimbursements_total,
        "kpi_strip_items": [
            {
                "label": "Batch Total",
                "value": _ugx_compact(
                    advances_total + partners_total + reimbursements_total
                ),
                "helper": "All queued payouts",
                "icon": "currency",
                "variant": "finance",
            },
            {
                "label": "Advances Queued",
                "value": str(len(advances)),
                "helper": _ugx_compact(advances_total),
                "icon": "clock",
                "variant": "blue",
            },
            {
                "label": "Partner Payments Queued",
                "value": str(len(partners)),
                "helper": _ugx_compact(partners_total),
                "icon": "users",
                "variant": "purple",
            },
            {
                "label": "Reimbursements Queued",
                "value": str(reimbursements.count()),
                "helper": _ugx_compact(reimbursements_total),
                "icon": "report",
                "variant": "warning",
            },
        ],
    }
    return render(request, "pages/accounts/batch_payments.html", context)


@require_page_permission("disbursements")
def approval_history_view(request):
    """Finance Approval History Page.

    WeeklyFundRequest has a single-tier lifecycle (owner confirms → accountant
    disburses → accountability is cleared) — there is no separate PL/CD/RVP
    sign-off stage on this model, so the ledger shows the three real
    milestones it actually tracks instead of fabricating an approval chain.
    """
    DISBURSED_ONWARD = ["disbursed", "paid", "closed", "cleared", "accounted"]
    CONFIRMED_ONWARD = ["confirmed_for_advance"] + DISBURSED_ONWARD

    requests = list(WeeklyFundRequest.objects.all().order_by("-week_start_date"))
    for r in requests:
        r.is_confirmed = r.status in CONFIRMED_ONWARD
        r.is_disbursed = r.status in DISBURSED_ONWARD
        r.is_accounted = r.accounted_amount is not None or r.status in [
            "closed",
            "cleared",
            "accounted",
        ]

    context = {
        "requests": requests,
        "kpi_strip_items": [
            {
                "label": "Total Requests",
                "value": str(len(requests)),
                "helper": "All fiscal years",
                "icon": "document",
                "variant": "neutral",
            },
            {
                "label": "Disbursed",
                "value": str(sum(1 for r in requests if r.is_disbursed)),
                "helper": "Funds released",
                "icon": "check",
                "variant": "success",
            },
            {
                "label": "Accounted",
                "value": str(sum(1 for r in requests if r.is_accounted)),
                "helper": "Fully reconciled",
                "icon": "shield",
                "variant": "blue",
            },
        ],
    }
    return render(request, "pages/accounts/approval_history.html", context)


@require_page_permission("disbursements")
def audit_log_view(request):
    """Finance Audit Log Page."""
    logs = (
        FinanceAuditLog.objects.all().select_related("activity").order_by("-timestamp")
    )

    context = {
        "logs": logs,
        "kpi_strip_items": [
            {
                "label": "Logged Events",
                "value": str(logs.count()),
                "helper": "All finance activity",
                "icon": "document",
                "variant": "neutral",
            },
        ],
    }
    return render(request, "pages/accounts/audit_log.html", context)


@require_page_permission("disbursements")
def monthly_request_view(request):
    """Monthly Country Finance Request Page — a live consolidation of this
    month's costed activity lines, grouped the same way as the budget board
    (apps.budget.services) and the fund-request category taxonomy used
    elsewhere in Finance."""
    from apps.core.fy import get_operational_fy, get_quarter_for_date
    from apps.activities.models import ActivityScheduleCostLine

    fy = get_operational_fy()
    quarter = get_quarter_for_date()
    today = timezone.now()

    month_lines = ActivityScheduleCostLine.objects.filter(
        fiscal_year=fy, month=today.month
    ).select_related("activity")

    staff_visits_total = (
        month_lines.filter(
            activity__delivery_type="staff",
            activity__activity_type__in=VISIT_TYPES,
        ).aggregate(v=Sum("amount"))["v"]
        or 0
    )
    partner_total = (
        month_lines.filter(activity__delivery_type="partner").aggregate(
            v=Sum("amount")
        )["v"]
        or 0
    )
    training_meeting_total = (
        month_lines.filter(activity__delivery_type="staff")
        .exclude(activity__activity_type__in=VISIT_TYPES)
        .aggregate(v=Sum("amount"))["v"]
        or 0
    )
    reimbursements_total = (
        ReimbursementClaim.objects.filter(
            created_at__year=today.year, created_at__month=today.month
        ).aggregate(v=Sum("reimbursement_amount"))["v"]
        or 0
    )
    aggregate_total = (
        staff_visits_total
        + partner_total
        + training_meeting_total
        + reimbursements_total
    )

    context = {
        "fy": fy,
        "quarter": quarter,
        "month_label": today.strftime("%B %Y"),
        "breakdown": {
            "staff_visits": staff_visits_total,
            "partner": partner_total,
            "trainings_meetings": training_meeting_total,
            "reimbursements": reimbursements_total,
            "total": aggregate_total,
        },
        "activity_count": month_lines.values("activity_id").distinct().count(),
    }
    return render(request, "pages/accounts/monthly_request.html", context)


@require_page_permission("disbursements")
def weekly_requests_view(request):
    """Weekly Fund Request Review Page."""
    requests = WeeklyFundRequest.objects.all().order_by("-week_start_date")
    total_requested = requests.aggregate(v=Sum("total_amount"))["v"] or 0
    total_disbursed = requests.aggregate(v=Sum("disbursed_amount"))["v"] or 0

    context = {
        "requests": requests,
        "kpi_strip_items": [
            {
                "label": "Weekly Requests",
                "value": str(requests.count()),
                "helper": "All weeks",
                "icon": "calendar",
                "variant": "neutral",
            },
            {
                "label": "Total Requested",
                "value": _ugx_compact(total_requested),
                "helper": "Sum across weeks",
                "icon": "currency",
                "variant": "finance",
            },
            {
                "label": "Total Disbursed",
                "value": _ugx_compact(total_disbursed),
                "helper": "Released so far",
                "icon": "check",
                "variant": "success",
            },
        ],
    }
    return render(request, "pages/accounts/weekly_requests.html", context)
