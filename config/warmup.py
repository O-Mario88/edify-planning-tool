"""Pay the process's one-off import cost before it takes traffic.

Django loads the URLconf lazily, on the first request. This platform's URLconf
pulls in the analytics engines, and those pull in pandas, NumPy and SciPy —
about seven seconds of imports on a one-vCPU instance (measured 2026-09-12,
config.urls alone: 7.7 s in a fresh process, 6.7 s of it SciPy and pandas).
With one worker that cost landed on the first person to open a page after
every deploy or restart, and everyone behind them queued for it: the
"freezing" the client reported.

Both server entry points call this once at import time, so a worker is warm
before Gunicorn marks it ready. Failures are logged and never fatal: a warm-up
that could take the process down would be worse than the stall it prevents.
"""

from __future__ import annotations

import importlib
import logging
import time

logger = logging.getLogger(__name__)

# The URLconf first (it imports most of the views), then the modules that are
# heavy even when the URLconf does not reach them.
WARM_MODULES = (
    "config.urls",
    "apps.analytics.platform_engine",
    "apps.analytics.decision_engine",
    "apps.analytics.subregion_analytics",
    "apps.analytics.district_insight",
    "apps.analytics.impact_engine",
    "apps.analytics.visit_effectiveness_engine",
    # SciPy is loaded lazily by the engines (four seconds); at boot it is
    # cheap to pay, so the first trend analysis of the day does not.
    "scipy.stats",
)


def warm() -> dict[str, float]:
    """Import every module in WARM_MODULES; return seconds spent per module."""
    timings: dict[str, float] = {}
    for name in WARM_MODULES:
        started = time.perf_counter()
        try:
            importlib.import_module(name)
        except Exception:  # noqa: BLE001 - warm-up must never take the process down
            logger.exception("warm-up import failed for %s", name)
        timings[name] = round(time.perf_counter() - started, 3)
    logger.info(
        "process warm in %.1fs (%s)",
        sum(timings.values()),
        ", ".join(
            f"{k.rsplit('.', 1)[-1]}={v}" for k, v in timings.items() if v >= 0.05
        ),
    )
    return timings
