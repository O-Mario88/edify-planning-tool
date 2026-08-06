"""What a platform metric has to declare about itself before it may be shown.

``manage.py build_kpi_inventory`` finds 281 KPI tiles across 37 modules built
in **25 different key shapes**. Some carry ``helper``, some ``hint``, some
``subtitle``; 11 of 281 carry a drill-down and none carries a data state.
Nothing carried a stable identifier, so the only way one service could
reference another's number was to look it up by its display label -- which
``CDDashboardService`` genuinely did, keying off the strings
``"Overall Target Achievement"`` and ``"Budget Utilization"``.

A metric with no identity cannot be deduplicated, tested, traced to a query, or
safely renamed. ``MetricSpec`` is that identity. The fields are not paperwork:
each one is a question that was previously answered implicitly and
inconsistently, and each is checked by a guard test.

  * ``denominator`` exists because a percentage without one cannot be audited,
    and because ``0/0`` was rendering as ``100%``.
  * ``date_basis`` exists because "this month" meant planned date on one page
    and closure date on another.
  * ``finance_stage`` exists because "Budget" was used for requested, approved
    and disbursed money on three different pages.
  * ``owner_page`` exists because the same number was recomputed on every
    dashboard that wanted to mention it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Category(str, Enum):
    """The kind of understanding a metric buys the reader.

    A KPI strip should not draw twice from the same category -- two tiles that
    both answer "how much is there?" are one tile and a duplicate.
    """

    SCALE = "scale"
    PROGRESS = "progress"
    PENDING_ACTION = "pending_action"
    RISK = "risk"
    QUALITY = "quality"
    FINANCE = "finance"
    OUTCOME = "outcome"
    READINESS = "readiness"
    CAPACITY = "capacity"
    COMPLIANCE = "compliance"


class Unit(str, Enum):
    COUNT = "count"
    PERCENT = "percent"
    MONEY_UGX = "money_ugx"
    SCORE = "score"
    DAYS = "days"


class DateBasis(str, Enum):
    """Which date a metric filters on.

    Mixing these inside one metric is the defect this enum exists to make
    impossible to write down: an activity planned in August, executed in
    September and closed in October belongs to a different month under each.
    """

    PLANNED_DATE = "activity_planned_date"
    EXECUTION_DATE = "activity_execution_date"
    CLOSURE_DATE = "activity_closure_date"
    SSA_ASSESSMENT_DATE = "ssa_assessment_date"
    SUBMISSION_DATE = "submission_date"
    APPROVAL_DATE = "approval_date"
    DISBURSEMENT_DATE = "disbursement_date"
    NETSUITE_BOOKING_DATE = "netsuite_booking_date"
    RECORD_CREATED = "record_created"
    # For metrics that describe a standing population rather than an event
    # ("schools in my portfolio"), where a date filter would be meaningless.
    NOT_TIME_BOUND = "not_time_bound"


class Period(str, Enum):
    """The window the metric covers. FY runs October–September (apps.core.fy)."""

    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    MID_YEAR = "mid_year"
    FINANCIAL_YEAR = "financial_year"
    ROLLING_30_DAYS = "rolling_30_days"
    ALL_TIME = "all_time"
    POINT_IN_TIME = "point_in_time"


class FinanceStage(str, Enum):
    """Where money sits in the pipeline.

    Required on every money metric. "Budget" on its own was being used for at
    least three of these, which is how a page can show two different correct
    numbers under the same word.
    """

    PLANNED = "planned"
    REQUESTED = "requested"
    APPROVED = "approved"
    DISBURSED = "disbursed"
    ACCOUNTED = "accounted"
    NETSUITE_BOOKED = "netsuite_booked"
    RETURNED = "returned"
    REIMBURSED = "reimbursed"
    OUTSTANDING = "outstanding"
    VARIANCE = "variance"


class FilterBehaviour(str, Enum):
    """How the metric responds to the page's filter controls.

    Declared rather than inferred, because a strip that silently mixes filtered
    and unfiltered tiles teaches the reader to distrust all of them.
    """

    FILTERED = "filtered"
    PARTIAL = "partial"
    FIXED_CONTEXT = "fixed_context"
    UNFILTERED_BENCHMARK = "unfiltered_benchmark"


@dataclass(frozen=True)
class MetricSpec:
    """One metric, defined once, for the whole platform."""

    # ── Identity ─────────────────────────────────────────────────────────────
    key: str
    label: str
    definition: str
    # The decision this metric supports. A metric that cannot complete the
    # sentence "the reader looks at this in order to ..." is decoration.
    question: str
    category: Category
    unit: Unit

    # ── Computation ──────────────────────────────────────────────────────────
    # Dotted path to the one service that computes it. Two services computing
    # one metric is the divergence this field prevents.
    service: str
    source_models: tuple[str, ...]
    numerator: str
    date_basis: DateBasis
    period: Period
    scope: str

    # ── Placement ────────────────────────────────────────────────────────────
    owner_page: str
    filter_behaviour: FilterBehaviour

    # ── Conditionally required ───────────────────────────────────────────────
    # Mandatory for PERCENT (checked in __post_init__): what the metric is a
    # share *of*.
    denominator: str | None = None
    # Mandatory for MONEY_UGX: which finance stage the amount represents.
    finance_stage: FinanceStage | None = None

    # ── Optional but load-bearing ────────────────────────────────────────────
    included_statuses: tuple[str, ...] = ()
    excluded_statuses: tuple[str, ...] = ()
    # Route name or path the tile links to. ``None`` is allowed only with a
    # stated reason, so "no drill-down" is a decision rather than an oversight.
    drilldown: str | None = None
    no_drilldown_reason: str | None = None
    # Pages other than the owner that may show this metric, each with the
    # different decision that justifies the repeat.
    secondary_pages: tuple[str, ...] = ()
    # Domain events after which this metric is stale and must be recomputed.
    refresh_events: tuple[str, ...] = ()
    roles: tuple[str, ...] = ()
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.key or self.key != self.key.lower().strip():
            raise ValueError(f"metric key must be lower-case and trimmed: {self.key!r}")

        if self.unit is Unit.PERCENT and not self.denominator:
            raise ValueError(
                f"{self.key}: a percentage must name its denominator -- "
                "an unaudited share is the defect, not the missing field"
            )
        if self.unit is Unit.MONEY_UGX and self.finance_stage is None:
            raise ValueError(
                f"{self.key}: a money metric must name its finance stage; "
                "'budget' alone has meant requested, approved and disbursed"
            )
        if self.drilldown is None and not self.no_drilldown_reason:
            raise ValueError(
                f"{self.key}: give a drilldown, or say why the number is "
                "purely contextual"
            )
        if self.drilldown and self.no_drilldown_reason:
            raise ValueError(f"{self.key}: it has a drilldown or it does not")

    @property
    def is_ratio(self) -> bool:
        return self.unit is Unit.PERCENT

    def approved_pages(self) -> tuple[str, ...]:
        return (self.owner_page, *self.secondary_pages)
