"""Tick boxes that act on a group (owner, 2026-10-05).

"can you add cancel activity from the activity profile ... add also group
reschedule where the users use checkboxes ... Also all the places with
checkboxes can you add 'Select All' Checkbox. look into the entire platform
where there are checkboxes. Add checkboxes to the calendar entry so people can
reschedule from the calendar direct. Make sure group cancel also is there."

What is pinned here: where the tick boxes and the bar are drawn and for whom,
Cancel on the activity's own page and drawer, and that a template which
repeats a tick box offers Select all. The service and its two drawers are
pinned in apps/activities/test_group_actions.py.
"""

from __future__ import annotations

import re

from django.conf import settings
from django.test import SimpleTestCase

from apps.activities.test_group_actions import GroupFixture
from apps.activities.test_profile_activities import PASSWORD

TEMPLATES = settings.BASE_DIR / "templates"
PICK = "data-activity-pick"
BAR = "data-activity-bar"


class TickBoxesOnThePlan(GroupFixture):
    def setUp(self):
        super().setUp()
        self.visit = self._visit(self.fresh)
        self.client.login(email=self.cceo.email, password=PASSWORD)

    def _plan(self, **params):
        return self.client.get(
            "/my-plan",
            {"period": "fy", "fy": self.visit.fy, **params},
        )

    def test_my_plan_ticks_live_rows_and_carries_the_bar(self):
        response = self._plan()

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'value="{self.visit.id}" {PICK}', html)
        self.assertIn('data-select-all="input[data-activity-pick]"', html)
        self.assertEqual(html.count(BAR), 1)
        self.assertIn('hx-get="/activity-selection/reschedule"', html)
        self.assertIn('hx-get="/activity-selection/cancel"', html)
        # Finished work has no box: nothing to move or call off.
        self.assertNotIn(f'value="{self.verified.id}" {PICK}', html)

    def test_the_rows_say_which_can_be_ticked(self):
        rows = {row["id"]: row for row in self._plan().context["school_visits"]}

        self.assertTrue(rows[self.visit.id]["can_pick"])
        if self.verified.id in rows:
            self.assertFalse(rows[self.verified.id]["can_pick"])

    def test_a_profile_ticks_planned_rows_for_the_one_who_runs_them(self):
        own = self.client.get(f"/schools/{self.school.school_id}")
        self.assertEqual(own.status_code, 200)
        self.assertContains(own, f'value="{self.planned.id}" {PICK}')
        self.assertContains(own, BAR)

        self.client.login(email=self.pl.email, password=PASSWORD)
        supervised = self.client.get(f"/schools/{self.school.school_id}")
        self.assertEqual(supervised.status_code, 200)
        # A supervisor reads the plan and is offered no box and no bar.
        self.assertNotContains(supervised, PICK)
        self.assertNotContains(supervised, BAR)

    def test_the_calendar_entry_carries_a_tick_box(self):
        day = self.visit.planned_date

        response = self.client.get("/calendar", {"year": day.year, "month": day.month})

        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn(f'value="{self.visit.id}" {PICK}', html)
        self.assertIn("calendar-event--pick", html)
        self.assertEqual(html.count(BAR), 1)
        self.assertTrue(response.context["pickable_total"])
        # Still a link to the activity, beside the box rather than around it.
        self.assertRegex(
            html,
            r'<a href="/my-plan/%s" class="calendar-event__copy">' % self.visit.id,
        )

    def test_a_supervisors_calendar_has_no_tick_boxes(self):
        day = self.visit.planned_date
        self.client.login(email=self.pl.email, password=PASSWORD)

        response = self.client.get("/calendar", {"year": day.year, "month": day.month})

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, PICK)
        self.assertFalse(response.context["pickable_total"])


class CancelOnTheActivityProfile(GroupFixture):
    def setUp(self):
        super().setUp()
        self.visit = self._visit(self.fresh)

    def _page(self, user, activity, *, drawer=False):
        self.client.login(email=user.email, password=PASSWORD)
        headers = {"HTTP_HX_REQUEST": "true"} if drawer else {}
        return self.client.get(f"/my-plan/{activity.id}", **headers)

    def test_the_page_offers_cancel_on_live_work(self):
        response = self._page(self.cceo, self.visit)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["can_cancel"])
        self.assertContains(
            response, f'hx-get="/my-plan/{self.visit.id}/cancel-drawer"'
        )
        self.assertContains(response, "Cancel Activity")

    def test_the_drawer_offers_it_too(self):
        response = self._page(self.cceo, self.visit, drawer=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, f'hx-get="/my-plan/{self.visit.id}/cancel-drawer"'
        )
        self.assertContains(response, "data-cancel-trigger")

    def test_finished_work_has_no_cancel(self):
        response = self._page(self.cceo, self.verified)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_cancel"])
        self.assertNotContains(response, "cancel-drawer")

    def test_a_supervisor_is_not_offered_it(self):
        """Role-blocked actions are hidden, not greyed (owner, 2026-09-27)."""
        response = self._page(self.pl, self.visit)

        if response.status_code == 200:
            self.assertFalse(response.context["can_cancel"])
            self.assertNotContains(response, "cancel-drawer")


class SelectAllContract(SimpleTestCase):
    """A template that repeats a tick box offers Select all."""

    #: Lists where ticking everything is not a choice anyone makes: each box
    #: is a finding or a grant of its own. Every entry says why.
    EXEMPT = {
        "pages/ia/review_workspace.html": "return reasons; the checklist above "
        "them is nine separate attestations",
        "partials/oversight/partner_return_drawer.html": "return reasons",
        "partials/hr/form_drawer.html": "the Programme Lead's return reasons",
        "partials/leave/impact_panel.html": "read-only ticks, never changed",
        "pages/documents/compliance.html": "one Resolve box in each comment's "
        "own form",
        "partials/today/queue_item.html": "one attestation in each item's own form",
        "partials/today/queue_row.html": "one attestation in each item's own form",
        "partials/activities/pick_cell.html": "one box; its table's header "
        "carries the Select all (pick_head.html)",
    }
    MARKERS = (
        "data-select-all",
        "partials/components/select_all.html",
        "partials/activities/pick_head.html",
        "components/school_plan_table_head.html",
        "toggleAll",
        "togglePage",
        "allChecked",
        "Select all",
        "Select page",
        "Select every",
    )
    LOOP = re.compile(
        r"\{%\s*for\b|\{%\s*endfor\s*%\}|<template\s+x-for|</template>", re.I
    )
    BOX = re.compile(r'type="checkbox"', re.I)

    def _repeats_a_box(self, text: str) -> bool:
        depth = 0
        position = 0
        events = [(m.start(), m.group(0).lower()) for m in self.LOOP.finditer(text)]
        boxes = [m.start() for m in self.BOX.finditer(text)]
        for box in boxes:
            while position < len(events) and events[position][0] < box:
                token = events[position][1]
                if "endfor" in token or token.startswith("</template"):
                    depth = max(0, depth - 1)
                else:
                    depth += 1
                position += 1
            if depth > 0:
                return True
        return False

    def test_every_repeated_tick_box_has_a_select_all(self):
        missing = []
        for path in sorted(TEMPLATES.rglob("*.html")):
            name = str(path.relative_to(TEMPLATES))
            text = path.read_text()
            if not self._repeats_a_box(text) or name in self.EXEMPT:
                continue
            # A row partial is ticked by the table that includes it.
            if not any(marker in text for marker in self.MARKERS):
                missing.append(name)
        row_partials = {
            "partials/planning/school_row.html",
            "partials/schools/directory_row.html",
            "partials/oversight/partner_school_row.html",
            "partials/oversight/partner_core_row.html",
        }
        self.assertEqual(
            [name for name in missing if name not in row_partials],
            [],
            "these templates repeat a tick box without a Select all",
        )

    def test_a_table_that_ticks_activities_has_the_header_box(self):
        for path in sorted(TEMPLATES.rglob("*.html")):
            text = path.read_text()
            if "partials/activities/pick_cell.html" not in text:
                continue
            with self.subTest(template=str(path.relative_to(TEMPLATES))):
                self.assertIn("partials/activities/pick_head.html", text)

    def test_the_script_is_loaded_by_the_shell(self):
        base = (TEMPLATES / "base.html").read_text()
        self.assertIn("js/group-select.js", base)

    def test_exemptions_still_exist(self):
        for name in self.EXEMPT:
            self.assertTrue((TEMPLATES / name).exists(), name)
