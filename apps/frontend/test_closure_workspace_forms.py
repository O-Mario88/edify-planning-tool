"""The closure workspace's Close & Lock and Reopen forms reach their actions.

Both posted to a trailing-slash path ("/activities/<id>/closure/close/",
"/activities/<id>/reopen/") while the routes have none, so each press was a
404 and no activity could be closed or reopened from the workspace. Found by
the interaction inventory's route check (2026-09-24 audit).
"""

from __future__ import annotations

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import resolve

from apps.accounts.models import StaffProfile
from apps.activities.models import Activity
from apps.geography.models import District, Region
from apps.schools.models import School


class ClosureWorkspaceFormsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            email="closure-forms@edify.test",
            password="password123",
            name="Closure Forms",
            roles=["Admin"],
            active_role="Admin",
            is_active=True,
        )
        StaffProfile.objects.create(id="closure-forms-staff", user=cls.user)
        region = Region.objects.create(name="Closure Forms Region")
        district = District.objects.create(name="Closure Forms District", region=region)
        school = School.objects.create(
            school_id="CLOSURE-FORMS-1",
            name="Closure Forms School",
            region=region,
            district=district,
        )
        cls.open_activity = Activity.objects.create(
            school=school, activity_type="school_visit", status="completed"
        )
        cls.closed_activity = Activity.objects.create(
            school=school, activity_type="school_visit", status="closed"
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _form_actions(self, activity):
        response = self.client.get(f"/activities/{activity.id}/closure/")
        self.assertEqual(response.status_code, 200)
        return re.findall(r'<form[^>]*action="([^"]+)"', response.content.decode())

    def test_every_form_on_the_workspace_resolves(self):
        from unittest import mock

        from apps.activities.closure_services import ClosureEligibilityService

        with mock.patch.object(
            ClosureEligibilityService, "_core_requirements_met", return_value=True
        ):
            actions = self._form_actions(self.open_activity)
        actions += self._form_actions(self.closed_activity)
        names = {resolve(action).func.__name__ for action in actions}
        self.assertIn("close_activity_action", names)
        self.assertIn("reopen_activity_action", names)

    def test_the_close_form_posts_to_the_close_action(self):
        response = self.client.post(
            f"/activities/{self.open_activity.id}/closure/close"
        )
        # The action runs (and refuses an ineligible activity) and redirects
        # back to the workspace; the old trailing-slash path was a 404.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"], f"/activities/{self.open_activity.id}/closure/"
        )
