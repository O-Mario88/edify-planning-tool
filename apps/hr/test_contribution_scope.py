"""The contribution scope reads its staff once a request (2026-10-24).

A Programme Lead's To-Do queue builds the team's target page, which asks for
each allocation's activities: the country's staff ids were read again for
every one of them, 1,318 identical queries of 3,524 on a seeded database,
seven and a half seconds before Home could show the queue. Inside a request
the ids are read once; outside one every call still reads them fresh.
"""

from __future__ import annotations

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.activities.models import Activity
from apps.core import request_cache
from apps.hr.contribution_scope import owner_ids, scope_activities


def _staff(email, role="CCEO", country="Uganda"):
    user = User.objects.create_user(
        email=email, name=email, roles=[role], active_role=role, password="x"
    )
    return StaffProfile.objects.create(user=user, title=role, country=country)


class ContributionScopeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.lead = _staff("scope-lead@t.org", "Program Lead")
        cls.cceo = _staff("scope-cceo@t.org")
        StaffSupervisorAssignment.objects.create(
            supervisee=cls.cceo, supervisor=cls.lead
        )

    def staff_queries(self, call, times=20):
        with request_cache.scoped():
            with CaptureQueriesContext(connection) as queries:
                for _ in range(times):
                    call()
        # The staff lookups themselves; the activity query's country filter
        # names the staff table in a subquery of its own.
        return [
            q
            for q in queries.captured_queries
            if q["sql"].startswith(('SELECT "staff_', 'SELECT DISTINCT "staff_'))
        ]

    def test_the_countrys_staff_are_read_once_a_request(self):
        read = self.staff_queries(
            lambda: list(scope_activities(Activity.objects.all(), country="Uganda"))
        )
        self.assertLessEqual(len(read), 2)

    def test_a_persons_ids_are_read_once_a_request(self):
        read = self.staff_queries(lambda: owner_ids(self.lead, True))
        self.assertLessEqual(len(read), 2)

    def test_the_answer_is_the_same_with_or_without_the_request_cache(self):
        fresh = owner_ids(self.lead, True)
        with request_cache.scoped():
            cached = owner_ids(self.lead, True)
        self.assertEqual(set(fresh), set(cached))
        self.assertIn(str(self.cceo.id), cached)
        self.assertIn(str(self.cceo.user_id), cached)
