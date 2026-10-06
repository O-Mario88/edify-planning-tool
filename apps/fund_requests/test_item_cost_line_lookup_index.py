"""Which fund requests hold a cost line is answered from an index.

Re-costing an activity replaces its cost lines and first asks which requests
hold the old ones (``apply_to_activity``). The unique constraint on the item
table leads with ``fund_request``, so it cannot answer a question that starts
from the cost line, and the lookup read every item: 7.6 ms a call on
production, 11,500 calls (audit, 2026-10-05).

The index is checked in the database's own catalogue rather than through a
query plan. With sequential scans priced out Postgres will walk the whole
unique index instead, which reads as an index scan and is not one.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase

from apps.fund_requests.models import FundRequestItem


class ItemCostLineLookupIndexTest(TestCase):
    def test_an_index_leads_with_the_cost_line(self):
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(
                cursor, FundRequestItem._meta.db_table
            )
        leading = [
            name
            for name, detail in constraints.items()
            if detail["index"]
            and detail["columns"][:1] == ["activity_schedule_cost_line_id"]
        ]

        self.assertTrue(
            leading,
            "fund_request_item needs an index led by "
            "activity_schedule_cost_line_id: re-costing an activity looks its "
            "requests up by cost line.",
        )
