"""Nothing here, and why: the two shapes that are not metrics.

THE DEFECT THIS FIXES (owner, 2026-09-07)

After the metric grids became panels: "now do the same for the empty states and
prose notes."

An EMPTY STATE was written out by hand on fifteen pages — the same centred
column, the same 48px square, the same clipboard glyph, the same muted sentence
— differing only in the words. Byte-identical markup in fifteen files is
fifteen places for it to drift, and the component it should have used already
existed under the name `.edify-empty-state`, declared twice with different
rules and no knowledge of a mark or a message.

A NOTE is a sentence the page needs to say beside the data: an amount that
could not be attributed, a quarter too young to forecast, a request returned
for correction. There were five, each a flat `bg-amber-50` rectangle that only
exists on one theme.

WHAT THESE TESTS HOLD

That the component is defined once and used everywhere, that the note carries
its tone the way the rest of the platform does, and — the part that actually
broke — that the table machinery leaves an empty state alone.
"""

import re

from django.test import SimpleTestCase

from .test_design_system_quality import _read

EMPTY_STATE_PAGES = (
    "templates/pages/accounts/accountability.html",
    "templates/pages/accounts/approval_history.html",
    "templates/pages/accounts/audit_log.html",
    "templates/pages/accounts/blocked.html",
    "templates/pages/accounts/cleared.html",
    "templates/pages/accounts/partner_payments.html",
    "templates/pages/accounts/ready_for_advance.html",
    "templates/pages/accounts/returned.html",
    "templates/pages/accounts/variance_review.html",
    "templates/pages/accounts/weekly_requests.html",
    "templates/pages/closure/blocked_closure.html",
    "templates/pages/ia/compare_evidence.html",
    "templates/partials/analytics/panels/completed_work.html",
    "templates/partials/analytics/panels/publishing_status.html",
)

NOTE_TEMPLATES = (
    "templates/partials/disbursements/disburse_drawer.html",
    "templates/partials/finance/country_budget/execution.html",
    "templates/partials/professional_development/_request_summary.html",
    "templates/partials/professional_development/request_form.html",
)

# The hand-rolled empty state: a centred column around a 48px icon square.
HAND_ROLLED = re.compile(
    r'<div class="w-12 h-12 rounded-surface bg-slate-50 border border-slate-100 '
    r"flex items-center justify-center text-slate-300 shadow-inner\">"
)


class EmptyStateTest(SimpleTestCase):
    def test_every_page_uses_the_one_component(self):
        for page in EMPTY_STATE_PAGES:
            with self.subTest(page=page):
                source = _read(page)
                self.assertIn('{% include "components/empty_state.html"', source)
                self.assertIsNone(HAND_ROLLED.search(source))

    def test_no_template_anywhere_still_writes_one_out_by_hand(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[2] / "templates"
        offenders = [
            str(path.relative_to(root))
            for path in root.rglob("*.html")
            if HAND_ROLLED.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])

    def test_the_component_is_defined_once(self):
        """It was declared three times: near the top of components.css as a
        dashed panel with no parts, again at the end with parts and no panel,
        and a third time in platform.css as a grid. An empty state took its
        container from one and its anatomy from another."""

        components = _read("static/css/components.css")
        platform = _read("static/css/platform.css")
        self.assertEqual(components.count("\n.edify-empty-state {"), 1)
        self.assertNotIn("main .edify-empty-state {", platform)
        # The values the platform copy carried are kept.
        block = components[components.index("\n.edify-empty-state {") :]
        block = block[: block.index("\n}")]
        self.assertIn("min-block-size: 10rem;", block)
        self.assertIn("border: 1px dashed var(--edify-border-strong);", block)
        self.assertIn("background-color: var(--edify-surface-muted);", block)

    def test_the_table_machinery_leaves_an_empty_state_alone(self):
        """The part that actually broke.

        A table cell's stacked text is flattened onto one line with a middle
        dot between the pieces — by CSS for the markup, and by micro-ux.js,
        which stamps `.edify-cell-wrap` / `.edify-cell-line` on what it finds.
        Both guards are by CLASS, and the hand-rolled empty states carried
        `flex flex-col`, which the guards excluded. The component does not, so
        the moment they became one the mark and the sentence landed on one line
        joined by "·", with the icon squashed out of its square.
        """

        css = _read("static/css/consistency.css")
        self.assertIn(
            ":is(td, th) > :is(div, p, span):not(.edify-cell-row):not(.edify-empty-state) >",
            css,
        )
        self.assertIn(
            ":is(td, th) > :is(div, p):not(.edify-cell-row):not(.edify-empty-state) +",
            css,
        )

        script = _read("static/js/micro-ux.js")
        self.assertIn(
            "'.flex, .grid, .inline-flex, form, .edify-empty-state'",
            script,
        )
        self.assertIn(
            ".edify-cell-hidden, .edify-empty-state'",
            script,
        )


class NoteTest(SimpleTestCase):
    def test_the_notes_use_the_shared_component(self):
        for template in NOTE_TEMPLATES:
            with self.subTest(template=template):
                source = _read(template)
                self.assertIn('class="edify-note', source)

    def test_a_note_carries_its_tone_the_way_the_platform_does(self):
        """A rule down the inline edge and a wash mixed from the tone token —
        not a flat `bg-amber-50`, which is one theme's colour written into the
        markup."""

        css = _read("static/css/components.css")
        block = css[css.index("\n.edify-note {") :]
        block = block[: block.index("\n}")]
        self.assertIn("border-inline-start: 3px solid", block)
        self.assertIn("color-mix(in srgb, var(--edify-note-tone)", block)

        for tone, token in (
            ("warning", "--edify-warning-text"),
            ("danger", "--edify-danger-text"),
            ("success", "--edify-success-text"),
            ("info", "--edify-accent"),
        ):
            self.assertIn(
                f'.edify-note[data-tone="{tone}"] {{ --edify-note-tone: var({token}); }}',
                css,
            )

    def test_the_converted_notes_carry_no_hand_picked_tint(self):
        tint = re.compile(
            r"bg-(amber|emerald|rose|slate|sky|indigo|violet|blue|teal)-50"
            r"(?:/\d+)? border border-\1-100"
        )
        for template in NOTE_TEMPLATES:
            with self.subTest(template=template):
                source = _read(template)
                offenders = [
                    line.strip()[:110]
                    for line in source.split("\n")
                    if tint.search(line)
                    and not re.search(r"\bh-\d+ w-\d+\b|\bw-\d+ h-\d+\b", line)
                ]
                self.assertEqual(offenders, [])
