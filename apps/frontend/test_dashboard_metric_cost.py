"""The dashboard must not build figures no branch will render.

`dashboard_view` computed `DashboardMetricsService.get_dashboard_metrics(user)`
at the top of the view, but every role except the generic fall-through returns
from its own branch with its own numbers, and three roles redirect away
entirely. The build cost 54-62 queries and 73-110 ms, and for those roles all
of it was discarded -- the Accountant's redirect alone ran 70 queries to
produce a 302.

These tests pin the ordering rather than a timing: a wall-clock threshold is
flaky on a loaded machine, but "was this service called at all" is exact.
"""

from collections import Counter
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext


def _user(email, role, name="Test Person"):
    return get_user_model().objects.create_user(
        email=email,
        name=name,
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )


class DashboardMetricCostTest(TestCase):
    """`get_dashboard_metrics` runs only for the role that renders it."""

    TARGET = (
        "apps.frontend.views.dashboard_views."
        "DashboardMetricsService.get_dashboard_metrics"
    )

    def _get_dashboard_as(self, role, email):
        user = _user(email, role)
        self.client.force_login(user)
        with patch(self.TARGET) as build_metrics:
            response = self.client.get("/dashboard")
        return response, build_metrics

    def test_a_redirecting_accountant_does_not_build_dashboard_metrics(self):
        response, build_metrics = self._get_dashboard_as(
            "Accountant", "acct-cost@edify.test"
        )
        self.assertEqual(response.status_code, 302)
        build_metrics.assert_not_called()

    def test_a_redirecting_ia_does_not_build_dashboard_metrics(self):
        response, build_metrics = self._get_dashboard_as(
            "ImpactAssessment", "ia-cost@edify.test"
        )
        self.assertEqual(response.status_code, 302)
        build_metrics.assert_not_called()

    def test_a_redirecting_partner_does_not_build_dashboard_metrics(self):
        response, build_metrics = self._get_dashboard_as(
            "PartnerFieldOfficer", "partner-cost@edify.test"
        )
        self.assertEqual(response.status_code, 302)
        build_metrics.assert_not_called()

    def test_the_cceo_branch_does_not_build_metrics_it_never_renders(self):
        response, build_metrics = self._get_dashboard_as("CCEO", "cceo-cost@edify.test")
        self.assertEqual(response.status_code, 200)
        build_metrics.assert_not_called()

    def test_the_country_director_branch_does_not_build_them_either(self):
        response, build_metrics = self._get_dashboard_as(
            "CountryDirector", "cd-cost@edify.test"
        )
        self.assertEqual(response.status_code, 200)
        build_metrics.assert_not_called()

    def test_the_program_lead_branch_does_not_build_them_either(self):
        response, build_metrics = self._get_dashboard_as(
            "Program Lead", "pl-cost@edify.test"
        )
        self.assertEqual(response.status_code, 200)
        build_metrics.assert_not_called()


class DashboardQueryBudgetTest(TestCase):
    """§51: a page needs a query budget, or N+1s creep back in unnoticed.

    The Admin dashboard ran 76 queries, 37 of them `COUNT(*)` on `activity`.
    Two loops were responsible: five weeks of planning progress at two counts
    each, and five clusters at two counts plus a school-id read and an SSA
    average each. Both are now single grouped queries, taking the page to 54.

    The ceiling is set a little above the measured figure so ordinary changes
    do not trip it, and far enough below the old number that the loops cannot
    return.
    """

    BUDGET = 62

    def test_the_admin_dashboard_stays_within_its_query_budget(self):
        user = _user("budget-admin@edify.test", "Admin")
        self.client.force_login(user)
        self.client.get("/dashboard")  # warm per-process caches

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(
            len(queries.captured_queries),
            self.BUDGET,
            f"the dashboard now runs {len(queries.captured_queries)} queries; "
            f"look for a count inside a loop",
        )

    def test_no_query_shape_repeats_enough_to_be_a_loop(self):
        """A count issued once per row is the shape this catches.

        Compared on a long prefix, not a short one: at 70 characters every
        `SELECT COUNT(*) FROM "activity" WHERE …` collapses into a single
        "shape" regardless of its filter, so thirteen genuinely different
        counts looked like a thirteen-iteration loop. The filter is the part
        that distinguishes them, so the comparison has to reach it.
        """
        user = _user("budget-admin-2@edify.test", "Admin")
        self.client.force_login(user)
        self.client.get("/dashboard")

        with CaptureQueriesContext(connection) as queries:
            self.client.get("/dashboard")

        shapes = Counter(q["sql"][:400] for q in queries.captured_queries)
        worst_shape, worst_count = shapes.most_common(1)[0]
        self.assertLessEqual(
            worst_count,
            6,
            f"{worst_count} identical queries suggest a loop:\n{worst_shape}",
        )


class RedirectRolesSkipPageDataTest(TestCase):
    """A redirect needs no alerts, no agenda and no avatar."""

    def test_the_accountant_redirect_costs_almost_nothing(self):
        """Session, user, and the policy gate's one EXISTS.

        The third query is `PolicyGateMiddleware` asking whether any live
        policy withholds the application. It runs on every authenticated
        request because that is what makes it a gate rather than a page --
        and it is one EXISTS, memoised per request, which short-circuits
        before any per-user read. The budget is 3 rather than 2 for exactly
        that reason; a fourth query here would mean the short-circuit broke.
        """
        user = _user("acct-queries@edify.test", "Accountant")
        self.client.force_login(user)
        self.client.get("/dashboard")  # warm any per-process caches

        with self.assertNumQueries(3):
            response = self.client.get("/dashboard")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/accounts")
