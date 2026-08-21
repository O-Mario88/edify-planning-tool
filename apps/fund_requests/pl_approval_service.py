"""PL Fund Approval — the weekly, team-scoped finance gate.

A Program Lead approves funding only for scheduled, costed, valid CCEO activities
under their supervision. The PL does NOT create budgets: every figure here is
derived from the CCEO's persisted `ActivityScheduleCostLine` budget lines (which
were generated automatically when activities were scheduled, priced from the CD
Cost Catalogue). The queue reads the auto-generated `WeeklyFundRequest` for each
supervised CCEO and week: the CCEO sends it (`submitted_to_pl`), the PL approves
or returns, and an approval routes it to the Accountant's disbursement queue.

One state machine: every mutation delegates to apps.fund_requests.weekly_service
(the same approve/return the weekly page uses), so this page can never disagree
with the request's own lifecycle. Scope rule: a PL sees only the CCEOs they
supervise (`StaffSupervisorAssignment`), never other PLs' portfolios.
"""

from __future__ import annotations

from apps.core.metrics import render_precomputed_metric_item

from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope
from apps.core.activity_types import (
    TRAINING_TYPES,
    VISIT_TYPES,
)

# Statuses that count as "PL-approved" — past the PL gate and routed to / through
# the Accountant for disbursement. Approve sends a plan straight to the accountant.
PL_APPROVED_STATUSES = (
    "approved_by_pl",
    "sent_to_accountant",
    "disbursed",
    "closed",
)

SSA_VISIT_TYPES = [
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "partner_ssa_collection",
    "ssa_activity",
    "core_assessment_visit",
]
CLUSTER_MEETING = ["cluster_meeting", "cluster_meeting_ssa_review"]
CLUSTER_TRAINING = ["cluster_training", "cluster_training_ssa_collection"]

CATEGORY_ORDER = [
    "Admin Budget",
    "Staff School Visits",
    "Partner School Visits",
    "Cluster Meetings",
    "Cluster Trainings",
    "In-School Trainings",
    "SSA Support Visits",
    "Field Events",
    "Other",
]
# Budget-mix segment colours (Tailwind bg classes).
MIX_COLORS = {
    "Field Events": "bg-cyan-500",
    "Admin Budget": "bg-sky-500",
    "Staff School Visits": "bg-emerald-500",
    "Partner School Visits": "bg-violet-500",
    "Cluster Meetings": "edify-primary-solid",
    "Cluster Trainings": "bg-amber-500",
    "In-School Trainings": "bg-orange-500",
    "SSA Support Visits": "bg-teal-500",
    "Other": "bg-slate-400",
}
MONTHS = [
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


from apps.core.metrics import format_ugx_compact as _ugx  # noqa: E402

# Was a local copy differing from the other two compact-UGX helpers only at the
# billion scale (.2f here, .1f in finance operations). One formatter now, so
# the same amount reads the same on the approval queue and the finance pages.


def _category(activity_type, delivery_type, programme_activity_type=None):
    if programme_activity_type == "admin":
        return "Admin Budget"
    if activity_type in VISIT_TYPES:
        return (
            "Partner School Visits"
            if delivery_type == "partner"
            else "Staff School Visits"
        )
    if activity_type in SSA_VISIT_TYPES:
        return "SSA Support Visits"
    if activity_type in CLUSTER_MEETING:
        return "Cluster Meetings"
    if activity_type in CLUSTER_TRAINING:
        return "Cluster Trainings"
    if activity_type in TRAINING_TYPES:
        return "In-School Trainings"
    if activity_type == "field_event":
        return "Field Events"
    return "Other"


def _scoped_cceos(scope):
    """The CCEO records this PL supervises. Returns dicts with both id spaces."""
    from apps.accounts.models import StaffProfile

    # Administrators have country-wide finance authority.  Their Fund
    # Approval page should therefore show the same CCEO plans they are allowed
    # to review, even when no explicit supervisor assignment was seeded for
    # the admin account.
    profile_ids = scope.supervised_staff_ids
    if scope.active_role == "Admin" and scope.country_scope:
        profile_ids = StaffProfile.objects.filter(
            user__active_role="CCEO", deleted_at__isnull=True
        ).values_list("id", flat=True)

    cceos = []
    for sp in StaffProfile.objects.filter(id__in=profile_ids).select_related("user"):
        cceos.append(
            {
                "staff_id": sp.id,
                "user_id": sp.user_id,
                "name": getattr(sp.user, "name", None) or "CCEO",
                "role": getattr(sp.user, "active_role", ""),
                "ids": [i for i in (sp.id, sp.user_id) if i],
            }
        )
    return cceos


def _require_pl(principal):
    role = getattr(principal, "active_role", None)
    if role not in ("Program Lead", "Admin"):
        raise Forbidden("Only a Program Lead can access team fund approvals.")


def _require_pl_action(principal):
    """Require team-fund approval authority.

    Admin reads team fund plans (_require_pl above) and does not approve them.
    Field budget approval is the CCEO→PL chain; an Admin approving into it is
    an approval nobody in the field made, recorded as though they had.
    """
    role = getattr(principal, "active_role", None)
    if role != "Program Lead":
        raise Forbidden("Only a Program Lead can act on team fund plans.")


WEEKLY_STATUS_LABELS = {
    None: ("Awaiting CCEO Send", "info"),
    "pending_responsible_confirmation": ("Awaiting CCEO Send", "info"),
    "not_requested": ("Not Requested", "info"),
    "submitted_to_pl": ("Awaiting Approval", "warning"),
    "submitted_to_cd": ("Awaiting CD", "info"),
    "confirmed_for_advance": ("At Accountant", "success"),
    "disbursed": ("Disbursed", "success"),
    "self_funded": ("Self-funded", "info"),
    "returned_by_pl": ("Returned", "danger"),
    "returned_by_cd": ("Returned", "danger"),
    "returned_by_accountant": ("Returned", "danger"),
}


def _week_floor(d):
    from datetime import timedelta

    return d - timedelta(days=d.weekday())


def _week_label(week_start):
    from datetime import timedelta

    week_end = week_start + timedelta(days=6)
    return f"{week_start:%b %d} – {week_end:%b %d}, {week_end:%Y}"


def _weekly_request_for(cceo_user_id, week_start):
    from .models import WeeklyFundRequest

    return WeeklyFundRequest.objects.filter(
        responsible_user=cceo_user_id, week_start_date=week_start
    ).first()


def _validate(cceo, lines, month):
    """Real validation of a CCEO's monthly fund plan. Returns issue list."""
    issues = []
    acts = {li.activity_id: li.activity for li in lines}
    for a in acts.values():
        if getattr(a, "cost_missing", False):
            issues.append(
                f"{a.get_activity_type_display()} has no cost rate (Cost Catalogue)."
            )
        if a.status in ("cancelled", "rejected"):
            issues.append(
                f"Cancelled activity included: {a.get_activity_type_display()}."
            )
        if (
            a.delivery_type == "partner"
            and a.activity_type in VISIT_TYPES
            and not a.school_id
        ):
            issues.append("Partner visit is not linked to a planned school.")
        if (
            a.activity_type in CLUSTER_TRAINING
            and not (
                (a.teachers_attended or 0)
                + (a.leaders_attended or 0)
                + (a.other_participants or 0)
            )
            and a.status in ("completed", "closed", "submitted_to_pl")
        ):
            issues.append("Cluster training is missing a participant count.")
    for li in lines:
        if not li.catalogue_id:
            issues.append("A budget line has no Cost Catalogue version.")
            break
    # dedupe, cap
    seen, out = set(), []
    for i in issues:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out[:6]


def _build_cceo_plan(cceo, lines, wfr):
    """Aggregate one CCEO's week of budget lines + their weekly fund request
    into a queue/detail record. The request (and the money the PL approves) is
    the staff advance on the WeeklyFundRequest; partner-delivered lines are
    plan context, paid through the partner-payment channel, never here."""

    # Partner-delivered lines never enter the staff funds: partners are paid
    # directly through the MOU partner-payment channel. They stay visible
    # only as context — the partner chip and the "paid via partner payments"
    # note — never as rows, totals or validation blockers of this request.
    def _is_vendor(li):
        # Mirrors fund_requests.fundable.vendor_direct_filter: school-visit
        # transport is paid to the transport company; accommodation joins the
        # vendor channel when Finance booked the hotel.
        return (li.line_item_type == "transport" and li.activity.school_id) or (
            li.line_item_type == "accommodation" and li.vendor_paid
        )

    def _is_partner(li):
        return li.activity.delivery_type == "partner" or li.partner_id is not None

    staff_lines = [li for li in lines if not _is_partner(li) and not _is_vendor(li)]
    partner_total = sum(li.amount for li in lines if _is_partner(li))
    vendor_transport_total = sum(
        li.amount
        for li in lines
        if not _is_partner(li)
        and li.line_item_type == "transport"
        and li.activity.school_id
    )
    vendor_accommodation_total = sum(
        li.amount
        for li in lines
        if not _is_partner(li)
        and li.line_item_type == "accommodation"
        and li.vendor_paid
    )
    total = sum(li.amount for li in staff_lines)
    acts = {}
    schools = set()
    cat_totals: dict[str, dict] = {}
    for li in staff_lines:
        a = li.activity
        acts[a.id] = a
        if a.school_id:
            schools.add(a.school_id)
        cat = _category(a.activity_type, a.delivery_type, a.programme_activity_type)
        d = cat_totals.setdefault(cat, {"total": 0, "acts": set()})
        d["total"] += li.amount
        d["acts"].add(a.id)

    act_list = list(acts.values())
    n_visits = sum(1 for a in act_list if a.activity_type in VISIT_TYPES)
    n_partner = len(
        {
            li.activity_id
            for li in lines
            if li.activity.delivery_type == "partner" or li.partner_id is not None
        }
    )
    n_clusters = sum(
        1 for a in act_list if a.activity_type in CLUSTER_MEETING + CLUSTER_TRAINING
    )
    n_trainings = sum(1 for a in act_list if a.activity_type in TRAINING_TYPES)

    # geography from the CCEO's schools (most common)
    districts = [
        a.school.district.name for a in act_list if a.school_id and a.school.district_id
    ]
    regions = [
        a.school.region.name for a in act_list if a.school_id and a.school.region_id
    ]
    district = max(set(districts), key=districts.count) if districts else "—"
    region = max(set(regions), key=regions.count) if regions else "—"

    issues = _validate(cceo, staff_lines, None)
    valid = not issues
    wfr_status = wfr.status if wfr else None
    status_label, status_tone = WEEKLY_STATUS_LABELS.get(
        wfr_status, ("Awaiting CCEO Send", "info")
    )
    if wfr_status == "submitted_to_pl" and not valid:
        status_label, status_tone = "Needs Review", "info"
    request_total = int(wfr.total_amount) if wfr else 0

    return {
        "cceo": cceo,
        "name": cceo["name"],
        "district": district,
        "region": region,
        "total": total,
        # The number on the queue card is the money this approval moves: the
        # request's staff advance (falling back to the staff share of the
        # week's lines while the request row has not materialised yet).
        "request_total": request_total,
        "partner_total": partner_total,
        "vendor_transport_total": vendor_transport_total,
        "vendor_accommodation_total": vendor_accommodation_total,
        "mission_total": total + vendor_transport_total + vendor_accommodation_total,
        "total_fmt": _ugx(request_total if wfr else total),
        "status": status_label,
        "status_tone": status_tone,
        "valid": valid,
        "issues": issues,
        "chips": {
            "visits": n_visits,
            "partner": n_partner,
            "clusters": n_clusters,
            "trainings": n_trainings,
        },
        "schools": schools,
        "activities": act_list,
        "cat_totals": cat_totals,
        "wfr_id": wfr.id if wfr else None,
        "wfr_status": wfr_status,
        "can_approve": bool(wfr and wfr_status == "submitted_to_pl" and valid),
        "can_return": bool(wfr and wfr_status == "submitted_to_pl"),
    }


def get_pl_fund_approvals(principal, filters=None):
    _require_pl(principal)
    filters = filters or {}
    scope = resolve_user_scope(principal)
    fy = filters.get("fy") or get_operational_fy()
    month = int(filters.get("month") or timezone.now().month)
    selected_id = filters.get("cceo")
    status_filter = filters.get("status")
    search = (filters.get("q") or "").strip().lower()

    from datetime import date as _date, timedelta

    from django.db.models import Count

    from apps.activities.models import ActivityScheduleCostLine

    cceos = _scoped_cceos(scope)
    all_ids = [i for c in cceos for i in c["ids"]]

    week_base = (
        ActivityScheduleCostLine.objects.filter(
            activity__responsible_staff_id__in=all_ids,
            activity__fy=fy,
            activity__deleted_at__isnull=True,
            week_start_date__isnull=False,
        )
        # Cancelled/rejected/deferred work must never reach a fund request.
        .exclude(activity__status__in=["cancelled", "rejected", "deferred"])
        if all_ids
        else ActivityScheduleCostLine.objects.none()
    )

    # Default to the team's busiest funded month (so the page opens populated),
    # then to that month's busiest week. Money moves weekly: the month filter
    # only narrows the week picker.
    if not filters.get("month") and all_ids:
        busiest = (
            week_base.filter(month__isnull=False)
            .values("month")
            .annotate(n=Count("id"))
            .order_by("-n")
            .first()
        )
        if busiest:
            month = int(busiest["month"])

    month_weeks = list(
        week_base.filter(month=month)
        .values("week_start_date")
        .annotate(n=Count("id"))
        .order_by("week_start_date")
    )

    week_start = None
    if filters.get("week"):
        try:
            week_start = _week_floor(_date.fromisoformat(str(filters["week"])[:10]))
        except ValueError:
            week_start = None
    if week_start is None:
        if month_weeks:
            week_start = max(month_weeks, key=lambda w: w["n"])["week_start_date"]
        else:
            week_start = _week_floor(timezone.localdate())

    weeks = [
        {
            "val": w["week_start_date"].isoformat(),
            "label": f"{w['week_start_date']:%b %d} – {w['week_start_date'] + timedelta(days=6):%b %d}",
        }
        for w in month_weeks
    ]
    if week_start.isoformat() not in {w["val"] for w in weeks}:
        weeks.append(
            {
                "val": week_start.isoformat(),
                "label": f"{week_start:%b %d} – {week_start + timedelta(days=6):%b %d}",
            }
        )

    lines = list(
        week_base.filter(week_start_date=week_start).select_related(
            "activity",
            "activity__school",
            "activity__school__district",
            "activity__school__region",
            "activity__cluster",
        )
    )

    # bucket lines by CCEO (match either id space)
    lines_by_cceo: dict[str, list] = {}
    for li in lines:
        rid = li.activity.responsible_staff_id
        cceo = next((c for c in cceos if rid in c["ids"]), None)
        if cceo:
            lines_by_cceo.setdefault(cceo["user_id"], []).append(li)

    # EVERYTHING AUTOMATIC: the weekly request row is generated when work is
    # scheduled. If a reschedule beat that signal here, heal it now — the
    # queue must never depend on a manual generation step. (Idempotent; only
    # runs for a CCEO whose row is missing.)
    from .weekly_service import generate_weekly_fund_request

    plans = []
    for c in cceos:
        c_lines = lines_by_cceo.get(c["user_id"], [])
        if not c_lines:
            continue
        wfr = _weekly_request_for(c["user_id"], week_start)
        if wfr is None:
            try:
                wfr = generate_weekly_fund_request(c["user_id"], week_start.isoformat())
            except Exception:
                wfr = None
        plans.append(_build_cceo_plan(c, c_lines, wfr))
    plans.sort(key=lambda p: -p["total"])

    # filters
    queue = plans
    if status_filter:
        queue = [p for p in queue if p["status"] == status_filter]
    if search:
        queue = [
            p
            for p in queue
            if search in p["name"].lower() or search in p["district"].lower()
        ]

    # ── KPIs (team-scoped, this week) ─────────────────────────────────────────
    total_requested = sum(p["request_total"] for p in plans)
    awaiting = [p for p in plans if p["wfr_status"] == "submitted_to_pl"]
    pending_send = [
        p
        for p in plans
        if p["wfr_status"] in (None, "pending_responsible_confirmation")
    ]
    approved = [
        p for p in plans if p["wfr_status"] in ("confirmed_for_advance", "disbursed")
    ]
    returned = [p for p in plans if (p["wfr_status"] or "").startswith("returned")]

    def _n(items):
        return f"{len(items)} request{'' if len(items) == 1 else 's'}"

    kpis = [
        render_precomputed_metric_item(
            "fund_requests_pl_approval_service_requested_this_week",
            _ugx(total_requested),
            icon="finance",
            variant="primary",
            helper=_n(plans),
        ),
        render_precomputed_metric_item(
            "fund_requests_pl_approval_service_awaiting_your_approval",
            _ugx(sum(p["request_total"] for p in awaiting)),
            icon="clock",
            variant="warning",
            helper=_n(awaiting),
        ),
        render_precomputed_metric_item(
            "fund_requests_pl_approval_service_awaiting_cceo_send",
            _ugx(sum(p["request_total"] or p["total"] for p in pending_send)),
            icon="briefcase",
            variant="info",
            helper=_n(pending_send),
        ),
        render_precomputed_metric_item(
            "fund_requests_pl_approval_service_approved_this_week",
            _ugx(sum(p["request_total"] for p in approved)),
            icon="check",
            variant="success",
            helper=_n(approved),
        ),
        render_precomputed_metric_item(
            "fund_requests_pl_approval_service_returned_for_review",
            _ugx(sum(p["request_total"] for p in returned)),
            icon="warning",
            variant="danger",
            helper=_n(returned),
        ),
    ]

    # ── Selected request detail ───────────────────────────────────────────────
    selected = None
    sel = next((p for p in queue if p["cceo"]["user_id"] == selected_id), None) or (
        queue[0] if queue else None
    )
    if sel:
        selected = _selected_detail(sel, week_start)

    from .partner_invoices import pl_invoice_queue

    return {
        "partner_invoices": pl_invoice_queue(principal),
        "fy": fy,
        "month": month,
        "month_label": MONTHS[month] if 1 <= month <= 12 else str(month),
        "fy_options": [fy, str(int(fy) - 1)],
        "week": week_start.isoformat(),
        "week_label": _week_label(week_start),
        "weeks": weeks,
        "queue": [_queue_card(p, sel) for p in queue],
        "queue_count": len(queue),
        "kpis": kpis,
        "selected": selected,
        "status_options": [
            "Awaiting CCEO Send",
            "Awaiting Approval",
            "Needs Review",
            "At Accountant",
            "Disbursed",
            "Returned",
        ],
        "has_team": bool(cceos),
        "principal_user_id": principal.user_id,
    }


def _queue_card(p, sel):
    return {
        "cceo_user_id": p["cceo"]["user_id"],
        "name": p["name"],
        "district": p["district"],
        "region": p["region"],
        "total_fmt": p["total_fmt"],
        "status": p["status"],
        "status_tone": p["status_tone"],
        "chips": p["chips"],
        "selected": bool(sel and sel["cceo"]["user_id"] == p["cceo"]["user_id"]),
        "initials": "".join(w[0] for w in p["name"].split()[:2]).upper(),
    }


def _selected_detail(p, week_start):
    # funding breakdown rows (real, from budget lines grouped by activity category)
    breakdown = []
    for cat in CATEGORY_ORDER:
        d = p["cat_totals"].get(cat)
        if not d:
            continue
        qty = len(d["acts"])
        breakdown.append(
            {
                "category": cat,
                "qty": qty,
                "unit_cost": _ugx(round(d["total"] / qty)) if qty else "—",
                "total": _ugx(d["total"]),
            }
        )

    hints = {
        None: "Auto-generated from the schedule — waiting for the CCEO to send it for approval.",
        "pending_responsible_confirmation": "Auto-generated from the schedule — waiting for the CCEO to send it for approval.",
        "not_requested": "The CCEO marked this week as not requested.",
        "submitted_to_cd": "Escalated — awaiting the Country Director.",
        "confirmed_for_advance": "Approved — at the Accountant for processing and disbursement.",
        "disbursed": "Disbursed — awaiting the CCEO's receipt confirmation and accountability.",
        "self_funded": "Marked self-funded — reimbursement follows accountability.",
        "returned_by_pl": "Returned for correction — waiting for a corrected re-submission.",
        "returned_by_cd": "Returned for correction — waiting for a corrected re-submission.",
        "returned_by_accountant": "Returned by the Accountant — waiting for a corrected re-submission.",
    }

    # §4/§5 Daily Field Cost (School Visit): the weighted School Visit Cost
    # Allocation and planned per-school figure come from the week's day
    # batches (workload weights, so a cluster meeting on a visit day never
    # inflates the per-school number). Falls back to the simple all-inclusive
    # division when the week predates batch analytics.
    visit_schools = len(
        {
            a.school_id
            for a in p["activities"]
            if a.activity_type in VISIT_TYPES and a.school_id
        }
    )
    from datetime import timedelta as _td

    from apps.daily_visit_batches.models import DailyVisitBatch

    week_batches = list(
        DailyVisitBatch.objects.filter(
            responsible_user=p["cceo"]["user_id"],
            visit_date__gte=week_start,
            visit_date__lte=week_start + _td(days=6),
            school_visit_allocation__isnull=False,
        )
    )
    visit_allocation = sum(b.school_visit_allocation for b in week_batches)
    batch_visit_count = sum(
        (b.workload_snapshot or {}).get("visit_count", 0) for b in week_batches
    )
    visit_unit_cost = None
    school_visit_allocation_fmt = None
    if visit_allocation and batch_visit_count:
        school_visit_allocation_fmt = _ugx(visit_allocation)
        visit_unit_cost = _ugx(round(visit_allocation / batch_visit_count))
    else:
        visit_cat = p["cat_totals"].get("Staff School Visits")
        if visit_cat and visit_schools:
            visit_unit_cost = _ugx(
                round(
                    (visit_cat["total"] + p["vendor_transport_total"]) / visit_schools
                )
            )

    return {
        "cceo_user_id": p["cceo"]["user_id"],
        "name": p["name"],
        "district": p["district"],
        "region": p["region"],
        "period": f"Week of {_week_label(week_start)}",
        "status": p["status"],
        "status_tone": p["status_tone"],
        "total_fmt": p["total_fmt"],
        "partner_total_fmt": _ugx(p["partner_total"]) if p["partner_total"] else None,
        "vendor_transport_fmt": (
            _ugx(p["vendor_transport_total"]) if p["vendor_transport_total"] else None
        ),
        "vendor_accommodation_fmt": (
            _ugx(p["vendor_accommodation_total"])
            if p["vendor_accommodation_total"]
            else None
        ),
        "mission_total_fmt": _ugx(p["mission_total"]),
        "visit_schools": visit_schools,
        "visit_unit_cost": visit_unit_cost,
        "school_visit_allocation_fmt": school_visit_allocation_fmt,
        "breakdown": breakdown,
        "valid": p["valid"],
        "issues": p["issues"],
        "wfr_id": p["wfr_id"],
        "wfr_status": p["wfr_status"],
        "can_approve": p["can_approve"],
        "can_return": p["can_return"],
        "waiting_hint": hints.get(p["wfr_status"], ""),
    }


# ── Actions ───────────────────────────────────────────────────────────────────
# All mutations delegate to weekly_service — the one state machine for weekly
# fund requests. Approval routing, separation of duties (never your own
# request), audit and notifications all live there.


def _resolve_cceo(principal, cceo_user_id):
    scope = resolve_user_scope(principal)
    cceo = next((c for c in _scoped_cceos(scope) if c["user_id"] == cceo_user_id), None)
    if not cceo:
        raise Forbidden("That CCEO is not on your supervised team.")
    return cceo


def _weekly_for_action(principal, cceo_user_id, week):
    from datetime import date as _date

    cceo = _resolve_cceo(principal, cceo_user_id)
    try:
        week_start = _week_floor(_date.fromisoformat(str(week)[:10]))
    except (TypeError, ValueError):
        raise BadRequest("A valid week is required.")
    wfr = _weekly_request_for(cceo["user_id"], week_start)
    if not wfr:
        raise BadRequest("No weekly fund request exists for that week.")
    return cceo, week_start, wfr


def approve(principal, cceo_user_id, week):
    """PL approves the CCEO's submitted weekly request → weekly_service routes
    it to the Accountant's disbursement queue (confirmed_for_advance)."""
    from . import weekly_service

    _require_pl_action(principal)
    cceo, week_start, wfr = _weekly_for_action(principal, cceo_user_id, week)
    if wfr.status != "submitted_to_pl":
        label, _tone = WEEKLY_STATUS_LABELS.get(wfr.status, (wfr.status, ""))
        raise BadRequest(f"This request is not awaiting your approval ({label}).")

    from apps.activities.models import ActivityScheduleCostLine

    lines = list(
        ActivityScheduleCostLine.objects.filter(
            activity__responsible_staff_id__in=cceo["ids"],
            week_start_date=week_start,
            activity__deleted_at__isnull=True,
            partner_id__isnull=True,
        )
        .exclude(activity__delivery_type="partner")
        .select_related("activity")
    )
    issues = _validate(cceo, lines, None)
    if issues:
        raise BadRequest("Cannot approve — request needs review: " + issues[0])

    return weekly_service.approve_weekly_request(wfr.id, principal)


def return_request(principal, cceo_user_id, week, data):
    """PL returns the weekly request for correction → returned_by_pl; the CCEO
    is notified and can correct and re-send."""
    from . import weekly_service

    _require_pl_action(principal)
    _cceo, _week_start, wfr = _weekly_for_action(principal, cceo_user_id, week)
    reason = (data.get("reason") or "").strip()
    comment = (data.get("comment") or "").strip()
    if not reason:
        raise BadRequest("A return reason is required.")
    merged = f"{reason} — {comment}" if comment else reason
    return weekly_service.return_weekly_request(wfr.id, {"reason": merged}, principal)


def approve_all_valid(principal, week):
    """Approve every supervised request that is submitted and passes
    validation; invalid or unsubmitted ones are left untouched."""
    from datetime import date as _date

    from . import weekly_service
    from apps.activities.models import ActivityScheduleCostLine

    _require_pl_action(principal)
    scope = resolve_user_scope(principal)
    try:
        week_start = _week_floor(_date.fromisoformat(str(week)[:10]))
    except (TypeError, ValueError):
        raise BadRequest("A valid week is required.")

    approved = 0
    for cceo in _scoped_cceos(scope):
        wfr = _weekly_request_for(cceo["user_id"], week_start)
        if not wfr or wfr.status != "submitted_to_pl":
            continue
        lines = list(
            ActivityScheduleCostLine.objects.filter(
                activity__responsible_staff_id__in=cceo["ids"],
                week_start_date=week_start,
                activity__deleted_at__isnull=True,
                partner_id__isnull=True,
            )
            .exclude(activity__delivery_type="partner")
            .select_related("activity")
        )
        if _validate(cceo, lines, None):
            continue
        try:
            weekly_service.approve_weekly_request(wfr.id, principal)
            approved += 1
        except (BadRequest, Forbidden):
            continue
    return approved
