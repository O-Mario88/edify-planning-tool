"""Invitations for cluster sessions planned before they were recorded (owner,
2026-09-23: "backfill the invited schools for older cluster sessions").

The drawers name the invited schools only since 2026-09-16, and a school
counts toward a cluster session only when it is named, so every session
planned for the whole cluster before then read "Not Planned" on its schools.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command

from apps.activities.cluster_attendance import backfill_session_invitations
from apps.activities.models import Activity, ClusterActivityAttendance
from apps.planning.test_school_planning_badges import BadgeFixture


class BackfillSessionInvitationsTest(BadgeFixture):
    def _old_session(self, **kw):
        # Planned the old way: for the cluster, naming no school.
        return self._session(invited=(), **kw)

    def _invited(self, session):
        return set(
            ClusterActivityAttendance.objects.filter(
                activity=session, invited=True
            ).values_list("school_id", flat=True)
        )

    def test_an_old_session_invites_the_cluster_and_its_schools_read_planned(self):
        session = self._old_session()
        Activity.objects.filter(id=session.id).update(
            teachers_per_school=2, expected_participants=6
        )
        self.assertEqual(self.badges(self.hope)[self.hope.id].trainings.total, 0)

        report = backfill_session_invitations()

        self.assertEqual(report["sessions"], 1)
        self.assertEqual(
            self._invited(session), {self.hope.id, self.grace.id, self.victory.id}
        )
        rows = ClusterActivityAttendance.objects.filter(activity=session)
        self.assertEqual({r.teachers for r in rows}, {2})
        self.assertFalse(any(r.attended for r in rows))
        badges = self.badges(self.hope, self.grace, self.victory)
        for school in (self.hope, self.grace, self.victory):
            self.assertEqual(badges[school.id].trainings.planned_count, 1)
        # The session keeps the head count and price it was planned with.
        session.refresh_from_db()
        self.assertEqual(session.expected_participants, 6)

    def test_partner_supported_schools_are_not_invited(self):
        session = self._old_session()
        with patch(
            "apps.planning.partner_school_policy.partner_supported_members",
            return_value={self.grace.id: "Ozeki Foundation"},
        ):
            backfill_session_invitations()
        self.assertEqual(self._invited(session), {self.hope.id, self.victory.id})

    def test_sessions_that_already_say_who_came_or_was_asked_are_left_alone(self):
        named = self._session(invited=[self.hope])
        delivered = self._old_session(status="ia_verified")
        attended = self._old_session()
        Activity.objects.filter(id=attended.id).update(
            attended_school_ids=[self.grace.id]
        )
        cancelled = self._old_session(status="cancelled")

        report = backfill_session_invitations()

        self.assertEqual(report["sessions"], 0)
        self.assertEqual(self._invited(named), {self.hope.id})
        for session in (delivered, attended, cancelled):
            self.assertFalse(
                ClusterActivityAttendance.objects.filter(activity=session).exists()
            )

    def test_it_runs_once_and_a_dry_run_writes_nothing(self):
        session = self._old_session(kind="cluster_meeting")
        out = StringIO()
        call_command("backfill_cluster_invitations", "--dry-run", stdout=out)
        self.assertIn(
            "Would invite 3 school(s) across 1 cluster session(s)", out.getvalue()
        )
        self.assertFalse(
            ClusterActivityAttendance.objects.filter(activity=session).exists()
        )

        call_command("backfill_cluster_invitations", stdout=StringIO())
        self.assertEqual(len(self._invited(session)), 3)
        self.assertEqual(
            backfill_session_invitations(),
            {"sessions": 0, "invitations": 0, "without_members": 0},
        )
