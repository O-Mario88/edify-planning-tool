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


class ClusterActionsAreOneMenuTest(SimpleTestCase):
    """A cluster's actions are one menu too (owner, 2026-09-26: "Check all
    clusters action buttons. The one action button with options should be
    implemented in all the platform"). The card offered Schedule and Assign
    in its menu and then, once opened, Schedule a Day of Visits and Add
    Schools as two more buttons above its schools."""

    CLUSTER = {"id": "c1", "name": "Cluster A", "risk": "healthy", "planning": {}}

    def _card(self, **flags):
        return render_to_string(
            "partials/clusters/cluster_card.html", {"cluster": self.CLUSTER, **flags}
        )

    def _items(self, html):
        return re.findall(r'role="menuitem"[^>]*>([^<]+)<', html)

    def test_a_planner_gets_every_cluster_action_in_the_card_menu(self):
        html = self._card(can_plan_clusters=True, can_add_cluster_schools=True)
        self.assertEqual(html.count("data-row-actions"), 1)
        self.assertEqual(
            self._items(html),
            [
                "Schedule Group Training",
                "Schedule Cluster Meeting",
                "Schedule a Day of Visits",
                "Partner to Facilitate",
                "Add Schools",
            ],
        )
        self.assertIn('hx-get="/clusters/c1/bulk-schedule-drawer"', html)
        self.assertIn('hx-get="/clusters/c1/bulk-assign-drawer"', html)

    def test_a_role_that_may_only_add_schools_gets_that_one_item(self):
        html = self._card(can_plan_clusters=False, can_add_cluster_schools=True)
        self.assertEqual(self._items(html), ["Add Schools"])

    def test_a_role_with_neither_gets_no_menu(self):
        self.assertNotIn("data-row-actions", self._card())

    def test_the_schools_table_ticks_schools_to_assign_to_a_partner(self):
        """Owner, 2026-09-29: a tick in the first column of the cluster's
        school list, for the schools that may go to a partner."""
        school = {
            "id": "s1",
            "schoolId": "S-1",
            "name": "Kasubi Primary",
            "canAssignPartner": True,
            "planningBadges": [],
        }
        blocked = {**school, "id": "s2", "schoolId": "S-2", "canAssignPartner": False}
        html = render_to_string(
            "partials/clusters/cluster_schools_table.html",
            {
                "schools": [school, blocked],
                "cluster_id": "c1",
                "can_assign_partner": True,
            },
        )
        self.assertIn('class="school-plan-table__select"', html)
        self.assertIn('value="S-1" x-model="selectedSchools"', html)
        self.assertNotIn('value="S-2" x-model="selectedSchools"', html)
        self.assertIn("/planning/bulk-assign-partner-drawer", html)
        self.assertIn("Assign to partner", html)
        # The first cell of the row is the tick.
        row = html.split('class="cluster-school-row"', 1)[1]
        self.assertLess(
            row.index("school-plan-table__select"), row.index('data-label="School ID"')
        )
        # Nothing on the list can go to a partner: no empty tick column,
        # which phones would pin as though it were the school's identity.
        none_open = render_to_string(
            "partials/clusters/cluster_schools_table.html",
            {"schools": [blocked], "cluster_id": "c1", "can_assign_partner": True},
        )
        self.assertNotIn("school-plan-table__select", none_open)
        # No assign permission: no tick column.
        plain = render_to_string(
            "partials/clusters/cluster_schools_table.html",
            {"schools": [school], "cluster_id": "c1", "can_assign_partner": False},
        )
        self.assertNotIn("school-plan-table__select", plain)

    def test_the_schools_table_no_longer_carries_its_own_buttons(self):
        html = render_to_string(
            "partials/clusters/cluster_schools_table.html",
            {"schools": [], "cluster_id": "c1", "can_bulk_schedule": True},
        )
        header = html.split("Schools in Cluster", 1)[1].split("This cluster has no", 1)[
            0
        ]
        self.assertNotIn("<button", header)
        self.assertNotIn("bulk-schedule-drawer", html)
