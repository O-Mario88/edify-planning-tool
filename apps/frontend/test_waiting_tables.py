"""Queues that wait on a person are tables with the action at the end of each
row (owner, 2026-09-23: "turn Waiting on you into a proper professional table
with Action button at the end of each row ... look at the ones that are not
table format").
"""

from __future__ import annotations

import re
from datetime import date

from django.template.loader import render_to_string
from django.test import Client, TestCase

from apps.accounts.models import StaffProfile, User
from apps.admin_ops.services import SupportTicketService


def _user(role, email):
    user = User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="x",
        is_active=True,
    )
    StaffProfile.objects.create(user=user, title=role)
    return user


def _table(html: str, marker: str) -> str:
    start = html.rindex("<table", 0, html.index(marker))
    return html[start : html.index("</table>", start)]


class FieldTodayWaitingTableTest(TestCase):
    def test_the_field_worker_s_queue_is_the_waiting_on_you_table(self):
        cceo = _user("CCEO", "waiting-cceo@example.test")
        self.client.force_login(cceo)
        html = self.client.get("/today/panel").content.decode()
        table = _table(html, "data-today-waiting-table")
        self.assertIn("data-waiting-table", table)
        self.assertEqual(
            re.findall(r'<th scope="col"[^>]*>([^<]+)</th>', table),
            ["Item", "Kind", "Status", "Due", "Actions"],
        )
        self.assertIn("Waiting on you", html)
        # The old bullet list is gone; exceptions keep their own panel.
        self.assertNotIn("Waiting for your confirmation", html)
        self.assertIn("Exceptions requiring attention", html)


class ProgrammeLeadCollaborationTablesTest(TestCase):
    def _render(self):
        return render_to_string(
            "partials/dashboards/pl/collaboration_view.html",
            {
                "fy": "2026",
                "collaboration": {
                    "regional_feedback": {"count": 1},
                    "regional_coaching": {"count": 1},
                    "cd_flags": {"open": 1, "overdue": 1},
                    "escalations": {"awaiting": 1, "delegated_back": 1},
                    "regional_rows": [
                        {
                            "subject": "Literacy training at Hope",
                            "detail": "Repeat the session",
                            "kind": "Training feedback",
                            "when_label": "Observed",
                            "when": date(2026, 9, 1),
                            "action_label": "Review",
                            "drawer": "/cce-leadership/feedback/fb-1",
                        },
                        {
                            "subject": "Q4 coaching",
                            "detail": "",
                            "kind": "Coaching conversation",
                            "when_label": "Held",
                            "when": date(2026, 9, 2),
                            "action_label": "Acknowledge",
                            "drawer": "/cce-leadership/coaching/co-1",
                        },
                    ],
                    "cd_rows": [
                        {
                            "subject": "Cluster A",
                            "detail": "Attendance evidence missing",
                            "kind": "Quality flag",
                            "due": date(2026, 9, 3),
                            "status": "Open",
                            "danger": True,
                            "action_label": "Answer",
                            "href": "/quality-checks",
                        },
                        {
                            "subject": "Budget overrun",
                            "detail": "",
                            "kind": "Escalation",
                            "due": None,
                            "status": "Awaiting decision · 4d open",
                            "danger": False,
                            "action_label": "View",
                            "href": "/escalations#esc-raised",
                        },
                        {
                            "subject": "Venue change",
                            "detail": "Decide locally",
                            "kind": "Delegated back",
                            "due": None,
                            "status": "Yours to act on",
                            "danger": True,
                            "action_label": "Act",
                            "href": "/escalations#esc-raised",
                        },
                    ],
                    "partner_delivery": {},
                },
                "collaboration_urls": {
                    "flags": "/quality-checks",
                    "escalations": "/escalations",
                    "feedback": "/cce-leadership/feedback",
                    "coaching": "/cce-leadership/coaching",
                    "partners": "/partner-oversight/",
                },
                "partner_engagement": {},
            },
        )

    def test_regional_lead_items_are_a_table_opening_each_record(self):
        table = _table(self._render(), "data-pl-regional-table")
        self.assertIn("data-waiting-table", table)
        self.assertIn('hx-get="/cce-leadership/feedback/fb-1"', table)
        self.assertIn('hx-get="/cce-leadership/coaching/co-1"', table)
        # The action is the last cell of every row.
        for row in re.findall(r"<tr>.*?</tr>", table.split("<tbody>")[1], re.S):
            self.assertIn('data-label="Action"', row.rsplit("<td", 1)[1])

    def test_country_director_items_are_a_table_with_an_action_each(self):
        table = _table(self._render(), "data-pl-cd-table")
        self.assertIn("data-waiting-table", table)
        for label, href in (
            ("Answer", "/quality-checks"),
            ("View", "/escalations#esc-raised"),
            ("Act", "/escalations#esc-raised"),
        ):
            self.assertIn(f'href="{href}">{label}<', table)
        self.assertNotIn("rpl-follow", table)


class AdminOpsQueuesTableTest(TestCase):
    def test_triage_is_a_table_whose_rows_submit_their_own_form(self):
        admin = _user("Admin", "waiting-admin@example.test")
        reporter = _user("CCEO", "waiting-reporter@example.test")
        ticket = SupportTicketService.create(reporter, {"title": "Cannot open"})
        client = Client()
        client.force_login(admin)
        html = client.get("/admin-ops/planning").content.decode()
        table = _table(html, "data-admin-triage-table")
        self.assertIn("data-waiting-table", table)
        self.assertIn(f'id="triage-{ticket.id}"', table)
        self.assertIn(f'form="triage-{ticket.id}"', table)
        self.assertIn(f'action="/admin-ops/tickets/{ticket.id}/triage"', table)
