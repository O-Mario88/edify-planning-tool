"""Opening a fiscal year inside a test, the way a Country Director would.

Since the owner's brief of 2026-09-15 a fiscal year has a governed planning
window: `assert_date_plannable` refuses a date in a year nobody has opened,
which is the point — FY2027 was opened deliberately, while FY2026 was still
being closed, and no year opens itself.

A walk that deliberately plans into a *later* year — proving entitlement slots
are counted per FY, or that a reschedule across the boundary moves every
period field — therefore has to open that year first. That is a fixture
detail, not the thing under test, so it lives here rather than being rewritten
in each walk.

Not exported from the planning app: production code opens a year through
`apps.planning.fy_policy.open_fy_planning`, which checks authority, audits the
change and announces it. This writes the row directly, which only a test may
do.
"""

from __future__ import annotations

import datetime

from django.utils import timezone


def open_fy_for_planning(fy: str, *, country: str = "Uganda"):
    """Ensure `fy` is open for planning. Idempotent; returns the policy."""
    from apps.core.fy import get_fy_date_range
    from apps.planning.fy_policy_models import FiscalYearPlanningPolicy

    start, end = get_fy_date_range(str(fy))
    policy, _ = FiscalYearPlanningPolicy.objects.get_or_create(
        country=country,
        fy=str(fy),
        defaults={
            "planning_open_at": timezone.now() - datetime.timedelta(days=1),
            "execution_start": start,
            "execution_end": end,
            "opened_by": "test",
            "updated_by": "test",
            "notes": "Opened by a test fixture.",
        },
    )
    return policy


__all__ = ["open_fy_for_planning"]
