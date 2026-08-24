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
        # One deliberate finding, recorded 2026-08-24 in the ledger: the
        # distribution drawers' live remaining-balance preview
        # (static/js/target-distribution.js). The envelope UX the owner asked
        # for — type a number, watch what is left fall to zero — requires the
        # subtraction to happen on the keystroke, and a round-trip per
        # keystroke is the stale-panel design it replaced. The figure is a
        # preview only: reconcile_team_level / reconcile_employee_level
        # recompute server-side on every save and approve, and refuse any
        # balance that does not hold, so nothing downstream ever consumes the
        # client's arithmetic. Before this entry the gate stood at zero (the
        # map's cohort totals and SSA mean moved server-side); it must not
        # grow past this one named exception.
        "javascript_business_maths": 1,
        # Closed. The six performance-conversation endpoints now declare
        # their audience at the route as well as enforcing it in
        # apps.hr.performance_engine. The engine still owns the real rules;
        # the declaration is what makes a page-permission audit able to see
        # them, which is what §9 is about.
        "unguarded_page_route": 0,
        # Closed. Views now delegate every workflow transition, including
        # upload bookkeeping and human triage decisions, to a domain service.
        "raw_workflow_mutation": 0,
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

    def test_system_health_uses_the_canonical_permission_gate(self):
        """The operator page and the release scanner must answer identically."""
        from apps.system_health.services import _permission_guards_audit

        scanner_findings = scan_unguarded_page_routes()
        health = _permission_guards_audit()

        self.assertEqual(health["unguardedCount"], len(scanner_findings))
        self.assertEqual(health["clean"], not scanner_findings)
        self.assertEqual(
            {row["route"] for row in health["unguardedRoutes"]},
            {finding.evidence for finding in scanner_findings},
        )


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
        from apps.system_health.production_readiness import (
            _workflow_mutations_in_source,
        )

        findings = _workflow_mutations_in_source(
            "def post(request):\n    batch.status = 'imported'\n",
            "apps/example/views.py",
        )
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].evidence, "batch.status = …")
        self.assertEqual(scan_raw_workflow_mutations(), [])

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


class JavaScriptScannerAccuracyTests(SimpleTestCase):
    """The scanner must catch real client-side arithmetic and nothing else.

    Both directions matter. A scanner that misses a real computation gives
    false assurance; one that reports honest code as a defect teaches people to
    route around the gate, which is worse — it destroys the signal rather than
    weakening it.

    The allowances tested here were added after the scanner flagged
    `totals = JSON.parse(...)` and `type.total = totals[key] ?? 0`, neither of
    which computes anything.
    """

    def _findings(self, line: str):
        import re

        from apps.system_health.production_readiness import (
            _JS_ASSIGNMENT_ONLY,
            _JS_BUSINESS_MATH,
            _JS_DESERIALISE,
            _JS_REDUCE,
            _JS_VISUAL_NAMES,
        )

        if _JS_VISUAL_NAMES.search(line):
            return False
        if _JS_DESERIALISE.search(line):
            return False
        if _JS_ASSIGNMENT_ONLY.search(line):
            return False
        return bool(
            _JS_BUSINESS_MATH.search(line)
            or (_JS_REDUCE.search(line) and re.search(r"total|amount|sum", line, re.I))
        )

    def test_it_still_catches_real_client_side_arithmetic(self):
        for line in (
            "total = a + b;",
            "this.amount = price * quantity;",
            "const sum = rows.reduce((acc, r) => acc + r.total, 0);",
            "budgetRemaining = budget - spent;",
            "row.achievement = done / target * 100;",
            "this.balance = opening + credits - debits;",
        ):
            with self.subTest(line):
                self.assertTrue(self._findings(line), f"missed: {line}")

    def test_it_does_not_flag_reading_a_value_the_server_computed(self):
        for line in (
            "type.total = totals[type.key] ?? 0;",
            "type.total = totals[type.key] || 0;",
            "this.total = data.total || 0;",
            "totals = JSON.parse(document.getElementById('x').textContent);",
            "let totals = JSON.parse(",
            "this.balance = 0;",
            "const amount = row.amount;",
        ):
            with self.subTest(line):
                self.assertFalse(self._findings(line), f"false positive: {line}")

    def test_visual_arithmetic_is_still_excluded(self):
        for line in (
            "const x = left + step * index;",
            "point.height = value / 100 * boxHeight;",
        ):
            with self.subTest(line):
                self.assertFalse(self._findings(line))
