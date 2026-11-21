"""A To-Do closes when its workflow moves, and every count the page shows
follows it at once (implementation brief 2026-11-21, /todos: "Filtered
counts correct after a task is resolved")."""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, User
from apps.command_center.todo_service import get_cached_todos
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.fund_requests import weekly_service
from apps.fund_requests.models import WeeklyFundRequest


class ToDoCountsFollowResolutionTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(
            email="cceo_counts@test.com",
            name="Ruth Officer",
            roles=[EdifyRole.CCEO.value],
            active_role=EdifyRole.CCEO.value,
            status="active",
            is_active=True,
        )
        StaffProfile.objects.create(user=cls.user, title="Ruth Officer")
        monday = timezone.localdate() - timedelta(days=timezone.localdate().weekday())
        cls.requests = [
            WeeklyFundRequest.objects.create(
                fy=get_operational_fy(),
                week_start_date=monday - timedelta(weeks=weeks),
                week_end_date=monday - timedelta(weeks=weeks) + timedelta(days=6),
                responsible_user=cls.user.id,
                status="pending_responsible_confirmation",
            )
            for weeks in (1, 2)
        ]

    def _fund_rows(self, queue):
        return [t for t in queue["todos"] if t["id"].startswith("wfr-")]

    def test_resolving_one_request_drops_it_from_every_count(self):
        before = get_cached_todos(self.user)
        self.assertEqual(len(self._fund_rows(before)), 2)
        finance_before = dict(before["categories"]).get("Finance", 0)

        weekly_service.not_requested(self.requests[0].id, self.user)

        after = get_cached_todos(self.user)
        rows = self._fund_rows(after)
        self.assertEqual([t["id"] for t in rows], [f"wfr-{self.requests[1].id}"])
        self.assertEqual(after["total"], before["total"] - 1)
        self.assertEqual(after["counts"]["total"], before["counts"]["total"] - 1)
        self.assertEqual(
            after["counts"]["waiting_me"], before["counts"]["waiting_me"] - 1
        )
        self.assertEqual(
            dict(after["categories"]).get("Finance", 0), finance_before - 1
        )

    def test_the_page_shows_the_counts_after_the_resolution(self):
        weekly_service.not_requested(self.requests[0].id, self.user)
        self.client.force_login(self.user)
        page = self.client.get("/todos").content.decode()
        self.assertNotIn(f"/fund-requests/weekly/{self.requests[0].id}", page)
        self.assertIn(f"/fund-requests/weekly/{self.requests[1].id}", page)
