"""Partners needing follow-up, for Partner Monitoring.

The Analytics page's Recommended Actions counted "Partners needing
follow-up"; the owner gave it a home on Partner Monitoring (2026-10-19), beside
each Partner it flags. The flag is the Country Director Analytics' own
recommendation (`CDAnalyticsService.partner_performance`), read here rather
than restated, so the two never disagree: a Partner on target whose schools'
SSA rose less than half a point is sent to a Quality Review, one below target
whose schools rose half a point or more to a Capacity Review.
"""

from __future__ import annotations

#: The recommendations Recommended Actions counted as needing follow-up.
FOLLOW_UP = ("Quality Review", "Capacity Review", "Put Under Review")


def partners_needing_follow_up(user, fy) -> dict[str, str]:
    """``{partner id: recommendation}`` for each Partner in the reader's
    country whose recommendation for ``fy`` is one of FOLLOW_UP."""
    from apps.analytics.cd_analytics_service import (
        CDAnalyticsService,
        _country_activities,
        country_for,
        resolve_cd_scope,
    )

    cd = resolve_cd_scope(str(fy), country=country_for(user))
    rows = CDAnalyticsService.partner_performance(cd, _country_activities(cd))["rows"]
    return {
        row["id"]: row["recommendation"]
        for row in rows
        if row["recommendation"] in FOLLOW_UP
    }
