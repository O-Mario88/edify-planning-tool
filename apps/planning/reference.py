"""The fiscal-year planning policies the platform cannot plan without.

A fiscal year with no policy row is not "unrestricted": `is_planning_open`
answers False, so every planning surface refuses the year and says nothing
useful about why. The rows are reference data, not user data — nobody creates
a fiscal year in the interface — and `planning.0011` seeds them.

A migration is enough for a database that only moves forward. It is not enough
for one that gets flushed: `TransactionTestCase` truncates every table and
migration-seeded rows do not come back, so the year silently closes for the
rest of that database's life. This module is the idempotent restore, wired to
post_migrate through apps/core/reference_data.py.

The dates are the owner's (brief of 2026-09-15): FY2026 runs to 30 September
2026; FY2027 runs 1 October 2026 – 30 September 2027 and opened for planning
on 15 September 2026, while FY2026 was still being closed.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

COUNTRY = "Uganda"

POLICIES = (
    {
        "fy": "2026",
        "planning_open_at": datetime(2025, 7, 1, tzinfo=timezone.utc),
        "execution_start": date(2025, 10, 1),
        "execution_end": date(2026, 9, 30),
        "notes": "FY2026 runs to 30 September 2026.",
    },
    {
        # 15 September 2026, 00:00 in Kampala (UTC+3).
        "fy": "2027",
        "planning_open_at": datetime(2026, 9, 14, 21, 0, tzinfo=timezone.utc),
        "execution_start": date(2026, 10, 1),
        "execution_end": date(2027, 9, 30),
        "notes": "FY2027 opened for planning by the owner's brief of 2026-09-15.",
    },
)


def ensure_planning_reference() -> None:
    """Put the seeded planning policies back. Safe to run repeatedly.

    `get_or_create`, never update: a Country Director who has since moved a
    window through the governed page owns that decision, and restoring a row
    must not quietly undo it.
    """
    from apps.planning.fy_policy_models import FiscalYearPlanningPolicy

    for row in POLICIES:
        FiscalYearPlanningPolicy.objects.get_or_create(
            country=COUNTRY,
            fy=row["fy"],
            defaults={
                "planning_open_at": row["planning_open_at"],
                "execution_start": row["execution_start"],
                "execution_end": row["execution_end"],
                "follow_up_visit_requires_prior_training": False,
                "opened_by": "reference_data",
                "updated_by": "reference_data",
                "notes": row["notes"],
            },
        )


def planning_reference_is_complete() -> bool:
    """Read-only: is every seeded year present?"""
    from apps.planning.fy_policy_models import FiscalYearPlanningPolicy

    present = set(
        FiscalYearPlanningPolicy.objects.filter(
            country=COUNTRY, fy__in=[row["fy"] for row in POLICIES]
        ).values_list("fy", flat=True)
    )
    return present == {row["fy"] for row in POLICIES}


__all__ = ["ensure_planning_reference", "planning_reference_is_complete"]
