"""PL Fund Approval — a team-scoped finance gate.

A Program Lead approves funding only for scheduled, costed, valid CCEO activities
under their supervision. The PL does NOT create budgets: every figure here is
derived from the CCEO's persisted `ActivityScheduleCostLine` budget lines (which
were generated from scheduled activities + the CD Cost Catalogue). The PL only
approves or returns.

Scope rule: a PL sees only the fund plans of the CCEOs they supervise
(`StaffSupervisorAssignment`), never other PLs' portfolios or country-wide queues.
Approval state is persisted on a monthly `FundRequest` per (CCEO, month); approve
→ `approved_by_pl`, return → `returned_by_pl` (which the CCEO's To-Do picks up).
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from apps.core.exceptions import BadRequest, Forbidden
from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope

# Statuses that count as "PL-approved" — past the PL gate and routed to / through
# the Accountant for disbursement. Approve sends a plan straight to the accountant.
PL_APPROVED_STATUSES = (
    "approved_by_pl",
    "sent_to_accountant",
    "disbursed",
    "closed",
)

VISIT_TYPES = ["school_visit", "follow_up_visit", "coaching_visit", "core_visit"]
SSA_VISIT_TYPES = [
    "baseline_ssa_visit",
    "school_visit_ssa_collection",
    "partner_ssa_collection",
    "ssa_activity",
    "core_assessment_visit",
]
TRAINING_TYPES = [
    "training",
    "school_improvement_training",
    "in_school_support",
    "core_training",
]
CLUSTER_MEETING = ["cluster_meeting", "cluster_meeting_ssa_review"]
CLUSTER_TRAINING = ["cluster_training", "cluster_training_ssa_collection"]

CATEGORY_ORDER = [
    "Staff School Visits",
    "Partner School Visits",
    "Cluster Meetings",
    "Cluster Trainings",
    "In-School Trainings",
    "SSA Support Visits",
    "Other",
]
# Budget-mix segment colours (Tailwind bg classes).
MIX_COLORS = {
    "Staff School Visits": "bg-emerald-500",
    "Partner School Visits": "bg-violet-500",
    "Cluster Meetings": "bg-blue-500",
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


def _ugx(n):
    n = int(n or 0)
    if n >= 1_000_000_000:
        return f"UGX {n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"UGX {n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"UGX {n / 1_000:.0f}K"
    return f"UGX {n:,}"


def _category(activity_type, delivery_type):
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
    return "Other"


def _scoped_cceos(scope):
    """The CCEO records this PL supervises. Returns dicts with both id spaces."""
    from apps.accounts.models import StaffProfile

    cceos = []
    for sp in StaffProfile.objects.filter(
        id__in=scope.supervised_staff_ids
    ).select_related("user"):
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


def _period_key(fy, month):
    return f"{fy}-M{int(month)}"


def _fund_request_for(cceo_user_id, fy, month):
    from .models import FundRequest

    return FundRequest.objects.filter(
        submitted_by_user_id=cceo_user_id,
        period="monthly",
        period_key=_period_key(fy, month),
    ).first()


def _status_label(fr, valid):
    """Queue status from the persisted FundRequest + validation."""
    if fr:
        s = fr.status
        if s in (
            "approved_by_pl",
            "approved",
            "disbursed",
            "closed",
            "sent_to_accountant",
            "submitted_to_cd",
            "approved_by_cd",
        ):
            return ("Approved", "success")
        if s in ("returned_by_pl", "returned", "rejected"):
            return ("Returned", "danger")
    if not valid:
        return ("Needs Review", "info")
    return ("Awaiting Approval", "warning")


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


def _build_cceo_plan(cceo, lines, fy, month):
    """Aggregate one CCEO's month of budget lines into a queue/detail record."""
    total = sum(li.amount for li in lines)
    acts = {}
    schools = set()
    cat_totals: dict[str, dict] = {}
    for li in lines:
        a = li.activity
        acts[a.id] = a
        if a.school_id:
            schools.add(a.school_id)
        cat = _category(a.activity_type, a.delivery_type)
        d = cat_totals.setdefault(cat, {"total": 0, "acts": set()})
        d["total"] += li.amount
        d["acts"].add(a.id)

    act_list = list(acts.values())
    n_visits = sum(
        1
        for a in act_list
        if a.activity_type in VISIT_TYPES and a.delivery_type != "partner"
    )
    n_partner = sum(1 for a in act_list if a.delivery_type == "partner")
    n_clusters = sum(
        1 for a in act_list if a.activity_type in CLUSTER_MEETING + CLUSTER_TRAINING
    )
    n_trainings = sum(
        1 for a in act_list if a.activity_type in TRAINING_TYPES + CLUSTER_TRAINING
    )

    # geography from the CCEO's schools (most common)
    districts = [
        a.school.district.name for a in act_list if a.school_id and a.school.district_id
    ]
    regions = [
        a.school.region.name for a in act_list if a.school_id and a.school.region_id
    ]
    district = max(set(districts), key=districts.count) if districts else "—"
    region = max(set(regions), key=regions.count) if regions else "—"

    fr = _fund_request_for(cceo["user_id"], fy, month)
    issues = _validate(cceo, lines, month)
    valid = not issues
    status_label, status_tone = _status_label(fr, valid)

    return {
        "cceo": cceo,
        "name": cceo["name"],
        "district": district,
        "region": region,
        "total": total,
        "total_fmt": _ugx(total),
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
        "fr_status": fr.status if fr else None,
        "fund_request_id": fr.id if fr else None,
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

    from apps.activities.models import ActivityScheduleCostLine

    cceos = _scoped_cceos(scope)
    all_ids = [i for c in cceos for i in c["ids"]]

    # Default to the team's busiest funded month (so the page opens populated).
    if not filters.get("month") and all_ids:
        from django.db.models import Count

        busiest = (
            ActivityScheduleCostLine.objects.filter(
                activity__responsible_staff_id__in=all_ids,
                activity__fy=fy,
                month__isnull=False,
            )
            .values("month")
            .annotate(n=Count("id"))
            .order_by("-n")
            .first()
        )
        if busiest:
            month = int(busiest["month"])

    lines = (
        list(
            ActivityScheduleCostLine.objects.filter(
                activity__responsible_staff_id__in=all_ids,
                activity__fy=fy,
                month=month,
                activity__deleted_at__isnull=True,
            ).select_related(
                "activity",
                "activity__school",
                "activity__school__district",
                "activity__school__region",
                "activity__cluster",
            )
        )
        if all_ids
        else []
    )

    # bucket lines by CCEO (match either id space)
    lines_by_cceo: dict[str, list] = {}
    for li in lines:
        rid = li.activity.responsible_staff_id
        cceo = next((c for c in cceos if rid in c["ids"]), None)
        if cceo:
            lines_by_cceo.setdefault(cceo["user_id"], []).append(li)

    plans = []
    for c in cceos:
        c_lines = lines_by_cceo.get(c["user_id"], [])
        if not c_lines:
            continue
        plans.append(_build_cceo_plan(c, c_lines, fy, month))
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

    # ── KPIs (team-scoped, this month) ────────────────────────────────────────
    total_requested = sum(p["total"] for p in plans)
    awaiting = [
        p
        for p in plans
        if p["status"] in ("Awaiting Approval", "Needs Review", "Ready")
    ]
    returned = [p for p in plans if p["status"] == "Returned"]
    unique_schools = len({s for p in plans for s in p["schools"]})
    from .models import FundRequest

    today = timezone.now().date()
    approved_today = FundRequest.objects.filter(
        reviewed_by_user_id=principal.user_id,
        status__in=PL_APPROVED_STATUSES,
        reviewed_at__date=today,
    )
    approved_today_total = sum(f.total_amount for f in approved_today)

    kpis = [
        {
            "label": "Total Requested This Month",
            "value": _ugx(total_requested),
            "icon": "finance",
            "variant": "primary",
            "helper": f"{len(plans)} plan{'' if len(plans) == 1 else 's'}",
        },
        {
            "label": "Awaiting Approval",
            "value": _ugx(sum(p["total"] for p in awaiting)),
            "icon": "clock",
            "variant": "warning",
            "helper": f"{len(awaiting)} request{'' if len(awaiting) == 1 else 's'}",
        },
        {
            "label": "Approved Today",
            "value": _ugx(approved_today_total),
            "icon": "check",
            "variant": "success",
            "helper": f"{approved_today.count()} request{'' if approved_today.count() == 1 else 's'}",
        },
        {
            "label": "Returned for Review",
            "value": _ugx(sum(p["total"] for p in returned)),
            "icon": "warning",
            "variant": "danger",
            "helper": f"{len(returned)} request{'' if len(returned) == 1 else 's'}",
        },
        {
            "label": "Planned Activities Funding",
            "value": _ugx(total_requested),
            "icon": "briefcase",
            "variant": "analytics",
            "helper": "From scheduled work",
        },
        {
            "label": "Average Cost per School",
            "value": _ugx(round(total_requested / unique_schools))
            if unique_schools
            else "—",
            "icon": "school",
            "variant": "info",
            "helper": f"{unique_schools} schools",
        },
    ]

    # ── Budget mix (aggregate categories across the team) ──────────────────────
    mix_tot: dict[str, int] = {}
    for p in plans:
        for cat, d in p["cat_totals"].items():
            mix_tot[cat] = mix_tot.get(cat, 0) + d["total"]
    mix_grand = sum(mix_tot.values()) or 1
    budget_mix = [
        {
            "label": cat,
            "amount": _ugx(mix_tot[cat]),
            "pct": round(mix_tot[cat] / mix_grand * 100),
            "color": MIX_COLORS.get(cat, "bg-slate-400"),
        }
        for cat in CATEGORY_ORDER
        if mix_tot.get(cat)
    ]

    # ── Recent approval activity (this PL's reviews) ──────────────────────────
    name_by_uid = {c["user_id"]: c["name"] for c in cceos}
    recent = []
    for fr in (
        FundRequest.objects.filter(reviewed_by_user_id=principal.user_id)
        .exclude(reviewed_at__isnull=True)
        .order_by("-reviewed_at")[:6]
    ):
        approved = fr.status in PL_APPROVED_STATUSES
        recent.append(
            {
                "name": name_by_uid.get(fr.submitted_by_user_id, "CCEO"),
                "action": "approved" if approved else "returned for review",
                "tone": "success" if approved else "danger",
                "amount": _ugx(fr.total_amount),
                "when": fr.reviewed_at.strftime("%b %-d, %-I:%M %p"),
            }
        )

    # ── Selected plan detail ──────────────────────────────────────────────────
    selected = None
    sel = next((p for p in queue if p["cceo"]["user_id"] == selected_id), None) or (
        queue[0] if queue else None
    )
    if sel:
        selected = _selected_detail(sel, fy, month)

    # right panel
    right = {
        "this_month": {
            "waiting": _ugx(sum(p["total"] for p in awaiting)),
            "returned": _ugx(sum(p["total"] for p in returned)),
            "approved_today": _ugx(approved_today_total),
        },
        "monthly": {
            "total": _ugx(total_requested),
            "approved": _ugx(
                sum(
                    f.total_amount
                    for f in FundRequest.objects.filter(
                        reviewed_by_user_id=principal.user_id,
                        status__in=PL_APPROVED_STATUSES,
                        fy=fy,
                    )
                )
            ),
            "pct": 0,
        },
        "rate": _approval_rate(plans),
        "rules": [
            "Funds must come from approved plans.",
            "Partner visits must map to planned schools.",
            "Cluster training budget scales by participants.",
            "Returned requests need correction before re-submission.",
        ],
    }
    approved_amt = sum(
        f.total_amount
        for f in FundRequest.objects.filter(
            reviewed_by_user_id=principal.user_id,
            status__in=PL_APPROVED_STATUSES,
            fy=fy,
        )
    )
    right["monthly"]["pct"] = (
        round(approved_amt / total_requested * 100) if total_requested else 0
    )

    return {
        "fy": fy,
        "month": month,
        "month_label": MONTHS[month] if 1 <= month <= 12 else str(month),
        "fy_options": [fy, str(int(fy) - 1)],
        "queue": [_queue_card(p, sel) for p in queue],
        "queue_count": len(queue),
        "kpis": kpis,
        "selected": selected,
        "budget_mix": budget_mix,
        "recent": recent,
        "right": right,
        "status_options": [
            "Awaiting Approval",
            "Ready",
            "Needs Review",
            "Returned",
            "Approved",
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


def _selected_detail(p, fy, month):
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
    # plan snapshot
    acts = p["activities"]
    staff_school_ids = {
        a.school_id for a in acts if a.school_id and a.delivery_type != "partner"
    }
    partner_visits = sum(1 for a in acts if a.delivery_type == "partner")
    snapshot = {
        "staff_schools": len(staff_school_ids),
        "partner_visits": partner_visits,
        "cluster_meetings": sum(1 for a in acts if a.activity_type in CLUSTER_MEETING),
        "trainings": sum(
            1 for a in acts if a.activity_type in TRAINING_TYPES + CLUSTER_TRAINING
        ),
        "total_schools": len(p["schools"]),
    }
    return {
        "cceo_user_id": p["cceo"]["user_id"],
        "name": p["name"],
        "district": p["district"],
        "region": p["region"],
        "period": f"{MONTHS[month]} 1 – {MONTHS[month]} {_month_end(fy, month)}, {fy}",
        "status": p["status"],
        "status_tone": p["status_tone"],
        "total_fmt": p["total_fmt"],
        "breakdown": breakdown,
        "snapshot": snapshot,
        "valid": p["valid"],
        "issues": p["issues"],
    }


def _month_end(fy, month):
    import calendar

    # FY month → calendar year: Oct–Dec belong to fy-1, Jan–Sep to fy.
    year = int(fy) - 1 if month >= 10 else int(fy)
    return calendar.monthrange(year, month)[1]


def _approval_rate(plans):
    approved = sum(1 for p in plans if p["status"] == "Approved")
    returned = sum(1 for p in plans if p["status"] == "Returned")
    pending = sum(
        1
        for p in plans
        if p["status"] in ("Awaiting Approval", "Needs Review", "Ready")
    )
    tot = approved + returned + pending or 1
    return {
        "approved": round(approved / tot * 100),
        "returned": round(returned / tot * 100),
        "pending": round(pending / tot * 100),
    }


# ── Actions ───────────────────────────────────────────────────────────────────
def _ensure_fund_request(principal, cceo, fy, month):
    """Get or build the monthly FundRequest that carries the approval state,
    rebuilt from the CCEO's live budget lines (the PL never edits amounts)."""
    from apps.activities.models import ActivityScheduleCostLine

    from .models import FundRequest, FundRequestItem

    lines = list(
        ActivityScheduleCostLine.objects.filter(
            activity__responsible_staff_id__in=cceo["ids"],
            activity__fy=fy,
            month=month,
            activity__deleted_at__isnull=True,
        ).select_related("activity")
    )
    if not lines:
        raise BadRequest("This plan has no scheduled, costed activities to approve.")
    total = sum(li.amount for li in lines)
    act_ids = {li.activity_id for li in lines}
    # update_or_create + the delete/recreate of items must be atomic — a crash
    # between the delete and the bulk_create would otherwise leave the
    # FundRequest with a stale total_amount/activity_count but zero items.
    with transaction.atomic():
        fr, _ = FundRequest.objects.update_or_create(
            submitted_by_user_id=cceo["user_id"],
            period="monthly",
            period_key=_period_key(fy, month),
            defaults={
                "fy": fy,
                "scope": "own",
                "submitted_by_role": "CCEO",
                "total_amount": total,
                "activity_count": len(act_ids),
            },
        )
        # keep items in sync with live budget lines
        fr.items.all().delete()
        FundRequestItem.objects.bulk_create(
            [
                FundRequestItem(
                    fund_request=fr,
                    activity_id=li.activity_id,
                    activity_schedule_cost_line_id=li.id,
                    amount=li.amount,
                    period="monthly",
                    period_key=_period_key(fy, month),
                )
                for li in lines
            ]
        )
    return fr, lines


def _resolve_cceo(principal, cceo_user_id):
    scope = resolve_user_scope(principal)
    cceo = next((c for c in _scoped_cceos(scope) if c["user_id"] == cceo_user_id), None)
    if not cceo:
        raise Forbidden("That CCEO is not on your supervised team.")
    return cceo


# Once the Accountant queue has taken any action on a plan, PL "Approve" is no
# longer a fresh decision — re-clicking it (stale tab, double-click) must not
# silently flip a disbursed/held plan back to "sent_to_accountant" and reopen
# it for a second payout.
_LOCKED_AFTER_ACCOUNTANT_ACTION = {"sent_to_accountant", "disbursed", "held"}


def approve(principal, cceo_user_id, fy, month):
    """PL approves a valid fund plan and routes it straight to the Accountant's
    disbursement queue → status ``sent_to_accountant`` (+ audit + notify the CCEO
    and the accountants who will disburse)."""
    from .models import FundRequest

    _require_pl(principal)
    cceo = _resolve_cceo(principal, cceo_user_id)

    existing = FundRequest.objects.filter(
        submitted_by_user_id=cceo["user_id"],
        period="monthly",
        period_key=_period_key(fy, month),
    ).first()
    if existing and existing.status in _LOCKED_AFTER_ACCOUNTANT_ACTION:
        raise BadRequest(
            f"This plan is already {existing.get_status_display()} — it cannot "
            "be approved again."
        )

    fr, lines = _ensure_fund_request(principal, cceo, fy, month)
    issues = _validate(cceo, lines, month)
    if issues:
        raise BadRequest("Cannot approve — plan needs review: " + issues[0])

    fr.status = "sent_to_accountant"
    fr.reviewed_by_user_id = principal.user_id
    fr.reviewed_at = timezone.now()
    fr.save(
        update_fields=["status", "reviewed_by_user_id", "reviewed_at", "updated_at"]
    )

    _audit(
        principal,
        "fund_request.approve_pl",
        fr,
        cceo,
        {"total": fr.total_amount, "routed_to": "accountant"},
    )
    _notify(
        principal,
        cceo,
        "fund_request_approved",
        "Fund plan approved & sent to Accountant",
        f"Your {MONTHS[month]} fund plan ({_ugx(fr.total_amount)}) was approved by your "
        "Program Lead and sent to the Accountant for disbursement.",
    )
    _notify_accountants(fr, cceo, month)
    return fr


# Accountant-side actions (disburse / hold / return / confirm receipt) live in
# apps.fund_requests.disbursement_dashboard_service — the accountant's queue.


def return_request(principal, cceo_user_id, fy, month, data):
    """PL returns a plan for correction → returned_by_pl (+ audit + notify + CCEO To-Do)."""
    _require_pl(principal)
    reason = (data.get("reason") or "").strip()
    if not reason:
        raise BadRequest("A return reason is required.")
    cceo = _resolve_cceo(principal, cceo_user_id)
    fr, _ = _ensure_fund_request(principal, cceo, fy, month)

    fr.status = "returned_by_pl"
    fr.reviewed_by_user_id = principal.user_id
    fr.reviewed_at = timezone.now()
    fr.review_note = (
        reason + (" — " + data["comment"] if data.get("comment") else "")
    )[:512]
    fr.save(
        update_fields=[
            "status",
            "reviewed_by_user_id",
            "reviewed_at",
            "review_note",
            "updated_at",
        ]
    )

    _audit(principal, "fund_request.return_pl", fr, cceo, {"reason": reason})
    _notify(
        principal,
        cceo,
        "fund_request_returned",
        "Fund plan returned for review",
        f"Your {MONTHS[month]} fund plan was returned by your Program Lead. Reason: {reason}",
    )
    # The CCEO's "Fix Fund Request" To-Do is derived automatically from the
    # returned_by_pl status (todo_service._fund_request_todos).
    return fr


def approve_all_valid(principal, fy, month):
    """Approve every valid, awaiting plan on the PL's team in one pass.

    Invalid ("Needs Review") plans are skipped, never force-approved. Returns
    (approved_count, skipped_count) so the caller can surface the outcome.
    """
    _require_pl(principal)
    data = get_pl_fund_approvals(principal, {"fy": fy, "month": month})
    approved = skipped = 0
    for q in data["queue"]:
        status = q["status"]
        if status in ("Awaiting Approval", "Ready"):
            try:
                approve(principal, q["cceo_user_id"], fy, month)
                approved += 1
            except (BadRequest, Forbidden):
                skipped += 1  # became invalid between render and approve
        elif status == "Needs Review":
            skipped += 1  # invalid plan — never force-approved
        # Already Approved/Returned plans are left untouched.
    return approved, skipped


def _audit(principal, action, fr, cceo, payload):
    try:
        from apps.audit.services import log as audit_log

        audit_log(
            action=action,
            subject_kind="FundRequest",
            subject_id=fr.id,
            actor_id=principal.user_id,
            actor_role=principal.active_role,
            success=True,
            payload={"cceo": cceo["name"], "period_key": fr.period_key, **payload},
        )
    except Exception:  # noqa: BLE001 - audit must never block the action
        pass


def _notify(principal, cceo, event, title, body):
    try:
        from apps.notifications.services import WorkflowNotificationService

        WorkflowNotificationService.trigger(
            event_type=event,
            category="finance",
            priority="high",
            title=title,
            body=body,
            context_type="FundRequest",
            context_id=cceo["user_id"],
            recipients=[cceo["user_id"]],
        )
    except Exception:  # noqa: BLE001
        pass


def _notify_accountants(fr, cceo, month):
    """Alert the accountants that a PL-approved fund plan is ready to disburse."""
    try:
        from apps.accounts.models import User
        from apps.notifications.services import WorkflowNotificationService

        ids = list(
            User.objects.filter(active_role="Accountant", is_active=True).values_list(
                "id", flat=True
            )
        )
        if not ids:
            return
        WorkflowNotificationService.trigger(
            event_type="fund_request_sent_to_accountant",
            category="finance",
            priority="high",
            title="Fund plan ready to disburse",
            body=f"{cceo['name']}'s {MONTHS[month]} fund plan ({_ugx(fr.total_amount)}) "
            "was approved by the Program Lead and is ready for disbursement.",
            context_type="FundRequest",
            context_id=fr.id,
            recipients=ids,
        )
    except Exception:  # noqa: BLE001
        pass
