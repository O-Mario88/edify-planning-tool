"""A card's own grid of numbers is the same panel, one step down.

THE DEFECT THIS FIXES (owner, 2026-09-07)

After the headline KPI tray stopped being a row of squares, the owner asked for
the in-card mini-summaries to be folded in too.

Those grids were hand-rolled with Tailwind utilities everywhere they appeared —
a tinted box per number, `bg-rose-50 border border-rose-100`, in as many colour
pairs as there were moods — so the CD's verification counts, the country
budget's month summary and the PL's personal targets each had their own idea of
what a small metric looks like. Beside a tray that had just become one panel,
they were the last squares on the page.

WHAT THESE TESTS HOLD

That the shared classes exist and carry the tray's anatomy and tokens, that tone
lands on the NUMBER rather than on a filled box, and that no converted template
has drifted back to a tinted card. The check is per-file and names the files,
because the failure mode here is not a broken page — it is one grid quietly
going back to boxes while the rest stay panels.
"""

import re

from django.test import SimpleTestCase

from .test_design_system_quality import _read

# These summaries now use the shared KPI strip. Remaining workqueue panels
# retain their own bodies, forms and actions below the metric.
CONVERTED = (
    "templates/pages/projects/index.html",
    "templates/partials/dashboards/cd/operations.html",
    "templates/partials/dashboards/pl/operations.html",
    "templates/partials/analytics/pl/activity_tracking.html",
    "templates/partials/hr/pd_dashboard/body.html",
    "templates/partials/finance/country_budget/root.html",
    "templates/partials/finance/country_budget/execution.html",
    # The icon-led tiles (owner, 2026-09-07: "fold in those tiles too"): three
    # impact summaries whose tinted boxes each carried a filled icon chip.
    "templates/partials/analytics/cd/impact_summary.html",
    "templates/partials/analytics/pl/impact_summary.html",
    "templates/partials/analytics/impact_summary.html",
)

# A metric drawn as a tinted rectangle: the shape that was removed. The
# opacity suffixes are optional because the impact summaries wrote theirs as
# `bg-violet-50/50 border border-violet-100/60`, and the accent-coloured one
# reached for the primary-soft utilities instead of a Tailwind colour.
TINTED_BOX = re.compile(
    r"rounded-surface (?:bg-(amber|emerald|rose|slate|sky|indigo|violet|blue|teal)-50(?:/\d+)?"
    r" border border-\1-100(?:/\d+)?"
    r"|edify-primary-soft-alpha-50 border edify-primary-border-alpha-60)"
)


class MetricPanelTest(SimpleTestCase):
    def test_the_shared_classes_carry_the_trays_anatomy(self):
        css = _read("static/css/components.css")
        panel = css[css.index(".edify-metric-panel {") :]
        panel = panel[: panel.index("\n}")]
        # One panel: border, radius, gradient — the same three the tray has.
        self.assertIn("border: 1px solid var(--edify-kpi-panel-border);", panel)
        self.assertIn("background-image: linear-gradient(", panel)
        self.assertIn("gap: 0;", panel)
        self.assertIn("overflow: clip;", panel)

        cell = css[css.index("\n.edify-metric {") :]
        cell = cell[: cell.index("\n}")]
        # The same hairline mechanism, so no rule needs the column count.
        self.assertIn("border-inline-start: 1px solid var(--edify-kpi-divider);", cell)
        self.assertIn("border-block-start: 1px solid var(--edify-kpi-divider);", cell)
        self.assertIn("margin-inline-start: -1px;", cell)
        self.assertIn("margin-block-start: -1px;", cell)

    def test_the_normalizers_that_would_repaint_it_name_it_by_hand(self):
        """Five card normalizers reach this element through generic arms like
        `[class*="-panel"]:not([class*="-panel-"])`, which `edify-metric-panel`
        matches exactly. Each excludes it by name, the way `.kpi-strip__item`
        already did.

        The `:not()` must be ATTACHED to the closing paren. Written on its own
        line it is a descendant combinator, and the rule stops meaning "a card
        that is not the panel" and starts meaning "anything inside a card" —
        which repainted every metric in the two dark themes while the panel
        around them came out right, and cost an hour to find.
        """

        import re

        for name in ("static/css/platform.css", "static/css/consistency.css"):
            with self.subTest(css=name):
                source = _read(name)
                self.assertIn(":not(.edify-metric-panel)", source)
                strays = re.findall(
                    r"\)\s*\n\s*(?:/\*.*?\*/\s*\n\s*)?:not\(\.edify-metric-panel\)",
                    source,
                    re.S,
                )
                self.assertEqual(strays, [])

    def test_the_columns_are_left_to_the_template(self):
        """Each of these grids already declares its own `grid-cols-*` and knows
        how many numbers it is showing; the component claims only the gap,
        because the hairlines replace it."""

        css = _read("static/css/components.css")
        panel = css[css.index(".edify-metric-panel {") :]
        panel = panel[: panel.index("\n}")]
        self.assertNotIn("grid-template-columns", panel)

    def test_tone_colours_the_number_and_never_a_box(self):
        css = _read("static/css/components.css")
        for tone in ("danger", "warning", "success", "info"):
            rule = f'.edify-metric[data-tone="{tone}"] .edify-metric__value'
            self.assertIn(rule, css)
        # No tone rule paints a surface behind the metric.
        for tone in ("danger", "warning", "success", "info"):
            block = css[css.index(f'.edify-metric[data-tone="{tone}"]') :]
            block = block[: block.index("}")]
            self.assertNotIn("background", block)

    def test_the_label_is_small_caps_like_the_trays(self):
        css = _read("static/css/components.css")
        label = css[css.index(".edify-metric__label {") :]
        label = label[: label.index("\n}")]
        self.assertIn("text-transform: uppercase;", label)
        self.assertIn("font-size: var(--edify-text-micro-size);", label)
        self.assertIn("color: var(--edify-text-muted);", label)

    def test_no_converted_grid_has_gone_back_to_tinted_boxes(self):
        for template in CONVERTED:
            with self.subTest(template=template):
                source = _read(template)
                self.assertIn("{% kpi_strip", source)
                # Only a tinted box holding a METRIC is an offender. The same
                # markup is also how this codebase writes an empty-state icon
                # holder (a `w-12 h-12` square around an svg) and a prose note
                # — the country budget's "could not be attributed to a country"
                # warning is a sentence, not a number, and it keeps its amber.
                lines = source.split("\n")
                offenders = []
                for i, line in enumerate(lines):
                    if not TINTED_BOX.search(line):
                        continue
                    if re.search(r"\bh-\d+ w-\d+\b|\bw-\d+ h-\d+\b", line):
                        continue
                    body = " ".join(lines[i : i + 5])
                    if "tabular-nums" in body or "edify-kpi-label" in body:
                        offenders.append(line.strip()[:120])
                self.assertEqual(offenders, [])

    def test_a_metric_can_lead_with_its_mark_beside_it(self):
        from django.template.loader import render_to_string

        rendered = render_to_string(
            "partials/analytics/cd/impact_summary.html",
            {
                "impact_summary": {
                    "students_impacted": 120,
                    "teachers_trained": 25,
                    "leaders_trained": 8,
                    "schools_improved": 4,
                    "champion_candidates": 7,
                }
            },
        )
        self.assertEqual(rendered.count('data-component="context-metric"'), 5)
        self.assertIn("Champion school candidates", rendered)
        self.assertRegex(rendered, r'class="context-metrics__value"[^>]*>\s*7\s*</')

    def test_the_prose_normaliser_leaves_component_type_alone(self):
        """consistency.css flattens every <p> in a page to body size. A
        metric's number, label and caption are <p> too, and were being
        flattened with the rest: the number and its small-caps label both
        measured 13px, and the caps read heavier than the figure. The
        normaliser names the parts it must not touch."""

        css = _read("static/css/consistency.css")
        rule = css[
            css.index(
                ":is(p, li, dd, .edify-profile-body, .edify-section__description):not("
            ) :
        ]
        rule = rule[: rule.index("{")]
        for part in (
            ".edify-metric__value",
            ".edify-metric__label",
            ".edify-metric__meta",
            ".edify-note__title",
            ".edify-note__body",
            ".edify-empty-state__message",
        ):
            with self.subTest(part=part):
                self.assertIn(part, rule)

    def test_every_metric_names_its_parts(self):
        """A cell without a label or a value is not a metric, and the panel's
        hairlines would frame an empty box."""

        for template in CONVERTED:
            with self.subTest(template=template):
                source = _read(template)
                metrics = re.findall(
                    r"{% kpi_metric(?: [^%]*)? %}(.*?){% endkpi_metric %}", source, re.S
                )
                self.assertGreater(len(metrics), 0)
                for metric in metrics:
                    self.assertIn("{% kpi_label %}", metric)
                    value = re.sub(
                        r"{% kpi_label %}.*?{% endkpi_label %}", "", metric, flags=re.S
                    )
                    self.assertTrue(value.strip(), template)


class HrActionCentreTest(SimpleTestCase):
    """The one grid that is a metric AND a workqueue.

    Each of the five queues states how many are waiting and then lists the
    first few with the button that clears them. Folding it onto the panel had
    to keep the second half working: the header became the label/value pair,
    and the rows, their forms and the bulk action stayed exactly where they
    were. The dev database has every queue empty, so this renders a populated
    one — the empty case is the one you see by accident, and the populated case
    is the one that breaks.
    """

    def _render(self):
        from django.template.loader import render_to_string

        return render_to_string(
            "partials/hr/pd_dashboard/body.html",
            {
                "fy": "2026",
                "country": "Uganda",
                "action_center": [
                    {
                        "key": "not_started",
                        "label": "Not yet started",
                        "count": 5,
                        "items": [
                            {
                                "staff_name": "Alice N",
                                "course_name": "Safeguarding",
                                "due_label": "Due 12 Sep",
                                "action": "remind",
                                "action_label": "Remind",
                                "id": "r1",
                            }
                        ],
                    },
                    {
                        "key": "ready_signoff",
                        "label": "Ready for HR sign-off",
                        "count": 0,
                        "items": [],
                    },
                ],
            },
        )

    def test_a_populated_queue_keeps_its_rows_and_its_buttons(self):
        html = self._render()
        section = html[html.index("HR Action Center") :]

        self.assertIn("edify-metric-panel", section)
        self.assertEqual(section.count('class="edify-metric"'), 2)
        self.assertIn("Alice N", section)
        self.assertIn("Safeguarding", section)
        # The row's own action and the bulk one below it.
        self.assertIn("Remind All (5)", section)
        self.assertIn('value="bulk_send_reminders"', section)

    def test_an_empty_queue_is_the_good_state_and_says_so(self):
        """Zero keeps a tone here, unlike the KPI tray: this is a queue, and
        empty means the work is done rather than the metric being unmeasured."""

        section = self._render()
        section = section[section.index("HR Action Center") :]
        self.assertIn('data-tone="warning"', section)
        self.assertIn('data-tone="success"', section)
        self.assertIn("Nothing here right now.", section)
