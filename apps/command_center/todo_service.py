"""System-generated To-Do operating queue — derived live from workflow state.

A To-Do is NOT stored. It is computed at read time from the current state of
activities, fund requests, SSA, schools, leave, etc. This means:

  • System-generated — no user creates them; they appear from workflow events.
  • Auto-closing — when the underlying action completes, the state changes and
    the derived To-Do simply disappears. No sync, no manual "tick complete".
  • Role-scoped — each principal only sees the actions that are theirs.

Final rule (per spec): Notifications say something happened; Messages discuss it;
My Plan shows scheduled execution; To-Do shows the exact action required now.

The activity-based derivations reuse `my_plan.services.compute_next_action` — the
single source of truth for "what's the next action on this activity".
"""

from __future__ import annotations

from datetime import date

from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.fy import get_operational_fy
from apps.core.scoping import resolve_user_scope

# Actions from compute_next_action that require the owner to act now.
ACTIONABLE = {
    "fix",
    "start",
    "complete",
    "evidence",
    "sf_id",
    "submit",
    "ssa",
    # Disbursed → the responsible user submits accountability (spend, receipts,
    # NetSuite Code). The Accountant then reviews it (_accountant_todos).
    "accountability",
}
WAITING = {"view_status"}  # done my part — blocked on IA/accounts/finance

# action -> (category, short button label)
ACTION_META = {
    "fix": ("Execution", "Fix"),
    "start": ("Execution", "Start"),
    "complete": ("Execution", "Complete"),
    "evidence": ("Evidence", "Upload"),
    "sf_id": ("Evidence", "Enter ID"),
    "submit": ("Execution", "Submit"),
    "ssa": ("SSA", "Upload SSA"),
    "accountability": ("Finance", "Submit Accountability"),
    "view_status": ("Execution", "View"),
}
PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
PRIORITY_LABEL = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
}


def _owner_ids(principal, scope):
    """Both identifier spaces — activities stamp responsible_staff_id as either
    the StaffProfile CUID or the User CUID depending on how they were created."""
    ids = {
        *(scope.staff_ids or []),
        getattr(principal, "staff_profile_id", None),
        getattr(principal, "user_id", None),
    }
    return [i for i in ids if i]


def _due(planned_date, today):
    """Return (due_label, due_tone, sort_key)."""
    if not planned_date:
        return ("—", "neutral", date.max)
    if planned_date < today:
        return ("Overdue", "danger", planned_date)
    if planned_date == today:
        return ("Today", "warning", planned_date)
    return (planned_date.strftime("%b %-d"), "info", planned_date)


def _act_priority(a, action, today):
    # High: due today, overdue, returned work, evidence/SF-ID/complete/fix.
    if action == "accountability":
        return "critical"  # money is out — accountability is the top loop to close
    if action in ("fix", "evidence", "sf_id", "complete"):
        return "high"
    if action == "start":
        return "high" if a.planned_date == today else "medium"
    if action in ("ssa", "submit"):
        return "medium"
    return "low"


def _act_status(a, action, today):
    if a.status in (
        "returned",
        "returned_by_pl",
        "returned_by_ia",
    ):
        return ("returned", "Returned", "danger")
    if action in WAITING:
        return ("blocked", "Waiting on Review", "neutral")
    if a.planned_date and a.planned_date < today:
        return ("overdue", "Overdue", "danger")
    if a.planned_date == today:
        return ("due_today", "Due Today", "warning")
    return ("waiting_me", "Waiting on Me", "info")


def _activity_todos(principal, scope, today, fy):
    from apps.activities.models import Activity
    from apps.my_plan.services import compute_next_action

    owner_ids = _owner_ids(principal, scope)
    if not owner_ids:
        return []
    qs = (
        Activity.objects.filter(deleted_at__isnull=True, fy=fy)
        .filter(
            Q(responsible_staff_id__in=owner_ids)
            | Q(monitored_by_staff_id__in=owner_ids, delivery_type="partner")
        )
        .exclude(status__in=["closed", "cancelled", "rejected", "not_planned"])
        .select_related("school", "cluster")
        .prefetch_related("schedule_cost_lines__advance_requests")[:120]
    )
    todos = []
    for a in qs:
        na = compute_next_action(a, today)
        action = na["action"]
        if action not in ACTIONABLE and action not in WAITING:
            continue
        category, btn = ACTION_META.get(action, ("Execution", "View"))
        status_key, status_label, status_tone = _act_status(a, action, today)
        due_label, due_tone, due_sort = _due(a.planned_date, today)
        where = (
            a.school.name if a.school_id else (a.cluster.name if a.cluster_id else "—")
        )
        atype = a.get_activity_type_display()
        todos.append(
            {
                "id": f"act-{a.id}",
                "title": na["text"],
                "description": f"{na['description']} — {where}",
                "category": category,
                "priority": _act_priority(a, action, today),
                "status_key": status_key,
                "status_label": status_label,
                "status_tone": status_tone,
                "due_label": due_label,
                "due_tone": due_tone,
                "linked": f"{where} · {atype}",
                "action_label": btn,
                "action_url": na["url"],
                "actionable": action in ACTIONABLE,
                "source": "Activity workflow",
                "_due_sort": due_sort,
            }
        )
    return todos


def _fund_request_todos(principal, role):
    from apps.fund_requests.models import WeeklyFundRequest

    todos = []
    uid = getattr(principal, "user_id", None)
    returned_statuses = [
        "returned_by_pl",
        "returned_by_cd",
        "returned_by_rvp",
        "returned_by_accountant",
    ]
    own = WeeklyFundRequest.objects.filter(
        responsible_user=uid,
        status__in=["pending_responsible_confirmation", *returned_statuses],
    ).order_by("-week_start_date")[:10]
    for w in own:
        returned = w.status in returned_statuses
        todos.append(
            {
                "id": f"wfr-{w.id}",
                "title": "Fix Fund Request" if returned else "Confirm Fund Request",
                "description": f"Weekly fund request {w.week_start_date:%b %-d}–{w.week_end_date:%b %-d}"
                + (" was returned" if returned else " needs your confirmation"),
                "category": "Finance",
                "priority": "critical" if returned else "high",
                "status_key": "returned" if returned else "waiting_me",
                "status_label": "Returned" if returned else "Waiting on Me",
                "status_tone": "danger" if returned else "info",
                "due_label": "Today",
                "due_tone": "warning",
                "linked": f"Weekly Fund Request · {w.week_start_date:%b %-d}",
                "action_label": "Open",
                "action_url": "/fund-requests/weekly",
                "actionable": True,
                "source": "Finance workflow",
                "_due_sort": date.today(),
            }
        )

    approver_status = {
        "Program Lead": "submitted_to_pl",
        "CountryDirector": "submitted_to_cd",
    }.get(role)
    if approver_status:
        approver_qs = WeeklyFundRequest.objects.filter(status=approver_status)
        if role == "Program Lead":
            # A PL approves only their own supervised CCEOs' requests —
            # never another PL's portfolio.
            from apps.accounts.models import StaffSupervisorAssignment

            supervised = StaffSupervisorAssignment.objects.filter(
                supervisor__user_id=uid
            ).values_list("supervisee__user_id", flat=True)
            approver_qs = approver_qs.filter(responsible_user__in=list(supervised))
        for w in approver_qs.order_by("-week_start_date")[:15]:
            todos.append(
                {
                    "id": f"wfr-appr-{w.id}",
                    "title": "Approve Fund Request",
                    "description": f"Fund request {w.week_start_date:%b %-d}–{w.week_end_date:%b %-d} awaits your approval",
                    "category": "Approval",
                    "priority": "medium",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "info",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": f"Weekly Fund Request · {w.week_start_date:%b %-d}",
                    "action_label": "Review",
                    "action_url": "/fund-requests/weekly",
                    "actionable": True,
                    "source": "Finance approval",
                    "_due_sort": date.max,
                }
            )

    # Monthly fund plans returned by the PL or the Accountant — the requester
    # must correct and re-submit. Auto-closes when the plan is re-approved
    # (status moves off returned_*).
    from apps.fund_requests.models import FundRequest

    for fr in FundRequest.objects.filter(
        submitted_by_user_id=uid,
        period="monthly",
        status__in=["returned_by_pl", "returned_by_accountant"],
    ).order_by("-reviewed_at")[:8]:
        by = "Accountant" if fr.status == "returned_by_accountant" else "Program Lead"
        todos.append(
            {
                "id": f"frmonth-{fr.id}",
                "title": "Fix Returned Fund Request",
                "description": (
                    fr.review_note or f"Your fund plan was returned by your {by}."
                ),
                "category": "Finance",
                "priority": "critical",
                "status_key": "returned",
                "status_label": "Returned",
                "status_tone": "danger",
                "due_label": "Today",
                "due_tone": "warning",
                "linked": f"Monthly Fund Plan · {fr.period_key}",
                "action_label": "Fix",
                "action_url": "/fund-requests/weekly",
                "actionable": True,
                "source": "Finance workflow",
                "_due_sort": date.today(),
            }
        )

    # Disbursed monthly plans awaiting the requester's receipt confirmation.
    # Auto-closes when receipt_confirmed_at is stamped (confirm on the weekly
    # fund page banner).
    for fr in FundRequest.objects.filter(
        submitted_by_user_id=uid,
        period="monthly",
        status="disbursed",
        receipt_confirmed_at__isnull=True,
    ).order_by("-disbursed_at")[:5]:
        todos.append(
            {
                "id": f"frreceipt-{fr.id}",
                "title": "Confirm Receipt of Funds",
                "description": f"Funds for your {fr.period_key} fund plan were disbursed"
                + (f" via {fr.disburse_method}" if fr.disburse_method else "")
                + ". Check your account and confirm receipt.",
                "category": "Finance",
                "priority": "high",
                "status_key": "waiting_me",
                "status_label": "Waiting on Me",
                "status_tone": "info",
                "due_label": "Today",
                "due_tone": "warning",
                "linked": f"Monthly Fund Plan · {fr.period_key}",
                "action_label": "Confirm",
                "action_url": "/fund-requests/weekly",
                "actionable": True,
                "source": "Finance workflow",
                "_due_sort": date.today(),
            }
        )
    return todos


def _school_quality_todos(scope):
    from apps.schools.models import School

    ids = scope.own_school_ids or scope.school_ids
    if not ids:
        return []
    qs = School.objects.filter(id__in=ids, deleted_at__isnull=True)
    todos = []

    def _q(title, desc, category, priority, label, url, sid, key):
        return {
            "id": f"sch-{sid}-{key}",
            "title": title,
            "description": desc,
            "category": category,
            "priority": priority,
            "status_key": "waiting_me",
            "status_label": "Waiting on Me",
            "status_tone": "info",
            "due_label": "—",
            "due_tone": "neutral",
            "linked": desc,
            "action_label": label,
            "action_url": url,
            "actionable": True,
            "source": "Data quality",
            "_due_sort": date.max,
        }

    for s in qs.filter(
        Q(primary_contact_name__isnull=True) | Q(primary_contact_name="")
    )[:8]:
        todos.append(
            _q(
                "Fix School Contact",
                s.name,
                "Data Quality",
                "low",
                "Fix",
                "/schools",
                s.id,
                "contact",
            )
        )
    for s in qs.filter(cluster_status="unclustered")[:8]:
        todos.append(
            _q(
                "Add School to Cluster",
                s.name,
                "Planning",
                "medium",
                "Cluster",
                "/clusters",
                s.id,
                "cluster",
            )
        )
    for s in qs.filter(cluster_status="clustered", current_fy_ssa_status="not_done")[
        :8
    ]:
        todos.append(
            _q(
                "Schedule Baseline SSA",
                s.name,
                "SSA",
                "medium",
                "Schedule",
                "/planning",
                s.id,
                "ssa",
            )
        )
    return todos


def _ia_todos(principal, role):
    if role not in ("ImpactAssessment", "Admin"):
        return []
    from apps.activities.models import Activity

    todos = []
    for a in (
        Activity.objects.filter(
            deleted_at__isnull=True,
            status="awaiting_ia_verification",
        )
        .select_related("school")
        .order_by("-updated_at")[:20]
    ):
        where = a.school.name if a.school_id else "—"
        todos.append(
            {
                "id": f"ia-{a.id}",
                "title": "Verify Activity",
                "description": f"{a.get_activity_type_display()} at {where} is awaiting verification",
                "category": "IA Verification",
                "priority": "high",
                "status_key": "waiting_me",
                "status_label": "Waiting on Me",
                "status_tone": "info",
                "due_label": "—",
                "due_tone": "neutral",
                "linked": f"{where} · {a.get_activity_type_display()}",
                "action_label": "Verify",
                "action_url": "/ia/dashboard/",
                "actionable": True,
                "source": "IA workflow",
                "_due_sort": date.max,
            }
        )
    return todos


def _leave_todos(principal, role):
    if role not in ("Program Lead", "CountryDirector", "HumanResources", "Admin"):
        return []
    from apps.accounts.models import Leave

    from apps.hr.leave_services import LeaveApprovalService

    todos = []
    # Scoped with the SAME predicate the approvals page uses. Without it every
    # PL, CD and HR user received a To-Do for every pending leave in the
    # platform — including staff they do not supervise — and the linked page
    # then filtered the item out, so the task could never be completed.
    pending = (
        Leave.objects.filter(status="pending")
        .select_related("staff__user")
        .order_by("start_date")[:100]
    )
    for lv in pending:
        if not LeaveApprovalService.is_authorized_approver(principal, lv):
            continue
        if len(todos) >= 10:
            break
        who = getattr(getattr(lv.staff, "user", None), "name", None) or "a staff member"
        todos.append(
            {
                "id": f"leave-{lv.id}",
                "title": "Review Leave Request",
                "description": f"{who} requested {lv.type or 'leave'} ({lv.days or '—'} days)",
                "category": "Leave",
                "priority": "medium",
                "status_key": "waiting_me",
                "status_label": "Waiting on Me",
                "status_tone": "info",
                "due_label": "—",
                "due_tone": "neutral",
                "linked": f"Leave · {who}",
                "action_label": "Review",
                "action_url": "/leave/approvals",
                "actionable": True,
                "source": "Leave workflow",
                "_due_sort": date.max,
            }
        )
    return todos


def _pl_fund_todos(principal, role):
    """PL 'Review {CCEO} Fund Plan' To-Dos — one per supervised CCEO whose fund
    plan awaits approval. Auto-closes when the PL approves/returns (status moves
    off 'Awaiting Approval')."""
    if role not in ("Program Lead", "Admin"):
        return []
    try:
        from apps.fund_requests.pl_approval_service import get_pl_fund_approvals

        d = get_pl_fund_approvals(principal, {})
    except Exception:  # noqa: BLE001
        return []
    todos = []
    for q in d.get("queue", []):
        if q["status"] not in ("Awaiting Approval", "Ready", "Needs Review"):
            continue
        todos.append(
            {
                "id": f"plfund-{q['cceo_user_id']}",
                "title": f"Review {q['name']} Fund Plan",
                "description": f"{q['total_fmt']} — {d['month_label']} fund plan awaits your approval",
                "category": "Budget Approval",
                "priority": "medium" if q["status"] == "Needs Review" else "high",
                "status_key": "waiting_me",
                "status_label": "Waiting on Me",
                "status_tone": "info",
                "due_label": "—",
                "due_tone": "neutral",
                "linked": f"Fund Plan · {q['name']}",
                "action_label": "Review",
                "action_url": "/fund-approvals",
                "actionable": True,
                "source": "Fund approval",
                "_due_sort": date.max,
            }
        )
    return todos[:8]


def _accountant_todos(principal, role):
    """Accountant disbursement-queue To-Dos — one per approved fund item ready
    to disburse, plus NetSuite closure items. All derive from live workflow
    state and auto-close when the accountant acts (status moves on)."""
    if role not in ("Accountant", "Admin"):
        return []
    from apps.accounts.models import User
    from apps.fund_requests.models import FundRequest, WeeklyFundRequest

    todos = []
    monthly = list(
        FundRequest.objects.filter(
            period="monthly", status="sent_to_accountant"
        ).order_by("-reviewed_at")[:10]
    )
    names = dict(
        User.objects.filter(
            id__in=[f.submitted_by_user_id for f in monthly]
        ).values_list("id", "name")
    )
    for fr in monthly:
        who = names.get(fr.submitted_by_user_id, "CCEO")
        todos.append(
            {
                "id": f"disb-fr-{fr.id}",
                "title": f"Disburse {who} Fund Plan",
                "description": f"{fr.period_key} plan approved by the PL — ready for disbursement",
                "category": "Finance",
                "priority": "high",
                "status_key": "waiting_me",
                "status_label": "Waiting on Me",
                "status_tone": "info",
                "due_label": "—",
                "due_tone": "neutral",
                "linked": f"Fund Plan · {fr.period_key}",
                "action_label": "Disburse",
                "action_url": "/disbursements",
                "actionable": True,
                "source": "Disbursement queue",
                "_due_sort": date.today(),
            }
        )
    for w in WeeklyFundRequest.objects.filter(status="confirmed_for_advance").order_by(
        "-week_start_date"
    )[:10]:
        todos.append(
            {
                "id": f"disb-wfr-{w.id}",
                "title": "Disburse Weekly Advance",
                "description": f"Confirmed advance for week {w.week_start_date:%b %-d} awaits disbursement",
                "category": "Finance",
                "priority": "high",
                "status_key": "waiting_me",
                "status_label": "Waiting on Me",
                "status_tone": "info",
                "due_label": "—",
                "due_tone": "neutral",
                "linked": f"Weekly Advance · {w.week_start_date:%b %-d}",
                "action_label": "Disburse",
                "action_url": "/disbursements",
                "actionable": True,
                "source": "Disbursement queue",
                "_due_sort": date.today(),
            }
        )
    # Accountability SUBMITTED (spend + NetSuite Code from the responsible
    # user) — the Accountant reviews and clears or returns it. The code is
    # entered by the submitter, not the Accountant; this To-Do is the review.
    from apps.fund_requests.models import AdvanceRequest

    for adv in (
        AdvanceRequest.objects.filter(status="accountability_pending")
        .select_related("activity")
        .order_by("accountability_submitted_at")[:8]
    ):
        todos.append(
            {
                "id": f"acct-review-{adv.id}",
                "title": "Review Accountability",
                "description": (
                    f"Accountability submitted (NetSuite {adv.accountability_netsuite_id or '—'}, "
                    f"UGX {adv.accounted_amount or 0:,} spent) awaits your clearance"
                ),
                "category": "Finance",
                "priority": "high",
                "status_key": "waiting_me",
                "status_label": "Waiting on Me",
                "status_tone": "info",
                "due_label": "—",
                "due_tone": "neutral",
                "linked": f"Advance · {adv.activity_id}",
                "action_label": "Review",
                "action_url": "/disbursements",
                "actionable": True,
                "source": "Reconciliation",
                "_due_sort": date.today(),
            }
        )
    return todos[:15]


def _country_budget_todos(principal, role):
    """Country Monthly Budget lifecycle To-Dos — CD review/fix, RVP review,
    Accountant prep — derived live from MonthlyWorkPlanBudget status. The CD
    "Review" nudge is scoped to the current operational month only (so old,
    untouched draft months don't pile up forever); a returned budget stays
    actionable regardless of month until the CD fixes and resubmits it."""
    from apps.monthly_work_plan.models import MonthlyWorkPlanBudget

    todos = []
    if role in ("CountryDirector", "Admin"):
        month_key = f"{date.today().year}-{date.today().month:02d}"
        current = MonthlyWorkPlanBudget.objects.filter(
            country_id="Uganda",
            month_key=month_key,
            status__in=["draft_generated", "cd_review", "admin_plan_added"],
        ).first()
        if current:
            todos.append(_country_budget_todo(current, returned=False))
        for b in MonthlyWorkPlanBudget.objects.filter(
            country_id="Uganda", status="returned_by_rvp"
        ).order_by("-month_key")[:5]:
            todos.append(_country_budget_todo(b, returned=True))

    if role in ("RegionalVicePresident", "Admin"):
        for b in MonthlyWorkPlanBudget.objects.filter(
            country_id="Uganda", status="submitted_to_rvp"
        ).order_by("-month_key")[:5]:
            todos.append(
                {
                    "id": f"cmb-rvp-{b.id}",
                    "title": "Review Country Monthly Budget",
                    "description": f"Uganda {b.month_key} Country Monthly Budget ({_country_budget_ugx(b.total_amount)}) awaits your approval.",
                    "category": "Budget Approval",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "info",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": f"Country Monthly Budget · {b.month_key}",
                    "action_label": "Review",
                    "action_url": "/country-budget",
                    "actionable": True,
                    "source": "Country budget workflow",
                    "_due_sort": date.max,
                }
            )

    if role in ("Accountant", "Admin"):
        for b in MonthlyWorkPlanBudget.objects.filter(
            country_id="Uganda", status="approved_by_rvp"
        ).order_by("-month_key")[:5]:
            todos.append(
                {
                    "id": f"cmb-acct-{b.id}",
                    "title": "Prepare Monthly Disbursement Queue",
                    "description": f"{b.month_key} Country Monthly Budget ({_country_budget_ugx(b.total_amount)}) was approved and is ready to prepare for disbursement.",
                    "category": "Finance",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "info",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": f"Country Monthly Budget · {b.month_key}",
                    "action_label": "Prepare",
                    "action_url": "/disbursements",
                    "actionable": True,
                    "source": "Country budget workflow",
                    "_due_sort": date.max,
                }
            )
    return todos


def _country_budget_ugx(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"UGX {n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"UGX {n / 1_000:.0f}K"
    return f"UGX {n:,}"


def _country_budget_todo(b, returned):
    return {
        "id": f"cmb-cd-{b.id}",
        "title": "Fix Returned Country Monthly Budget"
        if returned
        else f"Review {b.month_key} Country Monthly Budget",
        "description": (
            (
                b.rvp_review_note
                or "Your Country Monthly Budget was returned by the RVP."
            )
            if returned
            else f"{_country_budget_ugx(b.total_amount)} across {b.activity_count} activities — ready for your review."
        ),
        "category": "Budget Approval",
        "priority": "critical" if returned else "medium",
        "status_key": "returned" if returned else "waiting_me",
        "status_label": "Returned" if returned else "Waiting on Me",
        "status_tone": "danger" if returned else "info",
        "due_label": "Today" if returned else "—",
        "due_tone": "warning" if returned else "neutral",
        "linked": f"Country Monthly Budget · {b.month_key}",
        "action_label": "Fix" if returned else "Review",
        "action_url": "/country-budget",
        "actionable": True,
        "source": "Country budget workflow",
        "_due_sort": date.today() if returned else date.max,
    }


def _pl_analytics_todos(principal, role):
    """Serious analytics signals (schools without SSA, weak clusters, CCEOs
    behind target) surfaced as actionable PL To-Dos — derived live from the
    supervised-team portfolio, never stored. Program Leads only."""
    if role != "Program Lead":
        return []
    from datetime import date as _date

    from apps.analytics.pl_analytics_service import PLAnalyticsService

    out = []
    try:
        for t in PLAnalyticsService.pl_todos(principal):
            out.append(
                {
                    "id": t["id"],
                    "title": t["title"],
                    "description": t["description"],
                    "category": t.get("category", "Analytics"),
                    "priority": t.get("priority", "medium"),
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "info",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": "Program Lead Analytics",
                    "action_label": t.get("action_label", "Review"),
                    "action_url": t.get("action_url", "/analytics/program-lead"),
                    "actionable": True,
                    "source": "PL Analytics",
                    "_due_sort": _date.today(),
                }
            )
    except Exception:  # noqa: BLE001 — analytics To-Dos must never break the queue
        return []
    return out[:8]


def _my_target_todos(principal, role):
    """Personal target To-Dos — derived live from the My Targets focus engine.
    One actionable item per behind target area; auto-closes as soon as the
    area returns to pace (the focus list stops emitting it)."""
    if role not in ("CCEO", "Program Lead", "ProjectCoordinator"):
        return []
    from datetime import date as _date

    try:
        from apps.targets.my_targets import MyTargetQueryService

        page = MyTargetQueryService.get_page(principal)
        out = []
        for f in page["focus"][:3]:
            out.append(
                {
                    "id": f"target-{f['area'].lower().replace(' ', '-')}",
                    "title": f"Recover {f['area']} target",
                    "description": f"{f['achieved']} of {f['target']} this month — {f['reason']}.",
                    "category": "My Targets",
                    "priority": "high" if f["status"] == "Off Track" else "medium",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning" if f["status"] == "Off Track" else "info",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": "My Targets",
                    "action_label": f["action_label"],
                    "action_url": f["action_url"]
                    if f["action_url"] != "?mscs=new"
                    else "/my-targets",
                    "actionable": True,
                    "source": "My Targets",
                    "_due_sort": _date.today(),
                }
            )
        return out
    except Exception:  # noqa: BLE001 — target To-Dos must never break the queue
        return []


def _rvp_todos(principal, role):
    """RVP executive To-Dos — pending monthly/annual budget decisions and open
    strategy follow-ups. Auto-close: deciding the budget or closing the note
    stops the derivation."""
    if role != "RegionalVicePresident":
        return []
    from datetime import date as _date

    try:
        from apps.core.fy import get_operational_fy
        from apps.monthly_work_plan.models import (
            CountryAnnualBudget,
            MonthlyWorkPlanBudget,
        )

        fy = get_operational_fy()
        out = []
        for b in MonthlyWorkPlanBudget.objects.filter(
            fy=fy, status="submitted_to_rvp"
        ).order_by("month_key"):
            out.append(
                {
                    "id": f"rvp-mwpb-{b.id}",
                    "title": f"Review Country Monthly Budget {b.month_key}",
                    "description": f"UGX {b.total_amount:,} across {b.activity_count} "
                    "plan-backed activities awaits your approval.",
                    "category": "Approvals",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": f"Country Budget · {b.month_key}",
                    "action_label": "Review",
                    "action_url": "/country-budget/",
                    "actionable": True,
                    "source": "RVP approvals",
                    "_due_sort": _date.today(),
                }
            )
        for b in CountryAnnualBudget.objects.filter(fy=fy, status="submitted_to_rvp"):
            out.append(
                {
                    "id": f"rvp-annual-{b.id}",
                    "title": f"Review Country Annual Budget FY {b.fy}",
                    "description": f"UGX {b.total_amount:,} annual baseline awaiting "
                    "approval — approval locks the baseline.",
                    "category": "Approvals",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": f"Annual Budget · FY {b.fy}",
                    "action_label": "Review",
                    "action_url": "/dashboard",
                    "actionable": True,
                    "source": "RVP approvals",
                    "_due_sort": _date.today(),
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


def _strategy_note_todos(principal, role):
    """CD To-Dos from open RVP strategy notes — accountable guidance (§23)."""
    if role != "CountryDirector":
        return []
    from datetime import date as _date

    try:
        from apps.monthly_work_plan.models import StrategyNote

        out = []
        notes = StrategyNote.objects.filter(status="open").filter(
            models.Q(responsible_cd_id=principal.id)
            | models.Q(responsible_cd_id__isnull=True)
        )[:8]
        for n in notes:
            out.append(
                {
                    "id": f"strategy-note-{n.id}",
                    "title": f"Act on RVP guidance — {n.priority_label}",
                    "description": n.instruction[:180],
                    "category": "Strategy",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "info",
                    "due_label": n.deadline.strftime("%b %d") if n.deadline else "—",
                    "due_tone": "warning" if n.deadline else "neutral",
                    "linked": n.scope,
                    "action_label": "Open",
                    "action_url": "/dashboard",
                    "actionable": True,
                    "source": "RVP strategy note",
                    "_due_sort": n.deadline or _date.today(),
                }
            )
        return out
    except Exception:  # noqa: BLE001
        return []


def _core_school_todos(principal, role):
    """Core package To-Dos — the next missing slot per assigned core school,
    plus returned core work. Derived live: scheduling or fixing the slot makes
    the item disappear."""
    if role not in ("CCEO", "Program Lead"):
        return []
    from datetime import date as _date

    try:
        from apps.core.fy import get_operational_fy
        from apps.core_schools.models import CorePlan
        from apps.schools.models import School

        scope = resolve_user_scope(principal)
        school_pks = list(scope.school_ids or [])
        if not school_pks:
            return []
        sids = list(
            School.objects.filter(
                id__in=school_pks, school_type="core", deleted_at__isnull=True
            ).values_list("school_id", flat=True)
        )
        if not sids:
            return []
        names = dict(
            School.objects.filter(school_id__in=sids).values_list("school_id", "name")
        )
        done = {
            "Completed",
            "Accountant Confirmed",
            "ia_verified",
            "iaVerify",
            "accountant_confirmed",
        }
        in_flight = {
            "Scheduled",
            "scheduled",
            "Submitted",
            "submitted",
            "IA Pending",
            "ia_pending",
        }
        out = []
        plans = (
            CorePlan.objects.filter(school_id__in=sids, fy=get_operational_fy())
            .exclude(status__in=["Cancelled", "cancelled"])
            .prefetch_related("slots")
        )
        for plan in plans[:40]:
            slots = list(plan.slots.all())
            returned = [sl for sl in slots if sl.status in ("Returned", "returned")]
            for sl in returned[:2]:
                out.append(
                    {
                        "id": f"core-returned-{sl.id}",
                        "title": f"Fix returned core {sl.activity_type} — {names.get(plan.school_id, plan.school_id)}",
                        "description": sl.returned_reason
                        or "Returned by verification — correct and resubmit.",
                        "category": "Core Schools",
                        "priority": "high",
                        "status_key": "returned",
                        "status_label": "Returned",
                        "status_tone": "danger",
                        "due_label": "—",
                        "due_tone": "neutral",
                        "linked": names.get(plan.school_id, plan.school_id),
                        "action_label": "Open Core Schools",
                        "action_url": "/core-schools",
                        "actionable": True,
                        "source": "Core Schools",
                        "_due_sort": _date.today(),
                    }
                )
            for kind, label in (
                ("assessment", "Assessment"),
                ("visit", "Visit"),
                ("training", "Training"),
            ):
                kind_slots = sorted(
                    [sl for sl in slots if sl.activity_type == kind],
                    key=lambda sl: sl.sequence_number,
                )
                nxt = next(
                    (
                        sl
                        for sl in kind_slots
                        if sl.status not in done
                        and sl.status not in in_flight
                        and sl.status not in ("Returned", "returned")
                    ),
                    None,
                )
                if nxt is not None:
                    slot_tag = (
                        "Core Assessment"
                        if kind == "assessment"
                        else f"{label[0]}{nxt.sequence_number} Core {label}"
                    )
                    out.append(
                        {
                            "id": f"core-slot-{nxt.id}",
                            "title": f"Schedule {slot_tag} — {names.get(plan.school_id, plan.school_id)}",
                            "description": "Core package slot not yet scheduled this financial year.",
                            "category": "Core Schools",
                            "priority": "medium",
                            "status_key": "waiting_me",
                            "status_label": "Waiting on Me",
                            "status_tone": "info",
                            "due_label": "—",
                            "due_tone": "neutral",
                            "linked": names.get(plan.school_id, plan.school_id),
                            "action_label": "Plan Now",
                            "action_url": "/core-schools",
                            "actionable": True,
                            "source": "Core Schools",
                            "_due_sort": _date.today(),
                        }
                    )
        return out[:12]
    except Exception:  # noqa: BLE001 — core To-Dos must never break the queue
        return []


def _team_target_todos(principal, role):
    """PL supervision To-Dos — derived live from the team targets engine.
    Auto-close by construction: when the CCEO recovers, the plan is decided,
    or the backlog clears, the derivation stops emitting the item."""
    if role != "Program Lead":
        return []
    from datetime import date as _date

    try:
        from apps.targets.models import CatchUpPlan
        from apps.targets.team_targets import PLTeamTargetsService

        page = PLTeamTargetsService.get_page(principal)
        out = []
        for m in page["members"]:
            if m["status"] not in ("High Risk", "Critical"):
                continue
            out.append(
                {
                    "id": f"team-risk-{m['user_id']}",
                    "title": f"Review high-risk CCEO — {m['name']}",
                    "description": (
                        f"{m['month_pct'] or 0}% vs expected pace {m['pace']}% "
                        f"({m['status']}). Open the recovery queue."
                    ),
                    "category": "Team Targets",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": "Team Targets",
                    "action_label": "Review",
                    "action_url": "/team-targets",
                    "actionable": True,
                    "source": "Team Targets",
                    "_due_sort": _date.today(),
                }
            )
        pending = CatchUpPlan.objects.filter(
            pl_user_id=principal.id, status="submitted"
        ).count()
        if pending:
            out.append(
                {
                    "id": "team-catchup-queue",
                    "title": f"Approve {pending} catch-up plan{'s' if pending > 1 else ''}",
                    "description": "Submitted recovery plans are waiting for your decision.",
                    "category": "Team Targets",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "info",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": "Recovery queue",
                    "action_label": "Open Queue",
                    "action_url": "/team-targets",
                    "actionable": True,
                    "source": "Team Targets",
                    "_due_sort": _date.today(),
                }
            )
        sf_kpi = next((k for k in page["kpis"] if k["key"] == "sfid"), None)
        missing = int(sf_kpi["delta_unit"].split()[0]) if sf_kpi else 0
        if missing >= 5:
            out.append(
                {
                    "id": "team-sfid-backlog",
                    "title": f"Follow up {missing} missing Activity SF IDs",
                    "description": "Completed team activities are not credited until the Activity SF ID is entered.",
                    "category": "Team Targets",
                    "priority": "medium",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": "SF ID backlog",
                    "action_label": "Open Backlog",
                    "action_url": "/team-targets",
                    "actionable": True,
                    "source": "Team Targets",
                    "_due_sort": _date.today(),
                }
            )
        return out
    except Exception:  # noqa: BLE001 — team To-Dos must never break the queue
        return []


def _route_todos(principal, role):
    """Route Intelligence To-Dos for field staff — derived live from the
    staff member's own upcoming DailyVisitRouteBatches: fix weak school
    location data, and rework days whose route is not feasible/blocked.
    Poor location data never rejects a school — it creates this To-Do."""
    if role not in ("CCEO", "Program Lead"):
        return []
    from datetime import date as _date

    try:
        from apps.routes.models import DailyVisitRouteBatch

        out = []
        today = _date.today()
        batches = DailyVisitRouteBatch.objects.filter(
            responsible_user=principal.user_id, visit_date__gte=today
        ).order_by("visit_date")[:10]
        low_conf = [b for b in batches if b.confidence in ("low", "needs_cleanup")]
        if low_conf:
            days = ", ".join(b.visit_date.strftime("%d %b") for b in low_conf[:3])
            out.append(
                {
                    "id": "route-fix-location",
                    "title": "Fix school location / coordinates",
                    "description": f"Route estimate may be inaccurate — visit day(s) {days} include schools with incomplete location data.",
                    "category": "Data Quality",
                    "priority": "medium",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "info",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": "Route Intelligence",
                    "action_label": "Review Schools",
                    "action_url": "/my-plan",
                    "actionable": True,
                    "source": "Route Intelligence",
                    "_due_sort": today,
                }
            )
        bad = [
            b
            for b in batches
            if not b.feasible or b.status in ("not_feasible", "blocked")
        ]
        if bad:
            b = bad[0]
            out.append(
                {
                    "id": f"route-infeasible-{b.visit_date.isoformat()}",
                    "title": "Rework route plan — day overloaded",
                    "description": f"Your {b.visit_date.strftime('%d %b')} visit day is {b.get_status_display()} (load exceeds the working day or route rules). Reduce schools or split into another day.",
                    "category": "Planning",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning",
                    "due_label": b.visit_date.strftime("%d %b"),
                    "due_tone": "warning",
                    "linked": "Route Intelligence",
                    "action_label": "Open My Plan",
                    "action_url": "/my-plan",
                    "actionable": True,
                    "source": "Route Intelligence",
                    "_due_sort": b.visit_date,
                }
            )
        return out
    except Exception:  # noqa: BLE001 — route To-Dos must never break the queue
        return []


def _cd_analytics_todos(principal, role):
    """Country oversight signals (high-risk PL teams, recommended actions,
    escalated weekly fund requests, budget underutilization) surfaced as CD
    leadership To-Dos — derived live from country state. Country Director only."""
    if role != "CountryDirector":
        return []
    from datetime import date as _date

    from apps.analytics.cd_analytics_service import CDAnalyticsService

    out = []
    try:
        for t in CDAnalyticsService.cd_todos(principal):
            out.append(
                {
                    "id": t["id"],
                    "title": t["title"],
                    "description": t["description"],
                    "category": t.get("category", "Oversight"),
                    "priority": t.get("priority", "medium"),
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "info",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": "Country Director Analytics",
                    "action_label": t.get("action_label", "Review"),
                    "action_url": t.get("action_url", "/analytics/country-director"),
                    "actionable": True,
                    "source": "CD Analytics",
                    "_due_sort": _date.today(),
                }
            )
    except Exception:  # noqa: BLE001 — analytics To-Dos must never break the queue
        return []
    return out[:8]


# Employee-facing: what the requester must do next on their own record.
_PD_OWN_TITLES = {
    "returned_by_supervisor": (
        "Fix Returned PD Request",
        "Your supervisor returned",
        "Fix & Resubmit",
        "high",
    ),
    "returned_by_hr": (
        "Fix Returned PD Request",
        "HR returned",
        "Fix & Resubmit",
        "high",
    ),
    "disbursed": (
        "Confirm PD Enrollment",
        "Funds were disbursed for",
        "Confirm Enrollment",
        "medium",
    ),
    "approved_unfunded": (
        "Confirm PD Enrollment",
        "Your request was approved for",
        "Confirm Enrollment",
        "medium",
    ),
    "enrollment_pending": (
        "Confirm PD Enrollment",
        "Enrollment is pending for",
        "Confirm Enrollment",
        "medium",
    ),
    "ended": (
        "Mark PD Course Complete",
        "The course period has ended for",
        "Mark Complete",
        "high",
    ),
    "marked_complete": (
        "Upload PD Certificate",
        "Upload your completion certificate for",
        "Upload",
        "high",
    ),
    "certificate_uploaded": (
        "Confirm BambooHR Upload",
        "Confirm the BambooHR upload for",
        "Confirm",
        "medium",
    ),
    "bamboohr_confirmed": (
        "Submit PD Accountability",
        "Submit receipts and NetSuite Expense ID for",
        "Submit",
        "high",
    ),
}
# Reviewer-facing: what stage this principal is being asked to act on.
_PD_REVIEW_TITLES = {
    "submitted_to_supervisor": (
        "Review PD Request",
        "Approve or return",
        "Review",
        "high",
    ),
    "submitted_to_hr": (
        "Review PD Request (HR)",
        "HR approval needed for",
        "Review",
        "high",
    ),
    "pending_exception": (
        "Review PD Funding Exception",
        "Exception approval needed for",
        "Review",
        "critical",
    ),
    "approved_pending_funding": (
        "Disburse PD Funds",
        "Disbursement is due for",
        "Disburse",
        "high",
    ),
    "accountability_submitted": (
        "Clear PD Accountability",
        "Accountability awaits clearance for",
        "Clear",
        "medium",
    ),
    "awaiting_hr_signoff": (
        "Sign Off PD Completion",
        "Ready for HR sign-off:",
        "Sign Off",
        "medium",
    ),
}


def _pd_todos(principal, role):
    """Professional Development To-Dos — one shared derivation for every
    role, both the employee's own outstanding steps and anything they are
    the authorized reviewer for right now. Auto-closes: acting on the
    record advances its status and the derived item disappears."""
    try:
        from apps.professional_development.services import StaffPDService

        req = StaffPDService.action_required(principal)
        out = []
        for r in req["own"]:
            title, desc_prefix, action_label, priority = _PD_OWN_TITLES.get(
                r.status, ("Act on PD Request", "Action needed on", "Open", "medium")
            )
            out.append(
                {
                    "id": f"pd-own-{r.id}",
                    "title": title,
                    "description": f"{desc_prefix} “{r.course_name}”.",
                    "category": "Professional Development",
                    "priority": priority,
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": r.course_name,
                    "action_label": action_label,
                    "action_url": f"/my-professional-development/request?id={r.id}",
                    "actionable": True,
                    "source": "My Professional Development",
                    "_due_sort": r.updated_at.date(),
                }
            )
        for r in req["reviewing"]:
            title, desc_prefix, action_label, priority = _PD_REVIEW_TITLES.get(
                r.status, ("Review PD Request", "Action needed on", "Review", "medium")
            )
            out.append(
                {
                    "id": f"pd-review-{r.id}",
                    "title": title,
                    "description": f"{desc_prefix} {r.staff_name} — “{r.course_name}”.",
                    "category": "Professional Development",
                    "priority": priority,
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": f"{r.staff_name} · {r.course_name}",
                    "action_label": action_label,
                    "action_url": f"/my-professional-development/request?id={r.id}",
                    "actionable": True,
                    "source": "PD Review Queue",
                    "_due_sort": r.updated_at.date(),
                }
            )
        return out
    except Exception:  # noqa: BLE001 — PD To-Dos must never break the queue
        return []


def _field_debrief_todos(principal, role):
    """Field Debrief To-Dos (§21) — clarification responses owed by the
    submitter, escalated debriefs owed a leadership decision, open
    leadership actions owed by their owner, pending recommendations owed a
    supervisor decision, open support requests owed by the routed role, and
    restricted incidents owed a first-touch review. Auto-closes: resolving
    the action/request, responding to clarification, deciding the
    recommendation, or a leadership action being created on the incident
    removes the derived item."""
    try:
        from apps.debriefs.field_debrief_service import (
            RESTRICTED_ROUTING,
            FieldDebriefService,
        )
        from apps.debriefs.models import (
            DailyDebriefSupportRequest,
            DebriefActionStatus,
            DebriefStatus,
            RecommendationStatus,
        )

        out = []
        own_pending = FieldDebriefService.scoped_queryset(
            principal, {"mine": True}
        ).filter(status=DebriefStatus.CLARIFICATION_REQUESTED)
        for d in own_pending:
            out.append(
                {
                    "id": f"debrief-clarify-{d.id}",
                    "title": "Respond to Debrief Clarification",
                    "description": f"Your supervisor requested clarification on “{d.title}”.",
                    "category": "Field Debrief",
                    "priority": "high",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": d.title,
                    "action_label": "Respond",
                    "action_url": f"/debriefs/{d.id}",
                    "actionable": True,
                    "source": "Field Debrief",
                    "_due_sort": d.updated_at.date(),
                }
            )

        if role in (
            "Program Lead",
            "CountryDirector",
            "HumanResources",
            "ImpactAssessment",
            "RegionalVicePresident",
            "Admin",
        ):
            escalated = (
                FieldDebriefService.scoped_queryset(principal, {})
                .filter(status=DebriefStatus.ESCALATED)
                .exclude(
                    actions__status__in=(
                        DebriefActionStatus.OPEN,
                        DebriefActionStatus.ASSIGNED,
                        DebriefActionStatus.IN_PROGRESS,
                    )
                )
            )
            for d in escalated:
                out.append(
                    {
                        "id": f"debrief-escalated-{d.id}",
                        "title": "Review Escalated Field Debrief",
                        "description": f"“{d.title}” by {d.submitted_by_role} is escalated and needs a leadership decision.",
                        "category": "Field Debrief",
                        "priority": "high",
                        "status_key": "waiting_me",
                        "status_label": "Waiting on Me",
                        "status_tone": "danger",
                        "due_label": "—",
                        "due_tone": "neutral",
                        "linked": d.title,
                        "action_label": "Review",
                        "action_url": f"/debriefs/{d.id}",
                        "actionable": True,
                        "source": "Field Debrief",
                        "_due_sort": d.updated_at.date(),
                    }
                )

        from apps.debriefs.models import DailyDebriefAction

        my_actions = (
            DailyDebriefAction.objects.filter(owner_user_id=principal.user_id)
            .exclude(
                status__in=(DebriefActionStatus.RESOLVED, DebriefActionStatus.CLOSED)
            )
            .select_related("debrief")
        )
        for a in my_actions:
            out.append(
                {
                    "id": f"debrief-action-{a.id}",
                    "title": "Resolve Field Debrief Action",
                    "description": a.action,
                    "category": "Field Debrief",
                    "priority": a.priority
                    if a.priority in ("low", "medium", "high", "critical")
                    else "medium",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "warning"
                    if a.priority in ("high", "critical")
                    else "neutral",
                    "due_label": a.due_date.strftime("%d %b") if a.due_date else "—",
                    "due_tone": "danger"
                    if a.due_date and a.due_date < timezone.now().date()
                    else "neutral",
                    "linked": a.debrief.title,
                    "action_label": "Resolve",
                    "action_url": f"/debriefs/{a.debrief_id}",
                    "actionable": True,
                    "source": "Field Debrief",
                    "_due_sort": a.due_date or a.updated_at.date(),
                }
            )

        if role in ("Program Lead", "CountryDirector", "Admin"):
            pending_recommendations = FieldDebriefService.scoped_queryset(
                principal, {}
            ).filter(recommendation_status=RecommendationStatus.PROPOSED)
            for d in pending_recommendations:
                out.append(
                    {
                        "id": f"debrief-recommendation-{d.id}",
                        "title": "Decide Debrief Recommendation",
                        "description": f"“{d.title}” recommends {d.get_recommended_next_activity_type_display() or 'a follow-up'} — accept or reject.",
                        "category": "Field Debrief",
                        "priority": "medium",
                        "status_key": "waiting_me",
                        "status_label": "Waiting on Me",
                        "status_tone": "neutral",
                        "due_label": "—",
                        "due_tone": "neutral",
                        "linked": d.title,
                        "action_label": "Decide",
                        "action_url": f"/debriefs/{d.id}",
                        "actionable": True,
                        "source": "Field Debrief",
                        "_due_sort": d.updated_at.date(),
                    }
                )

        open_support_requests = DailyDebriefSupportRequest.objects.filter(
            status="open",
            requested_from_role=role,
            debrief__in=FieldDebriefService.scoped_queryset(principal, {}),
        ).select_related("debrief")
        for s in open_support_requests:
            out.append(
                {
                    "id": f"debrief-support-{s.id}",
                    "title": "Respond to Support Request",
                    "description": f"{s.get_support_type_display()} requested on “{s.debrief.title}”.",
                    "category": "Field Debrief",
                    "priority": "medium",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "neutral",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": s.debrief.title,
                    "action_label": "Respond",
                    "action_url": f"/debriefs/{s.debrief_id}",
                    "actionable": True,
                    "source": "Field Debrief",
                    "_due_sort": s.updated_at.date(),
                }
            )

        restricted_incidents = (
            FieldDebriefService.scoped_queryset(principal, {})
            .filter(
                is_restricted_incident=True,
                status=DebriefStatus.RESTRICTED_INCIDENT,
            )
            .exclude(
                actions__status__in=(
                    DebriefActionStatus.OPEN,
                    DebriefActionStatus.ASSIGNED,
                    DebriefActionStatus.IN_PROGRESS,
                )
            )
        )
        for d in restricted_incidents:
            routed_roles = RESTRICTED_ROUTING.get(d.restricted_incident_category, ())
            if role != "Admin" and role not in routed_roles:
                continue
            out.append(
                {
                    "id": f"debrief-restricted-{d.id}",
                    "title": "Review Restricted Incident",
                    "description": f"“{d.title}” is a restricted incident ({d.get_restricted_incident_category_display()}) awaiting first-touch review.",
                    "category": "Field Debrief",
                    "priority": "critical",
                    "status_key": "waiting_me",
                    "status_label": "Waiting on Me",
                    "status_tone": "danger",
                    "due_label": "—",
                    "due_tone": "neutral",
                    "linked": d.title,
                    "action_label": "Review",
                    "action_url": f"/debriefs/{d.id}",
                    "actionable": True,
                    "source": "Field Debrief",
                    "_due_sort": d.updated_at.date(),
                }
            )
        return out
    except Exception:  # noqa: BLE001 — Field Debrief To-Dos must never break the queue
        return []


def get_todos(principal) -> dict:
    """The full derived To-Do queue for a principal, sorted by priority then due."""
    role = getattr(principal, "active_role", None)
    scope = resolve_user_scope(principal)
    today = timezone.now().date()
    fy = get_operational_fy()

    todos = []
    todos += _activity_todos(principal, scope, today, fy)
    todos += _fund_request_todos(principal, role)
    todos += _school_quality_todos(scope)
    todos += _ia_todos(principal, role)
    todos += _leave_todos(principal, role)
    todos += _pl_fund_todos(principal, role)
    todos += _accountant_todos(principal, role)
    todos += _country_budget_todos(principal, role)
    todos += _pl_analytics_todos(principal, role)
    todos += _cd_analytics_todos(principal, role)
    todos += _route_todos(principal, role)
    todos += _my_target_todos(principal, role)
    todos += _team_target_todos(principal, role)
    todos += _core_school_todos(principal, role)
    todos += _rvp_todos(principal, role)
    todos += _strategy_note_todos(principal, role)
    todos += _pd_todos(principal, role)
    todos += _field_debrief_todos(principal, role)

    todos.sort(key=lambda t: (PRIORITY_ORDER.get(t["priority"], 9), t["_due_sort"]))
    for t in todos:
        t["priority_label"] = PRIORITY_LABEL.get(t["priority"], "—")

    counts = {
        "critical": sum(1 for t in todos if t["priority"] == "critical"),
        "due_today": sum(1 for t in todos if t["status_key"] == "due_today"),
        "waiting_me": sum(
            1 for t in todos if t["actionable"] and t["status_key"] != "blocked"
        ),
        "blocked": sum(1 for t in todos if t["status_key"] == "blocked"),
        "overdue": sum(1 for t in todos if t["status_key"] == "overdue"),
        "total": len(todos),
    }
    category_counts: dict[str, int] = {}
    for t in todos:
        category_counts[t["category"]] = category_counts.get(t["category"], 0) + 1

    return {
        "todos": todos,
        "counts": counts,
        "categories": sorted(category_counts.items()),
        "total": len(todos),
    }
