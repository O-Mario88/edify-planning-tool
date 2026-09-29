"""The audit trail's "acting for" cover is read once per request (2026-09-29).

Scheduling one visit writes several audit rows for the same actor, and each
row re-read the actor's profile and active cover. Inside a request the cover
is remembered; a cover or profile written in the request is seen.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.accounts.models import (
    Leave,
    StaffProfile,
    TemporaryCoverageAssignment,
    User,
)
from apps.audit.models import AuditLog
from apps.audit.services import log
from apps.core import request_cache


def _staff(key):
    user = User.objects.create_user(
        email=f"{key}@audit-memo.test",
        password="pw",
        name=key,
        roles=["CCEO"],
        active_role="CCEO",
        is_active=True,
    )
    return user, StaffProfile.objects.create(user=user, title="CCEO")


class ActingForMemoTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cover_user, cls.cover = _staff("cover")
        cls.away_user, cls.away = _staff("away")

    def setUp(self):
        request_cache.begin()
        self.addCleanup(request_cache.end)

    def _log(self):
        log(action="memo_probe", actor_id=self.cover_user.id, payload={"n": 1})
        return AuditLog.objects.order_by("-created_at", "-id").first().payload

    def _cover(self):
        now = timezone.now()
        leave = Leave.objects.create(
            staff=self.away,
            type="personal_time_off",
            start_date=(now.date() - timedelta(days=1)).isoformat(),
            end_date=(now.date() + timedelta(days=1)).isoformat(),
            days=3,
            days_charged=3,
            status="approved",
        )
        TemporaryCoverageAssignment.objects.create(
            original_staff=self.away,
            covering_staff=self.cover,
            leave_request=leave,
            start_datetime=now - timedelta(days=1),
            end_datetime=now + timedelta(days=1),
            scope="full",
            status="active",
        )

    def test_the_second_row_does_not_re_read_the_cover(self):
        self._cover()
        self.assertEqual(self._log()["acting_for"]["user_id"], self.away_user.id)
        with CaptureQueriesContext(connection) as queries:
            log(action="memo_probe", actor_id=self.cover_user.id)
        tables = " ".join(q["sql"] for q in queries.captured_queries)
        self.assertNotIn('"temporary_coverage_assignment"', tables)
        self.assertNotIn('FROM "staff_profile"', tables)
        self.assertEqual(self._log()["acting_for"]["user_id"], self.away_user.id)

    def test_a_cover_written_in_the_request_is_seen(self):
        self.assertNotIn("acting_for", self._log())
        self._cover()
        self.assertEqual(self._log()["acting_for"]["user_id"], self.away_user.id)

    def test_callers_cannot_change_the_remembered_cover(self):
        from apps.audit.services import _acting_for

        self._cover()
        _acting_for(self.cover_user.id)["acting_for"]["name"] = "changed"
        self.assertNotEqual(
            _acting_for(self.cover_user.id)["acting_for"]["name"], "changed"
        )
