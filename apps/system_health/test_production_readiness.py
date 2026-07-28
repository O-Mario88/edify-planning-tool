"""The hard-zero deployment gates, and the scanners that measure them.

Two things are tested here, and the distinction matters. The scanners are
tested against known-good and known-bad input, because a scanner that cannot
fail is not evidence. The gates themselves are asserted at their current
measured value, so a regression that reintroduces a defect fails the build
rather than quietly raising the number in a report nobody re-reads.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.system_health.production_readiness import (
    GATES,
    run_all,
    scan_dead_controls,
    scan_javascript_business_maths,
    scan_mock_runtime_data,
    scan_raw_workflow_mutations,
    scan_unguarded_page_routes,
)


class GateBaselineTests(SimpleTestCase):
    """Measured on this commit. Each number is a ceiling, never a target."""

    #: Gates that are clean and must stay clean.
    CLEAN_GATES = ("mock_runtime_data", "dead_control")

    #: Gates with known open findings, recorded in
    #: docs/production-readiness-ledger.md. The number may fall; it must never
    #: rise without the ledger entry that explains why.
    KNOWN_OPEN = {
        # Still 3: the canonical server-side weighted mean now exists and is
        # tested (apps/analytics/test_weighted_ssa_mean.py), but the regional
        # map template has not yet been switched over to it. Retiring the
        # JavaScript needs the boundary-to-district mapping to move server-side
        # too, which is a separate change.
        "javascript_business_maths": 3,
        "unguarded_page_route": 6,
        # Was 30. SSA verification, the accountant's return and the
        # accountability roll-up moved into their canonical services; the rest
        # are triaged in the ledger by whether a service owns that transition.
        "raw_workflow_mutation": 25,
    }

    def test_the_clean_gates_are_still_clean(self):
        results = run_all()
        for gate in self.CLEAN_GATES:
            with self.subTest(gate):
                self.assertEqual(
                    results[gate]["count"],
                    0,
                    f"{gate} regressed: {results[gate]['findings'][:3]}",
                )

    def test_no_known_gate_has_grown(self):
        results = run_all()
        for gate, ceiling in self.KNOWN_OPEN.items():
            with self.subTest(gate):
                self.assertLessEqual(
                    results[gate]["count"],
                    ceiling,
                    f"{gate} grew past its recorded {ceiling}. Fix it, or add a "
                    "ledger entry and move the ceiling deliberately.",
                )

    def test_every_gate_runs_without_erroring(self):
        for gate, data in run_all().items():
            with self.subTest(gate):
                self.assertNotIn("error", data, f"{gate} scanner raised")
                self.assertGreaterEqual(data["count"], 0)

    def test_every_finding_points_at_a_line(self):
        """A finding nobody can walk back to source is not evidence."""
        for gate, data in run_all().items():
            for finding in data["findings"][:5]:
                with self.subTest(gate=gate, path=finding["path"]):
                    self.assertTrue(finding["path"])
                    self.assertTrue(finding["evidence"])


class ScannerBehaviourTests(SimpleTestCase):
    """A scanner that cannot fail is not measuring anything."""

    def test_the_mock_scanner_does_not_count_itself(self):
        """It holds every pattern it looks for, so it matched itself twice."""
        paths = {f.path for f in scan_mock_runtime_data()}
        self.assertNotIn(
            "apps/system_health/production_readiness.py",
            paths,
        )

    def test_the_javascript_scanner_ignores_chart_geometry(self):
        """Pixel maths is legitimate; business maths is not."""
        findings = scan_javascript_business_maths()
        for finding in findings:
            with self.subTest(
                finding["path"] if isinstance(finding, dict) else finding.path
            ):
                self.assertNotIn("const x =", finding.evidence)

    def test_the_javascript_scanner_ignores_reads_and_initialisation(self):
        """`this.balance = 0` and `x = data.total || 0` compute nothing."""
        from apps.system_health.production_readiness import _JS_ASSIGNMENT_ONLY

        for line in (
            "this.balanceRemaining = 0;",
            "this.balanceRemaining = data.balance_remaining || 0;",
            "const total = payload.total;",
        ):
            with self.subTest(line):
                self.assertTrue(_JS_ASSIGNMENT_ONLY.search(line))

    def test_the_javascript_scanner_still_catches_a_real_computation(self):
        from apps.system_health.production_readiness import (
            _JS_ASSIGNMENT_ONLY,
            _JS_BUSINESS_MATH,
        )

        line = "sum = measured.reduce((s, m) => s + m.amount * m.n, 0) / weight;"
        self.assertFalse(_JS_ASSIGNMENT_ONLY.search(line))
        self.assertTrue(_JS_BUSINESS_MATH.search(line))

    def test_the_dead_control_scanner_spares_handler_backed_anchors(self):
        """`href="#"` beside an Alpine handler is an idiom, not a defect."""
        from apps.system_health.production_readiness import _DEAD_HREF, _HANDLER

        live = '<a href="#" @click="open = true">Filters</a>'
        dead = '<a href="#">Filters</a>'
        self.assertTrue(_DEAD_HREF.search(live) and _HANDLER.search(live))
        self.assertTrue(_DEAD_HREF.search(dead))
        self.assertFalse(_HANDLER.search(dead))

    def test_the_route_scanner_spares_mid_authentication_surfaces(self):
        """A user part-way through signing in has no role to check against."""
        from apps.system_health.production_readiness import _EXEMPT_VIEW_NAMES

        for name in ("login_view", "mfa_verify_view", "force_change_password_view"):
            self.assertIn(name, _EXEMPT_VIEW_NAMES)

    def test_the_workflow_scanner_finds_state_written_from_a_view(self):
        """The scanner must still be able to see this class of defect.

        It originally pointed at ssa_views.py, which set SSA verification
        status inline. That transition now lives in apps.ssa.services, so the
        assertion moved to a file that still has one -- and this test will move
        again as each is fixed, which is the point.
        """
        findings = scan_raw_workflow_mutations()
        paths = {f.path for f in findings}
        self.assertIn("apps/frontend/views/core_schools_views.py", paths)
        # The one that is fixed must stay fixed.
        self.assertNotIn("apps/frontend/views/ssa_views.py", paths)

    def test_every_declared_gate_has_a_scanner(self):
        self.assertEqual(
            set(GATES),
            {
                "mock_runtime_data",
                "javascript_business_maths",
                "dead_control",
                "unguarded_page_route",
                "raw_workflow_mutation",
            },
        )
        for scanner in (
            scan_mock_runtime_data,
            scan_javascript_business_maths,
            scan_dead_controls,
            scan_unguarded_page_routes,
            scan_raw_workflow_mutations,
        ):
            self.assertTrue(callable(scanner))
