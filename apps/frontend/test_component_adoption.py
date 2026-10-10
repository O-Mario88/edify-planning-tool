"""Page components: what they render, and how far the platform has moved to them.

The UI audit of 2026-10-01 named one root cause for the drift it found: pages
are hand-written markup, and the stylesheets recognise what a thing is by
guessing — a substring of a class name, a `:has()` chain, an id in a list —
and then override it with `!important`. The remedy is a rewrite into
components, which is a project and not a change; this file is its first stage
and its meter.

The first half pins the three components' behaviour
(apps/frontend/templatetags/components.py). The second half is a set of
ratchets, the same idea as test_design_token_ratchet.py: each ceiling is
today's count of the thing being replaced. A change may lower a count and its
ceiling; none may raise one. docs/ui-components.md says what to write instead.

Tables are counted in that document and not held here: {% data_table %} is one
table anatomy of about a hundred on the platform, and a ceiling would fail a
new table the component cannot yet express.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest import TestCase

from django.template import Context, Template, TemplateSyntaxError
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
SOURCE_CSS = ROOT / "static" / "css"

#: Page headers still written out by hand, tag by tag. 217 before the first
#: migration (2026-10-02), which moved the 105 whose markup was already the
#: canonical anatomy. What is left differs from it: a wrapper between the
#: header and its lead, a width utility that is live, a second row.
HAND_WRITTEN_HEADER_CEILING = 112

#: Filter forms that wire "apply on change" themselves instead of using
#: {% filter_bar %}. Each carries its own class set and its own fallback
#: button; seven that already had the component's class moved on 2026-10-02.
HAND_WIRED_FILTER_FORM_CEILING = 12

#: The two tools of restyling by guesswork, counted across the source
#: stylesheets: `!important`, and selectors that match a substring of a class
#: name. A component with a class of its own needs neither. The counts on
#: 2026-10-02 were 3,959 and 567; each ceiling sits ten above its count so that
#: branches already in flight that day can land. Lower them to the real counts
#: as those merge, and from then on only downwards. (`!important` fell to 3,953
#: later that day, when the calendar's event tabs stopped being a grid forced
#: over the rail; its ceiling keeps the same ten. 3,937 on 2026-10-08, when the
#: school name on the planning tables became a link and the rules that had
#: forced the old name button into its column went with it.)
#: Raised to the count, 3,958, on 2026-10-10 for three things the owner asked
#: for that day, each of which has to outrank rules that are themselves
#: `!important`: the drawer that opens under its own icon (the one drawer
#: shape and its phone sheet are forced, by four earlier passes, in
#: drawers.css), one body type in every table (over the size and weight
#: utilities templates write on cells), and compact rows (the tick box's
#: touch size). The desktop text-wrapping rules they replace are gone. No
#: headroom: from here only downwards.
IMPORTANT_CEILING = 3958
CLASS_SUBSTRING_SELECTOR_CEILING = 577

_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HEADER = re.compile(
    r"<(?:div|header|section)\b[^>]*\bclass=\"[^\"]*"
    r"(?<![\w-])edify-page-header(?![\w-])[^\"]*\""
)
_AUTO_FORM = re.compile(r"<form\b[^>]*requestSubmit\(\)")


def _page_templates():
    """Every template but the components' own."""
    for path in sorted(TEMPLATES.rglob("*.html")):
        if path.parent == TEMPLATES / "components":
            continue
        yield path, path.read_text(encoding="utf-8")


def _count(pattern: re.Pattern) -> tuple[int, list[str]]:
    found = {
        str(path.relative_to(ROOT)): len(pattern.findall(source))
        for path, source in _page_templates()
    }
    worst = sorted(found.items(), key=lambda item: -item[1])[:8]
    return sum(found.values()), [f"  {count:>3}  {name}" for name, count in worst]


def _css_count(pattern: str) -> int:
    total = 0
    for sheet in sorted(SOURCE_CSS.rglob("*.css")):
        if "vendor" in sheet.parts or sheet.name in {"main.css", "tokens.css"}:
            continue
        total += len(re.findall(pattern, _COMMENT.sub("", sheet.read_text())))
    return total


def _render(source: str, **context) -> str:
    return Template("{% load components %}" + source).render(Context(context))


def _flat(html: str) -> str:
    return re.sub(r">\s+<", "><", " ".join(html.split()))


class PageHeaderComponentTests(SimpleTestCase):
    def test_it_writes_the_canonical_anatomy(self):
        html = _flat(
            _render(
                '{% page_header eyebrow="Finance" title="Cost Catalogue" '
                'description="Approved cost items." %}'
                '<a href="/new">Add cost</a>{% endpage_header %}'
            )
        )
        self.assertEqual(
            html,
            '<header class="edify-page-header">'
            '<div class="edify-page-header__lead">'
            '<p class="edify-page-eyebrow">Finance</p>'
            '<h1 class="edify-page-title edify-page-header__title">'
            "Cost Catalogue</h1>"
            '<p class="edify-page-header__description">Approved cost items.</p>'
            "</div>"
            '<div class="edify-page-header__controls">'
            '<a href="/new">Add cost</a></div>'
            "</header>",
        )

    def test_parts_a_page_does_not_have_are_not_drawn(self):
        html = _render('{% page_header title="Settings" %}{% endpage_header %}')
        self.assertNotIn("edify-page-eyebrow", html)
        self.assertNotIn("edify-page-header__description", html)
        # A header whose controls render to nothing has no empty box beside
        # its title: the hand-written headers left one behind every role gate.
        self.assertNotIn("edify-page-header__controls", html)

        gated = _render(
            '{% page_header title="People" %}'
            '{% if can_add %}<a href="/new">New</a>{% endif %}'
            "{% endpage_header %}",
            can_add=False,
        )
        self.assertNotIn("edify-page-header__controls", gated)

    def test_a_part_with_logic_is_a_slot(self):
        html = _render(
            '{% page_header eyebrow="Planning" %}'
            "{% slot title %}{% if wide %}Country{% else %}Team{% endif %} "
            "Oversight{% endslot %}"
            "{% slot description %}{{ total }} visits{% endslot %}"
            "{% endpage_header %}",
            wide=True,
            total=12,
        )
        self.assertIn(">Country Oversight</h1>", html)
        self.assertIn(">12 visits</p>", html)

    def test_a_value_is_escaped_and_markup_in_the_body_is_kept(self):
        html = _render(
            "{% page_header title=name %}<a href='/x'>{{ name }}</a>"
            "{% endpage_header %}",
            name="R&D <team>",
        )
        self.assertIn(">R&amp;D &lt;team&gt;</h1>", html)
        self.assertIn("<a href='/x'>R&amp;D &lt;team&gt;</a>", html)

    def test_the_wrapper_can_stay_a_div_and_carry_an_aside(self):
        html = _flat(
            _render(
                '{% page_header title="Visits" element="div" %}'
                '{% slot aside %}<div id="export-slot"></div>{% endslot %}'
                "{% endpage_header %}"
            )
        )
        self.assertTrue(html.startswith('<div class="edify-page-header">'))
        self.assertTrue(html.endswith('<div id="export-slot"></div></div>'))

    def test_a_misspelt_argument_or_slot_fails_when_the_template_loads(self):
        with self.assertRaises(TemplateSyntaxError):
            _render('{% page_header titel="Visits" %}{% endpage_header %}')
        with self.assertRaises(TemplateSyntaxError):
            _render(
                '{% page_header title="Visits" %}'
                "{% slot subtitle %}x{% endslot %}{% endpage_header %}"
            )

    def test_the_include_still_renders_the_same_header(self):
        included = _flat(
            Template(
                '{% include "components/page_header.html" with eyebrow="A" '
                'title="B" description="C" %}'
            ).render(Context())
        )
        tagged = _flat(
            _render(
                '{% page_header eyebrow="A" title="B" description="C" %}'
                "{% endpage_header %}"
            )
        )
        self.assertEqual(included, tagged)


class FilterBarComponentTests(SimpleTestCase):
    def test_it_applies_on_change_and_keeps_a_button_only_without_script(self):
        html = _render(
            '{% filter_bar action="/loans" label="Loan filters" '
            'form_id="loan-filters" %}<select name="mfi"></select>'
            "{% endfilter_bar %}"
        )
        self.assertIn(
            '<form method="get" action="/loans" id="loan-filters" '
            'class="edify-filter-bar" aria-label="Loan filters" '
            'x-data @change="$el.requestSubmit()">',
            html,
        )
        self.assertIn('<select name="mfi"></select>', html)
        buttons = re.findall(r"<button\b", html)
        fallback = re.findall(
            r"<noscript><button\b[^>]*>Apply</button></noscript>", html
        )
        self.assertEqual((len(buttons), len(fallback)), (1, 1))

    def test_a_clear_link_is_drawn_when_the_page_names_one(self):
        self.assertNotIn(">Clear<", _render("{% filter_bar %}{% endfilter_bar %}"))
        html = _render('{% filter_bar reset_url="/loans" %}{% endfilter_bar %}')
        self.assertIn('<a href="/loans" class="btn btn-secondary h-9">Clear</a>', html)


class DataTableComponentTests(SimpleTestCase):
    def test_it_writes_the_card_the_title_band_and_the_scroll_region(self):
        html = _flat(
            _render(
                '{% data_table name="overdue" title="Overdue actions" '
                'caption="Actions past their date." %}'
                "{% slot summary %}{{ total }} actions{% endslot %}"
                "{% slot footer %}<nav>pager</nav>{% endslot %}"
                "<tbody><tr><td>One</td></tr></tbody>"
                "{% enddata_table %}",
                total=3,
            )
        )
        self.assertTrue(
            html.startswith(
                '<section class="card p-0 overflow-hidden" '
                'aria-labelledby="overdue-title">'
                '<header class="edify-table-titlebar '
            )
        )
        self.assertIn('<h3 id="overdue-title">Overdue actions</h3>', html)
        self.assertIn('<span class="tabular-nums">3 actions</span>', html)
        self.assertIn(
            '<div class="overflow-x-auto"><table class="edify-record-table ', html
        )
        self.assertIn('data-mobile-table="scroll">', html)
        self.assertIn(
            '<caption class="sr-only">Actions past their date.</caption>', html
        )
        self.assertIn("</table></div><nav>pager</nav></section>", html)

    def test_no_rows_draws_the_empty_slot_in_the_table_s_place(self):
        html = _render(
            '{% data_table title="Overdue actions" %}'
            "{% slot empty %}<p>Nothing overdue.</p>{% endslot %}"
            "{% slot footer %}<nav>pager</nav>{% endslot %}"
            "{% if rows %}<tbody></tbody>{% endif %}"
            "{% enddata_table %}",
            rows=[],
        )
        self.assertIn("<p>Nothing overdue.</p>", html)
        self.assertNotIn("<table", html)
        self.assertNotIn("pager", html)


class ComponentAdoptionRatchetTests(TestCase):
    def test_the_migrated_pages_use_the_components(self):
        """A floor under the first migration, so it cannot be quietly undone."""
        used = {"page_header": 0, "filter_bar": 0, "data_table": 0}
        for _path, source in _page_templates():
            for name in used:
                used[name] += source.count("{% " + name + " ")
        self.assertGreaterEqual(used["page_header"], 105, used)
        self.assertGreaterEqual(used["filter_bar"], 7, used)
        self.assertGreaterEqual(used["data_table"], 4, used)

    def test_every_template_that_uses_a_component_loads_the_library(self):
        missing = [
            str(path.relative_to(ROOT))
            for path, source in _page_templates()
            if re.search(r"{% (?:page_header|filter_bar|data_table) ", source)
            and not re.search(r"{%\s*load\b[^%]*\bcomponents\b", source)
        ]
        self.assertEqual(missing, [])

    def test_hand_written_page_headers_do_not_grow(self):
        total, worst = _count(_HEADER)
        self.assertLessEqual(
            total,
            HAND_WRITTEN_HEADER_CEILING,
            f"{total} hand-written page headers, ceiling "
            f"{HAND_WRITTEN_HEADER_CEILING}. Use {{% page_header %}} "
            "(docs/ui-components.md).\n" + "\n".join(worst),
        )

    def test_hand_wired_filter_forms_do_not_grow(self):
        total, worst = _count(_AUTO_FORM)
        self.assertLessEqual(
            total,
            HAND_WIRED_FILTER_FORM_CEILING,
            f"{total} filter forms wire apply-on-change themselves, ceiling "
            f"{HAND_WIRED_FILTER_FORM_CEILING}. Use {{% filter_bar %}}.\n"
            + "\n".join(worst),
        )

    def test_important_does_not_grow(self):
        total = _css_count(r"!important")
        self.assertLessEqual(
            total,
            IMPORTANT_CEILING,
            f"{total} `!important` declarations, ceiling {IMPORTANT_CEILING}. "
            "Give the thing a class of its own instead of outranking a guess.",
        )

    def test_class_substring_selectors_do_not_grow(self):
        total = _css_count(r"\[class[*^$]=")
        self.assertLessEqual(
            total,
            CLASS_SUBSTRING_SELECTOR_CEILING,
            f"{total} selectors match a substring of a class name, ceiling "
            f"{CLASS_SUBSTRING_SELECTOR_CEILING}. Select the component's class.",
        )

    def test_the_ceilings_are_kept_tight(self):
        """A ceiling far above the real count is no ratchet. When a change
        lowers a count, lower its ceiling in the same change."""
        slack = {
            "headers": HAND_WRITTEN_HEADER_CEILING - _count(_HEADER)[0],
            "filter forms": HAND_WIRED_FILTER_FORM_CEILING - _count(_AUTO_FORM)[0],
            "!important": IMPORTANT_CEILING - _css_count(r"!important"),
            "substring selectors": CLASS_SUBSTRING_SELECTOR_CEILING
            - _css_count(r"\[class[*^$]="),
        }
        loose = {name: gap for name, gap in slack.items() if gap > 15}
        self.assertEqual(loose, {}, "lower these ceilings to the real counts")
