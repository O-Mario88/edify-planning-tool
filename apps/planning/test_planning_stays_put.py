"""Scheduling saves the work and leaves the planner where they are.

Owner, 2026-09-18: "When I schedule, it opens My Plan immediately upon saving.
For me to continue planning, I have to go back to the planning page or core
planning or cluster... I want it to populate my plan without necessarily
opening My Plan, so the user can keep planning until they are done and then
open My Plan to confirm."

The activity landing on My Plan never depended on My Plan being open — it is
the same record either way. What the navigation actually cost was the planner's
place in the list, once per activity.

Three things stand in for the page load, and all three are asserted here,
because "stay here" without them is indistinguishable from a save that failed:
the drawer closes, the list behind it refreshes, and the confirmation is
painted now rather than queued for a page load that is not coming.
"""

from __future__ import annotations

import json
import pathlib

from django.test import Client

from apps.activities.models import Activity
from apps.planning.test_standard_support_scheduling import (
    StandardSupportBase,
    _schedulable_date,
)


class SchedulingStaysOnThePageTest(StandardSupportBase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.force_login(self.user)

    def _schedule(self, **extra):
        payload = {
            "school_id": self.school.school_id,
            "scheduled_date": _schedulable_date().isoformat(),
            "activity_purpose_text": "Show the donor the new classroom block",
            "expected_outcome": "Donor sees the work",
            "purpose_of_visit": "donor_visit",
            "catalogue_item_id": self.item("STANDARD_SCHOOL_VISIT").id,
            **extra,
        }
        return self.client.post(
            "/planning/schedule-action", payload, HTTP_HX_REQUEST="true"
        )

    def test_the_work_is_saved(self):
        """The control. Everything below is worthless if the save regressed."""
        response = self._schedule()

        self.assertIn(response.status_code, (200, 204))
        self.assertIsNotNone(Activity.objects.order_by("-created_at").first())

    def test_the_planner_is_not_sent_to_my_plan(self):
        body = self._schedule().content.decode()

        self.assertNotIn("window.location.href", body)
        self.assertNotIn("window.location.reload", body)

    def test_the_drawer_closes_and_the_list_behind_it_refreshes(self):
        """A row still offering to schedule work that is already scheduled is
        how the same visit gets planned twice."""
        response = self._schedule()

        triggers = json.loads(response["HX-Trigger"])
        self.assertIn("close-drawer", triggers)
        self.assertIn("planning-saved", triggers)

    def test_the_confirmation_is_painted_now_rather_than_queued(self):
        """`messages.success` paints on a page load, and this flow has none.

        A queued message would surface on whatever page the planner opened
        next, long after it stopped meaning anything.
        """
        response = self._schedule()
        body = response.content.decode()

        self.assertIn('hx-swap-oob="beforeend:#toast-container"', body)
        self.assertIn("scheduled", body.lower())
        # The link is offered, not followed: the planner decides when they are
        # done, which is the point of the whole change.
        self.assertIn("/my-plan", body)
        self.assertIn("Open My Plan", body)
        self.assertEqual(
            len(response.wsgi_request._messages._queued_messages)
            if hasattr(response.wsgi_request, "_messages")
            else 0,
            0,
            "a message queued for a page load that never comes is a "
            "confirmation the planner sees on some unrelated page later",
        )

    def test_the_planning_list_listens_for_the_refresh(self):
        """The event is only worth sending if something is listening.

        Read as source rather than rendered: the page extends a base chosen at
        request time, and what is asserted here is the wiring, which is in the
        template either way.
        """
        from django.template.loader import get_template

        source = pathlib.Path(
            get_template("pages/planning/index.html").origin.name
        ).read_text()

        self.assertIn("planning-saved from:body", source)
        self.assertIn('hx-target="#schools-table-container"', source)
