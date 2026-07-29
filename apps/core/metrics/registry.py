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
    FinanceStage,
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
    # ── Upload Center ────────────────────────────────────────────────────────
    MetricSpec(
        key="uploads_awaiting_review",
        label="Awaiting Review",
        definition=(
            "Records in the Upload Center whose next action is a review: a "
            "staged import batch, or a document submitted and not yet approved."
        ),
        question="What is waiting on somebody to look at it?",
        category=Category.PENDING_ACTION,
        unit=Unit.COUNT,
        service="apps.documents.upload_center.UploadCenterService",
        source_models=(
            "documents.DocumentAsset",
            "schools.SchoolImportBatch",
            "schools.SSAImportBatch",
        ),
        numerator="Authorised rows whose next action is a review step",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Only the categories the viewer's role can see",
        owner_page="uploads",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="uploads",
        notes=(
            "Counted across adapters, so one number covers imports and "
            "documents rather than a tile per source."
        ),
    ),
    MetricSpec(
        key="uploads_documents_published",
        label="Published",
        definition="Documents in the library that are published or effective.",
        question="How much of the library is live?",
        category=Category.SCALE,
        unit=Unit.COUNT,
        service="apps.documents.upload_center.UploadCenterService",
        source_models=("documents.DocumentAsset",),
        numerator="DocumentAsset rows in a readable status",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="Documents the viewer administers or is an audience for",
        owner_page="uploads",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="uploads",
    ),
    # ── Policy compliance ────────────────────────────────────────────────────
    MetricSpec(
        key="policy_acknowledgements_accepted",
        label="Accepted",
        definition=(
            "People who have agreed to the current version of a mandatory "
            "document, within the viewer's scope."
        ),
        question="Who has accepted the policies required of them?",
        category=Category.PROGRESS,
        unit=Unit.COUNT,
        service="apps.documents.compliance.PolicyComplianceService",
        source_models=("documents.DocumentAcknowledgement",),
        numerator="Acknowledgements in the agreed state",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="HR: their remit · CD: their country · PL: supervised staff",
        owner_page="policy_compliance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="policy_compliance",
        notes=(
            "Keyed on the version, so agreeing to v1 does not count as " "accepting v2."
        ),
    ),
    # ── Fund requests: the monthly summary band ─────────────────────────────
    # Five planned-money figures for the month the page has open. All PLANNED:
    # sums of ActivityScheduleCostLine for the selected month, before any
    # approval or disbursement -- naming the stage is what stops this band
    # disagreeing with a disbursement figure under the same word "budget".
    MetricSpec(
        key="fund_request_monthly_visits_budget",
        label="School Visits",
        definition=(
            "Planned school-visit spend for the selected month: the sum of schedule cost lines on visit activities planned in that month."
        ),
        question="How much of this month's plan is school visits?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Cost-line amounts on visit-type activities planned in the month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="fund_request_monthly_trainings_budget",
        label="Cluster Trainings",
        definition=("Planned cluster-training spend for the selected month."),
        question="How much of this month's plan is trainings?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Cost-line amounts on training-type activities planned in the month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="fund_request_monthly_meetings_budget",
        label="Cluster Meetings",
        definition=("Planned cluster-meeting spend for the selected month."),
        question="How much of this month's plan is cluster meetings?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Cost-line amounts on cluster-meeting activities planned in the month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="fund_request_monthly_admin_budget",
        label="Admin Budget (for CD)",
        definition=(
            "Planned administrative spend for the selected month -- the CD's monthly admin plan lines, not field-activity costs."
        ),
        question="How much administrative money does this month's plan carry?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Admin budget lines for the month",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="fund_request_monthly_total",
        label="Total Monthly Request",
        definition=(
            "Everything the selected month's plan asks for: visits, trainings, meetings and admin together."
        ),
        question="What will this month's plan request in total?",
        category=Category.FINANCE,
        unit=Unit.MONEY_UGX,
        finance_stage=FinanceStage.PLANNED,
        service="apps.frontend.views.budget_views._build_fund_requests_context",
        source_models=("activities.ActivityScheduleCostLine",),
        numerator="Sum of the four monthly components",
        date_basis=DateBasis.PLANNED_DATE,
        period=Period.MONTH,
        scope=(
            "Role-dependent: CCEO own plan · PL supervised team · "
            "CD/Admin their monthly admin plan (switchable to country)"
        ),
        owner_page="fund_requests",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="fund_requests",
    ),
    MetricSpec(
        key="policy_acknowledgements_overdue",
        label="Overdue",
        definition=(
            "Pending acknowledgements whose due date has passed, within the "
            "viewer's scope."
        ),
        question="Who has run out of time to respond?",
        category=Category.RISK,
        unit=Unit.COUNT,
        service="apps.documents.compliance.PolicyComplianceService",
        source_models=("documents.DocumentAcknowledgement",),
        numerator="Pending acknowledgements with due_date in the past",
        date_basis=DateBasis.RECORD_CREATED,
        period=Period.ALL_TIME,
        scope="HR: their remit · CD: their country · PL: supervised staff",
        owner_page="policy_compliance",
        filter_behaviour=FilterBehaviour.FILTERED,
        drilldown="policy_compliance",
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
