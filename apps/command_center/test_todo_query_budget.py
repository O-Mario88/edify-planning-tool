"""The To-Do page's query cost, pinned so it cannot get worse again.

Measured by scripts/latency_budget.py at 702 schools: /todos for a Country
Director was p95 829ms against an 800ms budget, on 501 queries. Isolating the
generators found one source -- `_cd_analytics_todos`, which runs the CD
analytics engine to derive a handful of items.

The cause was not the engine. `_weighted_achievement` already pools from a
pre-fetched per-user target series when it is given one, and every other caller
of `pl_oversight` primes that series first. `cd_todos` did not, so the ledger
was re-fetched once per Program Lead.

Priming it took /todos from 501 queries to 216, and p95 from 829ms to 414ms,
with byte-identical output.

A second O(Program Leads) term survived that: `_pl_cceos` was memoised per
Programme Lead, so each additional one was a fresh miss costing three more
queries on every Country Director surface that walks the list. Resolving the
whole list at once (CDAnalyticsService._pl_cceos_batch, primed onto the scope
by _prime_pl_cceos) makes that a fixed cost. /todos measured flat at 69
queries across 3, 9 and 18 Programme Leads.

Measured over the REQUEST, not by calling get_todos() directly. The two are
not the same number and only one of them is what production serves: several
hot paths memoise through apps.core.request_cache, which is deliberately
inert outside a request so nothing long-running can serve stale reference
data. Calling the service directly therefore pays a per-user re-read that no
page load pays -- around two queries per Programme Lead, all of it
active_target_areas() re-deriving org-wide configuration. Asserting the
growth shape against that path measures a policy, not a regression, so the
shape assertion below goes through the client and the direct path gets a
ceiling instead.
"""

from __future__ import annotations

from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
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

    #: Measured at 55 for a Country Director against this fixture after the
    #: series-priming fix (was ~120 before). The headroom covers a handful of
    #: Program Leads; it is a ceiling, never a target.
    CEILING = 90

    #: The direct, no-request path with three Programme Leads. Higher than
    #: CEILING because it re-reads what a request memoises; see the module
    #: docstring. A ceiling, never a target.
    DIRECT_CEILING = 100

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

    @override_settings(TODO_SNAPSHOT_CACHE_SECONDS=60)
    def test_shared_pages_reuse_one_short_lived_todo_snapshot(self):
        from apps.command_center import todo_service

        cache.clear()
        with patch.object(
            todo_service,
            "get_todos",
            wraps=todo_service.get_todos,
        ) as derive:
            first = todo_service.get_cached_todos(self.cceo)
            second = todo_service.get_cached_todos(self.cceo)

        self.assertEqual(first, second)
        self.assertEqual(derive.call_count, 1)

    def _page_queries(self):
        """/todos over the real request cycle — what a Country Director pays.

        Log in first and discard one response: the first request of a session
        also writes django_session, which is three queries of login and none
        of page cost.
        """
        self.client.force_login(self.cd)
        self.assertEqual(self.client.get("/todos").status_code, 200)
        with CaptureQueriesContext(connection) as captured:
            response = self.client.get("/todos")
        self.assertEqual(response.status_code, 200)
        return len(captured.captured_queries)

    def test_the_cost_does_not_grow_with_the_number_of_program_leads(self):
        """The regression that matters, stated as a shape rather than a number.

        ISSUE-007. Three Programme Leads to eighteen is a sixfold increase in
        the thing the page walks; the query count may not move at all. Stated
        as a shape because the absolute number is allowed to drift with
        unrelated work, and the growth is not.
        """
        for index in range(3):
            _user(f"pl{index}", "Program Lead")
        baseline = self._page_queries()

        for index in range(3, 18):
            _user(f"pl{index}", "Program Lead")
        grown = self._page_queries()

        self.assertEqual(
            baseline,
            grown,
            f"/todos cost {baseline} queries for a Country Director with 3 "
            f"Programme Leads and {grown} with 18. Something on this page is "
            "resolving Programme Leads one at a time again — see "
            "CDAnalyticsService._pl_cceos_batch.",
        )

    def test_calling_the_service_directly_stays_within_its_own_ceiling(self):
        """The no-request path is looser, but still bounded.

        It pays a per-user re-read the request cycle memoises away (see the
        module docstring), so it cannot hold the flat shape above. It can
        still be held to a ceiling, which is what stops an unbounded N+1 from
        hiding in the gap between the two paths.
        """
        for index in range(3):
            _user(f"pl{index}", "Program Lead")
        count = self._todo_queries(self.cd)
        self.assertLessEqual(
            count,
            self.DIRECT_CEILING,
            f"get_todos() cost {count} queries for a Country Director with 3 "
            f"Programme Leads, over a ceiling of {self.DIRECT_CEILING}.",
        )
