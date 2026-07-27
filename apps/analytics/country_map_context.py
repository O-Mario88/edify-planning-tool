"""Canonical country-wide dataset for the shared analytics map.

Every authorized analytics surface renders the same geography component.  Its
data must therefore come from one system scope rather than inheriting the
calling dashboard's role, portfolio, project, or ad-hoc filters.  The selected
fiscal year is the only map filter: it keeps SSA and delivered-activity facts
time-consistent while the School Directory remains the source of school
location and classification.
"""

from __future__ import annotations

from typing import Any

from apps.analytics.district_insight import district_insight
from apps.analytics.subcounty_insight import subcounty_insight
from apps.analytics.subregion_analytics import subregion_performance


def country_map_context(fy: str | None = None) -> dict[str, Any]:
    """Return the shared system-wide map contract for an authorized viewer."""

    return {
        "subregion_performance": subregion_performance(fy),
        "district_insight": district_insight(fy),
        "subcounty_insight": subcounty_insight(fy),
        "map_scope": {
            "label": "Country-wide system data",
            "fy": fy,
        },
    }


__all__ = ["country_map_context"]
