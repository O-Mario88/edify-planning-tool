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

The other way a test meets the boundary is by accident: a fixture that plans
a week ahead crosses into next year every late September.
`MidFiscalYearClock` keeps such a fixture inside one year.
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


class MidFiscalYearClock:
    """Mixin: a test class's clock runs from 12 May of the current fiscal year.

    For fixtures that schedule a week or two ahead and tie a core package or
    cost catalogue to the fiscal year of that day, while the code under test
    reads today's (`get_operational_fy()`). In the last week of September the
    two differ, and every such test failed until 1 October. 12 May is far
    enough from 30 September that "today plus a fortnight" stays in one year.

    The year is the CURRENT one, not a fixed one, because the test database is
    not frozen: `budget` migration 0003 seeds its rate card for the fiscal year
    the database is built in, and `active_catalogue()` prefers the newest
    card. A clock pinned to a fixed year would lose to that card every
    October. The year is resolved the way that migration resolves it.

    List it before `TestCase` so the clock is set before `setUpTestData` runs.
    It holds from `setUpClass` to `tearDownClass` and goes through `super()`,
    so a subclass is pinned too. freezegun's own class decorator binds
    `setUpClass` to the class it decorates, which would run a subclass's
    fixture against its parent.
    """

    @classmethod
    def setUpClass(cls):
        from django.conf import settings
        from freezegun import freeze_time

        from apps.core.fy import get_operational_fy

        fy = getattr(settings, "OPERATIONAL_FY", None) or get_operational_fy()
        # FY2026 runs 1 October 2025 to 30 September 2026, so its May is in
        # 2026. 09:00 UTC is midday in Kampala.
        cls._mid_fiscal_year_clock = freeze_time(f"{int(fy)}-05-12 09:00:00", tick=True)
        cls._mid_fiscal_year_clock.start()
        try:
            super().setUpClass()
        except BaseException:
            cls._mid_fiscal_year_clock.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            super().tearDownClass()
        finally:
            cls._mid_fiscal_year_clock.stop()


__all__ = ["MidFiscalYearClock", "open_fy_for_planning"]
