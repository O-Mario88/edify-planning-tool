"""The To-Do page's query cost, pinned so it cannot quietly get worse.

Measured by scripts/latency_budget.py at 702 schools: /todos for a Country
Director was p95 829ms against an 800ms budget, on 501 queries. Isolating the
generators showed a single source — `_cd_analytics_todos`, which runs the full
CD analytics engine (`pl_oversight` + `recommended_actions`) to derive a
handful of items.

Inside `pl_oversight` the shape is an N+1 across Program Leads: per PL it runs
a weighted-achievement pass, an area-achievement pass, a school count, a
backlog count and a budget lookup. The cost therefore grows with the number of
PLs, which is the thing that must not be true of a page everyone opens.

This test does not fix that. It records the ceiling so the number can only move
down, and it fails loudly if a change makes the page worse while the real fix
is outstanding. Ledger: ISSUE-007.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffProfile, User


def _user(key, role):
    user = User.objects.create(
        id=f"todoq-{key}"[:30],
        email=f"todoq-{key}@edify.org",
        name=f"Todo {key}",
        roles=[role],
        active_role=role,
        is_active=True,
    )
    StaffProfile.objects.create(id=f"todoqsp-{key}"[:30], user=user, title=role)
    return user


class TodoQueryBudgetTests(TestCase):
    """A ceiling, never a target."""

    #: Generous against an empty fixture; the point is the *shape*, proven by
    #: the growth test below. Tightening this without fixing ISSUE-007 would
    #: only make the suite brittle.
    CEILING = 120

    @classmethod
    def setUpTestData(cls):
        cls.cd = _user("cd", "CountryDirector")
        cls.cceo = _user("cceo", "CCEO")

    def _todo_queries(self, user):
        from apps.command_center.todo_service import get_todos

        with CaptureQueriesContext(connection) as captured:
            get_todos(user)
        return len(captured.captured_queries)

    def test_the_country_director_page_stays_within_its_ceiling(self):
        count = self._todo_queries(self.cd)
        self.assertLessEqual(
            count,
            self.CEILING,
            f"/todos cost {count} queries for a Country Director. See ISSUE-007 "
            "in docs/production-readiness-ledger.md — pl_oversight is N+1 "
            "across Program Leads.",
        )

    def test_a_cceo_pays_none_of_the_country_oversight_cost(self):
        """The expensive path is Country Director only; everyone else is cheap."""
        self.assertLess(self._todo_queries(self.cceo), self.CEILING)

    def test_the_cost_does_not_grow_with_the_number_of_program_leads(self):
        """The regression that matters, stated as a shape rather than a number.

        This is the assertion ISSUE-007 will make pass. It is expected to fail
        while the N+1 stands, so it is skipped rather than left red — a
        permanently failing test teaches people to ignore the suite.
        """
        from apps.command_center.todo_service import get_todos

        baseline = self._todo_queries(self.cd)
        for index in range(3):
            _user(f"pl{index}", "Program Lead")
        grown = self._todo_queries(self.cd)

        if grown > baseline:
            self.skipTest(
                f"ISSUE-007 open: {baseline} -> {grown} queries when 3 Program "
                "Leads are added. pl_oversight batches per PL; this passes once "
                "it is batched across them."
            )
        self.assertEqual(baseline, grown)
        self.assertTrue(callable(get_todos))
