import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


ROOT = Path(settings.BASE_DIR)


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _production_frontend_files():
    patterns = (
        "templates/**/*.html",
        "static/css/**/*.css",
        "static/js/**/*.js",
        "assets/css/**/*.css",
    )
    for pattern in patterns:
        yield from ROOT.glob(pattern)


def _contrast_ratio(foreground, background):
    def luminance(hex_color):
        values = [int(hex_color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in values
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    lighter, darker = sorted(
        (luminance(foreground), luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


class PlatformDesignSystemQualityTest(SimpleTestCase):
    def test_inter_is_the_global_and_compiled_ui_font(self):
        base = _read("templates/base.html")
        tokens = _read("static/css/design-system.css")
        compiled = _read("static/css/main.css")

        self.assertIn("family=Inter", base)
        self.assertIn("--edify-font-sans: 'Inter'", tokens)
        self.assertRegex(compiled, r"--font-sans:\s*Inter,")

    def test_no_unapproved_font_family_is_shipped(self):
        forbidden = re.compile(
            r"\b(Outfit|Georgia|Times New Roman|Roboto|Open Sans|Poppins|Montserrat|Arial)\b",
            re.IGNORECASE,
        )
        violations = []
        for path in _production_frontend_files():
            match = forbidden.search(path.read_text(encoding="utf-8"))
            if match:
                violations.append(f"{path.relative_to(ROOT)}: {match.group(0)}")
        self.assertEqual(
            violations, [], "Unapproved UI fonts: " + ", ".join(violations)
        )

    def test_charts_explicitly_use_inter(self):
        charts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
            if "fontFamily" in path.read_text(encoding="utf-8")
        )
        self.assertNotIn("fontFamily: 'Outfit", charts)
        self.assertNotIn('fontFamily: "Outfit', charts)
        self.assertIn("fontFamily: 'Inter", charts)

    def test_shared_cards_stretch_without_an_arbitrary_fixed_height(self):
        platform = _read("static/css/platform.css")
        components = _read("static/css/edify-components.css")
        self.assertIn("align-self: stretch", platform)
        self.assertIn("block-size: 100%", platform)
        self.assertNotIn("height: 108px", components)
        self.assertIn("height: 100%", components)

    def test_shared_responsive_contract_covers_mobile_and_tablet(self):
        platform = _read("static/css/platform.css")
        self.assertIn("@media (max-width: 63.9375rem)", platform)
        self.assertIn("@media (max-width: 47.5rem)", platform)
        self.assertIn("@media (max-width: 30rem)", platform)
        self.assertIn("platform-table-cards", platform)
        self.assertIn("min-block-size: 2.75rem", platform)

    def test_every_authenticated_page_inherits_compact_cockpit_density(self):
        shell = _read("templates/layouts/shell.html")
        platform = _read("static/css/platform.css")
        tokens = _read("static/css/design-system.css")
        self.assertIn('class="edify-workspace', shell)
        self.assertIn('data-density="compact"', shell)
        self.assertIn('data-analytics-engine="edify-python-1.0"', shell)
        self.assertIn("main.edify-workspace", platform)
        self.assertIn("--radius-surface: 13px", tokens)
        self.assertIn("platform-deferred", platform)
        self.assertIn("contain-intrinsic-size", platform)

    def test_dark_workspace_has_accessible_depth_and_primary_actions(self):
        tokens = _read("static/css/design-system.css")
        platform = _read("static/css/platform.css")

        for declaration in (
            "--edify-bg: #000000",
            "--edify-surface: #0d0d0f",
            "--edify-surface-raised: #151518",
            "--edify-surface-hover: #1c1c20",
            "--edify-text: #f5f7fa",
            "--edify-text-muted: #d6dde7",
            "--edify-text-subtle: #aeb9c7",
            "--edify-accent: #2563eb",
            "--edify-warning: #fb923c",
        ):
            self.assertIn(declaration, tokens)

        self.assertGreaterEqual(_contrast_ratio("#f5f7fa", "#0d0d0f"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#d6dde7", "#0d0d0f"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#aeb9c7", "#0d0d0f"), 4.5)
        self.assertGreaterEqual(_contrast_ratio("#ffffff", "#2563eb"), 4.5)
        self.assertIn("DARK WORKSPACE — CINEMATIC DEPTH, OPERATIONAL CLARITY", platform)
        self.assertIn(
            "background-image: var(--edify-button-primary-treatment)", platform
        )

    def test_program_lead_funding_card_is_intrinsically_responsive(self):
        dashboard = _read("templates/partials/dashboards/pl/body.html")
        funding = _read("templates/partials/dashboards/pl/funding_execution.html")
        pages = _read("static/css/pages.css")

        self.assertIn('class="pl-intelligence-grid"', dashboard)
        self.assertNotIn(
            "lg:col-span-5", dashboard[dashboard.index("SSA Intelligence") :]
        )
        self.assertIn("pl-funding-summary", funding)
        self.assertLess(
            funding.index("pl-funding-donut"), funding.index("pl-funding-statuses")
        )
        self.assertIn("container: pl-dashboard / inline-size", pages)
        self.assertIn(
            "grid-template-columns: minmax(0, 1fr) minmax(0, 1.18fr) minmax(10.5rem, 0.48fr)",
            pages,
        )
        self.assertIn("overflow-x: clip", pages)

    def test_operational_analytics_domains_use_the_shared_python_engine(self):
        domain_files = (
            "apps/analytics/ssa_performance_service.py",
            "apps/analytics/decision_engine.py",
            "apps/analytics/impact_engine.py",
            "apps/projects/planning_service.py",
            "apps/projects/my_plan_service.py",
            "apps/projects/impact_service.py",
            "apps/frontend/views/finance_operating_views.py",
            "apps/budget_intelligence/services.py",
        )
        for path in domain_files:
            self.assertIn("platform_engine", _read(path), path)

    def test_every_declared_tab_has_aria_state_and_a_real_panel(self):
        templates = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (ROOT / "templates").rglob("*.html")
        )
        tabs = re.findall(r"<(?:a|button)\b[^>]*\brole=\"tab\"[^>]*>", templates)
        self.assertGreater(len(tabs), 0)
        for tab in tabs:
            self.assertIn("aria-selected=", tab)
            controls = re.search(r'aria-controls="([^"]+)"', tab)
            self.assertIsNotNone(controls, tab)
            self.assertIn(f'id="{controls.group(1)}"', templates)
        self.assertIn('role="tabpanel"', templates)

    def test_tabs_have_shared_keyboard_navigation(self):
        script = _read("static/js/alpine-components.js")
        for key in ("ArrowRight", "ArrowLeft", "ArrowDown", "ArrowUp", "Home", "End"):
            self.assertIn(key, script)
        self.assertIn("htmx:afterSettle", script)

    def test_filter_and_tab_controls_keep_one_canonical_state(self):
        school_tabs = _read("templates/partials/schools/tabs.html")
        school_page = _read("templates/pages/schools/index.html")
        planning_page = _read("templates/pages/planning/index.html")
        planning_tabs = _read("templates/partials/planning/tabs.html")
        my_plan_tabs = _read("templates/partials/my_plan/period_tabs.html")
        messages = _read("templates/pages/messages/index.html")
        analytics = _read("templates/partials/analytics/filters.html")

        self.assertNotRegex(school_tabs, r'hx-get="/schools\?tab=')
        self.assertIn("filters-tab-input", school_tabs)
        self.assertIn('name="per_page"', school_page)
        self.assertIn('hx-push-url="true"', school_page)
        self.assertIn('hx-swap="outerHTML"', planning_page)
        self.assertIn('name="q"', planning_page)
        self.assertIn('role="tablist"', planning_tabs)
        self.assertNotRegex(my_plan_tabs, r'hx-get="/my-plan\?period=')
        self.assertIn("messages-active-tab", messages)
        self.assertNotRegex(messages, r'hx-get="/messages\?tab=')
        self.assertNotIn('hx-get="/analytics?fy=2026&quarter=Q2"', analytics)

    def test_finance_dashboard_does_not_ship_placeholder_tabs_or_actions(self):
        template = _read("templates/pages/accounts/dashboard.html")
        active_template = re.sub(
            r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}",
            "",
            template,
            flags=re.DOTALL,
        )
        self.assertNotIn("activeTab", active_template)
        self.assertNotIn("Documents &amp; Proofs (0)", active_template)
        self.assertNotIn("Disburse Funds\n</button>", active_template)
        self.assertIn("Open Canonical Disbursement Queue", active_template)
        self.assertIn("filteredFunds()", active_template)
