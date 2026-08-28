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

        self.assertIn("--brand-primary: #0e5da3;", tokens)
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

    def test_full_page_navigation_is_instant_across_the_platform(self):
        """Route changes must not cross-fade the outgoing and incoming pages.

        Cross-document View Transitions briefly expose the browser canvas
        between pages with different structures, which reads as a black close
        then reopen effect. Tabs and sidebar items are ordinary route links,
        so opting the root document into that transition affects the entire
        authenticated platform at once.
        """
        source = (ROOT / "static/css/custom.css").read_text()
        compiled = (ROOT / "static/css/main.css").read_text()
        base = (ROOT / "templates/base.html").read_text()

        for stylesheet in (source, compiled):
            self.assertNotIn("@view-transition", stylesheet)
            self.assertNotIn("::view-transition-old(root)", stylesheet)
            self.assertNotIn("::view-transition-new(root)", stylesheet)
        self.assertRegex(
            base,
            r"css/main\.css' %}\?v=\d{8}[a-z0-9]+",
            "The compiled stylesheet must keep a release-specific cache key.",
        )

    def test_workspace_route_links_prefetch_without_global_page_swaps(self):
        """Likely sibling views warm up natively, while navigation stays real.

        A global HTMX body swap would omit destination-specific head assets;
        prerendering would execute a second live page in the background. Native
        same-origin prefetch avoids both failure modes.
        """
        base = (ROOT / "templates/base.html").read_text()

        self.assertIn('type="speculationrules"', base)
        self.assertIn(".edify-section-nav__view-link[href]:not([aria-current])", base)
        self.assertIn(".edify-section-nav__link[href]:not([aria-current])", base)
        self.assertIn(".app-sidebar__item[href]:not([aria-current])", base)
        self.assertIn(".edify-bottom-nav__item[href]:not([aria-current])", base)
        self.assertIn('"eagerness": "moderate"', base)
        self.assertIn('"eagerness": "conservative"', base)
        self.assertNotIn('"eagerness": "eager"', base)
        self.assertNotIn('"prerender"', base)

    def test_consistency_layer_owns_legacy_primary_utilities_and_dark_headers(self):
        bridge = (ROOT / "static/css/consistency.css").read_text()

        self.assertIn('[class~="bg-slate-900"]', bridge)
        self.assertIn("background-color: var(--brand-primary) !important;", bridge)
        self.assertIn(".edify-selected-surface", bridge)
        self.assertIn("accent-color: var(--brand-primary);", bridge)
        self.assertIn(".btn-premium-primary", bridge)

    def test_profile_routes_share_one_label_value_typography_contract(self):
        tokens = (ROOT / "static/css/design-system.css").read_text()
        bridge = (ROOT / "static/css/consistency.css").read_text()

        self.assertIn("--edify-profile-value: var(--edify-accent-text);", tokens)
        self.assertIn("main .edify-profile-field__label", bridge)
        self.assertIn("main .edify-profile-field__value", bridge)
        self.assertIn("color: var(--edify-text) !important;", bridge)
        self.assertIn("color: var(--edify-profile-value) !important;", bridge)
        self.assertIn("font-family: var(--edify-font-sans) !important;", bridge)

        profile_templates = (
            "templates/pages/schools/detail.html",
            "templates/pages/clusters/detail.html",
            "templates/pages/districts/detail.html",
            "templates/pages/projects/detail.html",
            "templates/pages/partners/detail.html",
            "templates/pages/staff/detail.html",
            "templates/pages/profile/index.html",
            "templates/pages/admin/user_detail.html",
        )
        missing = [
            path
            for path in profile_templates
            if "edify-profile-page" not in (ROOT / path).read_text()
        ]
        self.assertEqual(missing, [], f"profile pages outside the contract: {missing}")

        school = (ROOT / "templates/pages/schools/detail.html").read_text()
        enrollment = school.split("Pupil Enrolment", 1)[1].split("</div>", 1)[0]
        self.assertIn("edify-profile-field__value", enrollment)
        self.assertNotIn("text-slate-800", enrollment)

    def test_light_mode_button_contract_has_only_primary_secondary_and_disabled_states(
        self,
    ):
        tokens = (ROOT / "static/css/design-system.css").read_text()
        platform = (ROOT / "static/css/platform.css").read_text()
        bridge = (ROOT / "static/css/consistency.css").read_text()

        self.assertIn("--edify-button-primary-treatment: none;", tokens)
        self.assertIn("--edify-button-secondary-treatment: none;", tokens)
        self.assertIn("--edify-action-button-block-size: 2.75rem;", platform)
        self.assertIn("--edify-action-button-radius: var(--radius-control);", platform)
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

    def test_kpi_strip_is_a_unified_executive_summary(self):
        """KPI strips follow the active theme and wrap on mobile, never scroll.

        Each metric reads as its own themed card (white in Light, dark in Dark,
        blue glass in Blue) via design tokens — no hardcoded navy panel — and
        narrow screens use a compact two-column summary instead of a carousel.
        """

        components = (ROOT / "static/css/components.css").read_text()
        template = (ROOT / "templates/components/kpi_strip.html").read_text()
        legacy_css = (ROOT / "static/css/custom.css").read_text()

        # The component and its grid/item anatomy still anchor the contract.
        self.assertIn(".kpi-strip {", components)
        self.assertIn(".kpi-strip__item {", components)
        self.assertIn('class="kpi-strip__grid" role="list"', template)
        self.assertIn('role="listitem"', template)

        # Items render as themed cards driven by design tokens, so the strip
        # follows the active workspace instead of a fixed navy panel.
        self.assertIn("background-color: var(--edify-surface)", components)
        self.assertIn("border: 1px solid var(--edify-border)", components)

        # The hardcoded navy palette is gone entirely.
        for navy_hex in ("#052d50", "#0a4169", "#07385f"):
            self.assertNotIn(navy_hex, components)
        self.assertNotIn("--edify-kpi-strip-background:", components)
        # No theme may force the strip onto the navy panel. (A scoped blue-theme
        # enhancement of the icon chips is fine; the combined navy override that
        # pinned both themes to --edify-kpi-strip-background must not return.)
        self.assertNotIn("background: var(--edify-kpi-strip-background)", components)

        # Mobile never scrolls a strip sideways: a compact 2x2 summary keeps
        # the operating queue in the first viewport and gives labels two lines.
        self.assertNotIn("scroll-snap-type: inline mandatory", components)
        self.assertIn(
            "grid-template-columns: repeat(2, minmax(0, 1fr)) !important",
            components,
        )
        self.assertIn("-webkit-line-clamp: 2", components)

        # Legacy overrides must not sneak the navy treatment back in.
        self.assertNotIn(".dark .kpi-strip", legacy_css)
        self.assertNotIn(".glass .kpi-strip", legacy_css)

    def test_popup_drawers_use_the_centered_dialog_contract(self):
        """Actions must never fall back to a full-height right-side drawer."""

        base_drawer = (
            ROOT / "templates/components/drawers/base_drawer.html"
        ).read_text()
        drawer_css = (ROOT / "static/css/drawers.css").read_text()

        self.assertIn("drawer_type|default:'center'", base_drawer)
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
        # The @theme block moved out of tailwind.source.css into _theme.css so
        # the tokens-only sign-in bundle could be built from the same block
        # rather than a second copy (see apps/core/tests/test_login_bundle.py).
        # The invariant this test protects is unchanged — aliases must resolve
        # to the semantic layer, never to literal values — only its address is.
        theme = (ROOT / "assets/css/_theme.css").read_text()

        for declaration in (
            "--color-edify-primary: var(--brand-primary);",
            "--color-edify-dark: var(--brand-primary-hover);",
            "--color-edify-soft: var(--brand-primary-soft);",
            "--color-edify-border: var(--brand-primary-border);",
            "--color-edify-text: var(--edify-text);",
            "--color-page: var(--edify-bg);",
        ):
            self.assertIn(declaration, theme)

        # And the block has to actually reach the application bundle.
        source = (ROOT / "assets/css/tailwind.source.css").read_text()
        self.assertIn('@import "./_theme.css"', source)

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

        # Files that actually RENDER a reschedule control. activity_table.html
        # used to be one; it now delegates its whole action cell to
        # activity_row.html, so the contract is checked where the control
        # lives rather than where it used to.
        sources = (
            "templates/partials/my_plan/activity_row.html",
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
        self.assertIn(">Schedule</span>", row)
        self.assertIn(">Assign</span>", row)
        self.assertNotIn("Schedule Now", row)

    def test_core_school_actions_share_the_school_name_row(self):
        row = (ROOT / "templates/partials/core_schools/school_row.html").read_text()
        css = (ROOT / "static/css/platform.css").read_text()

        school_id = row.index('class="school-record-row__school-id"')
        headline = row.index('class="core-school-row__headline"')
        title = row.index('class="school-record-row__title"', headline)
        actions = row.index(
            'class="school-record-row__actions core-school-row__actions"', title
        )
        metadata = row.index('class="school-record-row__metadata', actions)

        # The school ID leads the row — no decorative icon ahead of it.
        self.assertNotIn("school-record-row__icon", row)
        self.assertLess(school_id, title)
        self.assertLess(title, actions)
        self.assertLess(actions, metadata)
        self.assertIn("container: core-school-row / inline-size", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto", css)
        self.assertIn("@container core-school-row (max-width: 30rem)", css)

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
        alignment = partner_css.split("Partner workspace design-system alignment", 1)[1]

        for token in (
            "var(--edify-card-surface)",
            "var(--edify-card-border)",
            "var(--edify-card-shadow)",
            "var(--edify-action-button-block-size)",
            "var(--edify-success-light)",
            "var(--edify-warning-light)",
            "var(--edify-danger-light)",
            "var(--edify-focus-ring)",
        ):
            self.assertIn(token, alignment)

        self.assertIn(
            "btn-premium-primary partner-workspace__export-button", partner_template
        )
        self.assertIn(
            "btn-premium-secondary partner-workspace__filter-button", partner_template
        )

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
        contract = bridge.split("Special Projects uses the shared cockpit anatomy", 1)[
            1
        ]

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
            self.assertNotIn(
                '<link rel="stylesheet"',
                page.split("{% block shell_content %}", 1)[1],
                source,
            )

    def test_platform_uses_parent_cards_with_flat_internal_content(self):
        """Nested cards are flattened in pages, drawers, and legacy tile grids."""

        tokens = (ROOT / "static/css/design-system.css").read_text()
        bridge = (ROOT / "static/css/consistency.css").read_text()
        contract = bridge.split("FLAT CONTENT HIERARCHY", 1)[1]

        for token in (
            "--edify-content-divider:",
            "--edify-content-section-gap:",
            "--edify-content-row-padding:",
        ):
            self.assertIn(token, tokens)

        for selector in (
            ".edify-content-card",
            '[data-edify-surface="card"]',
            ".edify-section__heading",
            ".edify-data-row",
            ".drawer-surface",
            "ONE PLATFORM TYPE SCALE",
            ":not([data-edify-summary-kpi])",
        ):
            self.assertIn(selector, contract)

        for declaration in (
            "background-color: transparent !important;",
            "border-radius: 0 !important;",
            "box-shadow: none !important;",
            "border-block-end: 1px solid var(--edify-content-divider);",
            "font-size: var(--edify-text-body-size) !important;",
            "font-size: var(--edify-text-label-size) !important;",
            "font-size: var(--edify-text-micro-size) !important;",
        ):
            self.assertIn(declaration, contract)

    def test_every_retained_headline_uses_the_shared_kpi_tray(self):
        """Summary surfaces share one bounded renderer, never local card grids."""

        component = (ROOT / "templates/components/kpi_strip.html").read_text()
        self.assertIn("data-edify-summary-kpi", component)

        headline_summaries = (
            "templates/pages/dashboards/special_projects.html",
            "templates/pages/reports/index.html",
            "templates/pages/notifications/index.html",
            "templates/pages/todos/index.html",
            "templates/pages/admin_ops/team_plans.html",
            "templates/pages/hr/my_performance.html",
            "templates/pages/admin_ops/incident_detail.html",
            "templates/pages/admin_ops/planning.html",
            "templates/pages/admin_ops/support_queue.html",
            "templates/pages/staff/detail.html",
            "templates/pages/staff/index.html",
            "templates/pages/accounts/dashboard.html",
            "templates/partials/analytics/visit_effectiveness_workspace.html",
            "templates/partials/targets/my_body.html",
            "templates/partials/finance/country_budget/root.html",
            "templates/partials/fund_requests/kpis.html",
        )
        for source in headline_summaries:
            template = (ROOT / source).read_text()
            self.assertIn("components/kpi_strip.html", template, source)
            self.assertIn('variant="executive"', template, source)

        period_selector = (
            ROOT / "templates/pages/finance/fund_allocation.html"
        ).read_text()
        self.assertIn("budget-period-rail", period_selector)
        self.assertNotIn("edify-kpi-strip", period_selector)

    def test_adverse_states_use_the_danger_tone_and_absence_can_stay_neutral(self):
        bridge = (ROOT / "static/css/consistency.css").read_text()
        actions = (ROOT / "apps/planning/action_workspace.py").read_text()
        analytics = (ROOT / "apps/analytics/analytics_dashboard_service.py").read_text()
        school_bt = (
            ROOT / "templates/partials/schools/business_transformation.html"
        ).read_text()

        self.assertIn('[data-edify-tone="danger"]', bridge)
        self.assertIn('ActionState.BLOCKED: ("Blocked", "danger")', actions)
        self.assertIn('"key": "not_visited"', analytics)
        self.assertIn('"key": "not_trained"', analytics)
        self.assertGreaterEqual(analytics.count('"tone": "danger"'), 2)
        self.assertIn('data-edify-tone="{{ score.band_tone }}"', school_bt)
        self.assertIn("No negative compliance conclusion is inferred.", school_bt)

    def test_weight_hierarchy_reserves_bold_for_titles(self):
        tokens = (ROOT / "static/css/design-system.css").read_text()
        contract = (ROOT / "static/css/consistency.css").read_text()

        self.assertIn("--edify-text-body-weight:    400", tokens)
        self.assertIn("--edify-text-label-weight:   500", tokens)
        self.assertIn("--edify-text-micro-weight:   400", tokens)
        for tracking_token in (
            "--edify-text-display-tracking: normal",
            "--edify-text-heading-tracking: normal",
            "--edify-text-title-tracking: normal",
            "--edify-text-body-tracking: normal",
            "--edify-text-label-tracking: normal",
            "--edify-text-micro-tracking: normal",
        ):
            self.assertIn(tracking_token, tokens)
        self.assertIn("CONVENTIONAL WEIGHT HIERARCHY", contract)
        self.assertIn("NORMAL CHARACTER SPACING", contract)
        self.assertIn("letter-spacing: normal !important", contract)
        self.assertIn("font-weight: var(--edify-text-body-weight) !important", contract)
        self.assertIn(
            "font-weight: var(--edify-text-label-weight) !important", contract
        )
        for title_role in (
            ".card-title",
            ".panel-title",
            ".edify-section__heading",
            '[class*="__title"]',
            '[class*="__heading"]',
        ):
            self.assertIn(title_role, contract)

    def test_hero_kpi_value_outranks_the_strip_weight_normalisers(self):
        """The hero numeral must win its weight, not merely ask for it.

        consistency.css flattens every KPI-strip descendant to label weight
        with !important, to undo template drift. That is right for labels,
        helpers and meta — the quiet tiers are what make the number read as
        the number. But it also caught .kpi-strip__value, so the executive
        strip's font-weight was overridden while its font-size was not: the
        numeral rendered at the hero size in regular weight, and nothing
        failed. A silent half-applied rule is the exact defect this pins.
        """
        components = (ROOT / "static/css/components.css").read_text()
        block = components.split(".kpi-strip.kpi-strip--executive .kpi-strip__value")[1]
        block = block.split("}")[0]
        self.assertIn(
            "font-weight: 600 !important",
            block,
            "The hero KPI weight lost its !important, so the consistency.css "
            "normalisers will flatten it back to label weight silently.",
        )
        # Semibold, never bold: the numeral leads its label by size and ink,
        # not by a heavy block of weight, per the reference tiles.
        self.assertNotIn("font-weight: 700", block)
        self.assertIn("--edify-text-hero-size", block)

    def test_narrow_tiles_move_the_pill_onto_its_own_row(self):
        """The corner-pill composition needs room a six-up tile lacks.

        Below ~15rem the label's float spacer leaves less width than one
        unbreakable word, so the whole first line drops beneath the float and
        grazes the absolutely-positioned pill — five of six IA tiles at
        laptop width. The per-tile container query degrades to a pill-on-its-
        own-row layout and removes the spacer; deleting either half brings
        the collision back.
        """
        components = (ROOT / "static/css/components.css").read_text()
        self.assertIn("@container kpi-card (max-width: 14.99rem)", components)
        narrow = components.split("@container kpi-card (max-width: 14.99rem)")[1]
        narrow = narrow.split("\n}\n")[0]
        self.assertIn('"pill"', narrow)
        self.assertIn("content: none", narrow)

    def test_authenticated_pages_use_the_shells_single_main_region(self):
        """Nested page mains cause competing landmarks and inconsistent spacing."""

        pages = ROOT / "templates/pages"
        # Pages that render outside the app shell own their own main landmark:
        # `base.html` declares none, so without it these have no main at all.
        # The rule this test enforces is "no *second* main inside the shell's".
        standalone = {pages / "documents/canonical_document.html"}

        for page in pages.rglob("*.html"):
            if page in standalone:
                continue
            self.assertNotIn("<main", page.read_text(), page)
