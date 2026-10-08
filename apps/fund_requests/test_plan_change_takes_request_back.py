"""A plan that changes takes its unpaid weekly fund request back (owner,
2026-10-07).

"When you click complete or submit fund request and did not complete fund
request or it is returned … it blocks it from editing. Can you lift it so
that there is no restriction."

Once a week's request was sent for approval, moving a visit in that week was
refused: "This activity is already included in a submitted or approved weekly
fund request. Return that request before changing its cost." The officer who
sent it cannot return it, so the plan stood still until a Programme Lead did.

What is pinned here: a request that has been sent and not paid comes back to
its owner when the plan under it changes, rebuilt from the changed plan;
whoever had it on their list is told; a change that moves no money leaves the
request where it is; a change that is refused leaves it where it is; and a
request that has been paid still holds its cost.

The month's request (owner, 2026-10-08: "lift the monthly one too") is a
Programme Lead's snapshot of a whole team. It no longer refuses either, and it
is not taken back: it stays with its reviewer, or approved, and its lines and
total follow the changed plan.
"""

from __future__ import annotations

import datetime

from django.utils import timezone

from apps.accounts.models import User
from apps.activities import editing, services
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.activities.test_activity_editing import EditingFixture
from apps.activities.test_profile_activities import PASSWORD
from apps.core.exceptions import BadRequest
from apps.fund_requests import weekly_service
from apps.fund_requests.fundable import fundable_lines
from apps.fund_requests.models import AdvanceRequest, FundRequest, WeeklyFundRequest
from apps.fund_requests.plan_changes import TAKEN_BACK_EVENT
from apps.notifications.models import Notification

DRAFT = "pending_responsible_confirmation"


def _tuesday(weeks_ahead: int) -> datetime.date:
    """A Tuesday: the day after it is in the same week, and neither is a
    Sunday the calendar policy would refuse."""
    day = timezone.localdate() + datetime.timedelta(weeks=weeks_ahead)
    return day + datetime.timedelta(days=(1 - day.weekday()) % 7)


class SentRequestFixture(EditingFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.accountant = User.objects.create_user(
            email="profile-accountant@edify.org",
            name="Profile Accountant",
            roles=["Accountant"],
            active_role="Accountant",
            password=PASSWORD,
            is_active=True,
        )

    def setUp(self):
        super().setUp()
        self.day = _tuesday(3)
        self.next_day = self.day + datetime.timedelta(days=1)
        self.visit = self._visit_on(self.day)

    def _visit_on(self, day, school=None) -> Activity:
        # `_visit` counts days from today.
        return self._visit(school, days=(day - timezone.localdate()).days)

    def _request(self, day=None) -> WeeklyFundRequest | None:
        day = day or self.day
        return WeeklyFundRequest.objects.filter(
            responsible_user=self.cceo.id,
            week_start_date=day - datetime.timedelta(days=day.weekday()),
        ).first()

    def _send(self, day=None) -> WeeklyFundRequest:
        request = self._request(day)
        self.assertIsNotNone(request, "the visit raised no weekly request")
        weekly_service.request_advance(request.id, self.cceo)
        request.refresh_from_db()
        self.assertEqual(request.status, "submitted_to_pl")
        return request

    def _approve(self, request) -> WeeklyFundRequest:
        weekly_service.approve_weekly_request(request.id, self.pl)
        request.refresh_from_db()
        self.assertEqual(request.status, "confirmed_for_advance")
        return request

    def _move(self, activity, day, **more):
        with self.captureOnCommitCallbacks(execute=True):
            return editing.edit(
                activity.id,
                {
                    "scheduledDate": day.isoformat(),
                    "reason": "The head is away",
                    **more,
                },
                self.cceo,
            )

    def _notices(self, user) -> list[Notification]:
        return list(
            Notification.objects.filter(
                recipient_id=user.id, source_event_type=TAKEN_BACK_EVENT
            )
        )

    def _assert_request_is_the_plan(self, request) -> None:
        """The request carries exactly its owner's fundable lines that week."""
        live = fundable_lines(
            ActivityScheduleCostLine.objects.filter(
                responsible_user=request.responsible_user,
                planned_date__gte=request.week_start_date,
                planned_date__lte=request.week_end_date,
            )
        )
        self.assertEqual(
            set(request.lines.values_list("activity_budget_line_id", flat=True)),
            set(live.values_list("id", flat=True)),
        )
        self.assertEqual(request.total_amount, sum(line.amount for line in live))


class ARequestWithItsApproverComesBack(SentRequestFixture):
    def test_the_refusal_this_lifts(self):
        """The cost writer still refuses on its own: only a planner's change
        to the plan takes the request back."""
        self._send()

        with self.assertRaises(BadRequest) as refused:
            services.reprice_activity(self.visit, self.cceo)

        self.assertIn("request", str(refused.exception))
        self.assertEqual(self._request().status, "submitted_to_pl")

    def test_a_new_day_in_the_same_week(self):
        sent = self._send()

        self._move(self.visit, self.next_day)

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.planned_date, self.next_day)
        self.assertEqual(self.visit.status, "rescheduled")
        request = self._request()
        self.assertEqual(request.id, sent.id)
        self.assertEqual(request.status, DRAFT)
        self.assertIsNone(request.confirmed_at)
        self._assert_request_is_the_plan(request)
        self.assertEqual(
            set(
                AdvanceRequest.objects.filter(activity=self.visit).values_list(
                    "status", flat=True
                )
            )
            - {DRAFT, "draft_from_schedule"},
            set(),
        )

    def test_the_owner_sends_it_again(self):
        self._send()
        self._move(self.visit, self.next_day)

        request = self._send()

        self.assertEqual(request.status, "submitted_to_pl")
        self._assert_request_is_the_plan(request)

    def test_the_owner_and_the_approver_are_told(self):
        self._send()

        self._move(self.visit, self.next_day)

        mine = self._notices(self.cceo)
        self.assertEqual(len(mine), 1)
        self.assertIn("Send it for approval again", mine[0].body)
        # Named by what it is and where, so the owner knows which plan moved.
        self.assertIn(f"at {self.fresh.name}", mine[0].body)
        self.assertEqual(
            mine[0].target_route, f"/fund-requests/weekly/{self._request().id}"
        )
        theirs = self._notices(self.pl)
        self.assertEqual(len(theirs), 1)
        self.assertIn("nothing to approve", theirs[0].body)
        self.assertIn(self.cceo.name, theirs[0].body)

    def test_the_reschedule_door_does_the_same(self):
        self._send()
        self.assertTrue(self.client.login(email=self.cceo.email, password=PASSWORD))

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                f"/my-plan/{self.visit.id}/reschedule",
                {
                    "scheduled_date": self.next_day.isoformat(),
                    "reason": "School sports day",
                },
                HTTP_HX_REQUEST="true",
            )

        self.assertEqual(response.status_code, 200, response.content)
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.planned_date, self.next_day)
        self.assertEqual(self._request().status, DRAFT)

    def test_a_move_to_another_school(self):
        self._send()

        with self.captureOnCommitCallbacks(execute=True):
            moved = editing.edit(
                self.visit.id,
                {"schoolId": self.fresh_two.school_id, "reason": "Wrong school"},
                self.cceo,
            )

        again = Activity.objects.get(id=moved["id"])
        self.assertEqual(again.school_id, self.fresh_two.id)
        request = self._request()
        self.assertEqual(request.status, DRAFT)
        self._assert_request_is_the_plan(request)
        self.assertEqual(
            set(
                request.lines.values_list(
                    "activity_budget_line__activity_id", flat=True
                )
            ),
            {again.id},
        )


class AnApprovedRequestComesBack(SentRequestFixture):
    def test_approved_and_waiting_for_the_accountant(self):
        self._approve(self._send())
        self.assertEqual(
            set(
                AdvanceRequest.objects.filter(activity=self.visit).values_list(
                    "status", flat=True
                )
            ),
            {"confirmed_for_advance"},
        )

        self._move(self.visit, self.next_day)

        request = self._request()
        self.assertEqual(request.status, DRAFT)
        self._assert_request_is_the_plan(request)
        # Nothing of the old approval is left in the accountant's queue.
        self.assertFalse(
            AdvanceRequest.objects.filter(
                activity=self.visit,
                status__in=("confirmed_for_advance", "submitted_to_accountant"),
            ).exists()
        )
        told = self._notices(self.accountant)
        self.assertEqual(len(told), 1)
        self.assertIn("nothing to disburse", told[0].body)

    def test_it_goes_through_approval_again(self):
        self._approve(self._send())
        self._move(self.visit, self.next_day)

        request = self._approve(self._send())

        self._assert_request_is_the_plan(request)


class AWeekSetToNoAdvanceOpensAgain(SentRequestFixture):
    def test_the_week_reopens_with_the_changed_plan(self):
        request = self._request()
        weekly_service.not_requested(request.id, self.cceo)

        self._move(self.visit, self.next_day)

        request = self._request()
        self.assertEqual(request.status, DRAFT)
        self._assert_request_is_the_plan(request)
        self.assertGreater(request.lines.count(), 0)
        told = self._notices(self.cceo)
        self.assertEqual(len(told), 1)
        self.assertIn("No Advance", told[0].body)


class BothWeeksOfAMove(SentRequestFixture):
    def test_the_week_it_leaves_and_the_week_it_lands_in(self):
        later = _tuesday(4)
        other = self._visit_on(later, self.fresh_two)
        self._send(self.day)
        self._send(later)

        self._move(self.visit, later)

        # Nothing is left to fund in the week it left.
        self.assertIsNone(self._request(self.day))
        landed = self._request(later)
        self.assertEqual(landed.status, DRAFT)
        self._assert_request_is_the_plan(landed)
        self.assertEqual(
            set(
                landed.lines.values_list("activity_budget_line__activity_id", flat=True)
            ),
            {self.visit.id, other.id},
        )
        withdrawn = [n for n in self._notices(self.cceo) if "withdrawn" in n.body]
        self.assertEqual(len(withdrawn), 1)
        self.assertEqual(withdrawn[0].target_route, "/fund-requests/weekly")


class WhatLeavesTheRequestWhereItIs(SentRequestFixture):
    def test_a_change_that_moves_no_money(self):
        self._send()

        with self.captureOnCommitCallbacks(execute=True):
            editing.edit(
                self.visit.id,
                {
                    "activityPurposeText": "Review the improvement plan",
                    "expectedOutcome": "A dated plan",
                },
                self.cceo,
            )

        self.assertEqual(self._request().status, "submitted_to_pl")
        self.assertEqual(self._notices(self.cceo), [])
        self.assertEqual(self._notices(self.pl), [])

    def test_a_date_the_plan_will_not_take(self):
        self._send()

        with self.assertRaises(BadRequest):
            # Work is scheduled forward, never backward.
            self._move(self.visit, timezone.localdate() - datetime.timedelta(days=2))

        self.assertEqual(self._request().status, "submitted_to_pl")
        self.assertEqual(self._notices(self.cceo), [])
        self.assertEqual(self._notices(self.pl), [])

    def test_a_request_that_has_been_paid(self):
        request = self._approve(self._send())
        AdvanceRequest.objects.filter(activity=self.visit).update(status="disbursed")
        WeeklyFundRequest.objects.filter(id=request.id).update(status="disbursed")

        with self.assertRaises(BadRequest) as refused:
            self._move(self.visit, self.next_day)

        self.assertIn("budget amendment", str(refused.exception))
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.planned_date, self.day)
        self.assertEqual(self._request().status, "disbursed")
        self.assertEqual(self._notices(self.cceo), [])

    def test_one_paid_line_under_a_request_still_with_its_approver(self):
        """Paid through another channel while the week waited. The request is
        taken back and the cost writer then refuses, in one transaction: the
        request is with its approver again and nobody is told."""
        self._send()
        AdvanceRequest.objects.filter(activity=self.visit).update(status="disbursed")

        with self.assertRaises(BadRequest):
            self._move(self.visit, self.next_day)

        self.assertEqual(self._request().status, "submitted_to_pl")
        self.assertEqual(self._notices(self.pl), [])


class TheDrawersSaySo(SentRequestFixture):
    def setUp(self):
        super().setUp()
        self.assertTrue(self.client.login(email=self.cceo.email, password=PASSWORD))

    def test_nothing_is_said_while_the_request_is_a_draft(self):
        for door in ("edit-drawer", "reschedule-drawer"):
            with self.subTest(door=door):
                body = self.client.get(f"/my-plan/{self.visit.id}/{door}")
                self.assertEqual(body.status_code, 200)
                self.assertNotIn(b"data-sent-fund-request-note", body.content)

    def test_a_sent_request_is_named_before_the_save(self):
        request = self._send()
        week = f"{request.week_start_date:%-d %b} – {request.week_end_date:%-d %b}"

        for door in ("edit-drawer", "reschedule-drawer"):
            with self.subTest(door=door):
                body = self.client.get(
                    f"/my-plan/{self.visit.id}/{door}"
                ).content.decode()
                self.assertIn("data-sent-fund-request-note", body)
                self.assertIn(
                    f"The fund request for {week} has already been sent", body
                )


class MonthlyRequestFixture(SentRequestFixture):
    """A Programme Lead's team request for the month, sent to the Country
    Director (owner, 2026-10-08: "lift the monthly one too")."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.director = User.objects.create_user(
            email="profile-cd@edify.org",
            name="Profile Director",
            roles=["CountryDirector"],
            active_role="CountryDirector",
            password=PASSWORD,
            is_active=True,
        )

    def setUp(self):
        super().setUp()
        # A day whose tomorrow is in the same month, so "the next day" never
        # carries the visit out of the month's request.
        while self.next_day.month != self.day.month:
            self.day += datetime.timedelta(days=7)
            self.next_day = self.day + datetime.timedelta(days=1)
        if self.visit.planned_date != self.day:
            services.cancel(self.visit.id, {"reason": "Fixture day moved"}, self.cceo)
            self.visit = self._visit_on(self.day, self.fresh_two)
        self.fy, self.month = self.visit.fy, self.day.month

    def _other_school(self):
        """A fixture school that has not had its staff visit for the year."""
        return self.fresh_two if self.visit.school_id == self.fresh.id else self.fresh

    def _another_month(self) -> datetime.date:
        day = self.day + datetime.timedelta(weeks=5)
        while day.month == self.month:
            day += datetime.timedelta(weeks=1)
        return day

    def _send_the_month(self) -> FundRequest:
        from apps.fund_requests import monthly_request_service

        request = monthly_request_service.submit_to_cd(self.pl, self.fy, self.month)
        self.assertEqual(request.status, "submitted_to_cd")
        self.assertIn(
            self.visit.id, set(request.items.values_list("activity_id", flat=True))
        )
        return request

    def _approve_the_month(self, request) -> FundRequest:
        from apps.monthly_work_plan.country_budget_service import (
            approve_pl_monthly_request,
        )

        approve_pl_monthly_request(self.director, request.id)
        request.refresh_from_db()
        self.assertEqual(request.status, "approved_by_cd")
        return request

    def _assert_every_item_has_its_line(self, request) -> None:
        """No item names a line that no longer exists, and the request's
        total is the sum of its items and of the lines behind them."""
        request.refresh_from_db()
        items = list(
            request.items.values_list("activity_schedule_cost_line_id", "amount")
        )
        lines = dict(
            ActivityScheduleCostLine.objects.filter(
                id__in=[line_id for line_id, _amount in items]
            ).values_list("id", "amount")
        )
        self.assertEqual({line_id for line_id, _a in items}, set(lines))
        self.assertEqual(request.total_amount, sum(amount for _id, amount in items))
        self.assertEqual(request.total_amount, sum(lines.values()))

    def _month_notices(self, user) -> list[Notification]:
        from apps.fund_requests.plan_changes import MONTHLY_FOLLOWED_EVENT

        return list(
            Notification.objects.filter(
                recipient_id=user.id, source_event_type=MONTHLY_FOLLOWED_EVENT
            )
        )


class TheMonthsRequestFollowsThePlan(MonthlyRequestFixture):
    def test_a_sweep_is_still_refused(self):
        """Only a planner's own change carries the month's request along."""
        request = self._send_the_month()
        before = request.total_amount

        with self.assertRaises(BadRequest) as refused:
            services.reprice_activity(self.visit, self.cceo)

        self.assertIn("monthly fund request", str(refused.exception))
        request.refresh_from_db()
        self.assertEqual(request.total_amount, before)

    def test_a_new_day_in_the_same_month(self):
        request = self._send_the_month()

        self._move(self.visit, self.next_day)

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.planned_date, self.next_day)
        request.refresh_from_db()
        # It stays with the Country Director: nobody sends it again.
        self.assertEqual(request.status, "submitted_to_cd")
        self._assert_every_item_has_its_line(request)
        self.assertEqual(
            set(request.items.values_list("activity_schedule_cost_line_id", flat=True))
            & set(
                ActivityScheduleCostLine.objects.filter(
                    activity=self.visit
                ).values_list("id", flat=True)
            ),
            set(
                ActivityScheduleCostLine.objects.filter(
                    activity=self.visit
                ).values_list("id", flat=True)
            ),
        )

    def test_the_programme_lead_s_page_still_adds_up(self):
        from apps.budget.health import dangling_fund_request_items
        from apps.fund_requests import monthly_request_service

        self._send_the_month()

        self._move(self.visit, self.next_day)

        page = monthly_request_service.get_monthly_request(
            self.pl, {"fy": self.fy, "month": self.month}
        )
        self.assertEqual(page["shown_total"], page["live_total"])
        self.assertEqual(dangling_fund_request_items()["count"], 0)

    def test_the_change_is_in_the_audit_log(self):
        from apps.audit.models import AuditLog

        request = self._send_the_month()

        self._move(self.visit, self.next_day)

        entry = AuditLog.objects.filter(
            action="fund_request.followed_plan_change", subject_id=request.id
        ).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.payload["status"], "submitted_to_cd")

    def test_nobody_is_told_while_the_total_stands(self):
        request = self._send_the_month()
        before = request.total_amount

        self._move(self.visit, self.next_day)

        request.refresh_from_db()
        if request.total_amount == before:
            self.assertEqual(self._month_notices(self.pl), [])
        else:
            self.assertEqual(len(self._month_notices(self.pl)), 1)

    def test_a_move_out_of_the_month_leaves_the_request(self):
        other = self._visit_on(self.next_day, self._other_school())
        request = self._send_the_month()
        before = request.total_amount

        self._move(self.visit, self._another_month())

        request.refresh_from_db()
        self.assertEqual(request.status, "submitted_to_cd")
        self._assert_every_item_has_its_line(request)
        self.assertEqual(
            set(request.items.values_list("activity_id", flat=True)), {other.id}
        )
        self.assertLess(request.total_amount, before)
        told = self._month_notices(self.pl)
        self.assertEqual(len(told), 1)
        self.assertIn(f"UGX {request.total_amount:,}", told[0].body)
        self.assertIn(f"UGX {before:,}", told[0].body)
        self.assertEqual(told[0].target_route, "/accounts/monthly-request")

    def test_an_approved_month_stays_approved(self):
        self._visit_on(self.next_day, self._other_school())
        request = self._approve_the_month(self._send_the_month())

        self._move(self.visit, self._another_month())

        request.refresh_from_db()
        self.assertEqual(request.status, "approved_by_cd")
        self._assert_every_item_has_its_line(request)
        # Its preparer and the Country Director who approved it are told.
        self.assertEqual(len(self._month_notices(self.pl)), 1)
        theirs = self._month_notices(self.director)
        self.assertEqual(len(theirs), 1)
        self.assertEqual(theirs[0].target_route, "/budget")

    def test_a_month_that_has_been_paid_still_holds(self):
        request = self._send_the_month()
        FundRequest.objects.filter(id=request.id).update(status="disbursed")

        with self.assertRaises(BadRequest) as refused:
            self._move(self.visit, self.next_day)

        self.assertIn("monthly fund request", str(refused.exception))
        self.visit.refresh_from_db()
        self.assertEqual(self.visit.planned_date, self.day)

    def test_the_week_and_the_month_together(self):
        """Both were sent: the week comes back to its owner, the month
        follows where it is."""
        request = self._send_the_month()
        self._send()

        self._move(self.visit, self.next_day)

        self.visit.refresh_from_db()
        self.assertEqual(self.visit.planned_date, self.next_day)
        self.assertEqual(self._request(self.next_day).status, DRAFT)
        request.refresh_from_db()
        self.assertEqual(request.status, "submitted_to_cd")
        self._assert_every_item_has_its_line(request)


class ARebuildLeavesNoRequestItemBehind(MonthlyRequestFixture):
    def test_a_returned_month_keeps_its_lines_through_a_re_price(self):
        """A returned request was always re-priceable, and its items were
        left naming lines the re-price had deleted."""
        from apps.monthly_work_plan.country_budget_service import (
            return_pl_monthly_request,
        )

        request = self._send_the_month()
        return_pl_monthly_request(self.director, request.id, "Check the dates")

        with self.captureOnCommitCallbacks(execute=True):
            services.reprice_activity(self.visit, self.cceo)

        request.refresh_from_db()
        self.assertEqual(request.status, "returned_by_cd")
        self._assert_every_item_has_its_line(request)
        self.assertGreater(request.items.count(), 0)
