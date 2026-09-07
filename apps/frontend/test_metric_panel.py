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

# Every template whose metric grid was folded onto the shared panel. The two
# marked (orphaned) are not rendered by any view today — the unified /budget
# page replaced the country budget's own, and nothing includes the To-Do
# command centre — but they are still read by contract tests, and leaving them
# in the old style would make them a template to copy from.
CONVERTED = (
    "templates/pages/projects/index.html",
    "templates/partials/dashboards/cd/operations.html",
    "templates/partials/dashboards/pl/operations.html",
    "templates/partials/analytics/pl/activity_tracking.html",
    "templates/partials/hr/pd_dashboard/body.html",
    "templates/partials/finance/country_budget/root.html",  # orphaned
    "templates/partials/finance/country_budget/execution.html",  # orphaned
    "templates/partials/todos/command_center.html",  # orphaned
)

# A metric drawn as a tinted rectangle: the shape that was removed.
TINTED_BOX = re.compile(
    r"rounded-surface bg-(amber|emerald|rose|slate|sky|indigo|violet|blue|teal)-50"
    r" border border-\1-100"
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
                self.assertIn("edify-metric-panel", source)
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

    def test_every_metric_names_its_parts(self):
        """A cell without a label or a value is not a metric, and the panel's
        hairlines would frame an empty box."""

        for template in CONVERTED:
            with self.subTest(template=template):
                source = _read(template)
                cells = source.count('class="edify-metric ') + source.count(
                    'class="edify-metric"'
                )
                self.assertGreater(cells, 0)
                self.assertGreaterEqual(source.count("edify-metric__label"), 1)
                self.assertGreaterEqual(source.count("edify-metric__value"), 1)


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
