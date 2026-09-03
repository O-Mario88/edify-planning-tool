"""An approved visit runs the ordinary lifecycle from the requester's plan.

Owner, 2026-09-03: once the school owner approves, the visit belongs on the
My Plan of whoever asked (CD, IA or Accountant) and follows the normal
procedure — completion, verification, funding — through to closure of that
activity by the person who ran it.
"""

from __future__ import annotations

from apps.activities.closure_services import _assert_may_close
from apps.core.exceptions import Forbidden
from apps.planning import visit_requests
from apps.planning.test_visit_requests import VisitRequestFixture


class ApprovedVisitOnMyPlanTest(VisitRequestFixture):
    def test_the_approved_visit_appears_on_the_requesters_plan(self):
        for who in (self.cd, self.ia, self.accountant):
            with self.subTest(role=who.active_role):
                a = self._request(who)
                visit_requests.approve(a.id, self.cceo)
                a.refresh_from_db()
                self.assertEqual(a.status, "scheduled")

                self.client.force_login(who)
                page = self.client.get(f"/my-plan?fy={a.fy}&period=fy&status=scheduled")
                self.assertEqual(page.status_code, 200, who.active_role)
                self.assertContains(page, "Owned Primary")

    def test_a_pending_request_is_not_on_the_plan_yet(self):
        a = self._request(self.ia)
        self.client.force_login(self.ia)
        page = self.client.get(f"/my-plan?fy={a.fy}&period=fy")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Owned Primary")

    def test_the_requester_may_close_their_own_visit_and_nobody_elses(self):
        import datetime

        theirs = self._request(self.cd)
        visit_requests.approve(theirs.id, self.cceo)
        theirs.refresh_from_db()
        # The Country Director closes on planning authority, as before.
        _assert_may_close(self.cd, theirs)
        for offset, who in enumerate((self.ia, self.accountant), start=1):
            with self.subTest(role=who.active_role):
                # One visit per person per day at a school; move the date.
                self.day = self.__class__.day + datetime.timedelta(days=offset)
                own = self._request(who)
                visit_requests.approve(own.id, self.cceo)
                own.refresh_from_db()
                _assert_may_close(who, own)  # theirs: allowed
                with self.assertRaises(Forbidden):
                    _assert_may_close(who, theirs)

    def test_the_accountant_reaches_completed_activities(self):
        self.client.force_login(self.accountant)
        self.assertEqual(self.client.get("/completed-activities").status_code, 200)
