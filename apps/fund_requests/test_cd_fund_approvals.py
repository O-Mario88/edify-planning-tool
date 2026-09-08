"""The Country Director's approval queue.

PL, Project Coordinator, IA and Accountant weekly requests route to the CD
(`weekly_service._ROUTE_TO_CD`), but the approval page was PL-only: the CD
found each escalated request by guessing the staff tab and the week, the
dashboard offered Approve with no Return, and every notification and To-Do
linked to the bare weekly page. One queue, two stages (owner, 2026-09-03).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffSupervisorAssignment
from apps.activities.models import Activity, ActivityScheduleCostLine
from apps.core.exceptions import Forbidden
from apps.core.rbac import EdifyRole
from apps.fund_requests.models import WeeklyFundRequest
from apps.geography.models import District, Region
from apps.schools.models import School

User = get_user_model()


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


class CdFundApprovalQueueTest(TestCase):
    def setUp(self):
        self.region = Region.objects.create(name="CDQ Region")
        self.district = District.objects.create(name="CDQ District", region=self.region)
        self.school = School.objects.create(
            school_id="CDQ-SCH",
            name="CDQ School",
            region=self.region,
            district=self.district,
        )

        def _user(email, name, role):
            u = User.objects.create_user(
                email=email,
                name=name,
                roles=[role],
                active_role=role,
                password="x",
                is_active=True,
            )
            return u, StaffProfile.objects.create(user=u, title=role)

        self.cceo, self.cceo_sp = _user(
            "cdq-cceo@t.org", "Cara CCEO", EdifyRole.CCEO.value
        )
        self.pl, self.pl_sp = _user(
            "cdq-pl@t.org", "Pat PL", EdifyRole.COUNTRY_PROGRAM_LEAD.value
        )
        self.cd, self.cd_sp = _user(
            "cdq-cd@t.org", "Dora CD", EdifyRole.COUNTRY_DIRECTOR.value
        )
        StaffSupervisorAssignment.objects.create(
            supervisor=self.pl_sp, supervisee=self.cceo_sp
        )
        self.week_start = _monday(date(2026, 7, 6))
        self.pl_wfr = self._request_from(self.pl, "submitted_to_cd")
        self.cceo_wfr = self._request_from(self.cceo, "submitted_to_pl")

    def _request_from(self, owner, status):
        act = Activity.objects.create(
            school=self.school,
            delivery_type="staff",
            activity_type="school_visit",
            status="scheduled",
            responsible_staff_id=owner.id,
            fy="2026",
            scheduled_date=timezone.make_aware(timezone.datetime(2026, 7, 8, 9, 0)),
        )
        ActivityScheduleCostLine.objects.create(
            activity=act,
            cost_setting_key="primary_transport_per_day",
            label="Transport",
            unit_cost=50_000,
            quantity=1,
            amount=50_000,
            planned_date=date(2026, 7, 8),
            week_start_date=self.week_start,
            week_end_date=self.week_start + timedelta(days=6),
            month=7,
            fiscal_year="2026",
            catalogue_id="cat-v1",
            responsible_user=owner.id,
        )
        return WeeklyFundRequest.objects.create(
            fy="2026",
            week_start_date=self.week_start,
            week_end_date=self.week_start + timedelta(days=6),
            responsible_user=owner.id,
            total_amount=50_000,
            status=status,
        )

    def _filters(self):
        return {"fy": "2026", "month": 7, "week": self.week_start.isoformat()}

    def test_the_cd_queue_lists_requests_routed_to_the_cd_and_nothing_else(self):
        from apps.fund_requests.pl_approval_service import get_pl_fund_approvals

        page = get_pl_fund_approvals(self.cd, self._filters())
        owners = {c["cceo_user_id"] for c in page["queue"]}
        self.assertIn(self.pl.id, owners)
        self.assertNotIn(
            self.cceo.id, owners, "a CCEO's request waits on the PL, not the CD"
        )
        awaiting = [c for c in page["queue"] if c["status"] == "Awaiting Approval"]
        self.assertEqual([c["cceo_user_id"] for c in awaiting], [self.pl.id])

    def test_the_pl_queue_is_unchanged(self):
        from apps.fund_requests.pl_approval_service import get_pl_fund_approvals

        page = get_pl_fund_approvals(self.pl, self._filters())
        owners = {c["cceo_user_id"] for c in page["queue"]}
        self.assertEqual(owners, {self.cceo.id})

    def test_the_cd_approves_and_returns_from_the_queue(self):
        from apps.fund_requests import pl_approval_service as svc

        svc.return_request(
            self.cd,
            self.pl.id,
            self.week_start.isoformat(),
            {"reason": "Split the week"},
        )
        self.pl_wfr.refresh_from_db()
        self.assertEqual(self.pl_wfr.status, "returned_by_cd")

        self.pl_wfr.status = "submitted_to_cd"
        self.pl_wfr.save(update_fields=["status"])
        svc.approve(self.cd, self.pl.id, self.week_start.isoformat())
        self.pl_wfr.refresh_from_db()
        self.assertEqual(self.pl_wfr.status, "confirmed_for_advance")

    def test_the_cd_cannot_act_on_a_cceo_request_through_the_queue(self):
        from apps.core.exceptions import BadRequest
        from apps.fund_requests import pl_approval_service as svc

        with self.assertRaises((BadRequest, Forbidden)):
            svc.approve(self.cd, self.cceo.id, self.week_start.isoformat())

    def test_the_page_opens_for_the_cd(self):
        self.client.force_login(self.cd)
        response = self.client.get(
            f"/fund-approvals?fy=2026&month=7&week={self.week_start.isoformat()}"
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pat PL")
        response = self.client.post(
            "/fund-approvals/action",
            {
                "action": "approve",
                "cceo": self.pl.id,
                "week": self.week_start.isoformat(),
                "fy": "2026",
                "month": "7",
            },
        )
        self.assertIn(response.status_code, (200, 302))
        self.pl_wfr.refresh_from_db()
        self.assertEqual(self.pl_wfr.status, "confirmed_for_advance")

    def test_the_sidebar_offers_fund_approvals_to_the_cd(self):
        from types import SimpleNamespace

        from apps.core.navigation import build_sidebar_for_user

        urls = {
            i["url"]
            for g in build_sidebar_for_user(
                SimpleNamespace(is_authenticated=True, active_role="CD"), "/"
            )
            for i in g["items"]
        }
        self.assertIn("/fund-approvals", urls)

    def test_notifications_and_todos_link_to_the_request_itself(self):
        from apps.command_center.todo_service import get_todos
        from apps.notifications.services import NotificationLinkResolver

        route, _label = NotificationLinkResolver.resolve(
            "weekly_fund_request_submitted",
            "WeeklyFundRequest",
            self.pl_wfr.id,
            "CountryDirector",
        )
        self.assertEqual(route, f"/fund-requests/weekly/{self.pl_wfr.id}")
        todo = next(
            t
            for t in get_todos(self.cd)["todos"]
            if t["id"] == f"wfr-appr-{self.pl_wfr.id}"
        )
        self.assertEqual(todo["action_url"], f"/fund-requests/weekly/{self.pl_wfr.id}")
        self.assertEqual(todo["priority"], "high")
        self.assertIn("Week of", todo["due_label"])

    def test_the_dashboard_can_return_with_a_reason(self):
        self.client.force_login(self.cd)
        response = self.client.post(
            f"/dashboard/cd-return?id={self.pl_wfr.id}&fy=2026",
            {"reason": "Too many days"},
        )
        self.assertEqual(response.status_code, 200)
        self.pl_wfr.refresh_from_db()
        self.assertEqual(self.pl_wfr.status, "returned_by_cd")

    def test_the_dashboard_return_needs_a_reason(self):
        self.client.force_login(self.cd)
        response = self.client.post(
            f"/dashboard/cd-return?id={self.pl_wfr.id}&fy=2026", {"reason": ""}
        )
        self.assertEqual(response.status_code, 200)
        self.pl_wfr.refresh_from_db()
        self.assertEqual(self.pl_wfr.status, "submitted_to_cd")
