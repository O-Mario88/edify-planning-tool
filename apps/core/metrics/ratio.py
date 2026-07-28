"""One percentage helper, and an honestly-named one for the sites that lie.

Five modules defined their own ``_pct``, and they disagreed on the only case
that matters:

    apps/frontend/views/ia_views.py        round(part / whole * 100) if whole else 0
    apps/frontend/views/dashboard_views.py round(n / total * 100)    if total else 0
    apps/analytics/pl_analytics_service.py round(n / d * 100)        if d     else 0
    apps/hr/performance_engine.py          round(100 * num / den)    if den   else None

The HR one is right. "No schools in scope" is not "0% of schools assessed";
"no targets set" is not "0% achieved". Three copies return a figure that reads
as failure when the truth is that nothing was measured -- the same defect the
metric registry exists to prevent, still live across the analytics services.

Rather than unify on the wrong answer, this module provides both and makes the
difference impossible to miss at the call site:

* :func:`percentage` returns ``None`` for an empty denominator.
* :func:`percentage_or_zero` returns ``0``, and says so in its name.

Every current caller keeps its existing behaviour, so nothing moves on screen
today. What changes is that a site showing 0-for-missing now declares it, and
migrating one is a one-word edit rather than an archaeology exercise.

For a metric that renders through ``apps.core.metrics``, prefer
:meth:`MetricValue.ratio`, which carries the denominator and the data state
instead of a bare number.
"""

from __future__ import annotations


def percentage(numerator, denominator) -> int | None:
    """``numerator`` as a whole-number percentage of ``denominator``.

    ``None`` when there is nothing to be a percentage *of* -- which a caller
    must render as "no data", never as a zero.
    """
    if not denominator:
        return None
    return round(numerator / denominator * 100)


def percentage_or_zero(numerator, denominator) -> int:
    """:func:`percentage`, but an empty denominator reads as ``0``.

    The name is the point: a reader of the call site can see that a missing
    measurement will be displayed as a real-looking zero, and decide whether
    this is a surface where that is acceptable.
    """
    value = percentage(numerator, denominator)
    return 0 if value is None else value
