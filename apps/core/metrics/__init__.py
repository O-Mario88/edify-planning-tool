"""Canonical metric definitions for every KPI the platform displays.

Why this package exists
-----------------------

``manage.py build_kpi_inventory`` finds 281 KPI tiles built across 37 modules,
carrying 227 distinct labels in 25 different dict shapes. None carried a stable
identifier, 11 carried a drill-down, and none distinguished a measured zero
from missing data. The consequences were not cosmetic:

* ``CDDashboardService.kpis()`` read another service's number by its **display
  label** (``analytics["Overall Target Achievement"]["value"]``), so renaming a
  label would have silently broken the Country Director dashboard.

* "Planned This Week/Month/Quarter/FY" and "Completion Readiness" were each
  computed independently in ``apps/my_plan/services.py`` and
  ``apps/projects/my_plan_service.py`` against **different date bases** -- My
  Plan matches planned date with a null fallback to the scheduled timestamp,
  reads the quarter tile off a stored ``quarter`` field, and applies no date
  filter at all for the FY tile, while the Projects copy uses a strict
  ``planned_date`` range for all four. The two also rounded differently
  (``int()`` truncation against ``round()``), so two of three planned
  activities read as 66% on one page and 67% on the other.

* Every ratio on the platform returned ``0`` for an empty denominator, so "no
  schools were assessed" and "no school scored" rendered identically.

The fix is not a tidier card component -- the presentation layer was already
consolidated. It is giving each metric an identity, one owning service, a
declared denominator, a declared date basis, and an honest answer for the case
where there is no number to show.

Usage
-----

    from apps.core.metrics import MetricValue, render_metric

    tile = render_metric(
        "my_plan_completion_readiness_pct",
        MetricValue.ratio(completed, planned),
    )

``MetricValue.ratio`` returns NO_DATA rather than 0% when ``planned`` is zero,
and ``render_metric`` refuses to render a percentage that cannot name what it
is a percentage of.
"""

from apps.core.metrics.money import format_ugx_compact
from apps.core.metrics.payload import (
    RenderedMetric,
    accessible_description,
    format_value,
    render_metric,
    render_strip,
)
from apps.core.metrics.registry import (
    AMBIGUOUS_LABELS,
    METRIC_REGISTRY,
    all_metrics,
    check,
    get_metric,
    metrics_for_page,
)
from apps.core.metrics.spec import (
    Category,
    DateBasis,
    FilterBehaviour,
    FinanceStage,
    MetricSpec,
    Period,
    Unit,
)
from apps.core.metrics.states import (
    DEFAULT_STATE_TEXT,
    DataState,
    MetricValue,
)

__all__ = [
    "AMBIGUOUS_LABELS",
    "DEFAULT_STATE_TEXT",
    "METRIC_REGISTRY",
    "Category",
    "DataState",
    "DateBasis",
    "FilterBehaviour",
    "FinanceStage",
    "MetricSpec",
    "MetricValue",
    "Period",
    "RenderedMetric",
    "Unit",
    "accessible_description",
    "all_metrics",
    "check",
    "format_ugx_compact",
    "format_value",
    "get_metric",
    "metrics_for_page",
    "render_metric",
    "render_strip",
]
