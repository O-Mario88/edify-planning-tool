"""Country-envelope reconciliation — plan vs commitment vs actual.

The country monthly budget dead-ended at `approved_by_rvp`: the `disbursed` and
`closed` statuses existed but nothing ever wrote them, and no surface compared
the approved envelope against what the Accountant actually disbursed on the
separate advance ledger. CD and RVP approved money and could never see how the
approval executed.

Two independent money records exist, and this module is the only place they
meet:

  System A — NetSuiteExpenseRecord.amount_entered: the figure booked in
             NetSuite by the Accountant. The organisation's real accounts.
  System B — AdvanceRequest.disbursed_amount / accounted_amount: the advance
             ledger the field actually runs on, and the source of every number
             on every leadership dashboard today.

Where they disagree, the discrepancy was invisible. `reconcile_month` surfaces
it as a first-class figure rather than leaving leadership to trust whichever
system happened to feed the widget they were looking at.

All amounts are plain integer UGX (the professional_development app is the only
cents island in the platform).
"""

from __future__ import annotations

from datetime import date

from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.exceptions import BadRequest, NotFoundError

from .models import MonthlyWorkPlanBudget, MonthlyWorkPlanBudgetStatus


# Advance statuses where money has genuinely left the organisation. Mirrors
# fund_requests.models.MONEY_MOVED_ADVANCE_STATUSES; imported lazily so this
# module stays importable during app loading.
def _money_moved_statuses() -> tuple:
    from apps.fund_requests.models import MONEY_MOVED_ADVANCE_STATUSES

    return tuple(MONEY_MOVED_ADVANCE_STATUSES)


def _month_bounds(month_key: str) -> tuple[date, date]:
    """First day of the month, and first day of the next — a half-open range."""
    try:
        year_s, month_s = month_key.split("-")
        year, month = int(year_s), int(month_s)
    except (ValueError, AttributeError):
        raise BadRequest(f"Malformed month key '{month_key}'.")
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start, end


def _aware_bounds(month_key: str) -> tuple:
    """`_month_bounds` as timezone-aware datetimes.

    DateTimeField comparisons need aware values — filtering them with plain
    dates makes Django assume UTC midnight, which silently shifts the month
    boundary by the local offset and books edge-of-month money into the wrong
    envelope.
    """
    from datetime import datetime, time

    start, end = _month_bounds(month_key)
    tz = timezone.get_current_timezone()
    return (
        timezone.make_aware(datetime.combine(start, time.min), tz),
        timezone.make_aware(datetime.combine(end, time.min), tz),
    )


def _advances_for_month(month_key: str, country_id: str | None = None):
    """Advances whose activity falls in this envelope's month.

    Anchored on the activity's planned date rather than the disbursement date:
    the envelope funds a month of *work*, so a late disbursement for that
    month's work still belongs to that month's reconciliation.

    AdvanceRequest carries no country column, so country attribution runs
    through the responsible employee's StaffProfile. Today's deployment is
    single-country (HOME_COUNTRY_ID), which is why this was previously
    unfiltered — but a reconciliation that silently mixes countries would be
    wrong the moment a second one exists, and this function is handed a budget
    that already knows its country.

    Deliberately NOT a hard filter: an advance whose owner has no country set
    would silently vanish from the reconciliation, and money disappearing from
    a reconciliation is a worse failure than money appearing in it. Callers get
    the in-country set plus the unattributable remainder, and surface both.
    """
    from apps.fund_requests.models import AdvanceRequest

    start, end = _aware_bounds(month_key)
    qs = AdvanceRequest.objects.filter(
        Q(planned_date__gte=start, planned_date__lt=end)
        | Q(planned_date__isnull=True, created_at__gte=start, created_at__lt=end)
    )
    if not country_id or not _is_multi_country():
        return qs, qs.none()

    from apps.accounts.models import StaffProfile

    in_country_users = set(
        StaffProfile.objects.filter(country=country_id).values_list(
            "user_id", flat=True
        )
    )
    # responsible_user_id is a plain CharField holding a User id, not an FK.
    in_country = qs.filter(responsible_user_id__in=in_country_users)
    unattributed = qs.exclude(responsible_user_id__in=in_country_users)
    return in_country, unattributed


def _is_multi_country() -> bool:
    """Whether more than one country is actually in play.

    Single-country deployments skip the join entirely rather than paying for it
    on every reconciliation.
    """
    from apps.accounts.models import StaffProfile

    return (
        StaffProfile.objects.exclude(country__isnull=True)
        .exclude(country="")
        .values("country")
        .distinct()
        .count()
        > 1
    )


def reconcile_month(budget: MonthlyWorkPlanBudget) -> dict:
    """Compare one approved envelope against real money movement.

    Returns the four figures a decision-maker needs on the same screen, plus
    the System A vs System B delta that no surface previously showed.
    """
    advances, unattributed = _advances_for_month(
        budget.month_key, budget.country_id
    )
    moved = advances.filter(status__in=_money_moved_statuses())

    disbursed = moved.aggregate(t=Sum("disbursed_amount"))["t"] or 0
    accounted = moved.aggregate(t=Sum("accounted_amount"))["t"] or 0
    returned = moved.aggregate(t=Sum("returned_amount"))["t"] or 0
    committed = advances.aggregate(t=Sum("amount"))["t"] or 0

    # Money in this month that could not be attributed to a country. Reported,
    # never dropped — a reconciliation that quietly loses rows is worse than
    # one that admits what it could not place.
    unattributed_moved = unattributed.filter(status__in=_money_moved_statuses())
    unattributed_total = (
        unattributed_moved.aggregate(t=Sum("disbursed_amount"))["t"] or 0
    )

    # System A: what was actually booked in NetSuite for this month's work.
    netsuite_total = _netsuite_total(budget.month_key)

    approved = budget.total_amount or 0
    variance = approved - accounted
    utilisation = round((disbursed / approved) * 100, 1) if approved else 0.0

    # The reconciliation that did not exist: self-declared accountability
    # against the organisation's booked expense.
    ab_delta = accounted - netsuite_total
    ab_status = _ab_status(accounted, netsuite_total)

    return {
        "monthKey": budget.month_key,
        "status": budget.status,
        # Plan
        "approvedTotal": approved,
        "programTotal": budget.program_total or 0,
        "adminTotal": budget.admin_total or 0,
        # Commitment
        "committedTotal": committed,
        # Actual (System B — the advance ledger every dashboard reads)
        "disbursedTotal": disbursed,
        "accountedTotal": accounted,
        "returnedTotal": returned,
        "utilisationPct": utilisation,
        "unattributedTotal": unattributed_total,
        "unattributedCount": unattributed_moved.count(),
        "variance": variance,
        "variancePct": (round((variance / approved) * 100, 1) if approved else 0.0),
        "isOverspend": variance < 0,
        # Actual (System A — what NetSuite booked)
        "netsuiteTotal": netsuite_total,
        "systemDelta": ab_delta,
        "systemDeltaStatus": ab_status,
        "advanceCount": advances.count(),
        "settledCount": moved.filter(accounted_amount__isnull=False).count(),
    }


def _netsuite_total(month_key: str) -> int:
    """System A total for the month, matched through the advance ledger.

    NetSuiteExpenseRecord hangs off an Activity, so the month is taken from the
    expense date — that is the booking period the accounts actually use.
    """
    from apps.fund_requests.finance_models import NetSuiteExpenseRecord

    start, end = _month_bounds(month_key)
    return (
        NetSuiteExpenseRecord.objects.filter(
            expense_date__gte=start, expense_date__lt=end
        ).aggregate(t=Sum("amount_entered"))["t"]
        or 0
    )


def _ab_status(accounted: int, netsuite: int) -> str:
    """Classify the System A ↔ System B gap.

    'unbooked' is the case that matters most: the field has accounted for money
    that never appeared in NetSuite, which is exactly the discrepancy that was
    invisible to leadership.
    """
    if accounted == 0 and netsuite == 0:
        return "no_data"
    if accounted == netsuite:
        return "matched"
    # A tolerance below which rounding/timing is more likely than a real gap.
    tolerance = max(1000, int(max(accounted, netsuite) * 0.01))
    if abs(accounted - netsuite) <= tolerance:
        return "within_tolerance"
    return "unbooked" if accounted > netsuite else "overbooked"


def settlement_state(budget: MonthlyWorkPlanBudget) -> dict:
    """Whether this envelope is ready to move to disbursed/closed."""
    rec = reconcile_month(budget)
    every_advance_settled = (
        rec["advanceCount"] > 0 and rec["settledCount"] == rec["advanceCount"]
    )
    return {
        "canMarkDisbursed": (
            budget.status == MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT
            and rec["disbursedTotal"] > 0
        ),
        "canClose": (
            budget.status == MonthlyWorkPlanBudgetStatus.DISBURSED
            and every_advance_settled
        ),
        "blockingReason": _blocking_reason(budget, rec, every_advance_settled),
        "reconciliation": rec,
    }


def _blocking_reason(budget, rec: dict, settled: bool) -> str | None:
    status = budget.status
    if status == MonthlyWorkPlanBudgetStatus.SENT_TO_ACCOUNTANT:
        if rec["disbursedTotal"] <= 0:
            return "No disbursement has been recorded against this month yet."
        return None
    if status == MonthlyWorkPlanBudgetStatus.DISBURSED:
        if not settled:
            outstanding = rec["advanceCount"] - rec["settledCount"]
            return (
                f"{outstanding} advance(s) still awaiting accountability — the "
                "envelope cannot close until every advance is accounted for."
            )
        return None
    return None


def mark_disbursed(budget_id: str, principal) -> dict:
    """Move an envelope to `disbursed` once money has actually moved."""
    budget = _get(budget_id)
    state = settlement_state(budget)
    if not state["canMarkDisbursed"]:
        raise BadRequest(
            state["blockingReason"]
            or "This envelope is not at the sent-to-accountant stage."
        )
    return _advance_status(
        budget, MonthlyWorkPlanBudgetStatus.DISBURSED, principal, state["reconciliation"]
    )


def close_month(budget_id: str, principal) -> dict:
    """Close a fully-accounted envelope — the end of the loop."""
    budget = _get(budget_id)
    state = settlement_state(budget)
    if not state["canClose"]:
        raise BadRequest(
            state["blockingReason"] or "This envelope is not ready to close."
        )
    return _advance_status(
        budget, MonthlyWorkPlanBudgetStatus.CLOSED, principal, state["reconciliation"]
    )


def _advance_status(budget, status: str, principal, reconciliation: dict) -> dict:
    from apps.audit.services import log as audit_log

    previous = budget.status
    budget.status = status
    budget.save(update_fields=["status", "updated_at"])
    audit_log(
        action=f"country_budget_{status}",
        subject_kind="MonthlyWorkPlanBudget",
        subject_id=budget.id,
        actor_id=getattr(principal, "user_id", None),
        actor_role=getattr(principal, "active_role", None),
        payload={
            "monthKey": budget.month_key,
            "from": previous,
            "to": status,
            "approvedTotal": reconciliation["approvedTotal"],
            "accountedTotal": reconciliation["accountedTotal"],
            "variance": reconciliation["variance"],
            "systemDelta": reconciliation["systemDelta"],
        },
    )
    return {
        "id": budget.id,
        "status": budget.status,
        "reconciliation": reconciliation,
    }


def _get(budget_id: str) -> MonthlyWorkPlanBudget:
    budget = MonthlyWorkPlanBudget.objects.filter(id=budget_id).first()
    if not budget:
        raise NotFoundError("Country budget not found.")
    return budget


# ── Forecast against the annual ceiling ──────────────────────────────────────


# Days of a quarter that must have elapsed before a run-rate projection is
# published. Two weeks of a ~92-day quarter is enough for the divisor to stop
# dominating the arithmetic.
MIN_FORECAST_DAYS = 14


def quarter_forecast(fy: str, country_id: str | None = None) -> dict | None:
    """Answer "am I going to overspend this quarter?".

    The platform had no forecast of any kind, and CountryAnnualBudget's
    quarterly_phasing — the natural ceiling — was dead data no service read.
    This projects the current quarter's run-rate against that phasing.

    Returns None when no annual budget with phasing exists, so callers render
    an honest "not configured" rather than a fabricated projection.
    """
    from .models import CountryAnnualBudget

    annual = CountryAnnualBudget.objects.filter(fy=fy)
    if country_id:
        annual = annual.filter(country_id=country_id)
    annual = annual.first()
    if not annual:
        return None

    phasing = annual.quarterly_phasing or []
    if not phasing:
        return None

    today = timezone.now().date()
    quarter = _fy_quarter(today.month)
    ceiling = _phasing_value(phasing, quarter)
    if not ceiling:
        return None

    spent, elapsed, total_days = _quarter_spend(fy, quarter, today)
    if not total_days:
        return None

    fraction_elapsed = elapsed / total_days
    projected = int(spent / fraction_elapsed) if fraction_elapsed > 0 else spent
    overspend = projected - ceiling

    # A run-rate is meaningless in the first days of a quarter: dividing by
    # 1/92 multiplies a single disbursement by 92, so one ordinary payment on
    # day one "projects" a catastrophic overspend. Publishing that would train
    # people to ignore the metric — the same failure mode as an alert that
    # cries wolf. Below the threshold we still show spend-to-date, but we do
    # not claim to know where the quarter lands.
    reliable = elapsed >= MIN_FORECAST_DAYS

    return {
        "fy": fy,
        "quarter": quarter,
        "ceiling": ceiling,
        "spentToDate": spent,
        "projectedTotal": projected if reliable else None,
        "projectedOverspend": overspend if reliable else None,
        "willOverspend": bool(reliable and overspend > 0),
        "isReliable": reliable,
        "minForecastDays": MIN_FORECAST_DAYS,
        "pctElapsed": round(fraction_elapsed * 100, 1),
        "pctOfCeilingSpent": (round((spent / ceiling) * 100, 1) if ceiling else 0.0),
        "daysRemaining": total_days - elapsed,
    }


def _fy_quarter(month: int) -> str:
    """This organisation's FY runs Oct→Sep."""
    if month in (10, 11, 12):
        return "Q1"
    if month in (1, 2, 3):
        return "Q2"
    if month in (4, 5, 6):
        return "Q3"
    return "Q4"


def _phasing_value(phasing, quarter: str) -> int:
    """Read one quarter's ceiling.

    `quarterly_phasing` is a 4-element list (Q1..Q4) on the model; a dict is
    accepted too so a hand-edited or imported budget still resolves.
    """
    index = {"Q1": 0, "Q2": 1, "Q3": 2, "Q4": 3}[quarter]
    if isinstance(phasing, (list, tuple)):
        if index >= len(phasing):
            return 0
        try:
            return int(phasing[index] or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(phasing, dict):
        for key in (
            quarter,
            quarter.lower(),
            quarter[-1],
            f"q{quarter[-1]}",
            str(index),
        ):
            if key in phasing:
                try:
                    return int(phasing[key] or 0)
                except (TypeError, ValueError):
                    return 0
    return 0


def _quarter_spend(fy: str, quarter: str, today: date) -> tuple[int, int, int]:
    """(spent so far, days elapsed, days in quarter) for the FY quarter."""
    from apps.fund_requests.models import AdvanceRequest

    quarter_months = {
        "Q1": (10, 11, 12),
        "Q2": (1, 2, 3),
        "Q3": (4, 5, 6),
        "Q4": (7, 8, 9),
    }[quarter]

    year = today.year
    start_month = quarter_months[0]
    start_year = year if today.month >= start_month or start_month < 10 else year - 1
    if start_month >= 10 and today.month < 10:
        start_year = year - 1
    start = date(start_year, start_month, 1)

    end_month = quarter_months[-1]
    end_year = start_year if end_month >= start_month else start_year + 1
    if end_month == 12:
        end = date(end_year + 1, 1, 1)
    else:
        end = date(end_year, end_month + 1, 1)

    from datetime import datetime, time

    tz = timezone.get_current_timezone()
    start_dt = timezone.make_aware(datetime.combine(start, time.min), tz)
    end_dt = timezone.make_aware(datetime.combine(end, time.min), tz)

    spent = (
        AdvanceRequest.objects.filter(
            fy=fy,
            status__in=_money_moved_statuses(),
            disbursed_at__gte=start_dt,
            disbursed_at__lt=end_dt,
        ).aggregate(t=Sum("disbursed_amount"))["t"]
        or 0
    )
    total_days = (end - start).days
    elapsed = max(1, min((today - start).days + 1, total_days))
    return spent, elapsed, total_days


__all__ = [
    "reconcile_month",
    "settlement_state",
    "mark_disbursed",
    "close_month",
    "quarter_forecast",
]
