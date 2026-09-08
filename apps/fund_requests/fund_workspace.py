"""One fund workspace for the people who move money.

The Program Lead's Fund Approvals page and the Accountant's money movement
page share a composition: a headline strip, a queue of requests on the left,
the selected request in the middle, the month's position on the right, and
the budget mix and recent activity underneath. The two roles look at
different queues (team plans awaiting approval; advances awaiting
disbursement) through the same frame, so the panels here are built by the
same functions from the same records and cannot drift apart.

Everything is derived: the month panel, approval rate, budget mix and recent
activity all read the weekly fund requests, their cost lines and the audit
log. Nothing is typed in.
"""

from __future__ import annotations

from apps.core.metrics.ratio import percentage_or_zero

from collections import OrderedDict
from datetime import date, timedelta

from django.utils import timezone

from apps.core.metrics import format_ugx_compact

MIX_COLOURS = OrderedDict(
    [
        ("Staff School Visits", "var(--edify-success)"),
        ("Partner School Visits", "#8b5cf6"),
        ("Cluster Meetings", "var(--edify-accent)"),
        ("Cluster Trainings", "var(--edify-warn)"),
        ("In-School Trainings", "var(--edify-warn)"),
        ("SSA Support Visits", "#0d9488"),
        ("Admin Budget", "#64748b"),
        ("Field Events", "#64748b"),
        ("Other", "#94a3b8"),
    ]
)

LINE_TYPE_LABELS = {
    "transport": "Transport",
    "accommodation": "Accommodation",
    "meals": "Meals",
    "participant_meals": "Participant Meals",
    "materials": "Materials",
    "venue": "Venue",
    "airtime": "Airtime",
    "per_diem": "Per Diem",
}


def month_bounds(fy_year: int | None, month: int) -> tuple[date, date]:
    """First and last day of `month` in the calendar year it falls in."""
    year = fy_year or timezone.now().year
    start = date(year, month, 1)
    end = (
        date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    ) - timedelta(days=1)
    return start, end


def approval_rate(approved: int, returned: int, pending: int) -> dict:
    """The month's decisions as a share: approved, returned, still pending."""
    total = approved + returned + pending
    pct = percentage_or_zero(approved, total)
    from apps.core.donut import build_rings

    series = [
        {
            "key": "approved",
            "label": "Approved",
            "value": approved,
            "display": f"{percentage_or_zero(approved, total)}%",
            "color": "var(--edify-success)",
        },
        {
            "key": "returned",
            "label": "Returned",
            "value": returned,
            "display": f"{percentage_or_zero(returned, total)}%",
            "color": "var(--edify-danger)",
        },
        {
            "key": "pending",
            "label": "Pending",
            "value": pending,
            "display": f"{percentage_or_zero(pending, total)}%",
            "color": "var(--edify-warn)",
        },
    ]
    return {
        "pct": pct,
        "total": total,
        "donut": build_rings(series, share_of=total or None),
        "legend": [
            {
                "label": s["label"],
                "pct": percentage_or_zero(s["value"], total),
                "count": s["value"],
                "color": s["color"],
            }
            for s in series
        ],
    }


def budget_mix(totals_by_label: dict[str, int]) -> dict:
    """A stacked bar of where the money goes, largest share first, with the
    long tail folded into Other so the bar stays readable."""
    ordered = sorted(
        ((label, int(amount)) for label, amount in totals_by_label.items() if amount),
        key=lambda item: -item[1],
    )
    head, tail = ordered[:5], ordered[5:]
    if tail:
        head.append(("Other", sum(amount for _, amount in tail)))
    total = sum(amount for _, amount in head)
    segments = [
        {
            "label": label,
            "amount": amount,
            "amount_fmt": format_ugx_compact(amount),
            "pct": percentage_or_zero(amount, total),
            "color": MIX_COLOURS.get(label, "#94a3b8"),
        }
        for label, amount in head
    ]
    return {
        "total": total,
        "total_fmt": format_ugx_compact(total),
        "segments": segments,
    }


def recent_activity(
    actions: dict[str, str], *, subject_ids=None, actor_id=None, limit=3
) -> list[dict]:
    """The latest money decisions from the audit log, as one line each.

    `actions` maps an audit action to the verb shown ("approved", "returned
    for review"). Filtered to `subject_ids` (weekly request ids) and/or the
    acting user so a Program Lead reads their own team's decisions and the
    Accountant reads the disbursement desk's.
    """
    from apps.audit.models import AuditLog
    from apps.fund_requests.models import WeeklyFundRequest
    from django.contrib.auth import get_user_model

    qs = AuditLog.objects.filter(action__in=list(actions), success=True)
    if subject_ids is not None:
        qs = qs.filter(subject_id__in=list(subject_ids))
    if actor_id:
        qs = qs.filter(actor_id=actor_id)
    rows = list(qs.order_by("-created_at")[: max(limit * 3, limit)])
    wfrs = {
        w.id: w
        for w in WeeklyFundRequest.objects.filter(
            id__in={r.subject_id for r in rows if r.subject_id}
        )
    }
    names = dict(
        get_user_model()
        .objects.filter(id__in={w.responsible_user for w in wfrs.values()})
        .values_list("id", "name")
    )
    now = timezone.localtime()
    out = []
    for row in rows:
        wfr = wfrs.get(row.subject_id)
        if not wfr:
            continue
        when = timezone.localtime(row.created_at)
        if when.date() == now.date():
            when_label = f"Today, {when:%I:%M %p}".replace(" 0", " ")
        elif when.date() == now.date() - timedelta(days=1):
            when_label = f"Yesterday, {when:%I:%M %p}".replace(" 0", " ")
        else:
            when_label = f"{when:%d %b}, {when:%I:%M %p}".replace(" 0", " ")
        tone = "danger" if "return" in row.action else "success"
        out.append(
            {
                "tone": tone,
                "text": f"{names.get(wfr.responsible_user, 'Staff')} — {wfr.week_start_date:%b} Fund Plan {actions[row.action]}",
                "amount_fmt": format_ugx_compact(
                    wfr.disbursed_amount or wfr.total_amount
                ),
                "when": when_label,
            }
        )
        if len(out) == limit:
            break
    return out


def approvals_today(subject_ids, action="weekly_fund_request.approve") -> set[str]:
    """Weekly request ids approved today, from the audit log."""
    from apps.audit.models import AuditLog

    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return set(
        AuditLog.objects.filter(
            action=action,
            success=True,
            created_at__gte=start,
            subject_id__in=list(subject_ids),
        ).values_list("subject_id", flat=True)
    )


def progress_panel(
    title,
    allocation,
    approved,
    *,
    status_label,
    link,
    link_label,
    caption="Approved (to date)",
):
    pct = percentage_or_zero(approved, allocation)
    return {
        "title": title,
        "status_label": status_label,
        "status_tone": "success" if pct >= 50 or not allocation else "warning",
        "allocation_fmt": format_ugx_compact(allocation),
        "approved_fmt": format_ugx_compact(approved),
        "pct": min(pct, 100),
        "caption": caption,
        "link": link,
        "link_label": link_label,
    }
