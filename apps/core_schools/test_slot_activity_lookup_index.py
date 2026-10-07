"""Which slots mirror an activity is answered from an index.

``Activity.save()`` asks it on every save and the package-credit rules ask it
before crediting, so a scheduling action asks it for every activity it
touches. ``activity_id`` is a plain column rather than a foreign key, so
nothing indexed it and each question read the whole table: 5-7 ms a call on
production, 60,000 calls, a quarter of the database's time (audit,
2026-10-05).

The index is checked in the database's own catalogue, and its use through a
query plan over a table with rows in it. An empty table's plan proves
nothing: once Postgres has analysed the table as empty every index on it
costs the same, and the planner keeps the first one made, which is not this
one. That test passed or failed by whether autovacuum had reached the table
in the worker's database before it ran (CI, 2026-10-07).
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase

from apps.core_schools.models import CoreActivitySlot, CorePlan

#: Enough slots that reading them all through another index costs more than
#: finding one through this one.
SLOTS = 300


def indexes_leading_with(model, column: str) -> list[str]:
    """Names of the indexes on ``model``'s table whose first column is ``column``."""
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(
            cursor, model._meta.db_table
        )
    return [
        name
        for name, detail in constraints.items()
        if detail["index"] and detail["columns"][:1] == [column]
    ]


class SlotActivityLookupIndexTest(TestCase):
    def test_an_index_leads_with_the_activity(self):
        self.assertTrue(
            indexes_leading_with(CoreActivitySlot, "activity_id"),
            "core_activity_slot needs an index led by activity_id: "
            "Activity.save() looks slots up by it on every save.",
        )

    def test_the_lookup_uses_it(self):
        plan_row = CorePlan.objects.create(id="idx-plan", school_id="IDX-1", fy="2027")
        CoreActivitySlot.objects.bulk_create(
            CoreActivitySlot(
                id=f"idx-slot-{n}",
                core_plan=plan_row,
                school_id="IDX-1",
                intervention="leadership",
                activity_type="visit",
                sequence_number=n,
                activity_id=f"act-{n}",
            )
            for n in range(SLOTS)
        )
        with connection.cursor() as cursor:
            # Inside the test's transaction: the figures are this test's and
            # leave with it.
            cursor.execute("ANALYZE core_activity_slot")
            cursor.execute("ANALYZE core_plan")
            cursor.execute("SET LOCAL enable_seqscan = off")
        plan = (
            CoreActivitySlot.objects.filter(activity_id="act-1")
            .select_related("core_plan")
            .explain()
        )

        self.assertIn("Index Cond: ((activity_id)::text = 'act-1'::text)", plan)
