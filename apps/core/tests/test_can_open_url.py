"""A link is only offered to someone who can follow it (visual test,
2026-09-14): the shared check behind the `can_open` filter and the To-Do queue."""

from __future__ import annotations

from unittest.mock import patch

from django.test import TestCase

from apps.accounts.models import User
from apps.core.permissions import can_open_url, page_permission_for_url


def _user(role, email):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )


class CanOpenUrlTest(TestCase):
    def test_a_url_is_judged_by_the_page_gate_on_its_view(self):
        self.assertEqual(
            page_permission_for_url("/leave/team-availability"), "team_availability"
        )
        cceo = _user("CCEO", "open-cceo@t.org")
        lead = _user("Program Lead", "open-pl@t.org")
        self.assertFalse(can_open_url(cceo, "/leave/team-availability"))
        self.assertTrue(can_open_url(lead, "/leave/team-availability"))
        self.assertTrue(
            can_open_url(lead, "/leave/team-availability?week=2026-09-14"),
            "a query string does not change the page",
        )

    def test_unknown_or_empty_urls(self):
        cceo = _user("CCEO", "open-cceo2@t.org")
        self.assertTrue(can_open_url(cceo, "/no-such-route-here"))
        self.assertTrue(can_open_url(cceo, "https://example.org/elsewhere"))
        self.assertFalse(can_open_url(cceo, ""))

    def test_the_queue_lists_only_work_the_person_can_open(self):
        from apps.command_center import todo_service

        partner = _user("PartnerFieldOfficer", "open-partner@t.org")
        rows = [
            {
                "id": "open-row",
                "title": "Open me",
                "category": "Test",
                "priority": "high",
                "status_key": "waiting_me",
                "actionable": True,
                "action_url": "/my-plan",
                "_due_sort": "2026-09-14",
            },
            {
                "id": "closed-row",
                "title": "Not mine",
                "category": "Test",
                "priority": "high",
                "status_key": "waiting_me",
                "actionable": True,
                "action_url": "/clusters",
                "_due_sort": "2026-09-14",
            },
        ]
        with patch.object(todo_service, "_module_todos", return_value=rows):
            ids = [t["id"] for t in todo_service.get_todos(partner)["todos"]]
        self.assertIn("open-row", ids)
        self.assertNotIn("closed-row", ids)
