from html.parser import HTMLParser
from pathlib import Path
import re
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[2]

HEADER_FAMILIES = {
    "edify-page-hero",
    "edify-page-header",
    "platform-page-header",
    "platform-hero",
    "ia-hero",
    "help-center-hero",
    "help-shell__header",
    "hcos-hero",
    "sp-page-header",
    "pto-header",
    "tt-page-header",
    "calendar-workspace__header",
    "partner-workspace__header",
    "admin-command__header",
    "pd-page-header",
    "sp-plan__header",
    "spp-header",
    "spa-header",
}


class _HeaderSelectAudit(HTMLParser):
    """Locate select controls nested in any platform page-header family."""

    VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.select_lines = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        inside_header = any(node[1] for node in self.stack)
        is_header_content = bool(classes & HEADER_FAMILIES) or inside_header

        if tag == "select" and is_header_content:
            self.select_lines.append(self.getpos()[0])

        if tag not in self.VOID_ELEMENTS:
            self.stack.append((tag, is_header_content))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


class FilterCanvasToolbarContractTests(TestCase):
    def test_primary_filter_toolbars_expose_at_most_three_fields(self):
        violations = []
        form_pattern = re.compile(
            r'<form\b[^>]*data-component="filter-toolbar"[^>]*>(.*?)</form>',
            re.DOTALL,
        )
        enclosed_pattern = re.compile(
            r"<(?:dialog|details)\b.*?</(?:dialog|details)>", re.DOTALL
        )
        field_pattern = re.compile(r"<(?:select|input)\b([^>]*)>", re.DOTALL)

        for template in sorted((ROOT / "templates").rglob("*.html")):
            source = template.read_text(encoding="utf-8")
            for form in form_pattern.findall(source):
                primary = enclosed_pattern.sub("", form)
                fields = [
                    attrs
                    for attrs in field_pattern.findall(primary)
                    if not re.search(r'type=["\']hidden["\']', attrs)
                ]
                if len(fields) > 3:
                    violations.append(
                        f"{template.relative_to(ROOT)}: {len(fields)} primary fields"
                    )

        self.assertEqual(
            violations,
            [],
            "normal-width filter toolbars may expose at most three primary "
            "fields; put the rest in the shared filter drawer",
        )

    def test_page_headers_never_contain_filter_selects(self):
        violations = []

        for template in sorted((ROOT / "templates").rglob("*.html")):
            audit = _HeaderSelectAudit()
            audit.feed(template.read_text(encoding="utf-8"))
            for line in audit.select_lines:
                violations.append(f"{template.relative_to(ROOT)}:{line}")

        self.assertEqual(
            violations,
            [],
            "filter selects belong on the page canvas below the header card",
        )

    def test_legacy_page_filters_use_the_shared_canvas_toolbar(self):
        templates = (
            "templates/pages/admin/users.html",
            "templates/pages/admin_ops/team_plans.html",
            "templates/pages/calendar/index.html",
            "templates/pages/documents/compliance.html",
            "templates/pages/messages/index.html",
            "templates/pages/settings/activity_catalogue.html",
        )

        for relative_path in templates:
            markup = (ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(template=relative_path):
                self.assertTrue(
                    "edify-filter-bar" in markup or "platform-filter-bar" in markup
                )

    def test_partner_activity_filters_follow_the_header(self):
        for relative_path, filter_id in (
            ("templates/pages/partners/index.html", "partner-activity-filters"),
            ("templates/pages/partner/activities.html", "Activity filters"),
        ):
            markup = (ROOT / relative_path).read_text(encoding="utf-8")
            header_start = markup.index("edify-page-header")
            header_end = (
                markup.index("</header>", header_start)
                if "</header>" in markup[header_start:]
                else markup.index("</div>", header_start)
            )
            filter_start = markup.index(filter_id)
            with self.subTest(template=relative_path):
                self.assertLess(header_end, filter_start)

    def test_shared_filter_toolbars_are_canvas_level_single_rows(self):
        css = (ROOT / "static/css/consistency.css").read_text()
        canvas_contract = css.split("Filter bars live on the page canvas", 1)[1].split(
            "Page-canvas filter toolbar contract", 1
        )[0]
        row_contract = css.split("Page-canvas filter toolbar contract", 1)[1]

        for selector in (
            ".platform-filter-bar",
            ".edify-filter-bar",
            ".sp-filter-panel",
            ".spp-filter-panel",
            ".spa-filter-panel",
            ".tt-filter-panel",
            ".school-filters-form",
            ".school-filter-canvas",
            "#filters-form",
            "#core-filters-form",
            "#analytics-filters-form",
            "#pl-analytics-filters",
            "#cd-analytics-filters",
            "#cb-filters",
            "#debrief-filters",
            "#visits-filters",
            "#trainings-filters",
            "#pd-filters",
            "#spp-filters",
            "#spa-filters",
            "#sp-plan-filters",
            "#pl-dashboard-filters",
            "#project-filters",
            "#cluster-filters",
            '[data-component="filter-toolbar"]',
        ):
            self.assertIn(selector, canvas_contract)
            self.assertIn(selector, row_contract)

        for declaration in (
            "background: transparent !important;",
            "border: 0 !important;",
            "box-shadow: none !important;",
        ):
            self.assertIn(declaration, canvas_contract)

        for declaration in (
            "flex-flow: row nowrap !important;",
            "align-items: flex-end !important;",
            "overflow-x: auto;",
            "overscroll-behavior-inline: contain;",
        ):
            self.assertIn(declaration, row_contract)

    def test_mobile_filter_disclosure_does_not_reintroduce_a_card(self):
        css = (ROOT / "static/css/consistency.css").read_text()
        contract = css.split("The mobile disclosure remains useful", 1)[1]

        self.assertIn("main .mobile-family-filter", contract)
        self.assertIn("border-radius: 0 !important;", contract)
        self.assertIn("background: transparent !important;", contract)
        self.assertIn("main .mobile-family-filter > :not(summary)", contract)
        self.assertIn("border: 0 !important;", contract)

    def test_filter_field_wrappers_do_not_become_nested_cards(self):
        css = (ROOT / "static/css/consistency.css").read_text()
        contract = css.split("Page-canvas filter toolbar contract", 1)[1].split(
            "Labels and field groups are layout only", 1
        )[0]

        self.assertIn(
            '> :is(label, div):has(> :is(select, input:not([type="hidden"]), textarea))',
            contract,
        )
        self.assertIn("padding: 0 !important;", contract)
        self.assertIn("border: 0 !important;", contract)
        self.assertIn("background: transparent !important;", contract)
        self.assertIn("box-shadow: none !important;", contract)

        for selector in (
            ".sp-filter-panel",
            ".school-filters-form",
            "#filters-form",
            "#core-filters-form",
            "#analytics-filters-form",
            "#cluster-filters",
        ):
            self.assertIn(selector, contract)

    def test_debrief_filters_opt_into_the_shared_toolbar(self):
        template = (ROOT / "templates/pages/debriefs/dashboard.html").read_text()
        form = template.split('<form id="debrief-filters"', 1)[1].split("</form>", 1)[0]

        self.assertIn('data-component="filter-toolbar"', form)
        self.assertIn('class="platform-filter-bar"', form)
        self.assertNotIn("grid-cols-", form)
        self.assertEqual(form.count("<label"), 4)
        self.assertEqual(form.split("<dialog", 1)[0].count("<label"), 3)
        self.assertIn('data-component="filter-drawer"', form)
