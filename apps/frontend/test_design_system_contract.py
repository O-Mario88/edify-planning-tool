from pathlib import Path
import subprocess
import sys

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


class DesignSystemContractTest(SimpleTestCase):
    """Guard the shared contracts that prevent primary-style drift.

    These checks are intentionally source-level: the same tokens and bridge
    stylesheet are used by every Django route and HTMX fragment, so a browser
    snapshot of one page would not catch a later regression in the foundation.
    """

    def test_reference_blue_is_the_single_canonical_primary_token(self):
        tokens = (ROOT / "static/css/design-system.css").read_text()

        self.assertIn("--brand-primary: #0d5b9e;", tokens)
        self.assertIn("--brand-primary-hover: #0a4d86;", tokens)
        self.assertIn("--brand-primary-active: #083f70;", tokens)
        self.assertIn("--brand-primary-soft: #e4f2fb;", tokens)
        self.assertIn("--brand-primary-border: #8ac6ea;", tokens)
        self.assertIn("--edify-brand-primary: var(--brand-primary);", tokens)
        self.assertIn(":root.light {", tokens)
        self.assertIn(":root.theme-blue {", tokens)
        self.assertIn(":root.theme-dark {", tokens)

    def test_base_loads_the_final_consistency_layer_after_page_styles(self):
        base = (ROOT / "templates/base.html").read_text()

        self.assertIn("{% block feature_css %}{% endblock %}", base)
        self.assertIn("css/consistency.css", base)
        self.assertGreater(
            base.index("css/consistency.css"), base.index("css/platform.css")
        )
        self.assertGreater(
            base.index("css/consistency.css"),
            base.index("{% block feature_css %}{% endblock %}"),
        )

    def test_consistency_layer_owns_legacy_primary_utilities_and_dark_headers(self):
        bridge = (ROOT / "static/css/consistency.css").read_text()

        self.assertIn('[class~="bg-slate-900"]', bridge)
        self.assertIn("background-color: var(--brand-primary) !important;", bridge)
        self.assertIn(".edify-selected-surface", bridge)
        self.assertIn("accent-color: var(--brand-primary);", bridge)
        self.assertIn(".btn-premium-primary", bridge)

    def test_light_mode_button_contract_has_only_primary_secondary_and_disabled_states(
        self,
    ):
        tokens = (ROOT / "static/css/design-system.css").read_text()
        platform = (ROOT / "static/css/platform.css").read_text()
        bridge = (ROOT / "static/css/consistency.css").read_text()

        self.assertIn("--edify-button-primary-treatment: none;", tokens)
        self.assertIn("--edify-button-secondary-treatment: none;", tokens)
        self.assertIn("--edify-action-button-block-size: 2.75rem;", platform)
        self.assertIn("--edify-action-button-radius: 1rem;", platform)
        self.assertIn(
            "border: 1px solid var(--brand-primary-border) !important;", bridge
        )
        self.assertIn("background: var(--edify-surface-muted) !important;", bridge)
        self.assertIn(".btn-secondary", bridge)
        self.assertIn("Disabled must win over the primary/secondary aliases", bridge)

    def test_legacy_button_families_and_calendar_controls_use_the_shared_contract(self):
        """Every legacy action family must route through primary or secondary."""

        bridge = (ROOT / "static/css/consistency.css").read_text()

        for selector in (
            ".help-search-button",
            ".tile-filter-btn-primary",
            ".tile-filter-btn-secondary",
            ".premium-button-ghost",
            ".drawer-close-btn",
            ".forgot-button",
            "border-radius: var(--edify-action-button-radius) !important;",
            'input[type="file"]::file-selector-button',
            ".fc .fc-button-primary",
            '[class~="bg-slate-800"]',
            '[class*="border-slate-"][class*="rounded"]',
        ):
            self.assertIn(selector, bridge)

        self.assertIn(
            "Default view/navigation\n * controls are secondary; the selected calendar view is the one blue primary",
            bridge,
        )
        self.assertIn(".fc-button-primary:not(:disabled).fc-button-active", bridge)

    def test_active_sidebar_state_consumes_the_canonical_primary(self):
        sidebar = (ROOT / "static/css/components/sidebar.css").read_text()

        self.assertIn("background-color: var(--brand-primary) !important;", sidebar)
        self.assertIn("border: 1px solid var(--brand-primary-border);", sidebar)
        self.assertIn("background: var(--brand-primary-soft);", sidebar)

    def test_primary_chart_series_and_primary_kpi_icon_use_brand_tokens(self):
        tokens = (ROOT / "static/css/design-system.css").read_text()
        components = (ROOT / "static/css/components.css").read_text()

        self.assertIn("--edify-chart-blue: var(--brand-primary);", tokens)
        self.assertIn("--edify-chart-blue-soft: var(--brand-primary-soft);", tokens)
        self.assertIn(".kpi-strip__icon-container--primary {", components)
        self.assertIn("color: var(--brand-primary);", components)

    def test_kpi_strip_is_a_canvas_grid_not_a_parent_card(self):
        """KPI tiles keep their own cards; the strip itself stays transparent."""

        components = (ROOT / "static/css/components.css").read_text()
        legacy_css = (ROOT / "static/css/custom.css").read_text()

        self.assertIn(".kpi-strip {", components)
        self.assertIn("background: transparent;", components)
        self.assertIn(".kpi-strip__item {", components)
        self.assertNotIn(".dark .kpi-strip", legacy_css)
        self.assertNotIn(".glass .kpi-strip", legacy_css)

    def test_popup_drawers_use_the_centered_dialog_contract(self):
        """Actions must never fall back to a full-height right-side drawer."""

        base_drawer = (
            ROOT / "templates/components/drawers/base_drawer.html"
        ).read_text()
        drawer_css = (ROOT / "static/css/drawers.css").read_text()

        self.assertIn("type: 'center'", base_drawer)
        self.assertIn(".edify-popup-dialog {", drawer_css)
        self.assertIn("place-items: center;", drawer_css)
        self.assertIn(".edify-popup-dialog__surface {", drawer_css)
        self.assertIn("border-radius: var(--edify-radius-xl) !important;", drawer_css)

        for source in (
            "templates/partials/core_schools/schedule_visit_drawer.html",
            "templates/partials/core_schools/schedule_training_drawer.html",
            "templates/partials/core_schools/core_assessment_drawer.html",
            "templates/partials/core_schools/strategy_playbook_drawer.html",
            "templates/partials/core_schools/champion_review_drawer.html",
        ):
            popup = (ROOT / source).read_text()
            self.assertIn("edify-popup-dialog", popup, source)
            self.assertIn("edify-popup-dialog__surface", popup, source)
            self.assertNotIn("translate-x-full", popup, source)

    def test_tailwind_aliases_resolve_to_the_semantic_token_layer(self):
        source = (ROOT / "assets/css/tailwind.source.css").read_text()

        for declaration in (
            "--color-edify-primary: var(--brand-primary);",
            "--color-edify-dark: var(--brand-primary-hover);",
            "--color-edify-soft: var(--brand-primary-soft);",
            "--color-edify-border: var(--brand-primary-border);",
            "--color-edify-text: var(--edify-text);",
            "--color-page: var(--edify-bg);",
        ):
            self.assertIn(declaration, source)

    def test_help_center_uses_the_shared_primary_and_radius_tokens(self):
        help_css = (ROOT / "static/css/help-center.css").read_text()

        self.assertIn("--topic: var(--brand-primary);", help_css)
        self.assertIn("background: var(--brand-primary);", help_css)
        self.assertIn("background: var(--brand-primary-hover);", help_css)
        self.assertIn("border-radius: var(--radius-surface);", help_css)
        self.assertIn("border-radius: var(--radius-control);", help_css)
        self.assertNotIn("#277eca", help_css)

    def test_budget_workspaces_use_the_shared_selected_surface(self):
        monthly_request = (
            ROOT / "templates/partials/finance/monthly_request/root.html"
        ).read_text()
        monthly_budget = (ROOT / "templates/pages/budgets/monthly.html").read_text()

        self.assertIn("edify-selected-surface", monthly_request)
        self.assertNotIn("border-blue-500 bg-blue-600", monthly_request)
        self.assertIn("edify-selected-surface", monthly_budget)
        self.assertNotIn("border-blue-500 bg-blue-600", monthly_budget)

    def test_reschedule_actions_follow_one_reliable_drawer_contract(self):
        """Every entry point opens the shared reschedule drawer consistently."""

        sources = (
            "templates/partials/my_plan/activity_row.html",
            "templates/partials/my_plan/activity_table.html",
            "templates/partials/my_plan/activity_detail_drawer.html",
            "templates/pages/my_plan/detail.html",
        )

        for source in sources:
            template = (ROOT / source).read_text()
            self.assertIn("data-reschedule-trigger", template, source)
            self.assertIn('hx-target="#drawer-container"', template, source)
            self.assertIn('hx-swap="innerHTML"', template, source)
            self.assertIn('hx-trigger="click consume"', template, source)

        for source in sources:
            template = (ROOT / source).read_text()
            reschedule_button = template.split("data-reschedule-trigger", 1)[1].split(
                "</button>", 1
            )[0]
            self.assertNotIn("text-amber-600", reschedule_button, source)

        planning_service = (ROOT / "apps/planning/planning_service.py").read_text()
        self.assertIn("ActivityStatus.RESCHEDULED", planning_service)
        self.assertIn('.order_by("-planned_date", "-created_at")', planning_service)

        reschedule_view = (ROOT / "apps/frontend/views/my_plan_views.py").read_text()
        schedule_drawer = (
            ROOT / "templates/partials/planning/schedule_drawer.html"
        ).read_text()
        self.assertIn('"reschedule_mode": True', reschedule_view)
        self.assertIn('"partials/planning/schedule_drawer.html"', reschedule_view)
        self.assertIn("{% if reschedule_mode %}", schedule_drawer)
        self.assertIn("Save new date", schedule_drawer)

    def test_core_school_list_reuses_the_shared_record_layout(self):
        matrix = (
            ROOT / "templates/partials/core_schools/matrix_table.html"
        ).read_text()
        row = (ROOT / "templates/partials/core_schools/school_row.html").read_text()

        self.assertIn('"partials/core_schools/school_row.html"', matrix)
        self.assertIn("school-record-list", matrix)
        self.assertIn("school-record-row", row)
        self.assertIn(
            "{{ school.scheduled_visit_count }}/{{ school.visits_target }}", row
        )
        self.assertIn(
            "{{ school.scheduled_training_count }}/{{ school.trainings_target }}", row
        )
        self.assertNotIn("4 visits and 4 trainings", row)
        self.assertIn("<span>Schedule</span>", row)
        self.assertIn("<span>Assign</span>", row)
        self.assertNotIn("Schedule Now", row)

    def test_frontend_source_uses_semantic_primary_utilities(self):
        """A new page cannot quietly reintroduce a framework-blue primary."""

        for script in (
            "normalize_legacy_primary_utilities.py",
            "normalize_static_token_styles.py",
            "normalize_page_titles.py",
        ):
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / script), "--check"],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                completed.returncode,
                0,
                f"{script}:\n{completed.stdout}{completed.stderr}",
            )

    def test_partner_workspace_uses_shared_theme_surfaces_and_actions(self):
        """Partner Activities must inherit the same language in both themes."""

        partner_css = (ROOT / "static/css/custom.css").read_text()
        partner_template = (ROOT / "templates/pages/partners/index.html").read_text()
        alignment = partner_css.split(
            "Partner workspace design-system alignment", 1
        )[1]

        for token in (
            "var(--edify-card-surface)",
            "var(--edify-card-border)",
            "var(--edify-card-shadow)",
            "var(--edify-action-button-block-size)",
            "var(--edify-purple-light)",
            "var(--edify-success-light)",
            "var(--edify-warning-light)",
            "var(--edify-danger-light)",
            "var(--edify-focus-ring)",
        ):
            self.assertIn(token, alignment)

        self.assertIn("btn-premium-primary partner-workspace__export-button", partner_template)
        self.assertIn("btn-premium-secondary partner-workspace__filter-button", partner_template)

    def test_filter_wrappers_are_canvas_level_in_every_theme(self):
        """Filters stay out of cards; individual fields provide the affordance."""

        bridge = (ROOT / "static/css/consistency.css").read_text()
        contract = bridge.split("Filter bars live on the page canvas", 1)[1]

        for selector in (
            ".platform-filter-bar",
            ".sp-filter-panel",
            ".spp-filter-panel",
            ".spa-filter-panel",
            ".tt-filter-panel",
            "#filters-form",
            "#analytics-filters-form",
            "#pl-analytics-filters",
            "#cd-analytics-filters",
            "#cb-filters",
            ".school-filters-form",
            ".school-filter-canvas",
        ):
            self.assertIn(selector, contract)

        for declaration in (
            "background: transparent !important;",
            "box-shadow: none !important;",
            "background: var(--edify-surface-raised) !important;",
            "min-block-size: var(--edify-action-button-block-size) !important;",
            "box-shadow: var(--edify-focus-ring) !important;",
        ):
            self.assertIn(declaration, contract)

    def test_special_project_workspaces_use_the_final_shared_contract(self):
        """Feature CSS can arrange data, but cannot introduce a new UI kit."""

        bridge = (ROOT / "static/css/consistency.css").read_text()
        contract = bridge.split("Special Projects uses the shared cockpit anatomy", 1)[1]

        for selector in (
            ".sp-plan, .spp, .spa",
            ".sp-card, .spp-card, .spa-card",
            ".sp-button, .spp-button, .spa-button",
            ".sp-search input, .spp-search input, .spa-search input",
        ):
            self.assertIn(selector, contract)

        for token in (
            "var(--edify-card-surface)",
            "var(--edify-card-border)",
            "var(--edify-action-button-block-size)",
            "var(--edify-action-button-radius)",
            "var(--edify-font-label)",
            "var(--edify-focus-ring)",
        ):
            self.assertIn(token, contract)

        for source in (
            "templates/pages/calendar/index.html",
            "templates/pages/projects/analytics.html",
            "templates/pages/projects/planning.html",
            "templates/pages/projects/my_plan.html",
        ):
            page = (ROOT / source).read_text()
            self.assertIn("{% block feature_css %}", page, source)
            self.assertNotIn('<link rel="stylesheet"', page.split("{% block shell_content %}", 1)[1], source)

    def test_authenticated_pages_use_the_shells_single_main_region(self):
        """Nested page mains cause competing landmarks and inconsistent spacing."""

        pages = ROOT / "templates/pages"
        standalone = {pages / "auth/launch.html"}

        for page in pages.rglob("*.html"):
            if page in standalone:
                continue
            self.assertNotIn("<main", page.read_text(), page)
