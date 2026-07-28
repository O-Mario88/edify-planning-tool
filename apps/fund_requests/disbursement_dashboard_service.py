"""Fund Disbursement Dashboard — the Accountant's finance execution center.

The dashboard receives only approved, valid, scheduled, costed fund requests.
The accountant releases approved funds, tracks balances, holds/returns risky
items, monitors reconciliation, and closes finance after accountability +
NetSuite confirmation. The accountant never creates budgets or fund requests
here — every queue item was generated upstream by the planning workflow:

    Scheduled Activities → ActivityBudgetLines → Fund Request → PL/CD/RVP
    approval → Accountant Disbursement Queue → Disbursement → Execution →
    Evidence + SF ID → IA → Accountability → NetSuite → Cleared → Closed.

Queue sources (all real, no fabrication):
  • Monthly team fund plans   — FundRequest(period="monthly") from the PL gate
  • Weekly advances           — WeeklyFundRequest (owner-confirmed)
  • Partner payments          — IA-verified partner activities awaiting payment
  • Reimbursements            — self-funded advances with submitted claims
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.donut import build_rings
from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy

from .pl_approval_service import (
    CATEGORY_ORDER,
    MIX_COLORS,
    MONTHS,
    _category,
    _ugx,
)

# Monthly FundRequest status buckets.
M_PENDING_APPROVAL = {
    "submitted",
    "submitted_to_pl",
    "approved_by_pl",
    "submitted_to_cd",
    "approved_by_cd",
    "submitted_to_rvp",
    "approved_by_rvp",
}
M_PENDING_DISB = {"sent_to_accountant"}
M_RETURNED = {
    "returned",
    "rejected",
    "returned_by_pl",
    "returned_by_cd",
    "returned_by_rvp",
    "returned_by_accountant",
}

STATUS_OPTIONS = [
    "Pending Approval",
    "Pending Disbursement",
    "Held",
    "Disbursed",
    "Awaiting Reconciliation",
    "Returned",
    "Closed",
]
STATUS_TONES = {
    "Pending Approval": "neutral",
    "Pending Disbursement": "warning",
    "Held": "warning",
    "Disbursed": "success",
    "Awaiting Reconciliation": "info",
    "Returned": "danger",
    "Closed": "neutral",
}

HOLD_REASONS = [
    "Waiting for approver clarification",
    "Cash not available",
    "Bank issue",
    "Payment verification pending",
    "Policy exception",
    "High-risk request",
]
RETURN_REASONS = [
    "Approval incomplete",
    "Amount mismatch",
    "Missing payment details",
    "Duplicate request",
    "Budget line issue",
    "Wrong period",
    "Missing supporting document",
    "Cost Catalogue mismatch",
    "Unclear plan",
    "Other",
]
PAYMENT_METHODS = ["Mobile Money", "Bank Transfer", "Cash", "Cheque"]

RULES = [
    "Disbursements must match approved plans.",
    "All disbursements require supporting vouchers.",
    "Receipts must be submitted within the configured period.",
    "Unused funds must be returned within the plan period.",
    "Non-compliance can hold future funds.",
    "Final clearance requires IA verification.",
    "NetSuite Expense ID is required to close accountability.",
]

# Weekly budget-line types → human mix/breakdown labels.
LINE_TYPE_LABELS = {
    "transport": "Transport / Field Travel",
    "lunch": "Participant Meals",
    "participant_meals": "Participant Meals",
    "cluster_meeting_participant_meals": "Participant Meals",
    "venue": "Venue",
    "facilitation": "Facilitation",
    "mobilisation": "Mobilisation",
    "lump_sum": "Lump Sum",
}


def _require_accountant(principal):
    role = getattr(principal, "active_role", None)
    if role not in ("Accountant", "Admin"):
        raise Forbidden("Only a Program Accountant can access disbursements.")


def _require_accountant_action(principal):
    """Moving money is the Accountant's alone.

    Admin passes `_require_accountant` so the dashboard stays observable
    for support, but disburse/hold/release/return are finance clearance --
    the Platform Operations doctrine forbids Admin every one of them.
    """
    role = getattr(principal, "active_role", None)
    if role != "Accountant":
        raise Forbidden("Only a Program Accountant can act on disbursements.")


def _monthly_status(fr):
    """Queue status label for a monthly FundRequest."""
    s = fr.status
    if s in M_PENDING_APPROVAL:
        return "Pending Approval"
    if s in M_PENDING_DISB:
        return "Pending Disbursement"
    if s == "held":
        return "Held"
    if s == "disbursed":
        if fr.accountability_submitted_at and not fr.accountability_reviewed_at:
            return "Awaiting Reconciliation"
        return "Disbursed"
    if s in M_RETURNED:
        return "Returned"
    if s == "closed":
        return "Closed"
    return "Pending Approval"


def _weekly_status(w, has_pending_accountability=False):
    s = w.status
    if s == "pending_responsible_confirmation":
        return "Pending Approval"
    if s == "confirmed_for_advance":
        return "Pending Disbursement"
    if s == "disbursed":
        # Accountability now lives on the child AdvanceRequests (the
        # responsible user submits spend + NetSuite Code per advance) — a
        # submitted-but-unreviewed advance puts the request in reconciliation.
        if has_pending_accountability or (
            w.accountability_submitted_at and not w.accountability_reviewed_at
        ):
            return "Awaiting Reconciliation"
        return "Disbursed"
    if s in ("returned_by_accountant", "returned"):
        return "Returned"
    if s == "accounted":
        return "Closed"
    return "Pending Approval"


def weekly_status_buckets(wfrs) -> dict:
    """Canonical status bucket per WeeklyFundRequest (STATUS_OPTIONS labels).

    Single source of truth for "what queue-stage is this weekly advance in" —
    shared by the Disbursement Dashboard (_weekly_items) and the Accountant
    home dashboard (finance_operating_views.accountant_dashboard_view) so
    "current budget status" KPIs cannot diverge between the two surfaces.
    Returns {wfr.id: bucket_label}.
    """
    from .models import WeeklyFundRequestLine

    wfrs = list(wfrs)
    pending_wfr_ids = set(
        WeeklyFundRequestLine.objects.filter(
            weekly_fund_request__in=wfrs,
            activity_budget_line__advance_requests__status="accountability_pending",
        ).values_list("weekly_fund_request_id", flat=True)
    )
    return {
        w.id: _weekly_status(w, has_pending_accountability=w.id in pending_wfr_ids)
        for w in wfrs
    }


def _chain(stages):
    """[(label, state)] → chain dicts. States: approved|pending|returned|held|
    done|not_started|not_required."""
    return [{"label": lbl, "state": st} for lbl, st in stages]


def _monthly_chain(fr):
    s = fr.status
    pl = "pending"
    fin = "not_started"
    disb = "not_started"
    if s in M_RETURNED:
        pl = "returned" if s in ("returned_by_pl", "returned") else "approved"
        if s == "returned_by_accountant":
            fin = "returned"
    elif s in M_PENDING_DISB:
        pl, fin = "approved", "pending"
    elif s == "held":
        pl, fin = "approved", "held"
    elif s in ("disbursed", "closed"):
        pl, fin, disb = "approved", "approved", "done"
    return _chain(
        [
            ("PL", pl),
            ("CD", "not_required"),
            ("RVP", "not_required"),
            ("Finance", fin),
            ("Disbursement", disb),
        ]
    )


def _weekly_chain(w):
    s = w.status
    owner = "pending" if s == "pending_responsible_confirmation" else "approved"
    fin = "not_started"
    disb = "not_started"
    if s == "confirmed_for_advance":
        fin = "pending"
    elif s in ("disbursed", "accounted"):
        fin, disb = "approved", "done"
    elif s in ("returned_by_accountant", "returned"):
        fin = "returned"
    return _chain([("Owner", owner), ("Finance", fin), ("Disbursement", disb)])


def _user_names(ids):
    from apps.accounts.models import User

    return dict(
        User.objects.filter(id__in=[i for i in ids if i]).values_list("id", "name")
    )


def _month_of_period_key(period_key):
    # "2026-M4" → 4
    try:
        return int(period_key.rsplit("M", 1)[1])
    except (IndexError, ValueError):
        return None


# ── Queue building ────────────────────────────────────────────────────────────
def fy_totals_all_fund_types(fy) -> dict:
    """The financial year's money across monthly plans and weekly advances.

    The Accountant's home KPI strip used to build these from WeeklyFundRequest
    alone while naming them "Total Approved Funds", "Total Disbursed" and
    "Budget Utilization" -- figures a reader takes as the country's, not one
    fund type's. Monthly fund plans, which carry most of the value, were absent
    from every one of them.

    Both fund types are classified through the same two canonical status
    functions the queue uses (`_monthly_status`, `_weekly_status`), so a stage
    means the same thing here as it does on the Disbursement Dashboard.

    Partner payables and reimbursements are deliberately excluded: both are
    "due now" queues with no financial year of their own (see
    `_partner_items`), and folding a month-agnostic backlog into an FY total
    would make the figure mean neither one thing nor the other.

    Returns raw integers; callers format them.
    """
    from .models import FundRequest, WeeklyFundRequest

    monthly = list(FundRequest.objects.filter(period="monthly", fy=fy))
    weekly = list(
        WeeklyFundRequest.objects.filter(fy=fy).exclude(
            status__in=["not_requested", "cancelled"]
        )
    )
    weekly_buckets = weekly_status_buckets(weekly)

    staged: list[tuple[str, int, int, int]] = [
        (
            _monthly_status(f),
            f.total_amount or 0,
            f.disbursed_amount or 0,
            f.accounted_amount or 0,
        )
        for f in monthly
    ] + [
        (
            weekly_buckets[w.id],
            w.total_amount or 0,
            w.disbursed_amount or 0,
            w.accounted_amount or 0,
        )
        for w in weekly
    ]

    def _sum(*labels):
        return sum(total for status, total, _d, _a in staged if status in labels)

    def _count(*labels):
        return sum(1 for status, _t, _d, _a in staged if status in labels)

    # "Approved" = cleared approval and disbursable-or-beyond. Held belongs
    # here for the same reason it belongs in approved-not-disbursed: a hold
    # pauses approved money rather than rejecting it.
    approved = _sum(
        "Pending Disbursement", "Held", "Disbursed", "Awaiting Reconciliation", "Closed"
    )
    disbursed = sum(d for _s, _t, d, _a in staged)
    accounted = sum(a for _s, _t, _d, a in staged)

    return {
        "approved": approved,
        "pending_disbursement": _sum("Pending Disbursement", "Held"),
        "pending_disbursement_count": _count("Pending Disbursement", "Held"),
        "awaiting_approval": _sum("Pending Approval"),
        "awaiting_approval_count": _count("Pending Approval"),
        "disbursed": disbursed,
        "accounted": accounted,
        "returned": _sum("Returned"),
        "disbursed_count": _count("Disbursed", "Awaiting Reconciliation", "Closed"),
        "accounted_count": _count("Closed"),
        "record_count": len(staged),
    }


def month_overview_all_fund_types(fy, month) -> dict:
    """The month's money across every fund type, in raw UGX.

    THE canonical "where is this month's money" answer, shared by the
    Disbursement Dashboard and the Accountant's home dashboard so the two
    cannot drift apart again.

    Both surfaces used to carry a card titled "This Month Overview" with the
    same five rows, but the Accountant's home dashboard summed
    WeeklyFundRequest alone while this workspace summed the consolidated
    queue -- monthly fund plans, weekly advances, partner payments and
    reimbursements. On the seed that was UGX 1.25M against UGX 3.3M+: most of
    the month's money missing from the card an Accountant lands on.

    `approved_not_disbursed` includes Held, because a hold pauses approved
    money rather than rejecting it: `hold()` only accepts a request that has
    finished the approval chain, and `release()` puts it straight back.

    Returns raw integers; callers format them.
    """
    # Month-scoped fund types only. `_partner_items` describes itself as
    # "month-agnostic" and `_reimbursement_items` as "due now": both are
    # standing payable queues that belong to no particular month. Including
    # them made rows 1-3 of this card cover any month while rows 4-5 (Disbursed,
    # Reconciled) covered this one -- one card, two periods. They remain in the
    # queue list beside it, which is a work list rather than a period total.
    names: dict[str, str] = {}
    queue = _monthly_items(fy, month, names) + _weekly_items(fy, month, names)

    def _sum(status):
        return sum(i["amount"] for i in queue if i["status"] == status)

    from .models import FundRequest, WeeklyFundRequest

    disbursed = sum(
        f.disbursed_amount or f.total_amount
        for f in FundRequest.objects.filter(
            period="monthly",
            fy=fy,
            period_key=f"{fy}-M{month}",
            status__in=["disbursed", "closed"],
        )
    ) + sum(
        w.disbursed_amount or w.total_amount
        for w in WeeklyFundRequest.objects.filter(
            fy=fy,
            week_start_date__month=month,
            status__in=["disbursed", "accountability_pending", "accounted"],
        )
    )
    reconciled = sum(
        f.accounted_amount or 0
        for f in FundRequest.objects.filter(
            period="monthly",
            fy=fy,
            period_key=f"{fy}-M{month}",
            accountability_reviewed_at__isnull=False,
        )
    ) + sum(
        w.accounted_amount or 0
        for w in WeeklyFundRequest.objects.filter(
            fy=fy, week_start_date__month=month, status="accounted"
        )
    )

    return {
        "waiting_for_approval": _sum("Pending Approval"),
        "returned": _sum("Returned"),
        "approved_not_disbursed": _sum("Pending Disbursement") + _sum("Held"),
        "held": _sum("Held"),
        "disbursed": disbursed,
        "reconciled": reconciled,
    }


def _monthly_items(fy, month, names_out):
    from .models import FundRequest

    frs = list(
        FundRequest.objects.filter(period="monthly", fy=fy, period_key=f"{fy}-M{month}")
    )
    names = _user_names([f.submitted_by_user_id for f in frs])
    names_out.update(names)
    items = []
    for fr in frs:
        status = _monthly_status(fr)
        kind_label = (
            "Special Project Fund Plan"
            if fr.submitted_by_role == "ProjectCoordinator"
            else "Team Fund Plan"
        )
        items.append(
            {
                "key": f"fr:{fr.id}",
                "kind": "monthly",
                "kind_label": kind_label,
                "name": names.get(fr.submitted_by_user_id, "CCEO"),
                "subtitle": f"{MONTHS[month]} {fy} · {fr.activity_count} activities",
                "amount": fr.total_amount,
                "amount_fmt": _ugx(fr.total_amount),
                "status": status,
                "status_tone": STATUS_TONES[status],
                "obj": fr,
                "sort_time": fr.reviewed_at or fr.updated_at,
            }
        )
    return items


def _weekly_items(fy, month, names_out):
    from .models import WeeklyFundRequest

    wfrs = list(
        WeeklyFundRequest.objects.filter(fy=fy, week_start_date__month=month).exclude(
            status__in=["not_requested", "cancelled"]
        )
    )
    names = _user_names([w.responsible_user for w in wfrs])
    names_out.update(names)
    buckets = weekly_status_buckets(wfrs)
    items = []
    for w in wfrs:
        status = buckets[w.id]
        items.append(
            {
                "key": f"wfr:{w.id}",
                "kind": "weekly",
                "kind_label": "Weekly Advance",
                "name": names.get(w.responsible_user, "Staff"),
                "subtitle": f"Week {w.week_start_date:%b %-d} – {w.week_end_date:%b %-d}",
                "amount": w.total_amount,
                "amount_fmt": _ugx(w.total_amount),
                "status": status,
                "status_tone": STATUS_TONES[status],
                "obj": w,
                "sort_time": w.disbursed_at or w.updated_at,
            }
        )
    return items


def _partner_items():
    """IA-verified partner activities awaiting payment — due now, month-agnostic."""
    from apps.activities.models import Activity

    from .finance_services import PARTNER_PAYABLE_STATUSES

    acts = list(
        Activity.objects.filter(
            deleted_at__isnull=True,
            delivery_type="partner",
            status="ia_verified",
            payment_status__in=PARTNER_PAYABLE_STATUSES,
        ).select_related("school")[:200]
    )
    if not acts:
        return []
    from apps.partners.models import Partner

    partner_names = dict(
        Partner.objects.filter(
            id__in=[a.assigned_partner_id for a in acts if a.assigned_partner_id]
        ).values_list("id", "name")
    )
    from apps.activities.models import ActivityScheduleCostLine

    totals = {}
    for li in ActivityScheduleCostLine.objects.filter(
        activity_id__in=[a.id for a in acts]
    ):
        totals[li.activity_id] = totals.get(li.activity_id, 0) + li.amount
    items = []
    for a in acts:
        amt = totals.get(a.id, 0)
        items.append(
            {
                "key": f"act:{a.id}",
                "kind": "partner",
                "kind_label": "Partner Payment",
                "name": partner_names.get(a.assigned_partner_id, "Partner"),
                "subtitle": (
                    a.school.name if a.school_id else a.get_activity_type_display()
                ),
                "amount": amt,
                "amount_fmt": _ugx(amt),
                "status": "Pending Disbursement",
                "status_tone": STATUS_TONES["Pending Disbursement"],
                "obj": a,
                "sort_time": a.updated_at,
            }
        )
    return items


def _reimbursement_items(names_out):
    """Self-funded advances whose reimbursement claims are submitted — due now."""
    from .models import AdvanceRequest

    advs = list(
        AdvanceRequest.objects.filter(status="reimbursement_submitted").select_related(
            "activity"
        )[:25]
    )
    names = _user_names([a.responsible_user_id for a in advs])
    names_out.update(names)
    items = []
    for adv in advs:
        items.append(
            {
                "key": f"adv:{adv.id}",
                "kind": "reimbursement",
                "kind_label": "Reimbursement",
                "name": names.get(adv.responsible_user_id, "Staff"),
                "subtitle": adv.activity.get_activity_type_display()
                if adv.activity_id
                else "Self-funded activity",
                "amount": adv.amount,
                "amount_fmt": _ugx(adv.amount),
                "status": "Pending Disbursement",
                "status_tone": STATUS_TONES["Pending Disbursement"],
                "obj": adv,
                "sort_time": adv.accountability_submitted_at or adv.updated_at,
            }
        )
    return items


_STATUS_SORT = {
    "Pending Disbursement": 0,
    "Held": 1,
    "Pending Approval": 2,
    "Awaiting Reconciliation": 3,
    "Disbursed": 4,
    "Returned": 5,
    "Closed": 6,
}


# ── Detail building ───────────────────────────────────────────────────────────
def _monthly_detail(item, fy, month):
    """Funding breakdown + plan snapshot for a monthly plan, derived from its
    FundRequestItems' live budget lines (accountant never edits amounts)."""
    from apps.activities.models import ActivityScheduleCostLine

    fr = item["obj"]
    line_ids = list(fr.items.values_list("activity_schedule_cost_line_id", flat=True))
    lines = list(
        ActivityScheduleCostLine.objects.filter(id__in=line_ids).select_related(
            "activity", "activity__school"
        )
    )
    cats: dict[str, dict] = {}
    acts = {}
    schools = set()
    for li in lines:
        a = li.activity
        acts[a.id] = a
        if a.school_id:
            schools.add(a.school_id)
        cat = _category(a.activity_type, a.delivery_type)
        d = cats.setdefault(cat, {"total": 0, "acts": set()})
        d["total"] += li.amount
        d["acts"].add(a.id)
    breakdown = [
        {
            "category": c,
            "qty": len(cats[c]["acts"]),
            "unit_cost": _ugx(round(cats[c]["total"] / len(cats[c]["acts"])))
            if cats[c]["acts"]
            else "—",
            "total": _ugx(cats[c]["total"]),
            "raw_total": cats[c]["total"],
        }
        for c in CATEGORY_ORDER
        if c in cats
    ]
    act_list = list(acts.values())
    from .pl_approval_service import CLUSTER_MEETING, TRAINING_TYPES

    snapshot = [
        (
            "Planned schools by staff",
            len(
                {
                    a.school_id
                    for a in act_list
                    if a.school_id and a.delivery_type != "partner"
                }
            ),
        ),
        (
            "Partner school visits",
            sum(1 for a in act_list if a.delivery_type == "partner"),
        ),
        (
            "Cluster meetings planned",
            sum(1 for a in act_list if a.activity_type in CLUSTER_MEETING),
        ),
        (
            "Trainings planned",
            sum(1 for a in act_list if a.activity_type in TRAINING_TYPES),
        ),
        ("Total schools covered", len(schools)),
    ]
    return breakdown, snapshot


def _weekly_detail(item):
    w = item["obj"]
    groups: dict[str, dict] = {}
    for line in w.lines.all():
        label = LINE_TYPE_LABELS.get(
            line.line_item_type, line.line_item_type.replace("_", " ").title()
        )
        g = groups.setdefault(label, {"qty": 0, "total": 0})
        g["qty"] += line.quantity
        g["total"] += line.total_cost
    breakdown = [
        {
            "category": label,
            "qty": g["qty"],
            "unit_cost": _ugx(round(g["total"] / g["qty"])) if g["qty"] else "—",
            "total": _ugx(g["total"]),
            "raw_total": g["total"],
        }
        for label, g in sorted(groups.items(), key=lambda kv: -kv[1]["total"])
    ]
    snapshot = [
        ("Week", f"{w.week_start_date:%b %-d} – {w.week_end_date:%b %-d}"),
        ("Budget lines", w.lines.count()),
        ("Owner confirmed", "Yes" if w.confirmed_at else "Not yet"),
    ]
    return breakdown, snapshot


def _partner_detail(item):
    from apps.activities.models import ActivityScheduleCostLine

    a = item["obj"]
    lines = list(ActivityScheduleCostLine.objects.filter(activity_id=a.id))
    breakdown = [
        {
            "category": li.label,
            "qty": li.quantity,
            "unit_cost": _ugx(li.unit_cost),
            "total": _ugx(li.amount),
            "raw_total": li.amount,
        }
        for li in lines
    ]
    snapshot = [
        ("Activity", a.get_activity_type_display()),
        ("School", a.school.name if a.school_id else "—"),
        ("IA verification", "Verified"),
        ("Salesforce ID", a.salesforce_activity_id or "Missing"),
    ]
    return breakdown, snapshot


def _reimb_detail(item):
    adv = item["obj"]
    breakdown = [
        {
            "category": "Approved budget",
            "qty": 1,
            "unit_cost": _ugx(adv.amount),
            "total": _ugx(adv.amount),
            "raw_total": adv.amount,
        }
    ]
    if adv.accounted_amount is not None:
        breakdown.append(
            {
                "category": "Actual spend (claimed)",
                "qty": 1,
                "unit_cost": _ugx(adv.accounted_amount),
                "total": _ugx(adv.accounted_amount),
                "raw_total": adv.accounted_amount,
            }
        )
    snapshot = [
        ("Funding path", "Self-funded"),
        (
            "Claim submitted",
            f"{adv.accountability_submitted_at:%b %-d}"
            if adv.accountability_submitted_at
            else "—",
        ),
    ]
    return breakdown, snapshot


def _history(item):
    """Recent audit rows for the selected item — real trail, newest first."""
    try:
        from apps.audit.models import AuditLog

        if item["kind"] == "monthly":
            rows = AuditLog.objects.filter(
                subject_kind="FundRequest", subject_id=item["obj"].id
            ).order_by("-created_at")[:5]
            return [
                {
                    "action": r.action.split(".")[-1].replace("_", " ").title(),
                    "when": r.created_at.strftime("%b %-d, %-I:%M %p"),
                }
                for r in rows
            ]
    except Exception:  # noqa: BLE001
        pass
    return []


def _selected_detail(item, fy, month):
    kind = item["kind"]
    if kind == "monthly":
        breakdown, snapshot = _monthly_detail(item, fy, month)
        chain = _monthly_chain(item["obj"])
    elif kind == "weekly":
        breakdown, snapshot = _weekly_detail(item)
        chain = _weekly_chain(item["obj"])
    elif kind == "partner":
        breakdown, snapshot = _partner_detail(item)
        chain = _chain(
            [
                ("IA Verification", "approved"),
                ("Finance", "pending"),
                ("Payment", "not_started"),
            ]
        )
    else:
        breakdown, snapshot = _reimb_detail(item)
        chain = _chain(
            [
                ("Owner Claim", "approved"),
                ("Finance", "pending"),
                ("Payment", "not_started"),
            ]
        )

    obj = item["obj"]
    fr = obj if kind == "monthly" else None
    total = sum(b["raw_total"] for b in breakdown) or item["amount"]

    # Submitted-but-unreviewed accountability on a weekly item — the payload
    # the Accountant reviews (spend, returned, variance note, NetSuite Code,
    # all entered by the responsible user at submission).
    accountability = None
    if kind == "weekly":
        from .models import AdvanceRequest

        pending = list(
            AdvanceRequest.objects.filter(
                budget_line__weekly_request_lines__weekly_fund_request=obj,
                status="accountability_pending",
            ).select_related("budget_line")
        )
        if pending:
            accounted_total = sum(a.accounted_amount or 0 for a in pending)
            returned_total = sum(a.returned_amount or 0 for a in pending)
            disbursed_total = sum(
                (a.disbursed_amount or a.amount or 0) for a in pending
            )
            accountability = {
                "netsuite_id": pending[0].accountability_netsuite_id,
                "accounted_total": _ugx(accounted_total),
                "returned_total": _ugx(returned_total),
                "disbursed_total": _ugx(disbursed_total),
                "raw_accounted_total": accounted_total,
                "raw_returned_total": returned_total,
                "variance_note": next(
                    (a.last_note for a in pending if a.last_note), None
                ),
                "advances": [
                    {
                        "id": a.id,
                        "label": a.budget_line.label,
                        "netsuite_id": a.accountability_netsuite_id,
                        "accounted": _ugx(a.accounted_amount or 0),
                        "returned": _ugx(a.returned_amount or 0),
                    }
                    for a in pending
                ],
            }

    detail = {
        **{
            k: item[k]
            for k in (
                "key",
                "kind",
                "kind_label",
                "name",
                "subtitle",
                "status",
                "status_tone",
            )
        },
        "amount_fmt": _ugx(item["amount"] or total),
        "raw_amount": item["amount"] or total,
        "chain": chain,
        "breakdown": breakdown,
        "snapshot": snapshot,
        "history": _history(item),
        # Action gating: Disburse only when the required approval chain is done.
        "can_disburse": item["status"] == "Pending Disbursement" and kind == "monthly",
        "can_hold": item["status"] == "Pending Disbursement" and kind == "monthly",
        "can_release": item["status"] == "Held",
        "can_return": item["status"] in ("Pending Disbursement", "Held")
        and kind == "monthly",
        "fund_request_id": fr.id if fr else None,
        # Existing endpoints handle non-monthly kinds (weekly/partner/reimburse).
        "weekly_id": obj.id if kind == "weekly" else None,
        "activity_id": obj.id if kind == "partner" else None,
        "advance_id": obj.id if kind == "reimbursement" else None,
        "weekly_can_disburse": kind == "weekly"
        and item["status"] == "Pending Disbursement",
        # Accountability review: submitted advances await the Accountant's
        # clearance (approve_accountability enforces NetSuite Code + IA gates).
        "can_confirm_accountability": accountability is not None,
        "accountability": accountability,
        "held_reason": getattr(obj, "held_reason", None),
        "review_note": getattr(obj, "review_note", None),
        "disbursed_at": getattr(obj, "disbursed_at", None),
        "disburse_method": getattr(obj, "disburse_method", None),
        "disburse_reference": getattr(obj, "disburse_reference", None),
        "receipt_confirmed_at": getattr(obj, "receipt_confirmed_at", None),
    }
    return detail


# ── Reconciliation tracker ────────────────────────────────────────────────────
def _recon_status(obj, activities_missing_sf):
    if not obj.accountability_submitted_at:
        return "Awaiting Receipts"
    if activities_missing_sf:
        return "Awaiting Salesforce Match"
    if not obj.accountability_netsuite_id:
        return "Awaiting NetSuite ID"
    if not obj.accountability_reviewed_at:
        return "Partially Accounted"
    return "Closed"


RECON_NEXT_ACTION = {
    "Awaiting Receipts": "Requester uploads receipts",
    "Awaiting Salesforce Match": "Enter Activity SF ID",
    "Awaiting NetSuite ID": "Enter NetSuite Expense ID",
    "Partially Accounted": "Accountant reviews accountability",
    "Closed": "—",
}


def _reconciliation(fy, names):
    """Every disbursed-but-not-closed fund item enters reconciliation tracking."""
    from apps.activities.models import Activity

    from .models import FundRequest, WeeklyFundRequest

    today = timezone.now()
    rows = []
    counts = {k: 0 for k in RECON_NEXT_ACTION}

    monthly = list(
        FundRequest.objects.filter(period="monthly", fy=fy, status="disbursed")
    )
    # Activities on disbursed monthly plans that still miss a Salesforce ID.
    fr_act_ids = {}
    for fr in monthly:
        fr_act_ids[fr.id] = list(fr.items.values_list("activity_id", flat=True))
    all_act_ids = [aid for ids in fr_act_ids.values() for aid in ids]
    missing_sf = set(
        Activity.objects.filter(
            id__in=all_act_ids,
            salesforce_activity_id__isnull=True,
            status__in=["completed", "closed", "ia_verified"],
        ).values_list("id", flat=True)
    )
    for fr in monthly:
        status = _recon_status(
            fr, [a for a in fr_act_ids.get(fr.id, []) if a in missing_sf]
        )
        counts[status] += 1
        if status == "Closed":
            continue
        rows.append(
            {
                "label": f"{names.get(fr.submitted_by_user_id, 'CCEO')} — {fr.period_key} Fund Plan",
                "amount_fmt": _ugx(fr.disbursed_amount or fr.total_amount),
                "status": status,
                "days": (today - fr.disbursed_at).days if fr.disbursed_at else 0,
                "next_action": RECON_NEXT_ACTION[status],
            }
        )

    for w in WeeklyFundRequest.objects.filter(
        fy=fy, status__in=["disbursed", "accountability_pending"]
    ):
        status = _recon_status(w, [])
        counts[status] += 1
        if status == "Closed":
            continue
        rows.append(
            {
                "label": f"{names.get(w.responsible_user, 'Staff')} — Week {w.week_start_date:%b %-d}",
                "amount_fmt": _ugx(w.disbursed_amount or w.total_amount),
                "status": status,
                "days": (today - w.disbursed_at).days if w.disbursed_at else 0,
                "next_action": RECON_NEXT_ACTION[status],
            }
        )
    counts["Closed"] += WeeklyFundRequest.objects.filter(
        fy=fy, status="accounted"
    ).count()
    rows.sort(key=lambda r: -r["days"])
    return {
        # Template-friendly keys (no dict-lookup filter needed).
        "counts": {
            "receipts": counts["Awaiting Receipts"],
            "sf": counts["Awaiting Salesforce Match"],
            "netsuite": counts["Awaiting NetSuite ID"],
            "partial": counts["Partially Accounted"],
            "closed": counts["Closed"],
        },
        "raw_counts": counts,
        "rows": rows[:8],
    }


# ── Recent disbursement activity ──────────────────────────────────────────────
def _recent(fy, names):
    from .models import FundRequest, PartnerPayment, WeeklyFundRequest

    events = []
    for fr in FundRequest.objects.filter(
        period="monthly", disbursed_at__isnull=False
    ).order_by("-disbursed_at")[:6]:
        events.append(
            {
                "who": names.get(fr.submitted_by_user_id, "CCEO"),
                "what": f"{fr.period_key} Fund Plan",
                "action": "Disbursed",
                "tone": "success",
                "amount_fmt": _ugx(fr.disbursed_amount or fr.total_amount),
                "at": fr.disbursed_at,
            }
        )
    for w in WeeklyFundRequest.objects.filter(disbursed_at__isnull=False).order_by(
        "-disbursed_at"
    )[:6]:
        events.append(
            {
                "who": names.get(w.responsible_user, "Staff"),
                "what": f"Weekly Advance {w.week_start_date:%b %-d}",
                "action": "Disbursed",
                "tone": "success",
                "amount_fmt": _ugx(w.disbursed_amount or w.total_amount),
                "at": w.disbursed_at,
            }
        )
    for p in PartnerPayment.objects.order_by("-payment_date")[:4]:
        events.append(
            {
                "who": p.partner_name,
                "what": "Partner Payment",
                "action": "Paid",
                "tone": "success",
                "amount_fmt": _ugx(p.amount_paid),
                "at": p.payment_date,
            }
        )
    for fr in FundRequest.objects.filter(
        period="monthly", status="returned_by_accountant"
    ).order_by("-reviewed_at")[:3]:
        if fr.reviewed_at:
            events.append(
                {
                    "who": names.get(fr.submitted_by_user_id, "CCEO"),
                    "what": f"{fr.period_key} Fund Plan",
                    "action": "Returned",
                    "tone": "danger",
                    "amount_fmt": _ugx(fr.total_amount),
                    "at": fr.reviewed_at,
                }
            )
    events = [e for e in events if e["at"]]
    events.sort(key=lambda e: e["at"], reverse=True)
    for e in events:
        e["when"] = e["at"].strftime("%b %-d, %-I:%M %p")
    return events[:6]


# ── The dashboard view-model ──────────────────────────────────────────────────
def get_disbursement_dashboard(principal, filters=None):
    _require_accountant(principal)
    filters = filters or {}
    fy = filters.get("fy") or get_operational_fy()
    month = int(filters.get("month") or timezone.now().month)
    status_filter = filters.get("status") or ""
    search = (filters.get("q") or "").strip().lower()
    selected_key = filters.get("item")

    names: dict[str, str] = {}
    queue = (
        _monthly_items(fy, month, names)
        + _weekly_items(fy, month, names)
        + _partner_items()
        + _reimbursement_items(names)
    )

    # Default the month to the busiest funded month if this one is empty.
    if not queue and not filters.get("month"):
        from .models import FundRequest

        busiest = (
            FundRequest.objects.filter(period="monthly", fy=fy)
            .values_list("period_key", flat=True)
            .first()
        )
        m = _month_of_period_key(busiest) if busiest else None
        if m and m != month:
            month = m
            queue = (
                _monthly_items(fy, month, names)
                + _weekly_items(fy, month, names)
                + _partner_items()
                + _reimbursement_items(names)
            )

    queue.sort(key=lambda i: (_STATUS_SORT.get(i["status"], 9), -i["amount"]))

    # Filters apply to the visible queue (KPIs stay month-truthful).
    visible = queue
    if status_filter:
        visible = [i for i in visible if i["status"] == status_filter]
    if search:
        visible = [
            i
            for i in visible
            if search in i["name"].lower()
            or search in i["kind_label"].lower()
            or search in i["subtitle"].lower()
        ]

    # ── KPIs ──────────────────────────────────────────────────────────────────
    def _sum(status):
        return sum(i["amount"] for i in queue if i["status"] == status)

    def _count(status):
        return sum(1 for i in queue if i["status"] == status)

    total_month = sum(i["amount"] for i in queue)
    pending_disb = _sum("Pending Disbursement")
    awaiting_appr = _sum("Pending Approval")
    held_amt = _sum("Held")
    returned_amt = _sum("Returned")

    today = timezone.now().date()
    from .models import FundRequest, WeeklyFundRequest

    disb_today = sum(
        f.disbursed_amount or f.total_amount
        for f in FundRequest.objects.filter(period="monthly", disbursed_at__date=today)
    ) + sum(
        w.disbursed_amount or w.total_amount
        for w in WeeklyFundRequest.objects.filter(disbursed_at__date=today)
    )
    sp_month = sum(
        i["amount"] for i in queue if i["kind_label"] == "Special Project Fund Plan"
    )

    kpis = [
        {
            "label": "Total Funds This Month",
            "value": _ugx(total_month),
            "icon": "finance",
            "variant": "primary",
            "helper": f"{len(queue)} item{'' if len(queue) == 1 else 's'}",
        },
        {
            "label": "Pending Disbursement",
            "value": _ugx(pending_disb),
            "icon": "clock",
            "variant": "warning",
            "helper": f"{_count('Pending Disbursement')} request{'' if _count('Pending Disbursement') == 1 else 's'}",
        },
        {
            "label": "Disbursed Today",
            "value": _ugx(disb_today),
            "icon": "check",
            "variant": "success",
            "helper": "Released today",
        },
        {
            "label": "Awaiting Approval Completion",
            "value": _ugx(awaiting_appr),
            "icon": "briefcase",
            "variant": "analytics",
            "helper": f"{_count('Pending Approval')} in approval chain",
        },
        {
            "label": "Held",
            "value": _ugx(held_amt),
            "icon": "warning",
            "variant": "danger",
            "helper": f"{_count('Held')} paused",
        },
        {
            "label": "Special Projects Funds",
            "value": _ugx(sp_month),
            "icon": "school",
            "variant": "info",
            "helper": "This month",
        },
    ]

    # ── Month overview + status donut ─────────────────────────────────────────
    # One implementation, two surfaces (see month_overview_all_fund_types); the
    # donut and the disbursed-this-month KPI below read the same figures the
    # card does, so a page cannot disagree with itself either.
    _overview_raw = month_overview_all_fund_types(fy, month)
    disbursed_month = _overview_raw["disbursed"]
    overview = {
        "waiting": _ugx(_overview_raw["waiting_for_approval"]),
        "returned": _ugx(_overview_raw["returned"]),
        "approved_not_disbursed": _ugx(_overview_raw["approved_not_disbursed"]),
        "disbursed": _ugx(_overview_raw["disbursed"]),
        "reconciled": _ugx(_overview_raw["reconciled"]),
    }

    donut_amounts = {
        "approved": pending_disb + held_amt,
        "pending": awaiting_appr,
        "disbursed": disbursed_month,
        "returned": returned_amt,
    }
    donut_total = sum(donut_amounts.values()) or 1
    donut = {k: round(v / donut_total * 100) for k, v in donut_amounts.items()}
    donut["total_fmt"] = _ugx(sum(donut_amounts.values()))

    # Concentric rings for the shared donut component: each stage a share of
    # the month's money, the centre reading the total.
    donut_rings = build_rings(
        [
            {
                "key": "disbursed",
                "label": "Disbursed",
                "value": disbursed_month,
                "display": _ugx(disbursed_month),
                "color": "var(--edify-success)",
            },
            {
                "key": "approved",
                "label": "Approved",
                "value": pending_disb + held_amt,
                "display": _ugx(pending_disb + held_amt),
                "color": "var(--edify-accent)",
            },
            {
                "key": "pending",
                "label": "Pending",
                "value": awaiting_appr,
                "display": _ugx(awaiting_appr),
                "color": "var(--edify-warning)",
            },
            {
                "key": "returned",
                "label": "Returned",
                "value": returned_amt,
                "display": _ugx(returned_amt),
                "color": "var(--edify-danger)",
            },
        ],
        share_of=sum(donut_amounts.values()) or None,
    )

    # ── Allocation & utilization (planned budget lines vs money out) ──────────
    from apps.activities.models import ActivityScheduleCostLine

    allocation = ActivityScheduleCostLine.objects.filter(
        activity__fy=fy, month=month, activity__deleted_at__isnull=True
    ).values_list("amount", flat=True)
    allocation_total = sum(allocation)
    utilized = disbursed_month
    committed = pending_disb + held_amt
    available = max(0, allocation_total - utilized - committed)
    utilization = {
        "allocation": _ugx(allocation_total),
        "utilized": _ugx(utilized),
        "committed": _ugx(committed),
        "available": _ugx(available),
        "pct": round(utilized / allocation_total * 100) if allocation_total else 0,
    }

    # ── Disbursement mix (where the month's money goes, by category) ──────────
    mix_tot: dict[str, int] = {}
    for i in queue:
        if i["kind"] == "monthly":
            d, _snap = _monthly_detail(i, fy, month)
            for b in d:
                mix_tot[b["category"]] = mix_tot.get(b["category"], 0) + b["raw_total"]
        elif i["kind"] == "weekly":
            d, _snap = _weekly_detail(i)
            for b in d:
                mix_tot[b["category"]] = mix_tot.get(b["category"], 0) + b["raw_total"]
        elif i["kind"] == "partner":
            mix_tot["Partner Payments"] = (
                mix_tot.get("Partner Payments", 0) + i["amount"]
            )
        else:
            mix_tot["Reimbursements"] = mix_tot.get("Reimbursements", 0) + i["amount"]
    mix_grand = sum(mix_tot.values()) or 1
    extra_colors = [
        "bg-rose-500",
        "bg-cyan-500",
        "edify-primary-solid",
        "bg-fuchsia-500",
        "bg-lime-600",
        "bg-slate-500",
    ]
    mix = []
    for idx, (cat, amt) in enumerate(sorted(mix_tot.items(), key=lambda kv: -kv[1])):
        mix.append(
            {
                "label": cat,
                "amount": _ugx(amt),
                "pct": round(amt / mix_grand * 100),
                "color": MIX_COLORS.get(cat, extra_colors[idx % len(extra_colors)]),
            }
        )

    # ── Cash position (derived from real commitments; no bank feed exists) ────
    fy_disbursed = sum(
        f.disbursed_amount or f.total_amount
        for f in FundRequest.objects.filter(
            period="monthly", fy=fy, disbursed_at__isnull=False
        )
    ) + sum(
        w.disbursed_amount or w.total_amount
        for w in WeeklyFundRequest.objects.filter(fy=fy, disbursed_at__isnull=False)
    )
    sp_fy = sum(
        f.disbursed_amount or f.total_amount
        for f in FundRequest.objects.filter(
            period="monthly",
            fy=fy,
            disbursed_at__isnull=False,
            submitted_by_role="ProjectCoordinator",
        )
    )
    fy_allocation = sum(
        ActivityScheduleCostLine.objects.filter(
            activity__fy=fy, activity__deleted_at__isnull=True
        ).values_list("amount", flat=True)
    )
    cash = {
        "fy_allocation": _ugx(fy_allocation),
        "committed": _ugx(committed),
        "pending_requests": _ugx(awaiting_appr),
        "program_funds": _ugx(fy_disbursed - sp_fy),
        "special_projects": _ugx(sp_fy),
        "available": _ugx(max(0, fy_allocation - fy_disbursed - committed)),
    }

    # ── Selected detail ───────────────────────────────────────────────────────
    sel = next((i for i in visible if i["key"] == selected_key), None) or (
        visible[0] if visible else None
    )
    selected = _selected_detail(sel, fy, month) if sel else None

    recon = _reconciliation(fy, names)
    recon_rate_total = sum(recon["raw_counts"].values()) or 1
    recon_rate = round(recon["raw_counts"]["Closed"] / recon_rate_total * 100)

    return {
        "fy": fy,
        "month": month,
        "month_label": MONTHS[month] if 1 <= month <= 12 else str(month),
        "fy_options": [fy, str(int(fy) - 1)],
        "queue": [{k: v for k, v in i.items() if k != "obj"} for i in visible],
        "queue_count": len(visible),
        "selected": selected,
        "kpis": kpis,
        "overview": overview,
        "donut": donut,
        "donut_rings": donut_rings,
        "utilization": utilization,
        "mix": mix,
        "cash": cash,
        "recon": recon,
        "recon_rate": recon_rate,
        "recent": _recent(fy, names),
        "rules": RULES,
        "status_options": STATUS_OPTIONS,
        "hold_reasons": HOLD_REASONS,
        "return_reasons": RETURN_REASONS,
        "payment_methods": PAYMENT_METHODS,
    }


# ── Accountant actions (monthly fund plans) ───────────────────────────────────
def _get_monthly_fr(fund_request_id, expected_statuses, for_update=False):
    from .models import FundRequest

    qs = FundRequest.objects.filter(id=fund_request_id, period="monthly")
    if for_update:
        qs = qs.select_for_update()
    fr = qs.first()
    if not fr:
        raise BadRequest("Fund plan not found.")
    if fr.status not in expected_statuses:
        raise BadRequest(
            f"This fund plan is not in a state for that action (currently {fr.get_status_display()})."
        )
    return fr


def disburse(principal, fund_request_id, data=None):
    """Release approved funds → ``disbursed``. Records payment method/reference
    and notifies the requester to confirm receipt."""
    _require_accountant_action(principal)
    data = data or {}

    now = timezone.now()
    method = (data.get("method") or "").strip() or None
    reference = (data.get("reference") or "").strip() or None

    # Marking the plan "disbursed" and writing its per-activity Disbursement
    # audit rows must succeed or fail together — a crash between the two would
    # otherwise leave a FundRequest marked disbursed with zero Disbursement
    # records backing it. The status check + transition also happen inside
    # this same atomic block under select_for_update() so a double-click (two
    # near-simultaneous requests) can't both pass the "still sent_to_accountant"
    # check before either commits — the second request blocks on the row lock,
    # then sees status already "disbursed" and is rejected instead of writing
    # a second set of Disbursement audit rows.
    from .finance_models import Disbursement

    with transaction.atomic():
        fr = _get_monthly_fr(fund_request_id, {"sent_to_accountant"}, for_update=True)

        try:
            amount = int(data.get("amount") or fr.total_amount)
        except (TypeError, ValueError):
            amount = fr.total_amount
        if amount <= 0 or amount > fr.total_amount:
            raise BadRequest(
                "Disbursed amount must be positive and within the approved total."
            )
        fraction = amount / fr.total_amount if fr.total_amount else 0

        # Cross-channel guard. AdvanceRequest is the one shared ledger every
        # disbursement channel converges on (see MONEY_MOVED_ADVANCE_STATUSES
        # in models.py), and services.py:307 already refuses on this basis.
        # This path did not, so the same ActivityScheduleCostLine could be paid
        # once here and once via the Weekly Advance button on the very same
        # screen -- reproduced end to end as 250,000 UGX released as 500,000.
        from .models import (
            MONEY_MOVED_ADVANCE_STATUSES,
            AdvanceRequest,
            AdvanceRequestStatus,
        )

        line_ids = [
            i.activity_schedule_cost_line_id
            for i in fr.items.all()
            if i.activity_schedule_cost_line_id
        ]
        if line_ids:
            clash = (
                AdvanceRequest.objects.select_for_update()
                .filter(
                    budget_line_id__in=line_ids,
                    status__in=MONEY_MOVED_ADVANCE_STATUSES,
                )
                .count()
            )
            if clash:
                raise BadRequest(
                    f"Cannot disburse — {clash} of this plan's budget lines "
                    "already had money released through the weekly/advance "
                    "queue. Releasing again would pay the same work twice."
                )

        fr.status = "disbursed"
        fr.disbursed_amount = amount
        fr.disbursed_at = now
        fr.disbursed_by_user_id = principal.user_id
        fr.disburse_method = method
        fr.disburse_reference = reference
        fr.save(
            update_fields=[
                "status",
                "disbursed_amount",
                "disbursed_at",
                "disbursed_by_user_id",
                "disburse_method",
                "disburse_reference",
                "updated_at",
            ]
        )

        # One DisbursementRecord per activity the plan actually funds — the same
        # audit trail apps.fund_requests.finance_services.AdvanceDisbursementService
        # writes for single-activity advances. Disbursement.activity is required,
        # so a month-level release still needs one row per activity it covers;
        # split proportionally when a partial amount was released.
        Disbursement.objects.bulk_create(
            [
                Disbursement(
                    activity_id=item.activity_id,
                    fund_request=fr,
                    amount_disbursed=round(item.amount * fraction),
                    disbursed_at=now,
                    disbursed_by=principal.user_id,
                    payment_method=method or "",
                    payment_reference=reference or "",
                    notes=f"Monthly fund plan {fr.period_key}",
                )
                for item in fr.items.all()
            ]
        )

        # Post the release to the shared ledger too. Without this the guard is
        # one-directional: the weekly/advance queue would still see these lines
        # as unpaid and release them a second time.
        if line_ids:
            AdvanceRequest.objects.filter(
                budget_line_id__in=line_ids,
            ).exclude(status__in=MONEY_MOVED_ADVANCE_STATUSES).update(
                status=AdvanceRequestStatus.DISBURSED,
                disbursed_at=now,
                updated_at=now,
            )

    _audit(
        principal,
        "fund_request.disburse",
        fr,
        {
            "amount": amount,
            "method": fr.disburse_method,
            "reference": fr.disburse_reference,
        },
    )
    _notify_requester(
        fr,
        "fund_request_disbursed",
        "Funds disbursed — confirm receipt",
        f"Funds for your {fr.period_key} fund plan ({_ugx(amount)}) have been disbursed. "
        "Check your account and confirm receipt.",
    )
    return fr


def hold(principal, fund_request_id, data):
    """Pause a disbursement without rejecting it → ``held``. Requires a reason."""
    _require_accountant_action(principal)
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("A hold reason is required.")
    fr = _get_monthly_fr(fund_request_id, {"sent_to_accountant"})
    fr.status = "held"
    fr.held_reason = (
        reason + (" — " + data["comment"] if data.get("comment") else "")
    )[:256]
    fr.held_at = timezone.now()
    fr.save(update_fields=["status", "held_reason", "held_at", "updated_at"])
    _audit(principal, "fund_request.hold", fr, {"reason": reason})
    _notify_requester(
        fr,
        "fund_request_held",
        "Fund plan on hold",
        f"Your {fr.period_key} fund plan is on hold: {reason}. No correction is "
        "needed yet — the Accountant will release or return it.",
    )
    return fr


def release(principal, fund_request_id):
    """Release a held plan back into the disbursement queue."""
    _require_accountant_action(principal)
    fr = _get_monthly_fr(fund_request_id, {"held"})
    fr.status = "sent_to_accountant"
    fr.held_reason = None
    fr.held_at = None
    fr.save(update_fields=["status", "held_reason", "held_at", "updated_at"])
    _audit(principal, "fund_request.release_hold", fr, {})
    return fr


def return_item(principal, fund_request_id, data):
    """Return a fund plan for correction → ``returned_by_accountant``. The
    requester's Fix To-Do derives automatically from this status."""
    _require_accountant_action(principal)
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("A return reason is required.")
    fr = _get_monthly_fr(fund_request_id, {"sent_to_accountant", "held"})
    fr.status = "returned_by_accountant"
    fr.reviewed_by_user_id = principal.user_id
    fr.reviewed_at = timezone.now()
    fr.review_note = (
        reason + (" — " + data["comment"] if data.get("comment") else "")
    )[:512]
    fr.held_reason = None
    fr.held_at = None
    fr.save(
        update_fields=[
            "status",
            "reviewed_by_user_id",
            "reviewed_at",
            "review_note",
            "held_reason",
            "held_at",
            "updated_at",
        ]
    )
    _audit(principal, "fund_request.return_accountant", fr, {"reason": reason})
    _notify_requester(
        fr,
        "fund_request_returned",
        "Fund plan returned by Accountant",
        f"Your {fr.period_key} fund plan was returned by the Accountant. Reason: {reason}",
    )
    return fr


def confirm_receipt(principal, fund_request_id):
    """The requester confirms the disbursed funds arrived. Auto-closes the
    Confirm-Receipt To-Do (derive-from-state)."""
    from .models import FundRequest

    fr = FundRequest.objects.filter(id=fund_request_id, period="monthly").first()
    if not fr:
        raise BadRequest("Fund plan not found.")
    if fr.submitted_by_user_id != principal.user_id:
        raise Forbidden("Only the requester can confirm receipt of these funds.")
    if fr.status != "disbursed":
        raise BadRequest("These funds are not marked as disbursed.")
    if fr.receipt_confirmed_at:
        return fr
    fr.receipt_confirmed_at = timezone.now()
    fr.save(update_fields=["receipt_confirmed_at", "updated_at"])
    _audit(principal, "fund_request.receipt_confirmed", fr, {})
    return fr


def _audit(principal, action, fr, payload):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="FundRequest",
            subject_id=fr.id,
            actor_id=principal.user_id,
            actor_role=getattr(principal, "active_role", ""),
            success=True,
            payload={"period_key": fr.period_key, "total": fr.total_amount, **payload},
        )
    except Exception:  # noqa: BLE001 — audit must never block the action
        pass


def _notify_requester(fr, event, title, body):
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event,
            category="finance",
            priority="high",
            title=title,
            body=body,
            context_type="FundRequest",
            context_id=fr.id,
            recipients=[fr.submitted_by_user_id],
        )
    except Exception:  # noqa: BLE001
        pass


# ── Accountant transitions that used to live in the view ─────────────────────


@transaction.atomic
def return_weekly_request(principal, weekly_request, reason: str):
    """Send a confirmed weekly advance back for correction.

    Moved out of finance_views: the view re-stated the Accountant check as an
    inline `active_role != "Accountant"` string comparison, which is a second
    definition of an authority this module already owns. One gate, one place --
    otherwise the two drift and the weaker one becomes the way in.
    """
    from apps.audit.services import log as audit_log
    from apps.fund_requests.models import AdvanceRequestStatus

    _require_accountant_action(principal)
    if not (reason or "").strip():
        raise BadRequest("A return reason is required.")
    if weekly_request.status != "confirmed_for_advance":
        raise BadRequest(
            "Only a confirmed request can be returned by the accountant — this "
            f"one is already {weekly_request.get_status_display()}."
        )

    weekly_request.status = "returned_by_accountant"
    weekly_request.confirmed_at = None
    weekly_request.save(update_fields=["status", "confirmed_at", "updated_at"])

    # Only advances still awaiting disbursement move with it. One already
    # disbursed or accounted on a sibling line must never be silently reopened.
    moved = 0
    for line in weekly_request.lines.select_related("activity_budget_line"):
        advance = line.activity_budget_line.advance_requests.filter(
            status=AdvanceRequestStatus.CONFIRMED_FOR_ADVANCE
        ).first()
        if advance:
            advance.status = AdvanceRequestStatus.RETURNED
            advance.last_note = reason
            advance.save(update_fields=["status", "last_note", "updated_at"])
            moved += 1

    audit_log(
        # The established audit vocabulary. Moving this transition into the
        # service must not rename the event that already exists in history.
        action="weekly_fund_request.return_by_accountant",
        subject_kind="WeeklyFundRequest",
        subject_id=weekly_request.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        success=True,
        reason=reason,
        payload={
            "reason": reason,
            "total_amount": weekly_request.total_amount,
            "advances_returned": moved,
        },
    )
    return weekly_request


def roll_up_accountability(weekly_request, advances) -> bool:
    """Project child advance state onto the parent weekly request.

    A projection, not an independent transition: the parent becomes
    `accounted` because every child already is. It lives here beside the
    transitions it summarises so the derivation has one definition.

    Faithful to the view it replaces, deliberately. An earlier draft of this
    function handled only ACCOUNTED and dropped the reimbursed case, the
    reviewed-at stamp and both money totals -- wiring that in would have been a
    silent loss of behaviour dressed up as a refactor. REIMBURSEMENT_SUBMITTED
    and REIMBURSEMENT_DISBURSED are legitimate in-progress states and must not
    close the request.
    """
    from apps.fund_requests.models import AdvanceRequestStatus

    advances = list(advances)
    if not advances:
        return False
    closing = (AdvanceRequestStatus.ACCOUNTED, AdvanceRequestStatus.REIMBURSED)
    if not all(advance.status in closing for advance in advances):
        return False

    codes = sorted(
        {
            advance.accountability_netsuite_id
            for advance in advances
            if advance.accountability_netsuite_id
        }
    )
    now = timezone.now()
    weekly_request.status = "accounted"
    weekly_request.accountability_netsuite_id = ", ".join(codes)[:128] or None
    weekly_request.accountability_submitted_at = (
        weekly_request.accountability_submitted_at
        or min(
            (
                advance.accountability_submitted_at
                for advance in advances
                if advance.accountability_submitted_at
            ),
            default=now,
        )
    )
    weekly_request.accountability_reviewed_at = now
    weekly_request.accounted_amount = sum(
        advance.accounted_amount or 0 for advance in advances
    )
    weekly_request.returned_amount = sum(
        advance.returned_amount or 0 for advance in advances
    )
    weekly_request.save(
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
    return True
