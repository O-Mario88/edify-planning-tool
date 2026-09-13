"""Fund Approvals opens where a decision is waiting (Programme Lead alignment, 2026-09-13).

It opened on the team's busiest funded month and that month's busiest week,
which put a lead in front of a week with nothing to approve while a request sat
in another. With no week or month chosen it now opens on the earliest week
holding a team request waiting on this approver, else the current week. The
layout is unchanged (owner rule): only where it opens moved.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment, User
from apps.core.fy import get_operational_fy
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import WeeklyFundRequest
from apps.fund_requests.pl_approval_service import get_pl_fund_approvals


def _person(email, name, role):
    user = User.objects.create(
        email=email,
        name=name,
        roles=[role.value],
        active_role=role.value,
        is_active=True,
        status="active",
    )
    return user, StaffProfile.objects.create(user=user, title=name)


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


class OpeningWeekTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fy = get_operational_fy()
        cls.pl_user, cls.pl = _person(
            "open-pl@t.test", "Opening Lead", EdifyRole.COUNTRY_PROGRAM_LEAD
        )
        cls.cceo_user, cls.cceo = _person(
            "open-cceo@t.test", "Opening CCEO", EdifyRole.CCEO
        )
        cls.rival_user, cls.rival = _person(
            "open-rival@t.test", "Rival CCEO", EdifyRole.CCEO
        )
        StaffSupervisorAssignment.objects.create(supervisee=cls.cceo, supervisor=cls.pl)

    def _request(self, user, week_start, status):
        return WeeklyFundRequest.objects.create(
            fy=self.fy,
            week_start_date=week_start,
            week_end_date=week_start + timedelta(days=6),
            responsible_user=user.id,
            total_amount=100_000,
            status=status,
        )

    def test_it_opens_on_the_earliest_week_waiting_on_the_lead(self):
        this_week = _monday(timezone.localdate())
        earliest = this_week - timedelta(weeks=5)
        self._request(self.cceo_user, this_week - timedelta(weeks=2), "submitted_to_pl")
        self._request(self.cceo_user, earliest, "submitted_to_pl")
        # Earlier still, but not waiting on anyone — and another team's request.
        self._request(self.cceo_user, earliest - timedelta(weeks=3), "disbursed")
        self._request(self.rival_user, earliest - timedelta(weeks=4), "submitted_to_pl")

        ctx = get_pl_fund_approvals(self.pl_user, {})

        self.assertEqual(ctx["week"], earliest.isoformat())
        self.assertEqual(ctx["month"], earliest.month)

    def test_with_nothing_waiting_it_opens_on_the_current_week(self):
        this_week = _monday(timezone.localdate())
        self._request(self.cceo_user, this_week - timedelta(weeks=3), "disbursed")

        ctx = get_pl_fund_approvals(self.pl_user, {})

        self.assertEqual(ctx["week"], this_week.isoformat())

    def test_a_chosen_week_is_kept(self):
        this_week = _monday(timezone.localdate())
        self._request(self.cceo_user, this_week - timedelta(weeks=5), "submitted_to_pl")
        chosen = this_week - timedelta(weeks=1)

        ctx = get_pl_fund_approvals(self.pl_user, {"week": chosen.isoformat()})

        self.assertEqual(ctx["week"], chosen.isoformat())
