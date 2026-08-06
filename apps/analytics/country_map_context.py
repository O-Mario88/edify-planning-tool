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


#: The four school cohorts the map legend counts.
SCHOOL_TYPE_KEYS = ("core", "client", "champion", "core_trained")


def school_type_totals(districts: dict[str, Any]) -> dict[str, int]:
    """Country-wide school counts per cohort.

    A plain sum over every district, which never depended on the map at all --
    the template computed it in `syncSchoolTotals` only because that is where
    the district payload happened to be parsed. §40 permits no authoritative
    business analytic in JavaScript, and a legend that tells a Country Director
    how many Core schools exist is exactly that.
    """
    totals = {key: 0 for key in SCHOOL_TYPE_KEYS}
    for district in districts.values():
        distribution = (district or {}).get("school_distribution") or {}
        for key in SCHOOL_TYPE_KEYS:
            totals[key] += distribution.get(key) or 0
    return totals


def country_map_context(fy: str | None = None) -> dict[str, Any]:
    """Return the shared system-wide map contract for an authorized viewer."""
    districts = district_insight(fy)

    return {
        "subregion_performance": subregion_performance(fy),
        "district_insight": districts,
        "subcounty_insight": subcounty_insight(fy),
        "school_type_totals": school_type_totals(districts),
        "map_scope": {
            "label": "Country-wide system data",
            "fy": fy,
        },
    }


__all__ = ["country_map_context", "school_type_totals"]
