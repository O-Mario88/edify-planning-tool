"""The surfaces: derived To-Dos, the two workspaces, and the health checks.

Separate from test_school_actions.py, which proves the lifecycle. This file
proves that what the lifecycle records actually reaches the people who need
it — a correct TeamAction nobody can see is the same failure as no record.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSchoolAssignment, User
from apps.core.rbac import EdifyRole
from apps.geography.models import District, Region
from apps.planning.action_health import school_action_health
from apps.planning.action_models import ActionState, TeamAction
from apps.planning.action_service import resolve_manually, return_to_sender, send_action
from apps.planning.action_workspace import (
    ISSUE_LABELS,
    actions_received,
    actions_sent,
    school_action_history,
)
from apps.planning.urgent_attention import resolve_urgent_issue
from apps.schools.models import School


def _user(email, role):
    return User.objects.create_user(
        email=email,
        name=email.split("@")[0],
        roles=[role],
        active_role=role,
        password="pw12345678",
        is_active=True,
        status="active",
    )


class SurfaceFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        region = Region.objects.create(name="SF Region")
        cls.district = District.objects.create(name="SF District", region=region)
        cls.fy = "2026"
        cls.cceo = _user("sf-cceo@t.org", EdifyRole.CCEO.value)
        cls.cceo_sp = StaffProfile.objects.create(user=cls.cceo, country="Uganda")
        cls.pl = _user("sf-pl@t.org", EdifyRole.COUNTRY_PROGRAM_LEAD.value)
        cls.pl_sp = StaffProfile.objects.create(user=cls.pl, country="Uganda")

    def _school(self, sid):
        school = School.objects.create(
            name=f"SF {sid}",
            school_id=sid,
            region_id=self.district.region_id,
            district_id=self.district.id,
            school_type="client",
        )
        StaffSchoolAssignment.objects.create(staff=self.cceo_sp, school_id=school.id)
        return school

    def _send(self, school, **kw):
        return send_action(
            sender=self.pl,
            school=school,
            issue=resolve_urgent_issue(school, self.fy, []),
            fy=self.fy,
            **kw,
        )


class DerivedTodoTests(SurfaceFixture):
    """The To-Do is derived from the TeamAction, never stored beside it."""

    def _todos(self, user):
        from apps.command_center.todo_service import _school_action_todos

        return _school_action_todos(user)

    def test_a_sent_action_becomes_a_todo_for_the_recipient(self):
        school = self._school("SF-T1")
        action = self._send(school)
        todos = self._todos(self.cceo)
        self.assertEqual(len(todos), 1)
        self.assertEqual(todos[0]["title"], action.requested_action)
        self.assertEqual(todos[0]["description"], school.name)
        # Straight to the work, not to a dashboard to search from.
        self.assertEqual(todos[0]["action_url"], action.workflow_route)
        self.assertIn(self.pl.name, todos[0]["source"])

    def test_the_sender_does_not_get_their_own_action_as_a_todo(self):
        self._send(self._school("SF-T2"))
        self.assertEqual(self._todos(self.pl), [])

    def test_the_todo_disappears_when_the_action_closes(self):
        """Auto-closing is the whole reason To-Dos are derived rather than
        stored — no sync step to forget."""
        school = self._school("SF-T3")
        action = self._send(school)
        self.assertEqual(len(self._todos(self.cceo)), 1)

        action.state = ActionState.RESOLVED
        action.resolved_at = timezone.now()
        action.save()
        self.assertEqual(self._todos(self.cceo), [])

    def test_an_overdue_action_reads_as_overdue_in_the_queue(self):
        school = self._school("SF-T4")
        action = self._send(school)
        action.due_date = timezone.localdate() - timedelta(days=3)
        action.save()
        todo = self._todos(self.cceo)[0]
        self.assertEqual(todo["status_key"], "overdue")
        self.assertEqual(todo["due_tone"], "danger")
        self.assertEqual(todo["due_label"], "Overdue")

    def test_the_due_column_renders_as_text_not_a_python_tuple(self):
        """_due returns (label, tone, sort_key). Passing the whole triple
        through as due_label printed "('Aug 8', 'info', datetime.date(...))"
        on the page — the template renders whatever it is handed."""
        school = self._school("SF-T7")
        todo = self._todos(self.cceo)[0] if self._send(school) else None
        self.assertIsInstance(todo["due_label"], str)
        self.assertNotIn("datetime", todo["due_label"])
        self.assertIsInstance(todo["due_tone"], str)

    def test_nothing_is_stored_beyond_the_team_action(self):
        """A second persisted To-Do row would need its own sync to disappear.
        There is no such model — the count of TeamActions is the count of
        stored records."""
        school = self._school("SF-T5")
        self._send(school)
        self.assertEqual(TeamAction.objects.filter(school_id=school.id).count(), 1)

    def test_the_full_todo_queue_includes_school_actions(self):
        """Wired into get_todos, not just callable in isolation."""
        from apps.command_center.todo_service import get_todos

        school = self._school("SF-T6")
        action = self._send(school)
        data = get_todos(self.cceo)
        self.assertIn(f"tact-{action.id}", [t["id"] for t in data["todos"]])


class WorkspaceTests(SurfaceFixture):
    def test_the_sender_sees_what_they_sent_and_who_owes_it(self):
        school = self._school("SF-W1")
        self._send(school)
        data = actions_sent(self.pl)
        self.assertEqual(len(data["rows"]), 1)
        row = data["rows"][0]
        self.assertEqual(row["school"], school.name)
        self.assertEqual(row["counterparty"], self.cceo.name)
        self.assertEqual(row["counterparty_label"], "Assigned to")

    def test_the_recipient_sees_the_same_row_from_the_other_end(self):
        school = self._school("SF-W2")
        self._send(school)
        row = actions_received(self.cceo)["rows"][0]
        self.assertEqual(row["counterparty"], self.pl.name)
        self.assertEqual(row["counterparty_label"], "Sent by")

    def test_neither_sees_the_others_rows(self):
        other = _user("sf-other@t.org", EdifyRole.CCEO.value)
        self._send(self._school("SF-W3"))
        self.assertEqual(actions_received(other)["rows"], [])
        self.assertEqual(actions_sent(other)["rows"], [])

    def test_issue_labels_never_render_as_mangled_acronyms(self):
        """ "no_ssa".title() gives "No Ssa", which reads as a typo."""
        school = self._school("SF-W4")
        self._send(school)
        self.assertEqual(actions_sent(self.pl)["rows"][0]["issue"], "No SSA")
        self.assertEqual(ISSUE_LABELS["no_ssa"], "No SSA")

    def test_tabs_partition_the_rows(self):
        a = self._school("SF-W5")
        b = self._school("SF-W6")
        self._send(a)
        action_b = self._send(b)
        action_b.state = ActionState.RESOLVED
        action_b.resolved_at = timezone.now()
        action_b.save()

        self.assertEqual(len(actions_sent(self.pl, tab="open")["rows"]), 1)
        self.assertEqual(len(actions_sent(self.pl, tab="resolved")["rows"]), 1)
        self.assertEqual(len(actions_sent(self.pl, tab="all")["rows"]), 2)

    def test_counts_distinguish_confirmed_from_hand_closed(self):
        school = self._school("SF-W7")
        action = self._send(school)
        action.state = ActionState.RESOLVED
        action.resolved_at = timezone.now()
        action.resolved_by_system = False
        action.save()

        counts = actions_sent(self.pl)["counts"]
        self.assertEqual(counts["resolved"], 1)
        self.assertEqual(counts["auto_resolved"], 0)

    def test_history_survives_closure(self):
        """Persisting rather than notifying is what lets a school show a
        pattern instead of a clean slate."""
        school = self._school("SF-W8")
        action = self._send(school)
        return_to_sender(action, self.cceo, "Not mine.")
        history = school_action_history(school.id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["state"], ActionState.RETURNED)


class HealthCheckTests(SurfaceFixture):
    def _check(self, key):
        checks = school_action_health()["checks"]
        return next(c for c in checks if c["key"] == key)

    def test_a_never_run_sweep_is_reported(self):
        """Without the sweep nothing auto-resolves and the queue silently
        reverts to a permanent list of problems."""
        c = self._check("school_action_sweep_running")
        self.assertEqual(c["severity"], "warning")
        self.assertIn("never run", c["current_state"])

    def test_a_recent_sweep_is_healthy(self):
        from apps.realtime.models import ScheduledJobExecution

        ScheduledJobExecution.objects.create(
            job_name="school_action_sweep",
            started_at=timezone.now(),
            status="success",
        )
        self.assertEqual(self._check("school_action_sweep_running")["severity"], "ok")

    def test_a_long_stale_overdue_backlog_is_flagged(self):
        old = timezone.localdate() - timedelta(days=30)
        for i in range(6):
            action = self._send(self._school(f"SF-H{i}"))
            action.due_date = old
            action.state = ActionState.OVERDUE
            action.save()
        c = self._check("school_action_stale_overdue")
        self.assertEqual(c["severity"], "warning")

    def test_an_action_assigned_to_a_deactivated_account_is_critical(self):
        """It holds its school off the unassigned queue while nobody is going
        to act on it — invisible in both places at once."""
        school = self._school("SF-H9")
        self._send(school)
        self.cceo.is_active = False
        self.cceo.save()
        c = self._check("school_action_orphaned_recipient")
        self.assertEqual(c["severity"], "critical")

    def test_hand_closed_resolutions_are_surfaced(self):
        school = self._school("SF-H10")
        action = self._send(school)
        # low_ssa is not system-verifiable in the same way; force the state to
        # represent a manual close without going through the refusal.
        action.state = ActionState.RESOLVED
        action.resolved_at = timezone.now()
        action.resolved_by_system = False
        action.save()
        c = self._check("school_action_resolution_provenance")
        self.assertEqual(c["severity"], "warning")
        self.assertIn("0 of 1", c["current_state"])


class ManualResolutionRefusalTests(SurfaceFixture):
    def test_the_refusal_is_enforced_for_every_system_verifiable_issue(self):
        from apps.planning.action_service import ActionError, SYSTEM_VERIFIABLE

        school = self._school("SF-M1")
        action = self._send(school)
        self.assertIn(action.issue_type, SYSTEM_VERIFIABLE)
        with self.assertRaises(ActionError):
            resolve_manually(action, self.cceo, "Trust me.")
