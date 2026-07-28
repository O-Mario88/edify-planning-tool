"""The one inventory of every metric the platform is allowed to display.

Add a metric by adding one ``MetricSpec`` here and computing it in the one
service the spec names -- never by writing a fresh ``{"label": ..., "value":
...}`` dict in whichever view happens to need the number. That is how the
platform arrived at 281 KPI tiles built in 25 different key shapes, 21 labels
computed independently in more than one module, and one service reading two of
another's values by their *display labels*.

``check()`` is called by the guard tests. It is deliberately strict about the
things that were actually wrong rather than about style.
"""

from __future__ import annotations

from collections import Counter, defaultdict

from apps.core.metrics.spec import (
    Category,
    DateBasis,
    FilterBehaviour,
    MetricSpec,
    Period,
    Unit,
)


# ── Labels that describe nothing ─────────────────────────────────────────────
# Section 10 of the KPI mandate. "Budget" was in use for requested, approved and
# disbursed money; "Pending" for three unrelated queues. A label that needs the
# reader to guess which one it means is a defect, not a shorthand.
AMBIGUOUS_LABELS = frozenset(
    {
        "actual",
        "amount",
        "budget",
        "coverage",
        "count",
        "overall",
        "pending",
        "performance",
        "progress",
        "rate",
        "score",
        "status",
        "summary",
        "total",
    }
)


METRIC_REGISTRY: tuple[MetricSpec, ...] = (
    # ── My Plan: the personal scheduled-work family ──────────────────────────
    # Owned by My Plan. `projects/my_plan_service.py` and
    # `command_center/dashboard_service.py` each built their own copies of
    # these four labels against a *different* date basis -- see the module
    # docstring of apps/core/metrics/__init__.py for the divergence.
    MetricSpec(
        key="my_plan_activities_planned_week",
        label="My Activities Planned This Week",
        definition=(
            "Activities owned by the signed-in user whose planned date falls in "
            "the current week. Legacy rows with no planned date fall back to "
            "their scheduled timestamp so imported records stay visible."
        ),
        question="What am I committed to delivering this week?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Activities owned by the user, planned within the current week",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.WEEK,
        scope="Signed-in user's own activities (apps.core.scoping.owner_ids)",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="my_plan",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
        notes="Fixed context: the tile always means *this* week, never the filtered period.",
    ),
    MetricSpec(
        key="my_plan_activities_planned_month",
        label="My Activities Planned This Month",
        definition=(
            "Activities owned by the signed-in user whose planned date falls in "
            "the current calendar month, with the same legacy fallback."
        ),
        question="How loaded is my month?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Activities owned by the user, planned within the current month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="my_plan",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
    ),
    MetricSpec(
        key="my_plan_activities_planned_quarter",
        label="My Activities Planned This Quarter",
        definition=(
            "Activities owned by the signed-in user stamped with the current "
            "financial quarter. Note the basis differs from the week and month "
            "tiles: this reads the stored `quarter` field rather than a date "
            "range, so a row with a mis-stamped quarter is counted by its stamp."
        ),
        question="How loaded is my quarter?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Activities owned by the user stamped with the current quarter",
        # Declared honestly: this genuinely is not a planned-date filter.
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.QUARTER,
        scope="Signed-in user's own activities",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="my_plan",
        refresh_events=("activity_scheduled", "activity_rescheduled"),
        notes=(
            "Basis divergence from the week/month tiles is recorded here rather "
            "than hidden; reconciling it needs a data-repair pass over `quarter`."
        ),
    ),
    MetricSpec(
        key="my_plan_activities_planned_fy",
        label="My Activities Planned This Financial Year",
        definition=(
            "Every activity owned by the signed-in user within the selected "
            "financial year. The FY narrowing comes from the page's FY scope, "
            "not from a date filter on the tile."
        ),
        question="What is my whole-year commitment?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="All in-scope activities owned by the user for the FY",
        date_basis=DateBasis.NOT_TIME_BOUND,
        period=Period.FINANCIAL_YEAR,
        scope="Signed-in user's own activities, FY-scoped by the page",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FIXED_CONTEXT,
        drilldown="my_plan",
        refresh_events=("activity_scheduled",),
    ),
    # These three narrow to the *selected* period (`qs_period`), unlike the
    # four tiles above, which always describe the current week/month/quarter/FY
    # regardless of the filter. Same strip, two filter behaviours -- declared
    # here so the difference is visible rather than surprising.
    MetricSpec(
        key="my_plan_visits_scheduled_period",
        label="School Visits Scheduled This Period",
        definition=(
            "Activities of a school-visit type owned by the user within the "
            "selected period."
        ),
        question="How much of my selected period is school contact?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Visit-type activities owned by the user in the period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities, narrowed to the selected period",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
        refresh_events=("activity_scheduled",),
    ),
    MetricSpec(
        key="my_plan_trainings_scheduled_period",
        label="Trainings Scheduled This Period",
        definition=(
            "Activities of a training type owned by the user within the "
            "selected period."
        ),
        question="How much of my selected period is training delivery?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Training-type activities owned by the user in the period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities, narrowed to the selected period",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
        refresh_events=("activity_scheduled",),
    ),
    MetricSpec(
        key="my_plan_cluster_meetings_scheduled_period",
        label="Cluster Meetings Scheduled This Period",
        definition=(
            "Cluster meeting and cluster SSA review activities owned by the "
            "user within the selected period."
        ),
        question="How much of my selected period is cluster convening?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Cluster meeting activities owned by the user in the period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities, narrowed to the selected period",
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
        refresh_events=("activity_scheduled",),
    ),
    MetricSpec(
        key="my_plan_completion_readiness_pct",
        label="My Completed Share of Planned Work",
        definition=(
            "Share of the user's activities in the selected period that have "
            "reached a completed work status. Uses "
            "apps.core.activity_types.COMPLETED_WORK_STATUSES, which includes "
            "the legacy 'completed' value; target *credit* deliberately uses a "
            "stricter set (targets.my_targets.IA_VERIFIED_STATUSES)."
        ),
        question="Am I on track to finish what I planned for this period?",
        category=Category.PROGRESS,
        unit=Unit.PERCENT,
        service="apps.my_plan.services.get_my_plan_context",
        source_models=("activities.Activity",),
        numerator="Activities in COMPLETED_WORK_STATUSES within the period",
        denominator="All the user's activities planned within the same period",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope="Signed-in user's own activities",
        included_statuses=(
            "ia_verified",
            "closed",
            "accountant_confirmed",
            "completed",
        ),
        owner_page="my_plan",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="my_plan",
        refresh_events=("activity_closed", "activity_ia_verified"),
        notes=(
            "Renamed from 'Completion Readiness', which named neither the "
            "numerator nor the period. An empty period is NO_DATA, not 0% -- "
            "the previous implementations both returned 0."
        ),
    ),
)


# ── Accessors ────────────────────────────────────────────────────────────────
_BY_KEY: dict[str, MetricSpec] = {m.key: m for m in METRIC_REGISTRY}


def get_metric(key: str) -> MetricSpec:
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(
            f"unregistered metric {key!r} -- add a MetricSpec to "
            f"apps/core/metrics/registry.py before displaying it"
        ) from None


def all_metrics() -> tuple[MetricSpec, ...]:
    return METRIC_REGISTRY


def metrics_for_page(page: str) -> tuple[MetricSpec, ...]:
    return tuple(m for m in METRIC_REGISTRY if page in m.approved_pages())


def check() -> None:
    """Fail loudly on the defects this registry exists to prevent."""
    duplicate_keys = [
        k for k, n in Counter(m.key for m in METRIC_REGISTRY).items() if n > 1
    ]
    if duplicate_keys:
        raise ValueError(f"duplicate metric keys: {sorted(duplicate_keys)}")

    # Two metrics with one label are indistinguishable to a reader, which is
    # precisely how a page ends up showing "the same thing" twice.
    by_label: dict[str, list[str]] = defaultdict(list)
    for m in METRIC_REGISTRY:
        by_label[m.label.casefold()].append(m.key)
    clashes = {label: keys for label, keys in by_label.items() if len(keys) > 1}
    if clashes:
        raise ValueError(f"metrics sharing a label: {clashes}")

    vague = [
        m.key for m in METRIC_REGISTRY if m.label.strip().casefold() in AMBIGUOUS_LABELS
    ]
    if vague:
        raise ValueError(
            f"labels that do not say what they count: {sorted(vague)} -- "
            f"name the state, period and scope"
        )

    # One metric, one owning page (section 4). A metric listing itself as a
    # secondary appearance of its own owner is a copy-paste, not a decision.
    for m in METRIC_REGISTRY:
        if m.owner_page in m.secondary_pages:
            raise ValueError(f"{m.key}: owner_page repeated in secondary_pages")
