"""A country role's visit runs the ordinary lifecycle from their own plan.

Owner, 2026-09-03: the visit belongs on the My Plan of whoever is going —
the Country Director, Impact Assessment or the Accountant — and follows the
normal procedure (completion, verification, funding) through to closure of
that activity by the person who ran it.

Two ways in since 2026-09-21. The Country Director and Impact Assessment
schedule outright, so their visit is on their plan from the moment they save
it. The Accountant still asks, so theirs arrives when the school's owner
approves it. Both land in the same place and run the same course, which is
what this file walks.
"""

from __future__ import annotations

from apps.activities.closure_services import _assert_may_close
from apps.core.exceptions import Forbidden
from apps.planning import visit_requests
from apps.planning.test_visit_requests import VisitRequestFixture


class ApprovedVisitOnMyPlanTest(VisitRequestFixture):
    def test_the_visit_appears_on_the_plan_of_whoever_is_going(self):
        for who in (self.cd, self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                a = self._request(who)
                if a.status == visit_requests.AWAITING:
                    visit_requests.approve(a.id, self.cceo)
                    a.refresh_from_db()
                self.assertEqual(a.status, "scheduled")

                self.client.force_login(who)
                page = self.client.get(f"/my-plan?fy={a.fy}&period=fy&status=scheduled")
                self.assertEqual(page.status_code, 200, who.active_role)
                self.assertContains(page, "Owned Primary")
                # One visit per person per day at a school: clear this one
                # before the next role schedules the same day.
                a.status = "cancelled"
                a.save(update_fields=["status"])

    def test_a_pending_request_is_not_on_the_plan_yet(self):
        """The Accountant's, since theirs is the visit that still waits."""
        a = self._request(self.accountant)
        self.assertEqual(a.status, visit_requests.AWAITING)
        self.client.force_login(self.accountant)
        page = self.client.get(f"/my-plan?fy={a.fy}&period=fy")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Owned Primary")

    def test_the_requester_may_close_their_own_visit_and_nobody_elses(self):
        import datetime

        theirs = self._request(self.cd)
        theirs.refresh_from_db()
        # The Country Director closes on planning authority, as before.
        _assert_may_close(self.cd, theirs)
        from apps.core.calendar_policy import SchedulingPolicyService

        day = self.__class__.day
        for who in (self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                # One visit per person per day at a school; move the date to
                # the next day the calendar allows (a plain +1/+2 landed on a
                # Sunday whenever the base day was a Friday).
                day += datetime.timedelta(days=1)
                while SchedulingPolicyService.check(None, day)["status"] == "blocked":
                    day += datetime.timedelta(days=1)
                self.day = day
                # Each person's own visit at another school in the portfolio,
                # so the one being closed is unambiguously theirs.
                own = self._request(who, self._owned_school(who.active_role))
                if own.status == visit_requests.AWAITING:
                    visit_requests.approve(own.id, self.cceo)
                own.refresh_from_db()
                _assert_may_close(who, own)  # theirs: allowed
                with self.assertRaises(Forbidden):
                    _assert_may_close(who, theirs)

    def test_the_accountant_reaches_completed_activities(self):
        self.client.force_login(self.accountant)
        self.assertEqual(self.client.get("/completed-activities").status_code, 200)
