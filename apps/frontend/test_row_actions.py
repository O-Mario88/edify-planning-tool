"""One record's actions are one Actions menu (owner, 2026-09-26).

"Fix the tablet mode action buttons — it is wrapping Schedule and Assign
buttons instead of the same row. For it to be neat, switch to Action button
with options to schedule and assign. Every page use actions with dropdown
options."

`{% row_actions %}` (apps/frontend/templatetags/row_actions.py) wraps a row's
items in components/row_actions.html; these tests pin what every row gets from
it, and the Planning school row as the first user.
"""

from __future__ import annotations

import re

from django.template import Context, Template
from django.template.loader import render_to_string
from django.test import SimpleTestCase


def _render(source: str, **context) -> str:
    return Template("{% load row_actions %}" + source).render(Context(context))


class RowActionsTagTest(SimpleTestCase):
    def test_items_are_wrapped_in_the_shared_menu(self):
        html = _render(
            "{% row_actions name %}"
            '<button type="button" class="row-menu__item" role="menuitem">Schedule</button>'
            '<button type="button" class="row-menu__item" role="menuitem">Assign</button>'
            "{% endrow_actions %}",
            name="Kasubi Primary",
        )
        self.assertIn("data-row-actions", html)
        self.assertIn('x-data="rowMenu"', html)
        self.assertIn('class="row-menu__trigger"', html)
        self.assertIn('aria-haspopup="menu"', html)
        self.assertIn('aria-label="Actions for Kasubi Primary"', html)
        self.assertIn('role="menu"', html)
        list_html = html.split('role="menu"', 1)[1]
        self.assertIn(">Schedule</button>", list_html)
        self.assertIn(">Assign</button>", list_html)

    def test_the_record_name_is_escaped(self):
        html = _render(
            '{% row_actions name %}<a class="row-menu__item" role="menuitem" href="/x">Open</a>{% endrow_actions %}',
            name='St. "Mary\'s" <Primary>',
        )
        self.assertIn("Actions for St. &quot;Mary&#x27;s&quot; &lt;Primary&gt;", html)

    def test_a_row_with_nothing_to_offer_renders_nothing(self):
        html = _render(
            "{% row_actions name %}{% if allowed %}<button>Schedule</button>{% endif %}"
            "{% endrow_actions %}",
            name="Kasubi Primary",
            allowed=False,
        )
        self.assertEqual(html.strip(), "")

    def test_the_menu_answers_the_keyboard(self):
        shell = render_to_string(
            "components/row_actions.html", {"items": "", "name": ""}
        )
        for binding in (
            '@keydown.arrow-down.prevent="move(1)"',
            '@keydown.arrow-up.prevent="move(-1)"',
            '@keydown.home.prevent="focusItem(0)"',
            '@keydown.end.prevent="focusItem(-1)"',
            '@keydown.escape.window="open && dismiss()"',
            "focusItem(0)",
        ):
            self.assertIn(binding, shell)
        # An unavailable item keeps the list open; any other item closes it.
        self.assertIn("[role=menuitem]:not([aria-disabled=true])", shell)


class PlanningRowIsOneMenuTest(SimpleTestCase):
    """The Planning school row: Schedule and Assign, one menu, one line."""

    def _row(self, **school):
        base = {
            "id": "s1",
            "schoolId": "S-1",
            "name": "Kasubi Primary",
            "staffCanSchedule": True,
            "canAssignPartner": True,
            "blockedActions": [],
            "planningBadges": [],
        }
        base.update(school)
        return render_to_string(
            "partials/planning/school_row.html",
            {"school": base, "can_schedule": True, "can_assign_partner": True},
        )

    def _actions_cell(self, html):
        return html.split('data-label="Actions"', 1)[1].split("</td>", 1)[0]

    def test_schedule_and_assign_are_items_of_one_menu(self):
        cell = self._actions_cell(self._row())
        self.assertEqual(cell.count("data-row-actions"), 1)
        self.assertNotIn("school-record-action", cell)
        items = re.findall(r'role="menuitem"[^>]*>(\w+)', cell)
        self.assertEqual(items, ["Schedule", "Assign"])
        self.assertIn('hx-get="/planning/schedule-modal?school_id=S-1"', cell)
        self.assertIn('hx-get="/planning/assign-partner-modal?school_id=S-1"', cell)

    def test_a_locked_action_stays_on_the_menu_and_says_why(self):
        cell = self._actions_cell(
            self._row(
                staffCanSchedule=False,
                staffScheduleReason="Visited this year already.",
            )
        )
        schedule = cell.split('data-visit-locked="true"', 1)[1].split("</button>", 1)[0]
        self.assertIn(
            '<span class="row-menu__reason">Visited this year already.</span>', schedule
        )
        locked = re.search(r"<button[^>]*data-visit-locked=\"true\"[^>]*>", cell).group(
            0
        )
        self.assertIn('aria-disabled="true"', locked)
        self.assertNotIn("hx-get", locked)
