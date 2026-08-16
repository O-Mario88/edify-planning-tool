"""Platform-wide contracts for the exhaustive mobile micro-UX pass."""

from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[2]


def _read(relative_path: str) -> str:
    return ROOT.joinpath(relative_path).read_text(encoding="utf-8")


class MobileMicroUXContractTest(SimpleTestCase):
    def test_authenticated_shell_cannot_opt_out_of_micro_ux(self):
        base = _read("templates/base.html")
        shell = _read("templates/layouts/shell.html")

        self.assertIn("css/components/mobile-micro-ux.css", base)
        self.assertIn("js/micro-ux.js", base)
        self.assertIn('data-mobile-system="micro-ux-v1"', shell)
        self.assertLess(
            base.index("css/consistency.css"), base.index("mobile-micro-ux.css")
        )

    def test_mobile_controls_and_forms_have_platform_touch_contracts(self):
        styles = _read("static/css/components/mobile-micro-ux.css")
        for marker in (
            '.edify-workspace :where(button, [role="button"], summary, [role="tab"])',
            ".edify-workspace a[href]",
            "min-block-size: 2.75rem !important",
            "font-size: 16px !important",
            'label:has(input[type="checkbox"])',
            ":user-invalid",
            ":focus-visible",
            "@media (pointer: coarse)",
            "@media (forced-colors: active)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, styles)

    def test_touch_checkboxes_are_not_enlarged_or_given_a_field_focus_square(self):
        base = _read("templates/base.html")
        bridge = _read("static/css/consistency.css")

        coarse_rule = base.split("@media (max-width: 48rem), (pointer: coarse)", 1)[
            1
        ].split("</style>", 1)[0]
        self.assertNotIn(":where(input, select, textarea)", coarse_rule)
        self.assertIn('input[type="text"]', coarse_rule)
        self.assertIn('input[type="time"]', coarse_rule)

        field_focus_rule = bridge.split(
            "Text-entry controls receive the broad field ring", 1
        )[1].split('main :is(input[type="checkbox"]', 1)[0]
        self.assertIn(':not([type="checkbox"]):not([type="radio"])', field_focus_rule)
        self.assertNotIn("main :is(input, select, textarea):focus", field_focus_rule)

        # Selection controls retain the keyboard-only ring from the layer that
        # loads after consistency.css; only persistent pointer focus is quiet.
        styles = _read("static/css/components/mobile-micro-ux.css")
        behavior = _read("static/js/micro-ux.js")
        self.assertIn('data-edify-input-modality="pointer"', styles)
        self.assertIn("outline: none !important", styles)
        self.assertIn("dataset.edifyInputModality = 'pointer'", behavior)
        self.assertIn("dataset.edifyInputModality = 'keyboard'", behavior)

    def test_every_rendered_table_is_adaptively_enhanced(self):
        behavior = _read("static/js/micro-ux.js")
        styles = _read("static/css/components/mobile-micro-ux.css")

        self.assertIn("root.querySelectorAll('table').forEach(enhanceTable)", behavior)
        self.assertIn("ensureTableCaption", behavior)
        self.assertIn("header.setAttribute('scope', 'col')", behavior)
        self.assertIn("enhanceTableChoices(table)", behavior)
        self.assertIn("Select all records", behavior)
        self.assertIn("makeScrollRegion(table, label)", behavior)
        self.assertIn(".edify-table-choice", styles)
        self.assertNotIn("edify-mobile-table--cards", styles)
        self.assertIn("edify-mobile-table--scroll", styles)
        self.assertIn("tableNeedsInlineScroll(table)", behavior)
        self.assertIn("tableColumnCount(table) > 5", behavior)
        self.assertIn("table.matches('.sr-only, .edify-visually-hidden')", behavior)
        self.assertIn("table.classList.add('edify-mobile-table--scroll')", behavior)
        self.assertIn("edify-mobile-table--fit", styles)
        self.assertIn("Scrollable table:", behavior)
        self.assertNotIn("can-scroll-inline", behavior)
        self.assertNotIn("box-shadow: inset", styles)

    def test_pagination_is_named_and_touch_safe_at_source(self):
        pager = _read("templates/components/table_pager.html")
        styles = _read("static/css/components/mobile-micro-ux.css")

        self.assertIn("edify-pagination__control", pager)
        self.assertIn('aria-label="Previous page"', pager)
        self.assertIn('aria-label="Next page"', pager)
        self.assertIn('aria-label="Page {{ p }}, current page"', pager)
        self.assertIn('aria-label="Page {{ p }}"', pager)
        self.assertIn("--edify-pagination-control-size: 1.875rem", styles)
        self.assertIn("--edify-pagination-control-size: 2rem", styles)
        self.assertIn("--edify-pagination-control-size: 1.75rem", styles)
        self.assertIn(".edify-pagination__direction-symbol", styles)

        for path in (
            "templates/pages/admin/unmatched_ssa_queue.html",
            "templates/pages/staff/index.html",
            "templates/partials/clusters/cluster_list.html",
            "templates/partials/core_schools/planning_queue.html",
            "templates/partials/core_schools/matrix_table.html",
            "templates/partials/core_schools/team_oversight.html",
            "templates/partials/finance/fund_allocation_table.html",
            "templates/partials/planning/school_table.html",
            "templates/partials/projects/planning_workspace.html",
            "templates/partials/schools/table.html",
            "templates/partials/evidence/workspace.html",
            "templates/partials/my_plan/_pager.html",
            "templates/partials/dashboards/pl/urgent_schools_page.html",
            "templates/pages/hr/module_workspace.html",
            "templates/pages/ia/partials/queue_table.html",
        ):
            with self.subTest(path=path):
                self.assertIn("edify-pagination-scope", _read(path))

    def test_tabs_and_custom_modals_gain_keyboard_behavior(self):
        behavior = _read("static/js/micro-ux.js")
        for marker in (
            "enhanceTabList",
            "enhanceTabReveal",
            "revealTab(selected, true)",
            "revealTab(focused, false)",
            "tablist.scrollTo",
            "requestAnimationFrame(alignTab)",
            "window.setTimeout(alignTab, 220)",
            "revealRect.right - stripRect.right",
            "revealTab(active, true, true)",
            "prefers-reduced-motion: reduce",
            "dataset.edifyTabRevealReady",
            "'ArrowLeft', 'ArrowRight', 'Home', 'End'",
            "inertOutside(dialog)",
            "restoreOutside(state.background)",
            "dialog.addEventListener('keydown', keyHandler)",
            "state.previousFocus.focus",
            "nameDialog(dialog)",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, behavior)

    def test_scrollable_tabs_use_smooth_reveal_with_reduced_motion_fallback(self):
        styles = _read("static/css/platform.css")

        self.assertIn("scroll-behavior: smooth", styles)
        self.assertIn("scroll-padding-inline: 0.5rem", styles)
        reduced = styles.split("@media (prefers-reduced-motion: reduce)", 1)[1]
        self.assertIn('[role="tablist"]', reduced)
        self.assertIn("scroll-behavior: auto", reduced)

    def test_tab_assets_are_cache_busted_together(self):
        base = _read("templates/base.html")

        self.assertIn("platform.css' %}?v=20260812tables1", base)
        self.assertIn("pages.css' %}?v=20260812tables2", base)
        self.assertIn("mobile-micro-ux.css' %}?v=20260812checkbox1", base)
        self.assertIn("micro-ux.js' %}?v=20260812checkbox1", base)

    def test_dashboard_tables_keep_real_table_modes(self):
        for path, mode in (
            ("templates/partials/dashboards/pl/backlog_snapshot.html", "fit"),
            ("templates/partials/dashboards/pl/cceo_performance.html", "scroll"),
            ("templates/partials/dashboards/urgent_schools_table.html", "scroll"),
            ("templates/partials/dashboards/pl/ssa_intelligence.html", "fit"),
            ("templates/partials/oversight/cd_workspace.html", "scroll"),
            ("templates/partials/oversight/pl_workspace.html", "scroll"),
        ):
            with self.subTest(path=path):
                self.assertIn(f'data-mobile-table="{mode}"', _read(path))

    def test_mobile_table_card_modes_and_visible_duplicate_lists_are_gone(self):
        for path in ROOT.joinpath("templates").rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            with self.subTest(template=str(path.relative_to(ROOT))):
                self.assertNotIn('data-mobile-table="cards"', source)

        for path in (
            "templates/pages/ia/partials/queue_table.html",
            "templates/partials/projects/portfolio_list.html",
            "templates/partials/oversight/pl_workspace.html",
            "templates/partials/oversight/cd_workspace.html",
        ):
            source = _read(path)
            self.assertNotIn('class="md:hidden', source)
            self.assertNotIn('class="lg:hidden', source)

        pages = _read("static/css/pages.css")
        team_targets = _read("templates/partials/targets/team/body.html")
        leave = _read("templates/pages/leave/personal_time_off.html")
        self.assertNotIn("tt-mobile-performance", team_targets)
        self.assertNotIn("pto-tracker-cards", leave)
        self.assertNotIn(".tt-mobile-performance", pages)
        self.assertNotIn(".pto-tracker-cards", pages)

    def test_message_and_calendar_tab_rails_cannot_collapse_or_clip(self):
        styles = _read("static/css/platform.css")
        messages = _read("templates/pages/messages/index.html")

        self.assertIn("messages-filter-bar", messages)
        self.assertIn("flex-direction: column", styles)
        self.assertIn("main .calendar-workspace__filters", styles)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", styles)
        self.assertIn("min-inline-size: 0 !important", styles)

    def test_feedback_and_accessible_name_auditing_are_centralized(self):
        base = _read("templates/base.html")
        behavior = _read("static/js/micro-ux.js")

        self.assertIn('id="edify-live-polite"', base)
        self.assertIn('id="edify-live-assertive"', base)
        self.assertIn("auditInteractiveNames", behavior)
        self.assertIn("enhanceFormLabels", behavior)
        self.assertIn("label.htmlFor = field.id", behavior)
        self.assertIn("dataset.edifyA11yWarning", behavior)
        self.assertIn("htmx:responseError", behavior)
        self.assertIn("htmx:sendError", behavior)

    def test_legacy_action_buttons_cannot_accidentally_submit_forms(self):
        behavior = _read("static/js/micro-ux.js")

        self.assertIn("normalizeActionButtonTypes", behavior)
        self.assertIn("button:not([type])", behavior)
        self.assertIn("button.type = 'button'", behavior)
        self.assertIn("dataset.edifyImplicitActionButtons", behavior)

    def test_title_only_icon_controls_receive_a_real_accessible_name(self):
        behavior = _read("static/js/micro-ux.js")

        self.assertIn("control.setAttribute('aria-label', control.title)", behavior)

    def test_templates_do_not_use_positive_tabindex(self):
        offenders = []
        for path in ROOT.joinpath("templates").rglob("*.html"):
            source = path.read_text(encoding="utf-8")
            for value in range(1, 10):
                if f'tabindex="{value}"' in source:
                    offenders.append(str(path.relative_to(ROOT)))
                    break
        self.assertEqual(offenders, [])

    def test_full_screen_overlays_are_declared_as_named_dialogs(self):
        dialog_contracts = {
            "templates/partials/partners/create_partner_drawer.html": "onboard-partner-title",
            "templates/partials/core_schools/schedule_visit_drawer.html": "schedule-core-visit-title",
            "templates/partials/core_schools/core_assessment_drawer.html": "core-school-assessment-title",
            "templates/partials/core_schools/champion_review_drawer.html": "champion-review-title",
            "templates/partials/core_schools/schedule_training_drawer.html": "schedule-core-training-title",
            "templates/partials/core_schools/strategy_playbook_drawer.html": "core-strategy-playbook-title",
            "templates/pages/leave/public_holidays.html": "add-calendar-block-title",
            "templates/pages/targets/index.html": "target-rollup-title",
            "templates/pages/professional_development/index.html": "pd-policy-title",
            "templates/pages/dashboards/rvp.html": "strategy-note-title",
        }
        for path, title_id in dialog_contracts.items():
            source = _read(path)
            with self.subTest(path=path):
                self.assertIn('role="dialog"', source)
                self.assertIn('aria-modal="true"', source)
                self.assertIn(f'aria-labelledby="{title_id}"', source)
                self.assertIn(f'id="{title_id}"', source)
