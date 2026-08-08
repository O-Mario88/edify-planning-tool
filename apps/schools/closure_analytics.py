"""Closure quality: which closures are wrong, weak or late.

This is the Impact Assessment lens, and it deliberately asks a different
question from the leadership one. A Country Director wants to know how many
schools the programme lost and where. IA wants to know which of those records
should not be believed — because a closure recorded four months after the fact,
or one covering a school still flagged as somebody's duplicate, corrupts every
count built on top of it, including the CD's.

Five signals, each chosen because somebody can act on it:

* **Closed while flagged as a duplicate.** The service refuses to *record* a
  closure whose reason is "duplicate record" — that is a row which should not
  have existed, not a school that shut, and it goes to the duplicate workflow
  instead. But nothing stops a school from being closed for an ordinary reason
  while its duplicate flag is still open, and that is worse than either alone:
  the closure removes it from the directory, so the merge that would have
  reconciled the two histories now never happens.
* **Missing enrolment.** A closure with no learner count cannot say what the
  programme lost. The gap is reported, never filled with a zero.
* **Reopenings.** A school that reopens is a closure that turned out to be
  wrong. Not misconduct — schools do resume — but the rate is the honest
  measure of how well closure decisions are being made.
* **Unconfirmed operation.** Closed because nobody could confirm the school was
  still running, which is an absence of evidence rather than evidence of
  closure. The weakest ground there is, and worth checking.
* **Recording lag.** Days between the school stopping and anybody recording it.
  While that gap is open the programme reports reaching a school it has already
  lost, so the lag is a measure of how stale the country's numbers run.

Everything here reads `SchoolClosure`, never the school's current state: the
question is what was true when the decision was made, and the school has since
moved on.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db.models import Avg, Count, F, IntegerField, Q, Sum
from django.db.models.functions import Cast, ExtractDay, TruncMonth

from apps.schools.lifecycle_models import ClosureReason, SchoolClosure

#: Closed on the absence of evidence rather than evidence of closure.
WEAK_GROUND_REASONS = frozenset({ClosureReason.UNCONFIRMED})

#: A school whose duplicate flag was never resolved. Closing it strands the
#: merge: the record leaves the directory still unreconciled with its twin.
UNRESOLVED_DUPLICATE = "potential"

#: A closure recorded more than this long after the school stopped means the
#: programme spent that period counting a school it no longer reached. Not a
#: rule anybody breaks deliberately — usually the closure was discovered on a
#: visit — but the window is where the reporting error lives.
STALE_RECORDING_DAYS = 30

#: The archive and the queues page at most this many rows. Tables are paged in
#: the template; this bounds what is fetched so a country with thousands of
#: closures does not build them all to show twenty.
MAX_ROWS = 500


def _base(fy_start: date | None = None, fy_end: date | None = None, scope=None):
    """Every closure, optionally within a period and a viewer's scope.

    The period is half-open [start, end) to match `core.fy.get_fy_date_range`.
    An inclusive end would count 1 October in both the year that ended and the
    year that began, which is how a school gets closed twice in reporting.

    Scope goes through `scoped_school_queryset`, the one definition of what an
    *analytics* surface may aggregate over, so an RVP means the same thing here
    as on every other intelligence page: their assigned regions, or the whole
    deployment when no geography is configured. Passing `None` means country —
    it is not a synonym for "no access", and a caller that wants nothing should
    not call.

    Reopened closures stay in. A closure that was undone is exactly what IA
    needs to see — excluding it would hide the mistakes and leave only the
    decisions nobody revisited.
    """
    qs = SchoolClosure.objects.all()
    if scope is not None:
        from apps.core.scoping import scoped_school_queryset

        schools = scoped_school_queryset(scope)
        if schools is not None:
            # A subquery rather than a list of ids: a region can hold thousands
            # of schools and shipping them as literals is how a page stops
            # scaling.
            qs = qs.filter(school_id__in=schools.values("id"))
    if fy_start is not None:
        qs = qs.filter(effective_date__gte=fy_start)
    if fy_end is not None:
        qs = qs.filter(effective_date__lt=fy_end)
    return qs


def closure_quality(fy_start: date | None = None, fy_end: date | None = None) -> dict:
    """The IA summary. One pass of aggregates, then the rows that need work.

    The counts and the lists come from the same queryset, so a number here can
    never disagree with the list it labels — the failure that makes a dashboard
    quietly untrustworthy.
    """
    base = _base(fy_start, fy_end)

    totals = base.aggregate(
        recorded=Count("id"),
        # Not a closure reason — the service refuses those — but the school's
        # own unresolved duplicate flag at the time it was closed.
        stranded_duplicates=Count(
            "id", filter=Q(school__duplicate_status=UNRESOLVED_DUPLICATE)
        ),
        reopened=Count("id", filter=Q(reopened_at__isnull=False)),
        weak_ground=Count("id", filter=Q(reason_category__in=WEAK_GROUND_REASONS)),
        missing_enrollment=Count("id", filter=Q(enrollment_at_closure__isnull=True)),
        # A reopened school is operating again, so the programme did not lose
        # it. Its enrolment stops counting as removed the moment it reopens.
        enrollment_removed=Sum(
            "enrollment_at_closure", filter=Q(reopened_at__isnull=True)
        ),
        money_under_review=Count("id", filter=Q(locked_activities_for_review__gt=0)),
    )

    recorded = totals["recorded"] or 0

    # ── Recording lag ────────────────────────────────────────────────────────
    # created_at is when somebody recorded the closure; effective_date is when
    # the school stopped. The difference is how long the country reported a
    # school it had already lost.
    lag = base.annotate(
        lag_days=Cast(ExtractDay(F("created_at") - F("effective_date")), IntegerField())
    ).aggregate(
        average=Avg("lag_days"),
        stale=Count("id", filter=Q(lag_days__gt=STALE_RECORDING_DAYS)),
    )

    return {
        "recorded": recorded,
        "stranded_duplicates": totals["stranded_duplicates"] or 0,
        "reopened": totals["reopened"] or 0,
        "weak_ground": totals["weak_ground"] or 0,
        "missing_enrollment": totals["missing_enrollment"] or 0,
        "money_under_review": totals["money_under_review"] or 0,
        "enrollment_removed": totals["enrollment_removed"] or 0,
        "average_recording_lag": (
            round(lag["average"]) if lag["average"] is not None else None
        ),
        "stale_recordings": lag["stale"] or 0,
        # A rate is only meaningful against the closures it could have applied
        # to. Reported as None rather than 0% when there is nothing to divide
        # by, so an empty period does not read as a perfect one.
        "reopening_rate": (
            round((totals["reopened"] or 0) / recorded * 100, 1) if recorded else None
        ),
    }


def by_reason(
    fy_start: date | None = None, fy_end: date | None = None, scope=None
) -> list[dict]:
    """Closures grouped by why, with weak grounds flagged rather than hidden.

    Ordered by count so the reasons worth investigating rise to the top, and
    every reason carries its own missing-enrolment count — a category where
    nobody records learner numbers is a training problem, not a data problem.
    """
    labels = dict(ClosureReason.choices)
    rows = (
        _base(fy_start, fy_end, scope)
        .values("reason_category")
        .annotate(
            total=Count("id"),
            missing_enrollment=Count(
                "id", filter=Q(enrollment_at_closure__isnull=True)
            ),
            reopened=Count("id", filter=Q(reopened_at__isnull=False)),
            enrollment=Sum("enrollment_at_closure"),
        )
        .order_by("-total")
    )
    return [
        {
            "key": row["reason_category"],
            "label": labels.get(row["reason_category"], row["reason_category"]),
            "total": row["total"],
            "missing_enrollment": row["missing_enrollment"],
            "reopened": row["reopened"],
            "enrollment": row["enrollment"] or 0,
            "is_weak_ground": row["reason_category"] in WEAK_GROUND_REASONS,
        }
        for row in rows
    ]


def monthly_trend(months: int = 12, scope=None) -> list[dict]:
    """Closures per month, and how many of them were later undone.

    Bounded to a window rather than all history: a trend line nobody can read
    is not a trend, and an unbounded group-by grows with the table.
    """
    since = date.today().replace(day=1) - timedelta(days=31 * max(1, months - 1))
    rows = (
        _base(fy_start=since, scope=scope)
        .annotate(month=TruncMonth("effective_date"))
        .values("month")
        .annotate(
            total=Count("id"),
            reopened=Count("id", filter=Q(reopened_at__isnull=False)),
        )
        .order_by("month")
    )
    return [
        {
            "month": row["month"],
            "total": row["total"],
            "reopened": row["reopened"],
        }
        for row in rows
    ]


def needs_attention(limit: int = MAX_ROWS) -> list[dict]:
    """The actual worklist: closures IA should look at, and why.

    A row can carry more than one flag, and each is named. "This school is a
    problem" is not actionable; "this closure has no enrolment count and was
    recorded 47 days late" is.
    """
    rows = (
        SchoolClosure.objects
        # Lag is annotated rather than compared in Python so a late recording
        # can be a *reason to appear* here, not merely a column once the row
        # arrived for some other reason. Every tile on the page has to lead to
        # the closures it counts, and "recorded late" was previously counted in
        # the summary and reachable from nowhere.
        .annotate(
            lag_days=Cast(
                ExtractDay(F("created_at") - F("effective_date")), IntegerField()
            )
        )
        .filter(
            Q(school__duplicate_status=UNRESOLVED_DUPLICATE)
            | Q(reason_category__in=WEAK_GROUND_REASONS)
            | Q(enrollment_at_closure__isnull=True)
            | Q(locked_activities_for_review__gt=0)
            | Q(lag_days__gt=STALE_RECORDING_DAYS)
        )
        # A reopened school is operating again; whatever was wrong with its
        # closure is no longer withholding anything. Kept out of the queue so
        # the worklist stays work.
        .filter(reopened_at__isnull=True)
        .select_related("school", "school__district")
        .order_by("-effective_date")[:limit]
    )

    out = []
    for closure in rows:
        flags = []
        if closure.school.duplicate_status == UNRESOLVED_DUPLICATE:
            flags.append(
                {
                    "key": "stranded_duplicate",
                    "label": "Closed with its duplicate flag unresolved",
                    "tone": "danger",
                }
            )
        if closure.reason_category in WEAK_GROUND_REASONS:
            flags.append(
                {
                    "key": "weak_ground",
                    "label": "Closed without confirmation",
                    "tone": "warning",
                }
            )
        if closure.enrollment_at_closure is None:
            flags.append(
                {
                    "key": "no_enrollment",
                    "label": "No enrolment recorded",
                    "tone": "warning",
                }
            )
        if closure.locked_activities_for_review:
            flags.append(
                {
                    "key": "money_under_review",
                    "label": f"{closure.locked_activities_for_review} awaiting finance",
                    "tone": "warning",
                }
            )

        lag = None
        if closure.created_at and closure.effective_date:
            lag = (closure.created_at.date() - closure.effective_date).days
        if lag is not None and lag > STALE_RECORDING_DAYS:
            flags.append(
                {
                    "key": "recorded_late",
                    "label": f"Recorded {lag} days after closing",
                    "tone": "warning",
                }
            )

        out.append(
            {
                "closure": closure,
                "school": closure.school,
                "district": getattr(closure.school.district, "name", ""),
                "flags": flags,
                "lag_days": lag,
                "is_stale": lag is not None and lag > STALE_RECORDING_DAYS,
                "reopened": closure.reopened_at is not None,
            }
        )
    return out


def reopenings(limit: int = MAX_ROWS) -> list[dict]:
    """Closures that were undone, newest first.

    Kept as its own list rather than a flag on the worklist above: a reopening
    is not outstanding work, it is evidence about how closure decisions are
    being made, and mixing the two would put resolved items in a queue.
    """
    rows = (
        SchoolClosure.objects.filter(reopened_at__isnull=False)
        .select_related("school", "school__district")
        .order_by("-reopened_at")[:limit]
    )
    return [
        {
            "closure": closure,
            "school": closure.school,
            "district": getattr(closure.school.district, "name", ""),
            "days_closed": (
                (closure.reopened_at.date() - closure.effective_date).days
                if closure.reopened_at and closure.effective_date
                else None
            ),
        }
        for closure in rows
    ]


# ── The leadership lens ──────────────────────────────────────────────────────
# Everything below answers the Country Director's question, which is not the
# one above. IA asks which records are wrong; the CD asks where the programme
# is losing schools and what that did to the plan. The two must not be merged
# into one "closure dashboard": a page that mixes work-to-fix with country
# performance leaves nobody knowing which numbers they are accountable for.


def country_summary(
    fy_start: date | None = None, fy_end: date | None = None, scope=None
) -> dict:
    """What the country lost, and what the loss did to delivery.

    With a scope, "the country" is whatever that viewer oversees — an RVP's
    assigned regions. The shape does not change with the audience, only the
    rows it is computed from.

    Schools that have since reopened are excluded from the losses: they are
    operating again, so counting them would report a programme smaller than it
    is. They are reported separately rather than silently dropped.

    The learner total carries its own coverage. Some schools have no enrolment
    count at all, so the honest statement is "X learners across Y of Z closed
    schools" — a bare total implies a completeness the data does not have.
    """
    base = _base(fy_start, fy_end, scope)
    lost = base.filter(reopened_at__isnull=True)

    totals = lost.aggregate(
        schools=Count("id"),
        learners=Sum("enrollment_at_closure"),
        counted=Count("id", filter=Q(enrollment_at_closure__isnull=False)),
        # What closing did to work that was already planned. Read from the
        # closure's own snapshot rather than re-queried: these are facts about
        # the day the decision was made, and the plan has moved since.
        activities_cancelled=Sum("activities_cancelled"),
        budget_released=Sum("budget_released"),
        partners_withdrawn=Sum("partner_assignments_withdrawn"),
        awaiting_finance=Sum("locked_activities_for_review"),
        districts=Count("school__district", distinct=True),
    )

    schools = totals["schools"] or 0
    counted = totals["counted"] or 0

    return {
        "schools_lost": schools,
        "learners_lost": totals["learners"] or 0,
        "schools_counted": counted,
        "schools_without_enrollment": schools - counted,
        "districts_affected": totals["districts"] or 0,
        "reopened": base.filter(reopened_at__isnull=False).count(),
        "activities_cancelled": totals["activities_cancelled"] or 0,
        "budget_released": totals["budget_released"] or 0,
        "partners_withdrawn": totals["partners_withdrawn"] or 0,
        "awaiting_finance": totals["awaiting_finance"] or 0,
        # An average built on partial coverage would read as a fact about all
        # closed schools. None when nothing has an enrolment count.
        "average_school_size": (
            round((totals["learners"] or 0) / counted) if counted else None
        ),
    }


def by_place(
    field: str = "district",
    fy_start: date | None = None,
    fy_end: date | None = None,
    limit: int = 50,
    scope=None,
) -> list[dict]:
    """Where the losses are, worst first.

    Concentration is the point. Eight schools lost across eight districts is a
    country-wide drift; eight lost in one district is a district in trouble,
    and the two call for completely different responses. A national total
    cannot tell them apart, so this list exists to.
    """
    if field not in {"district", "region"}:
        raise ValueError("by_place groups by district or region only")

    name = f"school__{field}__name"
    rows = (
        _base(fy_start, fy_end, scope)
        .filter(reopened_at__isnull=True)
        .values(name)
        .annotate(
            schools=Count("id"),
            learners=Sum("enrollment_at_closure"),
            counted=Count("id", filter=Q(enrollment_at_closure__isnull=False)),
            activities_cancelled=Sum("activities_cancelled"),
        )
        .order_by("-schools", "-learners")[:limit]
    )
    return [
        {
            "name": row[name] or "Not recorded",
            "schools": row["schools"],
            "learners": row["learners"] or 0,
            "schools_without_enrollment": row["schools"] - (row["counted"] or 0),
            "activities_cancelled": row["activities_cancelled"] or 0,
        }
        for row in rows
    ]
